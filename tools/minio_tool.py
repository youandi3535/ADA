"""tools.minio_tool — MinIO 공통 클라이언트 (Day05 §3).

S3 호환 boto3 클라이언트, 멱등/재시도/Presigned URL 헬퍼.
"""

from __future__ import annotations

import io
import os
import tempfile
import threading
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

from ada.core.config import settings
from ada.core.logger import get_logger

log = get_logger("minio")


def _looks_decoded_ok(df: Any) -> bool:
    """디코딩 검증 — 컬럼명에 한글이 복원됐거나 mojibake 흔적이 없으면 True.

    mojibake(예: '구분별' → '±¸ºÐº°') 는 CP949/EUC-KR 바이트를 latin 계열로
    잘못 디코딩했을 때 Latin-1 Supplement(U+00A0~U+00FF) 문자가 다수 나타난다.
    """
    try:
        text = " ".join(map(str, df.columns))
    except Exception:  # noqa: BLE001
        return True
    if not text:
        return True
    # 한글(가~힣)이 하나라도 있으면 정상 디코딩으로 판단
    if any("가" <= ch <= "힣" for ch in text):
        return True
    # Latin-1 Supplement(mojibake 흔적) 비율이 높으면 깨진 것으로 판단
    suspicious = sum(1 for ch in text if " " <= ch <= "ÿ")
    return suspicious < max(2, int(len(text) * 0.2))


def _read_csv_robust(body: bytes) -> Any:
    """한국어 CSV 강건 로딩 — utf-8 → cp949/euc-kr 검증 → chardet 보조.

    HJ 2026-06-14 — chardet 이 한국어 CP949/EUC-KR 을 latin 계열(Windows-1252/
    ISO-8859)로 오판하면 read_csv 가 에러 없이 mojibake 로 읽어 이후 컬럼 의미
    분석이 전부 깨진다. utf-8 실패 시 cp949/euc-kr 을 우선 시도하고 한글 복원을
    검증한 뒤 채택한다.
    """
    import pandas as pd  # noqa: WPS433

    # 1) BOM 포함 utf-8 우선 (정상 utf-8 CSV)
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return pd.read_csv(io.BytesIO(body), encoding=enc)
        except UnicodeDecodeError:
            continue

    # 2) utf-8 실패 = 한국어 인코딩 가능성 높음 → cp949/euc-kr 명시 시도 + 검증
    for enc in ("cp949", "euc-kr"):
        try:
            df = pd.read_csv(io.BytesIO(body), encoding=enc)
        except Exception:  # noqa: BLE001
            continue
        if _looks_decoded_ok(df):
            return df

    # 3) chardet 보조 — 단, latin 계열 오판은 cp949 로 대체
    try:
        import chardet  # noqa: WPS433

        det = chardet.detect(body[:65536]) or {}
        enc = (det.get("encoding") or "").lower()
        if not enc or enc.startswith(("iso-8859", "windows-125", "latin")):
            enc = "cp949"
        return pd.read_csv(io.BytesIO(body), encoding=enc)
    except Exception:  # noqa: BLE001
        # 4) 최후 — cp949 강제
        return pd.read_csv(io.BytesIO(body), encoding="cp949")


# HJ 2026-06-14 — 단계 간 동일 object 반복 로드 제거용 프로세스 로컬 캐시.
#   G4~G5 에서 tuner·training·eval·explainability 가 같은 parquet/csv 를 매번
#   재다운로드·재디코딩하던 낭비 제거. key=object|fmt — 같은 object=같은 bytes=
#   같은 DataFrame 이므로 결과는 비트 동일(무손실). maxsize·MB 상한으로 워커 메모리 보호.
#   주의: 반환 DataFrame 은 read-only 사용 (호출부는 select_dtypes/drop 등 새 객체 생성).
_DF_CACHE_MAXSIZE = 2
_DF_CACHE_MAX_MB = 600.0
_df_cache: "OrderedDict[str, Any]" = OrderedDict()
_df_cache_lock = threading.Lock()


def _df_cache_get(key: str) -> Any:
    with _df_cache_lock:
        if key in _df_cache:
            _df_cache.move_to_end(key)
            return _df_cache[key]
    return None


def _df_cache_put(key: str, df: Any) -> None:
    try:
        mb = float(df.memory_usage(deep=True).sum()) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        mb = 0.0
    if mb > _DF_CACHE_MAX_MB:
        return  # 과대 DataFrame 은 캐시 제외 (워커 2.5GB 메모리 보호)
    with _df_cache_lock:
        _df_cache[key] = df
        _df_cache.move_to_end(key)
        while len(_df_cache) > _DF_CACHE_MAXSIZE:
            _df_cache.popitem(last=False)


class MinIOClient:
    """boto3 S3 호환 클라이언트. 싱글턴은 ``get_minio_client()`` 사용."""

    def __init__(self) -> None:
        endpoint = settings.minio_endpoint
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"http://{endpoint}"

        self.bucket = settings.minio_bucket
        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            # HJ 2026-06-19 — 명시적 타임아웃·재시도 한도. 이전엔 미설정이라 MinIO 가 연결은 되는데
            #   응답이 멈추는 상황(stale 소켓·네트워크 stall)에서 데이터 로드가 사실상 무한 대기 →
            #   1단계(데이터 파악) 팝업에 글자 0 인 채 워커가 멈추던 원인. read_timeout 은 '바이트 간
            #   무응답' 기준이라 대용량 정상 전송은 영향 없고, 진짜 stall 만 끊는다. 끊기면 파이프라인이
            #   실패로 떨어져 워치독·자가치유가 포착(무한 멈춤보다 안전).
            config=Config(
                signature_version="s3v4",
                connect_timeout=15,
                read_timeout=120,
                retries={"max_attempts": 3, "mode": "standard"},
            ),
            region_name="us-east-1",
        )
        self._ensure_bucket()

    # ------------------------------------------------------------------
    def _ensure_bucket(self) -> None:
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket", "NotFound"):
                self.s3.create_bucket(Bucket=self.bucket)
                log.info("bucket_created", bucket=self.bucket)

    # ------------------------------------------------------------------
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def upload_file(self, local_path: str, object_name: str) -> str:
        self.s3.upload_file(local_path, self.bucket, object_name)
        return f"s3://{self.bucket}/{object_name}"

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    def upload_bytes(self, body: bytes, object_name: str, content_type: str = "application/octet-stream") -> str:
        self.s3.put_object(Bucket=self.bucket, Key=object_name, Body=body, ContentType=content_type)
        return f"s3://{self.bucket}/{object_name}"

    def object_key(self, minio_path: str) -> str:
        """``s3://<bucket>/<key>`` 또는 순수 key 문자열 → object key (단일 진입점).

        버킷명과 무관하게 ``s3://*/`` 접두 한 단계만 제거한다. 호출부가
        ``path.replace(f"s3://{self.bucket}/", "")`` 로 직접 벗기면 저장 당시 버킷명과
        현재 ``self.bucket`` 이 다를 때(설정 변경·오래된 DB 경로) 접두가 안 벗겨져
        key 에 ``s3://옛버킷/...`` 가 남아 NoSuchKey 를 유발한다. 모든 다운로드 경로는
        이 메서드로 key 를 해석한다.
        """
        if minio_path.startswith("s3://"):
            parts = minio_path.split("/", 3)  # ['s3:', '', '<bucket>', '<key>']
            return parts[3] if len(parts) >= 4 else minio_path
        return minio_path

    def download_bytes(self, object_name: str) -> bytes:
        resp = self.s3.get_object(Bucket=self.bucket, Key=object_name)
        return resp["Body"].read()

    def load_dataframe(self, object_name: str, fmt: str = "csv") -> Any:
        """csv/parquet/xlsx/json/zip 자동 핸들링.

        HJ 2026-06-14 — 동일 object 반복 로드는 프로세스 캐시에서 즉시 반환
        (단계 간 재다운로드·재디코딩 제거). 같은 bytes → 같은 DataFrame, 무손실.
        """
        cache_key = f"{object_name}|{fmt.lower()}"
        cached = _df_cache_get(cache_key)
        if cached is not None:
            return cached
        df = self._load_dataframe_uncached(object_name, fmt)
        _df_cache_put(cache_key, df)
        return df

    def _load_dataframe_uncached(self, object_name: str, fmt: str = "csv") -> Any:
        import pandas as pd  # noqa: WPS433

        body = self.download_bytes(object_name)
        buf = io.BytesIO(body)
        fmt = fmt.lower()
        if fmt in ("csv", "txt"):
            # HJ 2026-06-14 — 한국어 인코딩 강건 로딩 (chardet 오판 회피).
            # 기존 utf-8→chardet→cp949 순서는 chardet 이 CP949 를 latin 계열로
            # 오판하면 mojibake(±¸ºÐº°)로 읽혀 컬럼 의미 분석이 깨졌다.
            return _read_csv_robust(body)
        if fmt == "parquet":
            return pd.read_parquet(buf)
        if fmt in ("xlsx", "xls"):
            return pd.read_excel(buf)
        if fmt == "json":
            return pd.read_json(buf)
        if fmt == "zip":
            with zipfile.ZipFile(buf) as zf:
                csvs = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csvs:
                    raise ValueError("ZIP 내부에 CSV 가 없습니다.")
                with zf.open(csvs[0]) as f:
                    return pd.read_csv(f)
        raise ValueError(f"Unknown format: {fmt}")

    def save_dataframe(self, df: Any, object_name: str, fmt: str = "parquet") -> str:
        buf = io.BytesIO()
        if fmt == "parquet":
            df.to_parquet(buf, index=False)
            ct = "application/octet-stream"
        elif fmt == "csv":
            df.to_csv(buf, index=False)
            ct = "text/csv"
        else:
            raise ValueError(f"Unknown format: {fmt}")
        buf.seek(0)
        return self.upload_bytes(buf.read(), object_name, content_type=ct)

    def save_model(self, model_obj: Any, object_name: str) -> str:
        import joblib  # noqa: WPS433

        with tempfile.NamedTemporaryFile(delete=False, suffix=".joblib") as f:
            joblib.dump(model_obj, f.name)
            tmp = f.name
        try:
            return self.upload_file(tmp, object_name)
        finally:
            os.unlink(tmp)

    def save_artifact(self, local_path: str, artifact_type: str, job_id: str) -> str:
        name = Path(local_path).name
        object_name = f"{artifact_type}/{job_id}/{name}"
        return self.upload_file(local_path, object_name)

    def list_objects(self, prefix: str = "") -> list[str]:
        paginator = self.s3.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def get_presigned_url(self, object_name: str, expiry: int = 3600) -> str:
        return self.s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_name},
            ExpiresIn=expiry,
        )

    def object_exists(self, object_name: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=object_name)
            return True
        except ClientError:
            return False


_singleton: Optional[MinIOClient] = None


def get_minio_client() -> MinIOClient:
    global _singleton
    if _singleton is None:
        _singleton = MinIOClient()
    return _singleton

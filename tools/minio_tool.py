"""tools.minio_tool — MinIO 공통 클라이언트 (Day05 §3).

S3 호환 boto3 클라이언트, 멱등/재시도/Presigned URL 헬퍼.
"""
from __future__ import annotations

import io
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from tenacity import retry, stop_after_attempt, wait_exponential

from ada.core.config import settings
from ada.core.logger import get_logger

log = get_logger("minio")


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
            config=Config(signature_version="s3v4"),
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
    def upload_bytes(self, body: bytes, object_name: str,
                     content_type: str = "application/octet-stream") -> str:
        self.s3.put_object(Bucket=self.bucket, Key=object_name,
                           Body=body, ContentType=content_type)
        return f"s3://{self.bucket}/{object_name}"

    def download_bytes(self, object_name: str) -> bytes:
        resp = self.s3.get_object(Bucket=self.bucket, Key=object_name)
        return resp["Body"].read()

    def load_dataframe(self, object_name: str, fmt: str = "csv") -> Any:
        """csv/parquet/xlsx/json/zip 자동 핸들링."""
        import pandas as pd  # noqa: WPS433

        body = self.download_bytes(object_name)
        buf = io.BytesIO(body)
        fmt = fmt.lower()
        if fmt in ("csv", "txt"):
            try:
                return pd.read_csv(buf, encoding="utf-8")
            except UnicodeDecodeError:
                buf.seek(0)
                try:
                    import chardet  # noqa: WPS433
                    enc = chardet.detect(body[:65536]).get("encoding") or "cp949"
                except Exception:
                    enc = "cp949"
                buf.seek(0)
                return pd.read_csv(buf, encoding=enc)
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

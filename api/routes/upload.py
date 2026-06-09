"""api.routes.upload — 업로드/프로파일 라우터 (Day06)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.db.models import Upload
from ada.db.session import get_db
from api.schemas.upload import ProfileResponse, UploadResponse
from tools.minio_tool import get_minio_client

router = APIRouter()

ALLOWED_EXTENSIONS = {".csv", ".tsv", ".parquet", ".zip", ".xlsx", ".xls", ".json", ".pdf", ".txt", ".html"}

# Magic byte 검증 (Day06 v2.4)
MAGIC_BYTES = {
    b"\x50\x4b\x03\x04": [".zip", ".xlsx"],  # ZIP (xlsx 포함)
    b"PAR1": [".parquet"],
    b"%PDF": [".pdf"],
}


def _check_magic(content: bytes, ext: str) -> bool:
    head = content[:8]
    for magic, exts in MAGIC_BYTES.items():
        if head.startswith(magic):
            return ext in exts
    # 그 외 텍스트류는 자유
    return ext in (".csv", ".tsv", ".txt", ".json", ".html")


@router.post("", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(422, detail=f"지원하지 않는 확장자: {ext}")

    content = await file.read()
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        actual_mb = len(content) / (1024 * 1024)
        raise HTTPException(
            413,
            detail=(
                f"파일 크기 초과 — 업로드 {actual_mb:.1f}MB > 상한 {settings.max_upload_size_mb}MB. "
                "큰 데이터는 샘플링 후 재업로드하거나 컬럼·기간을 좁혀 다시 시도해 주세요."
            ),
        )

    if not _check_magic(content, ext):
        raise HTTPException(422, detail="확장자와 매직바이트 불일치")

    sha = hashlib.sha256(content).hexdigest()

    # 중복 — sha256 기준
    dup = await db.scalar(select(Upload).where(Upload.sha256 == sha))
    if dup is not None:
        return UploadResponse(
            file_id=dup.file_id,
            filename=dup.filename,
            size_bytes=dup.size_bytes,
            sha256=dup.sha256,
            created_at=dup.created_at,
            minio_path=dup.minio_path,
            pii_columns=dup.pii_columns or [],
        )

    file_id = str(uuid.uuid4())
    object_name = f"uploads/{file_id}/{file.filename}"
    mc = get_minio_client()
    minio_path = mc.upload_bytes(content, object_name, content_type=file.content_type or "application/octet-stream")

    row = Upload(
        file_id=file_id,
        filename=file.filename or "",
        sha256=sha,
        size_bytes=len(content),
        minio_path=minio_path,
        original_mime=file.content_type,
        status="uploaded",
    )
    db.add(row)
    await db.flush()

    return UploadResponse(
        file_id=file_id,
        filename=row.filename,
        size_bytes=row.size_bytes,
        sha256=row.sha256,
        created_at=row.created_at or datetime.utcnow(),
        minio_path=row.minio_path,
        pii_columns=[],
    )


@router.get("/profile/{file_id}", response_model=ProfileResponse)
async def get_profile(file_id: str, db: AsyncSession = Depends(get_db)) -> ProfileResponse:
    row = await db.scalar(select(Upload).where(Upload.file_id == file_id))
    if row is None:
        raise HTTPException(404, detail="upload not found")
    return ProfileResponse(file_id=file_id, profile={"size_bytes": row.size_bytes, "filename": row.filename})


# ────────────────────────────────────────────────────────────
# HJ 2026-06-09 G1 단축 Phase 4 — θ-B + UI 연장 endpoint
# ────────────────────────────────────────────────────────────
# 파일 선택 시점 (정식 업로드 전) 에 frontend 가 헤더+sample 만 보냄.
# 백엔드는 카테고리·자동 의도 LLM 미리 시작 → Redis 캐시.
# 정식 업로드 후 data_profiler 가 동일 columns_signature 매칭 시 결과 회수.
# 효과: 사용자가 파일 선택 후 의도 입력하는 시간 ~10s 동안 카테고리 LLM (~15s) 흡수.
@router.post("/prefetch")
async def prefetch_analyze(payload: dict) -> dict:
    """파일 선택 시점 사전 분석.

    Body:
        columns: list[str]  — 파일의 컬럼명 (frontend 파싱)
        dtypes: dict[str, str] — 컬럼별 추정 dtype (선택)
        sample: list[dict]  — 첫 1~3행 sample (PII 위험 시 [])
        signature: str  — sha256(sorted_columns) frontend 가 미리 계산
        user_intent: str | None — 사용자 의도 텍스트 (선택, 의도 입력 중일 수 있음)

    Returns:
        signature, category, target_column, auto_intent, cached: bool
    """
    import asyncio as _aio
    import hashlib as _hash
    import json as _json
    import logging as _log

    import redis as _redis

    columns = payload.get("columns") or []
    dtypes = payload.get("dtypes") or {}
    sample = payload.get("sample") or []
    user_intent = (payload.get("user_intent") or "").strip()[:300]

    if not columns or not isinstance(columns, list):
        raise HTTPException(422, detail="columns 필수")

    # signature 재계산 (frontend 신뢰 안 함, 보안)
    sig_input = _json.dumps(sorted(map(str, columns)), ensure_ascii=False).encode("utf-8")
    signature = _hash.sha256(sig_input).hexdigest()[:32]

    r = _redis.Redis.from_url(settings.redis_url)
    cache_key = f"ada:prefetch:{signature}"

    # 캐시 히트 → 즉시 반환 (반복 사용자)
    try:
        cached_raw = r.get(cache_key)
        if cached_raw:
            cached_data = _json.loads(cached_raw)
            return {
                "signature": signature,
                "category": cached_data.get("category"),
                "target_column": cached_data.get("target_column"),
                "auto_intent": cached_data.get("auto_intent"),
                "cached": True,
            }
    except Exception:  # noqa: BLE001
        pass

    # 캐시 미스 → 카테고리 LLM 호출 (fire-and-forget 으로 캐시 채움, 응답은 즉시 잠정)
    # NOTE: BaseAgent / DataProfilerAgent import 체인이 matplotlib 등 worker-only 패키지를
    #       끌어당겨 API 컨테이너에서 ImportError 발생. Ollama HTTP 직접 호출로 우회.
    async def _do_prefetch_llm() -> None:
        try:
            import asyncio as _aio2
            import urllib.request as _ur

            _CATEGORY_PROMPT = (
                "데이터셋을 한 카테고리로 분류:\n"
                "- tabular_ml: 분류·회귀 정형\n"
                "- tabular_dl: 딥러닝 필요 정형\n"
                "- timeseries: 시간 차원 예측\n"
                "- anomaly_detection: 이상치·이탈 탐지\n"
                "예측 타겟 컬럼도 식별 (anomaly_detection 이면 null).\n"
                "한자·중국어 금지. reason 한국어 1문장.\n"
                'JSON 만: {"category":"tabular_ml","target_column":"price","reason":"한국어 1문장"}'
            )
            user_prompt = (
                f"columns: {columns}\n"
                f"dtypes: {_json.dumps(dtypes, ensure_ascii=False)}\n"
                f"sample_rows: {_json.dumps(sample[:3], ensure_ascii=False)[:2000]}\n"
                f"user_intent: {user_intent or 'none'}"
            )
            base_url = settings.ollama_base_url.rstrip("/")
            model = settings.ollama_model_analysis

            def _sync_call() -> str:
                body = _json.dumps(
                    {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": _CATEGORY_PROMPT},
                            {"role": "user", "content": user_prompt},
                        ],
                        "stream": False,
                        "format": "json",  # Ollama 구조화 출력 강제
                        "options": {"num_predict": 200, "temperature": 0.0, "top_p": 0.9},
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                req = _ur.Request(
                    f"{base_url}/api/chat",
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with _ur.urlopen(req, timeout=60) as resp:
                    data = _json.loads(resp.read())
                    return data.get("message", {}).get("content", "") or ""

            text = await _aio2.to_thread(_sync_call)
            parsed = _json.loads(text) if text.strip().startswith("{") else {}
            category = parsed.get("category") or "tabular_ml"
            target_column = parsed.get("target_column") or None
            auto_intent = ""
            if category and target_column:
                if category == "tabular_ml":
                    auto_intent = f"{target_column} 을 예측해 주세요"
                elif category == "timeseries":
                    auto_intent = f"{target_column} 의 미래 값을 예측해 주세요"
                elif category == "anomaly_detection":
                    auto_intent = "이상치를 찾아 주세요"
            payload_out = {
                "category": category,
                "target_column": target_column,
                "auto_intent": auto_intent,
                "ts": _hash.sha256(b"_").hexdigest()[:8],
            }
            r.setex(cache_key, 1800, _json.dumps(payload_out, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            _log.getLogger(__name__).warning("prefetch_llm_failed: %s", e)

    # 백그라운드 시작 (fire-and-forget) — 사용자 응답은 즉시
    _aio.create_task(_do_prefetch_llm())

    return {
        "signature": signature,
        "category": None,  # 아직 LLM 완료 안 됨
        "target_column": None,
        "auto_intent": None,
        "cached": False,
    }


@router.get("/prefetch/{signature}")
async def prefetch_status(signature: str) -> dict:
    """frontend 가 polling 으로 prefetch 결과 회수 (LLM 완료까지 ~15s)."""
    import json as _json

    import redis as _redis

    r = _redis.Redis.from_url(settings.redis_url)
    try:
        cached_raw = r.get(f"ada:prefetch:{signature}")
        if cached_raw:
            cached_data = _json.loads(cached_raw)
            return {"ready": True, **cached_data}
    except Exception:  # noqa: BLE001
        pass
    return {"ready": False}

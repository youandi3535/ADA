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

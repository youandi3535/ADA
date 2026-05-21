"""api.schemas.upload — 업로드 응답 스키마."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    size_bytes: int
    sha256: str
    created_at: datetime
    minio_path: str
    pii_columns: list[str] = []


class ProfileResponse(BaseModel):
    file_id: str
    profile: dict[str, Any]
    created_at: Optional[datetime] = None

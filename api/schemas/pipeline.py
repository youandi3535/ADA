"""api.schemas.pipeline — 파이프라인 요청/응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"]
GateCode = Literal["G0", "G1", "G2", "G3", "G4", "G5"]
OutputCode = Literal["OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"]


class PipelineStartRequest(BaseModel):
    file_id: str
    # 게이트 주도: 미지정 시 데이터 프로파일 기반 자동 탐지 → G1 에서 사용자 확인/override
    category: Optional[Category] = None
    target_column: Optional[str] = None
    user_question: Optional[str] = None
    user_intent: Optional[str] = None
    max_retries: int = Field(default=3, ge=1, le=10)
    requested_outputs: list[OutputCode] = Field(default_factory=list)


class PipelineStartResponse(BaseModel):
    job_id: str
    status: str = "pending"
    created_at: datetime
    estimated_duration_min: Optional[int] = None


class GateResponseRequest(BaseModel):
    gate: GateCode
    choice: dict[str, Any]


class PipelineResumeRequest(BaseModel):
    gate: GateCode
    choice: dict[str, Any]


class PipelineStatusResponse(BaseModel):
    job_id: str
    status: str
    category: Optional[str] = None  # 게이트 주도: 자동탐지/확정된 카테고리
    target_column: Optional[str] = None  # 자동탐지/확정된 타깃
    current_agent: Optional[str] = None
    current_gate: Optional[str] = None
    progress_pct: int = 0
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    requested_outputs: list[str] = []
    output_paths: dict[str, str] = {}

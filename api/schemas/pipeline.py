"""api.schemas.pipeline — 파이프라인 요청/응답 스키마."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"]
GateCode = Literal["G1", "G2", "G3", "G4", "G5", "G6"]
OutputCode = Literal["OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"]


class PipelineStartRequest(BaseModel):
    file_id: str
    # 게이트 주도: 미지정 시 데이터 프로파일 기반 자동 탐지 → G2 에서 사용자 확인/override
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
    # 단계 baseline ETA — 단계 시작 시점에 file_size/rows/cols 기반으로 계산된 잔여 초.
    # 프론트가 (현재시각 - eta_base_ts) 만큼 감소시켜 표시한다.
    eta_sec: Optional[int] = None
    eta_base_ts: Optional[float] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    requested_outputs: list[str] = []
    output_paths: dict[str, str] = {}


# ----- /pipeline/result 응답 스키마 (Day 11 — 웹 대시보드 표시) -----
class OutputItem(BaseModel):
    """outputs 테이블 한 행 + presigned URL.

    Frontend(Streamlit) 가 이 항목을 카드로 그려내고,
    OUT-04 는 components.html 로 인라인 임베드, 나머지는 download_button 으로 처리.
    """

    code: str  # OUT-01..04, OUT-07
    filename: str  # presentation.pptx 등
    minio_path: str  # s3://bucket/outputs/...
    size_bytes: Optional[int] = None
    generation_ms: Optional[int] = None
    status: str = "completed"
    url: Optional[str] = None  # presigned (1h)
    url_expires_in: int = 3600


class PipelineResultResponse(BaseModel):
    job_id: str
    status: str  # job 상태 (completed / running / failed ...)
    outputs: list[OutputItem] = []
    requested_outputs: list[str] = []  # 요청된 코드 (참고용)

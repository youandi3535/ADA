"""ada.db.models — SQLAlchemy ORM 모델 (Day02 v2 — 24 테이블).

v1 10 + v2 14 = 24 테이블 매핑.
- pgvector 컬럼은 ``pgvector.sqlalchemy.Vector(768)`` 사용.
- v2 스코프 축소(2026-05-18) 적용: image/NLP 카테고리, OUT-05/06/08-13 산출물 제거.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

try:  # pgvector — 시작 시점에 없을 수 있음
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    from sqlalchemy import LargeBinary as _LB

    def Vector(dim: int):  # type: ignore[override]
        return _LB()


from ada.db.session import Base

# =============================================================================
# v1 코어 (10 테이블)
# =============================================================================


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False)
    # v2 ALTER (§2)
    role = Column(String(16), default="analyst")
    password_hash = Column(String(128))
    last_login_at = Column(DateTime(timezone=True))
    is_active = Column(Boolean, default=True)
    mfa_secret = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Upload(Base):
    __tablename__ = "uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    file_id = Column(String(64), unique=True, nullable=False)
    filename = Column(String(512), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    size_bytes = Column(BigInteger, nullable=False)
    minio_path = Column(String(1024), nullable=False)
    # 4 카테고리: tabular_ml / tabular_dl / timeseries / anomaly_detection
    category = Column(String(64))
    status = Column(String(32), default="uploaded")
    # v2 ALTER (§2)
    original_mime = Column(String(128))
    pii_scan_status = Column(String(32), default="pending")
    pii_columns = Column(JSONB, default=list)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    file_id = Column(String(64), nullable=False)
    category = Column(String(64), nullable=False)
    target_column = Column(String(255))
    user_question = Column(Text)
    status = Column(String(32), default="pending")
    retry_count = Column(Integer, default=0)
    error_message = Column(Text)
    # v2 ALTER (§2)
    current_gate = Column(String(8))  # G0..G5
    auto_resolved = Column(Boolean, default=False)
    requested_outputs = Column(JSONB, default=list)  # ["OUT-01","OUT-04",...]
    user_intent = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    agent_runs = relationship("AgentRun", back_populates="job", cascade="all, delete")
    models = relationship("Model", back_populates="job", cascade="all, delete")
    outputs = relationship("Output", back_populates="job", cascade="all, delete")

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @property
    def is_terminal(self) -> bool:
        return self.status in ("completed", "failed")


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    agent_name = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    duration_ms = Column(Integer)
    error = Column(Text)
    # v2 ALTER (§2)
    gate = Column(String(8))
    was_re_loop = Column(Boolean, default=False)
    payload = Column(JSONB)  # Pydantic 직렬화
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    job = relationship("Job", back_populates="agent_runs")


class Model(Base):
    __tablename__ = "models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    model_name = Column(String(128), nullable=False)
    framework = Column(String(64), nullable=False)
    metrics = Column(JSONB)
    minio_path = Column(String(1024))
    mlflow_run_id = Column(String(64))
    is_best = Column(Boolean, default=False)
    # 보안: SHA256 모델 무결성 (Day08 R-704)
    model_sha256 = Column(String(64))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    job = relationship("Job", back_populates="models")


class Experiment(Base):
    __tablename__ = "experiments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    mlflow_experiment_id = Column(String(64))
    category = Column(String(64), nullable=False)
    status = Column(String(32), default="created")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    artifact_type = Column(String(64), nullable=False)
    minio_path = Column(String(1024), nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class FailureLog(Base):
    __tablename__ = "failure_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    error_hash = Column(String(64), nullable=False, index=True)
    error_category = Column(String(64))
    error_message = Column(Text)
    stack_trace = Column(Text)
    proposed_rule = Column(Text)
    confidence = Column(Float)
    # v2 ALTER (§2)
    auto_handled_by_kb = Column(Boolean, default=False)
    error_kb_id = Column(UUID(as_uuid=True), ForeignKey("error_kb.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class SuccessPattern(Base):
    """v1 호환 테이블 — v2 에서는 self_learning_kb 가 권위, 신규 INSERT 금지."""

    __tablename__ = "success_patterns"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category = Column(String(64), nullable=False)
    pattern_hash = Column(String(64), unique=True, nullable=False)
    description = Column(Text)
    config = Column(JSONB)
    success_count = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Rule(Base):
    __tablename__ = "rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_code = Column(String(16), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(64))
    confidence = Column(Float, default=1.0)
    is_active = Column(Boolean, default=True)
    author = Column(String(128))
    # v2 ALTER (§2)
    pgvector_embedding = Column(Vector(768))
    version = Column(String(16), default="1.0.0")
    superseded_by = Column(UUID(as_uuid=True), ForeignKey("rules.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# =============================================================================
# v2 신규 (14 테이블)
# =============================================================================


class AgentRegistry(Base):
    __tablename__ = "agent_registry"
    __table_args__ = (CheckConstraint("char_length(persona) <= 200", name="chk_persona_len"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_name = Column(String(128), unique=True, nullable=False)
    role = Column(String(64), nullable=False)
    description = Column(Text)
    llm_model = Column(String(64))  # claude-sonnet-4-6 / claude-opus-4-7 / none
    persona = Column(Text, nullable=False, default="")
    persona_version = Column(String(16), default="v2.0")
    inputs = Column(JSONB, default=list)
    outputs = Column(JSONB, default=list)
    capabilities = Column(JSONB, default=list)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class InteractiveSession(Base):
    __tablename__ = "interactive_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    gate = Column(String(8), nullable=False)
    proposals = Column(JSONB)
    user_choice = Column(JSONB)
    auto_resolved = Column(Boolean, default=False)
    response_latency_sec = Column(Integer)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at = Column(DateTime(timezone=True))


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        UUID(as_uuid=True),
        ForeignKey("interactive_sessions.id", ondelete="CASCADE"),
    )
    adopted_rank = Column(Integer)
    rationale = Column(Text)
    recommended = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class SelfLearningKB(Base):
    """5종 KB 통합 단일 테이블 (마스터 §11.1 권위)."""

    __tablename__ = "self_learning_kb"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kb_type = Column(
        String(32), nullable=False
    )  # success_pattern / recipe / eda_template / hpo_warm_start / failure_lesson
    category = Column(String(64))
    hash = Column(String(64), unique=True)
    payload = Column(JSONB, nullable=False)
    embedding = Column(Vector(768))
    success_count = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)
    source_job_ids = Column(ARRAY(UUID(as_uuid=True)))
    created_by = Column(UUID(as_uuid=True))  # RLS
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class DatasetEmbedding(Base):
    __tablename__ = "dataset_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    upload_id = Column(UUID(as_uuid=True), ForeignKey("uploads.id", ondelete="CASCADE"))
    target = Column(Text)
    embedding = Column(Vector(768))
    created_by = Column(UUID(as_uuid=True))  # RLS
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class IntentEmbedding(Base):
    __tablename__ = "intent_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    target = Column(Text)  # user_intent 텍스트
    embedding = Column(Vector(768))
    created_by = Column(UUID(as_uuid=True))  # RLS
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class LessonEmbedding(Base):
    __tablename__ = "lesson_embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # UNIQUE — KBRAG.index_lesson 이 ON CONFLICT (kb_id) DO UPDATE 패턴 사용 (migration 0003).
    kb_id = Column(
        UUID(as_uuid=True),
        ForeignKey("self_learning_kb.id", ondelete="CASCADE"),
        unique=True,
    )
    target = Column(Text)
    embedding = Column(Vector(768))
    created_by = Column(UUID(as_uuid=True))  # RLS
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ErrorKB(Base):
    __tablename__ = "error_kb"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    error_hash = Column(String(64), unique=True, nullable=False)
    error_signature = Column(Text)
    fingerprint = Column(JSONB)  # stage / model / error_type
    resolution = Column(Text)
    patch_minio_path = Column(String(1024))
    success_count = Column(Integer, default=0)
    fail_count = Column(Integer, default=0)
    confidence = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)


class SecurityAuditLog(Base):
    __tablename__ = "security_audit_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(64), nullable=False)  # login / logout / api / agent / kb / output / security
    actor_user_id = Column(UUID(as_uuid=True))
    actor_role = Column(String(32))
    resource = Column(String(255))
    action = Column(String(64))
    result = Column(String(16))  # success / failure / blocked
    ip_address = Column(String(64))
    user_agent = Column(Text)
    details = Column(JSONB)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)


class Output(Base):
    __tablename__ = "outputs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"))
    output_code = Column(String(16), nullable=False)  # OUT-01..04, OUT-07
    minio_path = Column(String(1024), nullable=False)
    file_size_bytes = Column(BigInteger)
    generation_ms = Column(Integer)
    status = Column(String(16), default="completed")
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    job = relationship("Job", back_populates="outputs")


class PendingPatch(Base):
    __tablename__ = "pending_patches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    error_kb_id = Column(UUID(as_uuid=True), ForeignKey("error_kb.id"))
    patch_diff = Column(Text)
    test_plan = Column(Text)
    confidence = Column(Float)
    review_status = Column(String(16), default="pending")  # pending / approved / rejected
    reviewer = Column(String(128))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class JobDistillationLog(Base):
    __tablename__ = "job_distillation_log"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    kb_type = Column(String(32))
    kb_id = Column(UUID(as_uuid=True), ForeignKey("self_learning_kb.id"))
    distilled_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    notes = Column(Text)


class OutputRecipe(Base):
    __tablename__ = "output_recipes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    intent_pattern = Column(Text)
    recommended_outputs = Column(JSONB)  # ["OUT-01","OUT-04"]
    confidence = Column(Float, default=0.5)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class GateDecisionMetric(Base):
    __tablename__ = "gate_decision_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gate = Column(String(8), nullable=False)
    proposed_rank = Column(Integer)
    adopted_rank = Column(Integer)
    match = Column(Boolean)
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# =============================================================================
# v2.2 보강 — Day-A 백업/모델 카탈로그 placeholder
# =============================================================================


class BackupCatalog(Base):
    __tablename__ = "backup_catalog"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backup_type = Column(String(32))  # db / data / vault
    minio_path = Column(String(1024))
    sha256 = Column(String(64))
    size_bytes = Column(BigInteger)
    status = Column(String(16), default="ok")
    note = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class ModelArtifactCatalog(Base):
    __tablename__ = "model_artifact_catalog"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id = Column(UUID(as_uuid=True), ForeignKey("models.id"))
    sha256 = Column(String(64), nullable=False)
    cosign_sig = Column(Text)
    verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# =============================================================================
# 팀 Q&A 수집 — Claude Code 대화 로그 (KB 학습 원천 데이터)
# =============================================================================


class ConversationLog(Base):
    """팀원의 Claude Code 대화 1쌍 (질문 + 답변) 저장.

    flow:
        VS Code Stop 훅 → POST /kb/conversation → 이 테이블
        리눅스 서버 동기화 → 임베딩 → SelfLearningKB → processed=True
    """

    __tablename__ = "conversation_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_member = Column(String(128))  # git user or env 설정
    question = Column(Text, nullable=False)  # 팀원 질문
    answer = Column(Text, nullable=False)  # Claude 답변
    session_id = Column(String(64), index=True)  # Claude Code session ID
    project = Column(String(255))  # 프로젝트명
    source = Column(String(32), default="claude_code")  # claude_code / manual
    processed = Column(Boolean, default=False, index=True)  # 임베딩 완료?
    kb_id = Column(UUID(as_uuid=True), ForeignKey("self_learning_kb.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, index=True)


__all__ = [
    "User",
    "Upload",
    "Job",
    "AgentRun",
    "Model",
    "Experiment",
    "Artifact",
    "FailureLog",
    "SuccessPattern",
    "Rule",
    "AgentRegistry",
    "InteractiveSession",
    "Decision",
    "SelfLearningKB",
    "DatasetEmbedding",
    "IntentEmbedding",
    "LessonEmbedding",
    "ErrorKB",
    "SecurityAuditLog",
    "Output",
    "PendingPatch",
    "JobDistillationLog",
    "OutputRecipe",
    "GateDecisionMetric",
    "BackupCatalog",
    "ModelArtifactCatalog",
    "ConversationLog",
]

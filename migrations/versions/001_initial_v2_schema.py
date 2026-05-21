"""initial v2 schema — 24 tables + indexes + RLS + pgvector

Revision ID: 0001_initial_v2
Revises:
Create Date: 2026-05-21

작업지시서: Day02 v2 §1~§5 + v2.2 §1~§5 통합 베이스라인.
- v1 10 + v2 14 = 24 테이블
- pgvector IVFFlat 인덱스
- RLS 5개 민감 테이블
- JSONB GIN 인덱스
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_v2"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===== Extensions ========================================================
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "btree_gin";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector";')
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    # ===== users =============================================================
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("role", sa.String(16), server_default="analyst"),
        sa.Column("password_hash", sa.String(128)),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("mfa_secret", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== uploads ===========================================================
    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("file_id", sa.String(64), unique=True, nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("minio_path", sa.String(1024), nullable=False),
        sa.Column("category", sa.String(64)),
        sa.Column("status", sa.String(32), server_default="uploaded"),
        sa.Column("original_mime", sa.String(128)),
        sa.Column("pii_scan_status", sa.String(32), server_default="pending"),
        sa.Column("pii_columns", postgresql.JSONB, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_uploads_user", "uploads", ["user_id"])
    op.create_index("idx_uploads_sha256", "uploads", ["sha256"], unique=True)

    # ===== jobs ==============================================================
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("file_id", sa.String(64), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("target_column", sa.String(255)),
        sa.Column("user_question", sa.Text),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text),
        sa.Column("current_gate", sa.String(8)),
        sa.Column("auto_resolved", sa.Boolean, server_default=sa.false()),
        sa.Column("requested_outputs", postgresql.JSONB, server_default="[]"),
        sa.Column("user_intent", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_jobs_user", "jobs", ["user_id"])
    op.create_index("idx_jobs_status", "jobs", ["status"])

    # ===== agent_runs ========================================================
    op.create_table(
        "agent_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("agent_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("input_tokens", sa.Integer, server_default="0"),
        sa.Column("output_tokens", sa.Integer, server_default="0"),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("error", sa.Text),
        sa.Column("gate", sa.String(8)),
        sa.Column("was_re_loop", sa.Boolean, server_default=sa.false()),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_agent_runs_job", "agent_runs", ["job_id"])
    op.create_index("idx_agent_runs_agent", "agent_runs", ["agent_name"])
    op.execute(
        "CREATE INDEX idx_agent_runs_payload_gin ON agent_runs USING gin (payload);"
    )

    # ===== models ============================================================
    op.create_table(
        "models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("model_name", sa.String(128), nullable=False),
        sa.Column("framework", sa.String(64), nullable=False),
        sa.Column("metrics", postgresql.JSONB),
        sa.Column("minio_path", sa.String(1024)),
        sa.Column("mlflow_run_id", sa.String(64)),
        sa.Column("is_best", sa.Boolean, server_default=sa.false()),
        sa.Column("model_sha256", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_models_job", "models", ["job_id"])
    op.execute(
        "CREATE INDEX idx_models_metrics_gin ON models USING gin (metrics);"
    )

    # ===== experiments =======================================================
    op.create_table(
        "experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("mlflow_experiment_id", sa.String(64)),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="created"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== artifacts =========================================================
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("artifact_type", sa.String(64), nullable=False),
        sa.Column("minio_path", sa.String(1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== error_kb (먼저 — failure_logs FK 대상) ============================
    op.create_table(
        "error_kb",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("error_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("error_signature", sa.Text),
        sa.Column("fingerprint", postgresql.JSONB),
        sa.Column("resolution", sa.Text),
        sa.Column("patch_minio_path", sa.String(1024)),
        sa.Column("success_count", sa.Integer, server_default="0"),
        sa.Column("fail_count", sa.Integer, server_default="0"),
        sa.Column("confidence", sa.Float, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== failure_logs ======================================================
    op.create_table(
        "failure_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("error_hash", sa.String(64), nullable=False),
        sa.Column("error_category", sa.String(64)),
        sa.Column("error_message", sa.Text),
        sa.Column("stack_trace", sa.Text),
        sa.Column("proposed_rule", sa.Text),
        sa.Column("confidence", sa.Float),
        sa.Column("auto_handled_by_kb", sa.Boolean, server_default=sa.false()),
        sa.Column("error_kb_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("error_kb.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_failure_logs_hash", "failure_logs", ["error_hash"])

    # ===== success_patterns (v1 호환) =======================================
    op.create_table(
        "success_patterns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("pattern_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("config", postgresql.JSONB),
        sa.Column("success_count", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== rules =============================================================
    op.create_table(
        "rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("rule_code", sa.String(16), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("category", sa.String(64)),
        sa.Column("confidence", sa.Float, server_default="1.0"),
        sa.Column("is_active", sa.Boolean, server_default=sa.true()),
        sa.Column("author", sa.String(128)),
        sa.Column("pgvector_embedding", sa.dialects.postgresql.ARRAY(sa.Float)),  # Vector(768) — driver-specific
        sa.Column("version", sa.String(16), server_default="1.0.0"),
        sa.Column("superseded_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_rules_active", "rules", ["is_active", "category"])
    # Vector 컬럼 변환 (pgvector)
    op.execute("ALTER TABLE rules ALTER COLUMN pgvector_embedding TYPE vector(768) USING NULL;")

    # ===== agent_registry ====================================================
    op.create_table(
        "agent_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("agent_name", sa.String(128), unique=True, nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("llm_model", sa.String(64)),
        sa.Column("persona", sa.Text, nullable=False, server_default=""),
        sa.Column("persona_version", sa.String(16), server_default="v2.0"),
        sa.Column("inputs", postgresql.JSONB, server_default="[]"),
        sa.Column("outputs", postgresql.JSONB, server_default="[]"),
        sa.Column("capabilities", postgresql.JSONB, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("char_length(persona) <= 200", name="chk_persona_len"),
    )

    # ===== interactive_sessions / decisions =================================
    op.create_table(
        "interactive_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("gate", sa.String(8), nullable=False),
        sa.Column("proposals", postgresql.JSONB),
        sa.Column("user_choice", postgresql.JSONB),
        sa.Column("auto_resolved", sa.Boolean, server_default=sa.false()),
        sa.Column("response_latency_sec", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
    )
    op.create_index("idx_isession_job_gate", "interactive_sessions", ["job_id", "gate"])
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("interactive_sessions.id", ondelete="CASCADE")),
        sa.Column("adopted_rank", sa.Integer),
        sa.Column("rationale", sa.Text),
        sa.Column("recommended", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== self_learning_kb + embeddings ====================================
    op.create_table(
        "self_learning_kb",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("kb_type", sa.String(32), nullable=False),
        sa.Column("category", sa.String(64)),
        sa.Column("hash", sa.String(64), unique=True),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("success_count", sa.Integer, server_default="1"),
        sa.Column("confidence", sa.Float, server_default="0.5"),
        sa.Column("source_job_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True))),
        sa.Column("created_by", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.execute("ALTER TABLE self_learning_kb ADD COLUMN embedding vector(768);")
    op.create_index("idx_kb_type_cat", "self_learning_kb", ["kb_type", "category"])
    op.execute(
        "CREATE INDEX idx_kb_emb ON self_learning_kb "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists=100);"
    )

    for tbl, fk_col, fk_target in [
        ("dataset_embeddings", "upload_id", "uploads.id"),
        ("intent_embeddings", "job_id", "jobs.id"),
        ("lesson_embeddings", "kb_id", "self_learning_kb.id"),
    ]:
        op.create_table(
            tbl,
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                      server_default=sa.text("uuid_generate_v4()")),
            sa.Column(fk_col, postgresql.UUID(as_uuid=True),
                      sa.ForeignKey(fk_target, ondelete="CASCADE")),
            sa.Column("target", sa.Text),
            sa.Column("created_by", postgresql.UUID(as_uuid=True)),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.execute(f"ALTER TABLE {tbl} ADD COLUMN embedding vector(768);")
        op.execute(
            f"CREATE INDEX idx_{tbl}_emb ON {tbl} USING ivfflat "
            "(embedding vector_cosine_ops) WITH (lists=100);"
        )

    # ===== security_audit_log ===============================================
    op.create_table(
        "security_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_role", sa.String(32)),
        sa.Column("resource", sa.String(255)),
        sa.Column("action", sa.String(64)),
        sa.Column("result", sa.String(16)),
        sa.Column("ip_address", sa.String(64)),
        sa.Column("user_agent", sa.Text),
        sa.Column("details", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_audit_created_at", "security_audit_log", ["created_at"])

    # ===== outputs / pending_patches / job_distillation_log ================
    op.create_table(
        "outputs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("jobs.id", ondelete="CASCADE")),
        sa.Column("output_code", sa.String(16), nullable=False),
        sa.Column("minio_path", sa.String(1024), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger),
        sa.Column("generation_ms", sa.Integer),
        sa.Column("status", sa.String(16), server_default="completed"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_outputs_job", "outputs", ["job_id"])

    op.create_table(
        "pending_patches",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("error_kb_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("error_kb.id")),
        sa.Column("patch_diff", sa.Text),
        sa.Column("test_plan", sa.Text),
        sa.Column("confidence", sa.Float),
        sa.Column("review_status", sa.String(16), server_default="pending"),
        sa.Column("reviewer", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "job_distillation_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id")),
        sa.Column("kb_type", sa.String(32)),
        sa.Column("kb_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("self_learning_kb.id")),
        sa.Column("distilled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notes", sa.Text),
    )

    op.create_table(
        "output_recipes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("intent_pattern", sa.Text),
        sa.Column("recommended_outputs", postgresql.JSONB),
        sa.Column("confidence", sa.Float, server_default="0.5"),
        sa.Column("usage_count", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "gate_decision_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("gate", sa.String(8), nullable=False),
        sa.Column("proposed_rank", sa.Integer),
        sa.Column("adopted_rank", sa.Integer),
        sa.Column("match", sa.Boolean),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("jobs.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== v2.2 Day-A placeholders ===========================================
    op.create_table(
        "backup_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("backup_type", sa.String(32)),
        sa.Column("minio_path", sa.String(1024)),
        sa.Column("sha256", sa.String(64)),
        sa.Column("size_bytes", sa.BigInteger),
        sa.Column("status", sa.String(16), server_default="ok"),
        sa.Column("note", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "model_artifact_catalog",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("model_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("models.id")),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("cosign_sig", sa.Text),
        sa.Column("verified", sa.Boolean, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ===== RLS — v2.2 §2 ===================================================
    for tbl in (
        "self_learning_kb",
        "dataset_embeddings",
        "intent_embeddings",
        "lesson_embeddings",
        "security_audit_log",
    ):
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY;")

    op.execute(
        """
        CREATE POLICY kb_owner_policy ON self_learning_kb
          USING (created_by = NULLIF(current_setting('ada.current_user', true), '')::uuid
                 OR current_setting('ada.role', true) = 'admin');
        """
    )
    for tbl in ("dataset_embeddings", "intent_embeddings", "lesson_embeddings"):
        op.execute(
            f"""
            CREATE POLICY {tbl}_owner_policy ON {tbl}
              USING (created_by = NULLIF(current_setting('ada.current_user', true), '')::uuid
                     OR current_setting('ada.role', true) = 'admin');
            """
        )
    op.execute(
        """
        CREATE POLICY audit_admin_only ON security_audit_log
          USING (current_setting('ada.role', true) IN ('admin','service'));
        """
    )


def downgrade() -> None:
    for tbl in [
        "model_artifact_catalog", "backup_catalog", "gate_decision_metrics",
        "output_recipes", "job_distillation_log", "pending_patches", "outputs",
        "security_audit_log", "lesson_embeddings", "intent_embeddings",
        "dataset_embeddings", "self_learning_kb", "decisions",
        "interactive_sessions", "agent_registry", "rules", "success_patterns",
        "failure_logs", "error_kb", "artifacts", "experiments", "models",
        "agent_runs", "jobs", "uploads", "users",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {tbl} CASCADE;")

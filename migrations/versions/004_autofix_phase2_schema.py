"""ADR-006 Phase 2-F — Auto Error Resolution 운영 스키마.

Revision ID: 0004_autofix_phase2
Revises: 0003_lesson_unique
Create Date: 2026-05-27

목적:
    Phase 2-A (PII redactor) ~ Phase 2-E (sandbox) 의 영구화 + 운영 audit 추가.

변경:
    1. failure_logs ALTER — 4 컬럼 + 부분 인덱스
        - raw_error_encrypted (BYTEA)   : AES-GCM 암호화 원본 (KMS 키 분리)
        - redaction_types (JSONB)        : ["EMAIL", "PHONE", ...] audit
        - classified_as (VARCHAR(32))    : transient | code_bug | config | data | user_input | unknown
        - severity (VARCHAR(16))         : low | normal | high | critical
        - idx_failure_logs_hash_unhandled: 폴링 데몬 빠른 조회 (미처리 만)

    2. CREATE TABLE patch_applications  : 패치 적용 시도 audit log
    3. CREATE TABLE circuit_breaker_events: 회로 차단 상태 영구 기록

운영 영향:
    - 모든 변경은 ADD COLUMN / CREATE — 기존 데이터 손실 없음
    - PII 원본 (raw_error_encrypted) 는 KMS 키 분리 보관, downgrade 시 정보 손실 가능
    - 부분 인덱스 (postgresql_where) 는 PostgreSQL 전용

테스트 후 적용:
    alembic upgrade head
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_autofix_phase2"
down_revision: Union[str, None] = "0003_lesson_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) failure_logs — ADR-006 §5.1 (4 컬럼 + 1 인덱스)
    # ------------------------------------------------------------------
    op.add_column(
        "failure_logs",
        sa.Column("raw_error_encrypted", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "failure_logs",
        sa.Column(
            "redaction_types",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "failure_logs",
        sa.Column("classified_as", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "failure_logs",
        sa.Column(
            "severity",
            sa.String(length=16),
            nullable=True,
            server_default=sa.text("'normal'"),
        ),
    )

    # 폴링 데몬 빠른 조회 — 미처리 (auto_handled_by_kb=false) 인 행만 인덱싱
    # 운영 통계: 처리 완료 행이 압도적 다수 → 부분 인덱스로 80%+ 공간 절약
    op.create_index(
        "idx_failure_logs_hash_unhandled",
        "failure_logs",
        ["error_hash"],
        postgresql_where=sa.text("auto_handled_by_kb = false"),
    )

    # ------------------------------------------------------------------
    # 2) patch_applications — 패치 적용 audit
    # ------------------------------------------------------------------
    op.create_table(
        "patch_applications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pending_patch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pending_patches.id"),
        ),
        sa.Column(
            "error_kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("error_kb.id"),
        ),
        sa.Column("applied_by", sa.String(64)),
        sa.Column(
            "applied_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "sandbox_validation",
            postgresql.JSONB(astext_type=sa.Text()),
        ),
        sa.Column("git_commit_sha", sa.String(64)),
        sa.Column("rollback_commit_sha", sa.String(64)),
        sa.Column("status", sa.String(16)),  # success | rolled_back | failed
        sa.Column("duration_ms", sa.Integer()),
    )
    op.create_index(
        "idx_patch_apps_kb",
        "patch_applications",
        ["error_kb_id"],
    )
    op.create_index(
        "idx_patch_apps_time",
        "patch_applications",
        [sa.text("applied_at DESC")],
    )

    # ------------------------------------------------------------------
    # 3) circuit_breaker_events — Redis 외 영구 모니터링 채널
    # ------------------------------------------------------------------
    op.create_table(
        "circuit_breaker_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("breaker_name", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(16)),  # opened | half_open | closed
        sa.Column("failure_count", sa.Integer()),
        sa.Column("opened_at", sa.DateTime(timezone=True)),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "idx_cb_events_name",
        "circuit_breaker_events",
        ["breaker_name"],
    )
    op.create_index(
        "idx_cb_events_time",
        "circuit_breaker_events",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # 신규 테이블부터 (FK 역순)
    op.drop_index("idx_cb_events_time", table_name="circuit_breaker_events")
    op.drop_index("idx_cb_events_name", table_name="circuit_breaker_events")
    op.drop_table("circuit_breaker_events")

    op.drop_index("idx_patch_apps_time", table_name="patch_applications")
    op.drop_index("idx_patch_apps_kb", table_name="patch_applications")
    op.drop_table("patch_applications")

    # failure_logs 인덱스 + 컬럼
    op.drop_index("idx_failure_logs_hash_unhandled", table_name="failure_logs")
    op.drop_column("failure_logs", "severity")
    op.drop_column("failure_logs", "classified_as")
    op.drop_column("failure_logs", "redaction_types")
    op.drop_column("failure_logs", "raw_error_encrypted")

"""conversation_logs 테이블 추가 — 팀 Q&A 수집 (KB 학습 원천)

Revision ID: 0002_conversation_log
Revises: 0001_initial_v2
Create Date: 2026-05-25
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_conversation_log"
down_revision: Union[str, None] = "0001_initial_v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("team_member", sa.String(128), nullable=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("project", sa.String(255), nullable=True),
        sa.Column("source", sa.String(32), server_default="claude_code"),
        sa.Column("processed", sa.Boolean, server_default="false", nullable=False),
        sa.Column(
            "kb_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("self_learning_kb.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_conversation_logs_session_id", "conversation_logs", ["session_id"])
    op.create_index("ix_conversation_logs_processed", "conversation_logs", ["processed"])
    op.create_index("ix_conversation_logs_created_at", "conversation_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_conversation_logs_created_at", "conversation_logs")
    op.drop_index("ix_conversation_logs_processed", "conversation_logs")
    op.drop_index("ix_conversation_logs_session_id", "conversation_logs")
    op.drop_table("conversation_logs")

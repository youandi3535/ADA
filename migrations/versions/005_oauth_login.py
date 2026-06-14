"""v1 구글 OAuth 로그인 — oauth_accounts 신규 + users 확장.

Revision ID: 0005_oauth_login
Revises: 0004_autofix_phase2
Create Date: 2026-06-14

목적:
    소셜(구글) 로그인 v1 도입. 인증(누구인가)은 구글에 위임하고,
    우리 DB 에는 구글 sub(고유 ID)만 보관한다. 비밀번호는 저장하지 않는다.

변경:
    1. users ALTER — 3 컬럼 추가
        - name (VARCHAR(100))         : 구글 프로필 이름 (표시용)
        - is_verified (BOOLEAN)        : 이메일 인증 여부 (구글 로그인=true)
        - updated_at (TIMESTAMPTZ)     : 갱신 시각
        ※ password_hash 는 migration 001 부터 이미 nullable → 구글 전용 사용자 INSERT 가능
    2. CREATE TABLE oauth_accounts     : 소셜 연동 (1 user : N provider)
        - UNIQUE(provider, provider_account_id) : 같은 구글 계정 중복 연동 방지

로그인 이력(사용 기록)은 신규 테이블을 만들지 않고 기존 security_audit_log
(event_type='login') 를 재사용한다 — IP/user_agent/성공·실패가 이미 적재됨.

운영 영향:
    - 전부 ADD COLUMN / CREATE — 기존 데이터 손실 없음.
    - is_verified 는 server_default=false → 기존 사용자 행은 false 로 채워짐.

테스트 후 적용:
    alembic upgrade head
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_oauth_login"
down_revision: Union[str, None] = "0004_autofix_phase2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) users — 3 컬럼 추가 (구글 프로필/인증 상태)
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column("name", sa.String(length=100), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2) oauth_accounts — 소셜 연동 (1 user : N provider)
    # ------------------------------------------------------------------
    op.create_table(
        "oauth_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=20), nullable=False),  # 'google'
        sa.Column("provider_account_id", sa.String(length=255), nullable=False),  # 구글 sub
        sa.Column("email", sa.String(length=255)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_oauth_provider_account",
        ),
    )
    op.create_index("idx_oauth_accounts_user", "oauth_accounts", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_oauth_accounts_user", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "is_verified")
    op.drop_column("users", "name")

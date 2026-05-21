"""Alembic env.py  -  ADA v2 마이그레이션 진입점.

DATABASE_URL 환경변수를 그대로 사용한다 (코드 내 시크릿 하드코딩 금지, R-001).
Day02 부터 alembic revision --autogenerate 로 실제 테이블 추가.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config 로딩
config = context.config

# 로그 설정 (alembic.ini)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL 주입 (도커 안: postgres:5432, 호스트: localhost:5433)
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://autoai:changeme@localhost:5433/autoai",
)
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# 모델 메타데이터 — Day02 에서 ada.db.models 가 만들어지면 import
try:
    from ada.db.models import Base  # noqa: WPS433

    target_metadata = Base.metadata
except Exception:  # pragma: no cover - Day01 시점에는 ada.db 가 비어있을 수 있음
    target_metadata = None


def run_migrations_offline() -> None:
    """Offline mode — URL 만 사용, Engine 없음."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Online mode — Engine 으로 실제 DB 에 연결."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

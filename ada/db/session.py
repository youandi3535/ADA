"""ada.db.session — SQLAlchemy 비동기 엔진/세션.

Day02 §3 + v2.2 RLS 미들웨어 진입점.
"""

from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

# --- URL 정규화 ---------------------------------------------------------------
RAW_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://autoai:changeme@postgres:5432/autoai",
)

# postgresql:// → postgresql+asyncpg:// 자동 변환 (작업지시서 §3.1)
if RAW_URL.startswith("postgresql+asyncpg://"):
    ASYNC_URL = RAW_URL
elif RAW_URL.startswith("postgresql://"):
    ASYNC_URL = RAW_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    ASYNC_URL = RAW_URL

# --- Engine + Session --------------------------------------------------------
engine = create_async_engine(
    ASYNC_URL,
    pool_size=int(os.environ.get("DB_POOL_SIZE", "20")),
    max_overflow=int(os.environ.get("DB_POOL_OVERFLOW", "10")),
    pool_timeout=30,
    pool_pre_ping=True,
    echo=os.environ.get("LOG_LEVEL", "INFO").upper() == "DEBUG",
)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# --- FastAPI Depends ---------------------------------------------------------
async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 라우터용 비동기 세션 제너레이터.

    Celery 워커에서는 이 함수를 쓰지 말고 `AsyncSessionLocal()` 직접 사용.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """앱 부팅 시 테이블 생성 (개발/테스트). 운영은 Alembic 우선."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def set_rls_user(session: AsyncSession, user_id: str | None, role: str = "analyst") -> None:
    """v2.2 RLS 미들웨어 — 세션 단위 변수 설정.

    Postgres 의 `current_setting('ada.current_user', true)` 와 매칭된다.
    """
    if user_id:
        await session.execute(
            text("SELECT set_config('ada.current_user', :uid, true)"),
            {"uid": user_id},
        )
    await session.execute(
        text("SELECT set_config('ada.role', :role, true)"),
        {"role": role},
    )

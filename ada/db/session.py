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
# HJ 2026-06-15 — Celery 워커는 태스크마다 asyncio.run() 으로 새 이벤트루프를 만든다.
#   QueuePool 에 캐시된 asyncpg 커넥션은 그 커넥션을 생성한 (이전·이미 닫힌) 루프에 묶여 있어,
#   다음 태스크의 새 루프에서 재사용하면 "Event loop is closed / Future attached to a different
#   loop" 가 난다(_set_job_terminal 등 status/progress 갱신 간헐 실패의 근본 원인).
#   → 워커에서는 NullPool(풀링 없음): 매 세션마다 현재 루프에 묶인 새 커넥션을 만들고 세션 종료 시
#     즉시 닫아 루프 간 재사용을 원천 차단. 워커 태스크는 초·분 단위라 커넥션 생성 오버헤드(수 ms)는
#     무시 가능하다. API(uvicorn, 단일 장수 루프)는 성능을 위해 기존 QueuePool 을 유지한다.
_DB_POOL_OVERRIDE = os.environ.get("ADA_DB_POOL", "").strip().lower()


def _use_nullpool() -> bool:
    if _DB_POOL_OVERRIDE in ("null", "nullpool"):  # 운영/테스트 강제 오버라이드 우선
        return True
    if _DB_POOL_OVERRIDE in ("pool", "queuepool", "default"):
        return False
    import sys as _sys  # noqa: WPS433

    _argv = " ".join(_sys.argv).lower()  # celery worker/beat 프로세스 자동 감지
    return "celery" in _argv and ("worker" in _argv or "beat" in _argv)


if _use_nullpool():
    from sqlalchemy.pool import NullPool  # noqa: WPS433

    engine = create_async_engine(
        ASYNC_URL,
        poolclass=NullPool,  # 커넥션 풀링 비활성 — 루프 간 커넥션 재사용 차단
        echo=os.environ.get("LOG_LEVEL", "INFO").upper() == "DEBUG",
    )
else:
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

    ⚠️ 현재 상태 (2026-06-04):
        본 함수가 정의돼 있으나 ``get_db`` 의존성 체인에서 호출되지 않는다.
        Postgres RLS 정책을 실제로 활성화하려면 인증 미들웨어가 JWT 디코딩 후
        ``set_rls_user(session, user.id, user.role)`` 를 호출해야 한다.
        ``get_db_rls`` (아래) 를 사용하면 헤더에서 user_id 를 받아 적용 가능.
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


async def get_db_rls(
    x_user_id: str | None = None,
    x_role: str = "analyst",
) -> AsyncIterator[AsyncSession]:
    """RLS 가 적용된 세션 의존성.

    FastAPI 라우터에서 직접 의존성으로 쓰지 말고, 인증 미들웨어가
    Request.state.user_id / role 을 채운 뒤 본 함수를 호출해 사용한다.
    또는 헤더(X-User-Id) 기반 fallback. user_id 가 None 이면 RLS bypass 상황.

    Postgres 측 RLS 정책(migrations/001) 이 ``current_setting('ada.current_user')``
    를 참조하므로 세션 시작 시 SET 해야 행 단위 격리가 발동한다.
    """
    async with AsyncSessionLocal() as session:
        try:
            await set_rls_user(session, x_user_id, x_role)
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

"""api.routes.observability — Day 10 운영 관측 라우터 (HJ).

엔드포인트:
    GET /admin/observability/kpi   5종 KPI 측정 결과 (admin RBAC)

캐싱:
    settings.kpi_cache_ttl_seconds 초 동안 in-memory 캐시.
    ?cache=bypass 로 강제 갱신.

응답 헤더:
    X-KPI-Cache-Status: fresh | cached
    X-KPI-Cache-Age:    캐시 age (초)
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.db.session import get_db
from ada.observability.kpi import KPIResponse, compute_kpis, parse_window
from ada.security.rbac import require_perm

router = APIRouter(prefix="/admin/observability", tags=["Admin", "Observability"])

_admin_only = require_perm("admin.audit.read")

# ---------------------------------------------------------------------------
# in-memory TTL 캐시 (Phase 12-1)
# ---------------------------------------------------------------------------

_cache: dict[Any, tuple[float, KPIResponse]] = {}


def _cache_get(key: Any) -> tuple[KPIResponse, float] | None:
    """캐시 조회. (value, age_sec) 또는 None."""
    ttl = settings.kpi_cache_ttl_seconds
    if ttl <= 0:
        return None
    entry = _cache.get(key)
    if entry is None:
        return None
    cached_at, value = entry
    age = time.monotonic() - cached_at
    if age >= ttl:
        _cache.pop(key, None)
        return None
    return value, age


def _cache_put(key: Any, value: KPIResponse) -> None:
    if settings.kpi_cache_ttl_seconds <= 0:
        return
    _cache[key] = (time.monotonic(), value)


def _cache_clear() -> None:
    """테스트용 — 캐시 초기화."""
    _cache.clear()


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------


@router.get("/kpi", response_model=KPIResponse)
async def get_kpi(
    response: Response,
    since_hours: int = Query(default=24, ge=1, le=720, description="측정 윈도우 (시간, 1~720)"),
    cache: str = Query(default="default", description="'bypass' 시 캐시 무시하고 강제 갱신"),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> KPIResponse:
    """5종 KPI 측정 (admin 전용).

    응답:
        KPIResponse — 자세한 필드는 스키마 참조.

    헤더:
        X-KPI-Cache-Status: fresh | cached
        X-KPI-Cache-Age:    캐시 age (초)
    """
    since_hours = parse_window(since_hours)
    cache_key = (since_hours,)

    if cache != "bypass":
        hit = _cache_get(cache_key)
        if hit is not None:
            value, age = hit
            response.headers["X-KPI-Cache-Status"] = "cached"
            response.headers["X-KPI-Cache-Age"] = f"{age:.1f}"
            return value

    prom_url = settings.kpi_prometheus_url or None
    result = await compute_kpis(db, since_hours=since_hours, prometheus_url=prom_url)
    _cache_put(cache_key, result)
    response.headers["X-KPI-Cache-Status"] = "fresh"
    response.headers["X-KPI-Cache-Age"] = "0.0"
    return result

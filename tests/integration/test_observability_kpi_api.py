"""Day 10 — /admin/observability/kpi API 통합 테스트 (HJ).

검증 범위:
    - 응답 200 + KPIResponse 스키마
    - Query 검증 (since_hours ge=1, le=720)
    - 캐시 헤더 (X-KPI-Cache-Status fresh/cached)
    - cache=bypass 강제 갱신
    - 윈도우별 캐시 분리
    - TTL=0 캐시 비활성

전략:
    - 실제 DB / Auth 없이 FastAPI app.dependency_overrides 로 의존성 치환
    - compute_kpis 를 stub 함수로 monkeypatch
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


@pytest.fixture
def test_client(monkeypatch):
    """obs router 단독 마운트 + 의존성 치환."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ada.db.session import get_db
    from ada.observability.kpi import KPIResponse
    from api.routes import observability as obs

    # 캐시 초기화
    obs._cache_clear()

    # compute_kpis stub — DB 미사용
    async def _stub_compute(db, *, since_hours=24, include_prometheus=True, prometheus_url=None):
        return KPIResponse(
            since_hours=since_hours,
            measured_at=datetime.now(timezone.utc),
            kp1_e2e_success_rate=0.95,
            kp2_avg_duration_min=8.5,
            kp5_p95_api_ms=420.0,
            kp9_kb_citation_rate=0.4,
            n_jobs_total=20,
            n_jobs_terminal=18,
            agent_avg_duration_sec=1.1,
            data_source={
                "kp1": "stub",
                "kp2": "stub",
                "kp5": "stub",
                "kp9": "stub",
            },
            warnings=[],
        )

    monkeypatch.setattr(obs, "compute_kpis", _stub_compute)

    app = FastAPI()
    app.include_router(obs.router)

    # 의존성 치환 — admin 권한 통과 + db None
    async def _override_db():
        yield None

    def _override_admin():
        return {"sub": "test-admin", "role": "admin"}

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[obs._admin_only] = _override_admin

    yield TestClient(app)

    # 정리
    obs._cache_clear()


# ----- 1) 기본 동작 ----------------------------------------------------------


def test_get_kpi_returns_200(test_client):
    r = test_client.get("/admin/observability/kpi")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["since_hours"] == 24
    assert data["kp1_e2e_success_rate"] == 0.95
    assert data["n_jobs_total"] == 20


def test_response_schema_complete(test_client):
    r = test_client.get("/admin/observability/kpi")
    data = r.json()
    required = {
        "since_hours",
        "measured_at",
        "kp1_e2e_success_rate",
        "kp2_avg_duration_min",
        "kp5_p95_api_ms",
        "kp9_kb_citation_rate",
        "n_jobs_total",
        "n_jobs_terminal",
        "agent_avg_duration_sec",
        "data_source",
        "warnings",
    }
    assert required.issubset(data.keys())


def test_custom_since_hours(test_client):
    r = test_client.get("/admin/observability/kpi?since_hours=168")
    assert r.status_code == 200
    assert r.json()["since_hours"] == 168


# ----- 2) Query 검증 ---------------------------------------------------------


@pytest.mark.parametrize(
    "since,expected",
    [
        (1, 200),
        (24, 200),
        (720, 200),
        (0, 422),
        (721, 422),
        (-1, 422),
    ],
)
def test_since_hours_range_validation(test_client, since, expected):
    r = test_client.get(f"/admin/observability/kpi?since_hours={since}")
    assert r.status_code == expected, f"since={since}: {r.text[:200]}"


# ----- 3) 캐시 헤더 ----------------------------------------------------------


def test_first_call_is_fresh(test_client):
    r = test_client.get("/admin/observability/kpi?since_hours=12")
    assert r.headers.get("X-KPI-Cache-Status") == "fresh"


def test_second_call_is_cached(test_client):
    r1 = test_client.get("/admin/observability/kpi?since_hours=12")
    assert r1.headers.get("X-KPI-Cache-Status") == "fresh"

    r2 = test_client.get("/admin/observability/kpi?since_hours=12")
    assert r2.headers.get("X-KPI-Cache-Status") == "cached"
    age = float(r2.headers.get("X-KPI-Cache-Age", "0"))
    assert age >= 0.0


def test_cache_bypass(test_client):
    r1 = test_client.get("/admin/observability/kpi?since_hours=12")
    assert r1.headers.get("X-KPI-Cache-Status") == "fresh"

    r2 = test_client.get("/admin/observability/kpi?since_hours=12&cache=bypass")
    assert r2.headers.get("X-KPI-Cache-Status") == "fresh"


def test_different_windows_cached_separately(test_client):
    r1 = test_client.get("/admin/observability/kpi?since_hours=12")
    r2 = test_client.get("/admin/observability/kpi?since_hours=24")
    assert r1.headers.get("X-KPI-Cache-Status") == "fresh"
    assert r2.headers.get("X-KPI-Cache-Status") == "fresh"

    r3 = test_client.get("/admin/observability/kpi?since_hours=12")
    assert r3.headers.get("X-KPI-Cache-Status") == "cached"


# ----- 4) cache 비활성 (TTL=0) ----------------------------------------------


def test_cache_disabled_when_ttl_zero(monkeypatch, test_client):
    from ada.core import config
    from api.routes import observability as obs

    obs._cache_clear()
    monkeypatch.setattr(config.settings, "kpi_cache_ttl_seconds", 0)

    r1 = test_client.get("/admin/observability/kpi?since_hours=12")
    r2 = test_client.get("/admin/observability/kpi?since_hours=12")
    assert r1.headers.get("X-KPI-Cache-Status") == "fresh"
    assert r2.headers.get("X-KPI-Cache-Status") == "fresh"

"""Day 3 — Langfuse 연동 + /admin/audit 라우터.

DoD:
    - verify_connection() 이 키 없는 환경에서 connected=False 반환
    - admin router 가 FastAPI 에 마운트 시 /admin/audit 등장
    - admin RBAC: admin 토큰만 통과, analyst 는 403
    - prometheus_check 가 메트릭 노출 확인
"""

from __future__ import annotations

import pytest


# ----- 1) verify_connection — 키 없으면 connected=False -------------------------
def test_langfuse_verify_no_keys():
    from ada.core.langfuse_client import verify_connection

    r = verify_connection()
    assert r["connected"] is False
    assert "reason" in r


# ----- 2) admin router 가 /admin/audit + 헬스체크 라우트 노출 -----------------------
def test_admin_router_routes_listed():
    from api.routes.admin import router

    paths = {r.path for r in router.routes}
    assert "/admin/audit" in paths
    assert "/admin/audit/summary" in paths
    assert "/admin/observability/langfuse" in paths
    assert "/admin/observability/prometheus_check" in paths


# ----- 3) admin RBAC — analyst 는 403, admin 은 통과 -----------------------------
def test_admin_rbac_blocks_analyst(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ada.security.jwt import get_current_user
    from api.routes import admin as admin_routes

    app = FastAPI()
    app.include_router(admin_routes.router)

    async def fake_analyst():
        return {"user_id": "u1", "role": "analyst"}

    async def fake_admin():
        return {"user_id": "u2", "role": "admin"}

    # analyst 시도
    app.dependency_overrides[get_current_user] = fake_analyst
    client = TestClient(app)
    r1 = client.get("/admin/observability/langfuse")
    assert r1.status_code == 403

    # admin 으로 변경
    app.dependency_overrides[get_current_user] = fake_admin
    r2 = client.get("/admin/observability/langfuse")
    assert r2.status_code == 200
    assert "connected" in r2.json()


# ----- 4) prometheus_check 가 메트릭 sample_lines 노출 -----------------------------
def test_admin_prometheus_check(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ada.observability.metrics import record_agent_run
    from ada.security.jwt import get_current_user
    from api.routes import admin as admin_routes

    record_agent_run("AdminTestAgent", 0.05)

    app = FastAPI()
    app.include_router(admin_routes.router)

    async def fake_admin():
        return {"user_id": "u2", "role": "admin"}

    app.dependency_overrides[get_current_user] = fake_admin
    client = TestClient(app)
    r = client.get("/admin/observability/prometheus_check")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert isinstance(body["sample_lines"], list)


# ----- 5) verify_connection — Mock 으로 connected=True 반환 ---------------------
def test_langfuse_verify_mocked_client(monkeypatch):
    from ada.core import langfuse_client as lc

    class FakeClient:
        def auth_check(self):
            return True

    monkeypatch.setattr(lc, "get_langfuse_client", lambda: FakeClient())
    r = lc.verify_connection()
    assert r["connected"] is True
    assert r["reason"] == "ok"


# =============================================================================
# ADR-007 L2 — Phase 2 audit 라우트 (4종)
# =============================================================================


class _FakeScalarResult:
    """async db.scalars() 의 결과 시뮬레이션."""

    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows


class _FakeExecResult:
    """async db.execute() 결과 (count + group by 양쪽 모두)."""

    def __init__(self, scalar_val=0, rows=None):
        self._scalar = scalar_val
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def __iter__(self):
        return iter(self._rows)


class _FakeDBSession:
    """async DB session — Phase 2 audit 라우트 검증용 Stub."""

    def __init__(self, scalar_count=0, exec_rows=None, scalars_rows=None):
        self._scalar_count = scalar_count
        self._exec_rows = exec_rows or []
        self._scalars_rows = scalars_rows or []

    async def execute(self, *_a, **_k):
        # count 또는 group by — 호출 횟수 기반 분기는 단순화
        return _FakeExecResult(scalar_val=self._scalar_count, rows=self._exec_rows)

    async def scalars(self, *_a, **_k):
        return _FakeScalarResult(self._scalars_rows)


def _build_admin_app(monkeypatch, db_session: "_FakeDBSession", role: str = "admin"):
    """FastAPI app + admin router + Fake auth/db 의존성 셋업."""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI

    from ada.db.session import get_db
    from ada.security.jwt import get_current_user
    from api.routes import admin as admin_routes

    app = FastAPI()
    app.include_router(admin_routes.router)

    async def fake_db():
        yield db_session

    async def fake_user():
        return {"user_id": "u-test", "role": role}

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_user
    return app


def test_admin_failure_logs_pagination(monkeypatch):
    """L2.1 — /admin/autofix/failure_logs 페이지네이션 + 빈 결과."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = _build_admin_app(monkeypatch, _FakeDBSession())
    client = TestClient(app)
    r = client.get("/admin/autofix/failure_logs?page=1&page_size=10")
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] == 0
    assert body["items"] == []


def test_admin_failure_logs_filter_classified(monkeypatch):
    """L2.1 — classified_as 필터 query 가 라우트에 전달."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = _build_admin_app(monkeypatch, _FakeDBSession())
    client = TestClient(app)
    r = client.get("/admin/autofix/failure_logs?classified_as=transient")
    assert r.status_code == 200


def test_admin_failure_logs_blocks_analyst(monkeypatch):
    """L2.1 — analyst role 은 403."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = _build_admin_app(monkeypatch, _FakeDBSession(), role="analyst")
    client = TestClient(app)
    r = client.get("/admin/autofix/failure_logs")
    assert r.status_code == 403


def test_admin_patch_applications_returns_status_counts(monkeypatch):
    """L2.2 — patch_applications 의 status_counts 응답 필드."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    # group by 결과 = [("success", 3), ("failed", 1)]
    db = _FakeDBSession(scalar_count=4, exec_rows=[("success", 3), ("failed", 1)])
    app = _build_admin_app(monkeypatch, db)
    client = TestClient(app)
    r = client.get("/admin/autofix/patch_applications")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert "status_counts" in body
    assert body["status_counts"].get("success") == 3
    assert body["status_counts"].get("failed") == 1


def test_admin_circuit_breakers_returns_known_breakers(monkeypatch):
    """L2.3 — 3개 알려진 breaker (ollama/claude_cli/anthropic) 상태 반환."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    app = _build_admin_app(monkeypatch, _FakeDBSession())
    client = TestClient(app)
    r = client.get("/admin/autofix/circuit_breakers")
    assert r.status_code == 200
    body = r.json()
    assert "current_state" in body
    assert "recent_events" in body
    assert set(body["current_state"].keys()) == {"ollama", "claude_cli", "anthropic"}
    # state 는 closed | open | half_open | unknown 중 하나
    for name, info in body["current_state"].items():
        assert info["state"] in {"closed", "open", "half_open", "unknown"}


def test_admin_budget_returns_snapshot(monkeypatch):
    """L2.4 — budget 응답 필드."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from ada.error_handler.budget import reset_singleton

    reset_singleton()
    app = _build_admin_app(monkeypatch, _FakeDBSession())
    client = TestClient(app)
    r = client.get("/admin/autofix/budget")
    assert r.status_code == 200
    body = r.json()
    for key in (
        "today_spend_usd",
        "today_calls",
        "daily_limit_usd",
        "remaining_usd",
        "is_exceeded",
        "date_utc",
    ):
        assert key in body, f"{key} 누락"
    # 신선 환경 — spend 0
    assert body["today_spend_usd"] == 0.0
    assert body["today_calls"] == 0


# =============================================================================
# ADR-007 L3 — Langfuse 깊이 통합 검증
# =============================================================================


def test_base_agent_call_llm_api_imports_track_llm():
    """L3.1 — _call_llm_api 소스에 track_llm 통합 패턴 존재."""
    import inspect

    from agents.base import BaseAgent

    source = inspect.getsource(BaseAgent._call_llm_api)
    assert "from ada.core.langfuse_client import track_llm" in source
    assert "with track_llm(" in source
    assert "span.update(" in source


def test_base_agent_has_current_job_id_field():
    """L3.2 — _current_job_id 인스턴스 변수 존재 + default None."""
    from agents.base import BaseAgent

    class DummyAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state):  # type: ignore[override]
            pass

    agent = DummyAgent(session=None)
    assert hasattr(agent, "_current_job_id")
    assert agent._current_job_id is None


def test_log_agent_run_sets_current_job_id():
    """L3.2 — log_agent_run 진입 시 _current_job_id 가 state.job_id 로 세팅."""
    import asyncio

    from ada.core.state import PipelineState
    from agents.base import BaseAgent

    captured = []

    class TestAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state):  # type: ignore[override]
            async with self.log_agent_run(state):
                captured.append(self._current_job_id)

    agent = TestAgent(session=None)
    state = PipelineState(job_id="job-track-test", file_id="f", category="tabular_ml")
    asyncio.run(agent(state))
    assert captured == ["job-track-test"]


def test_api_main_lifespan_calls_langfuse_flush(monkeypatch):
    """L3.3 — api/main.py 의 lifespan shutdown 에 flush 호출 코드 존재."""
    src = open("api/main.py", encoding="utf-8").read()
    assert "from ada.core.langfuse_client import flush" in src
    assert "flush(timeout_sec=" in src

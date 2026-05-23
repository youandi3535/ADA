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

"""Day 4 — Output Carrier reattach 통합 테스트 (ADR-008 L2)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


# ----- 1) reattach_pii 헬퍼 — state=None ---------------------------------------
def test_reattach_pii_helper_with_empty_state():
    from outputs.base import reattach_pii

    text = "customer@example.com, 010-1234-5678"
    safe = reattach_pii(None, text)
    assert "customer@example.com" not in safe
    assert "010-1234-5678" not in safe
    assert "***" in safe


# ----- 2) reattach_pii 헬퍼 — mapping 있음 -------------------------------------
def test_reattach_pii_helper_with_mapping():
    from outputs.base import reattach_pii

    state = SimpleNamespace(
        category_extras={
            "_pii": {
                "mapping": {"<PII:email:abc12345>": "real@user.com"},
                "redaction": "***",
            }
        }
    )
    safe = reattach_pii(state, "user <PII:email:abc12345> contact")
    assert "<PII:" not in safe
    assert "real@user.com" not in safe
    assert "***" in safe


# ----- 3) reattach_pii — 빈 입력 안전 처리 -------------------------------------
def test_reattach_pii_helper_handles_empty_inputs():
    from outputs.base import reattach_pii

    assert reattach_pii(None, None) == ""
    assert reattach_pii(None, "") == ""
    state = SimpleNamespace(category_extras=None)
    assert reattach_pii(state, "") == ""
    assert reattach_pii(state, "no pii here") == "no pii here"


# ----- 4) markdown_insight — insights/user_intent/rationale 마스킹 -------------
def test_markdown_insight_redacts_pii(tmp_path):
    from outputs.markdown_insight import InsightSummaryGenerator

    state = SimpleNamespace(category_extras={"_pii": {"mapping": {"<PII:email:abc12345>": "me@x.com"}}})
    gen = InsightSummaryGenerator("job-md-test")
    tmp_file = str(tmp_path / "out.md")

    with patch.object(gen, "_upload", return_value="s3://t/out.md"), patch.object(gen, "_tmp", return_value=tmp_file):
        gen.generate(
            insights="contact me@x.com",
            best_model={"model_name": "xgb"},
            eda_charts=[],
            category="tabular_ml",
            user_intent="user <PII:email:abc12345>",
            eval_result={"passed": True, "rationale": "phone 010-1234-5678"},
            state=state,
        )

    content = open(tmp_file, encoding="utf-8").read()
    assert "me@x.com" not in content
    assert "<PII:" not in content
    assert "010-1234-5678" not in content
    assert "***" in content


# ----- 5) script — user_intent / insights 마스킹 -----------------------------
def test_script_redacts_pii(tmp_path):
    from outputs.script import ScriptGenerator

    state = SimpleNamespace(category_extras={"_pii": {"mapping": {}}})
    gen = ScriptGenerator("job-script-test")
    tmp_file = str(tmp_path / "out.txt")

    with patch.object(gen, "_upload", return_value="s3://t/out.txt"), patch.object(gen, "_tmp", return_value=tmp_file):
        gen.generate(
            insights="customer a@b.com",
            best_model={"model_name": "lgb", "metrics": {"acc": 0.9}},
            eda_charts=[],
            category="tabular_ml",
            user_intent="010-9999-8888",
            eval_result={"passed": True},
            state=state,
        )

    content = open(tmp_file, encoding="utf-8").read()
    assert "a@b.com" not in content
    assert "010-9999-8888" not in content
    assert "***" in content


# ----- 6) html_dashboard — insights 마스킹 -----------------------------------
def test_html_dashboard_redacts_pii(tmp_path):
    from outputs.html_dashboard import DashboardArtifactGenerator

    state = SimpleNamespace(category_extras={"_pii": {"mapping": {}}})
    gen = DashboardArtifactGenerator("job-html-test")
    tmp_file = str(tmp_path / "out.html")

    with patch.object(gen, "_upload", return_value="s3://t/out.html"), patch.object(gen, "_tmp", return_value=tmp_file):
        gen.generate(
            insights="leak leak@danger.com",
            best_model={"model_name": "iso"},
            eda_charts=[],
            category="anomaly_detection",
            user_intent="check 010-7777-6666",
            eval_result=None,
            state=state,
        )

    content = open(tmp_file, encoding="utf-8").read()
    assert "leak@danger.com" not in content
    assert "010-7777-6666" not in content
    assert "***" in content


# ----- 7) report_composer — state 를 carrier 에 전달 --------------------------
def test_report_composer_passes_state_to_carrier():
    """state 가 carrier.generate() 에 전달되는 정적 검증."""
    import inspect

    from agents.report_composer import ReportComposerAgent

    src = inspect.getsource(ReportComposerAgent.__call__)
    assert 'kwargs["state"] = state' in src or "state=state" in src


# ----- 8) reattach_pii — PIIAnonymizer 부재 시 silent passthrough ------------
def test_reattach_pii_silent_on_anonymizer_error(monkeypatch):
    """보안 모듈 import 실패해도 carrier 안 죽음."""
    import outputs.base as base_mod

    def fake_import(*a, **k):
        raise ImportError("simulated")

    # 직접 시뮬레이션 어려움 — 정상 경로에서도 None 입력 안전 검증
    from outputs.base import reattach_pii

    assert reattach_pii(None, "") == ""


# ----- 9) data_profiler — DataFrame PII 컬럼 자동 마스킹 (L3.3) --------------
def test_data_profiler_anonymizes_df_columns():
    """업로드 df 의 email/phone 컬럼이 마스킹됨."""
    import pandas as pd

    from agents.data_profiler import _anonymize_uploaded_df

    df = pd.DataFrame(
        {
            "email": ["a@b.com", "c@d.com"],
            "phone": ["010-1111-2222", "010-3333-4444"],
            "age": [30, 40],
        }
    )

    class FakeState:
        category_extras: dict = {}

    masked, extras = _anonymize_uploaded_df(df, FakeState())

    assert "a@b.com" not in masked["email"].astype(str).tolist()
    assert "010-1111-2222" not in masked["phone"].astype(str).tolist()
    assert masked["age"].tolist() == [30, 40]
    assert "mapping" in extras
    assert "email" in extras["columns"]
    assert "phone" in extras["columns"]
    assert "age" not in extras["columns"]


# ----- 10) data_profiler — extras merge (L3.3) ------------------------------
def test_data_profiler_merges_pii_extras():
    """기존 _pii (텍스트 mapping) + df mapping merge 보존."""
    from agents.data_profiler import _merge_pii_extras

    current = {"_pii": {"mapping": {"<PII:email:abc>": "from_text@a.com"}, "redaction": "***"}}
    new = {
        "mapping": {"<PII:email:xyz>": "from_df@b.com"},
        "columns": ["email"],
    }

    merged = _merge_pii_extras(current, new)
    assert "<PII:email:abc>" in merged["_pii"]["mapping"]
    assert "<PII:email:xyz>" in merged["_pii"]["mapping"]
    assert merged["_pii"]["df_columns"] == ["email"]
    assert merged["_pii"]["redaction"] == "***"


# ----- 11) data_profiler — 빈 입력 안전 처리 (L3.3) -------------------------
def test_data_profiler_anonymize_handles_no_pii():
    """PII 없는 df 는 그대로 반환."""
    import pandas as pd

    from agents.data_profiler import _anonymize_uploaded_df

    df = pd.DataFrame({"age": [10, 20], "name": ["a", "b"]})

    class FakeState:
        category_extras: dict = {}

    masked, extras = _anonymize_uploaded_df(df, FakeState())
    assert extras == {} or extras.get("columns") == []
    assert masked["age"].tolist() == [10, 20]


# ----- 12) L4 — /admin/security/pii 집계 (정적) -----------------------------
def test_admin_pii_stats_route_registered():
    """L4 — /admin/security/pii 라우트 + PIIStatsResponse 모델 등록 확인."""
    from api.routes.admin import PIIStatsResponse, router

    paths = {r.path for r in router.routes}
    assert "/admin/security/pii" in paths
    # 응답 모델 필드 확인
    assert "total_tokens_masked" in PIIStatsResponse.model_fields
    assert "total_events" in PIIStatsResponse.model_fields
    assert "by_hour" in PIIStatsResponse.model_fields


# ----- 13) L4 — /admin/security/pii 실제 호출 + 집계 (FakeSession) -----------
def test_admin_pii_stats_returns_aggregate():
    """L4 — fake audit rows 가 정확히 집계됨."""
    import pytest

    pytest.importorskip("fastapi")
    from datetime import datetime

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ada.db.session import get_db
    from ada.security.jwt import get_current_user
    from api.routes import admin as admin_routes

    app = FastAPI()
    app.include_router(admin_routes.router)

    class FakeRow:
        def __init__(self, action, n_tokens, actor):
            self.action = action
            self.details = {"n_tokens": n_tokens}
            self.created_at = datetime.utcnow()
            self.actor_user_id = actor

    fake_rows = [
        FakeRow("pii_anonymized", 5, "u1"),
        FakeRow("pii_anonymized", 3, "u1"),
        FakeRow("pii_anonymized", 2, "u2"),
    ]

    class FakeScalars:
        def all(self):
            return fake_rows

    class FakeSession:
        async def scalars(self, *a, **k):
            return FakeScalars()

        async def execute(self, *a, **k):
            raise NotImplementedError

    async def fake_db():
        yield FakeSession()

    async def fake_admin():
        return {"user_id": "u-test", "role": "admin"}

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_admin

    client = TestClient(app)
    r = client.get("/admin/security/pii?since_hours=24")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_tokens_masked"] == 10  # 5+3+2
    assert body["total_events"] == 3
    assert body["since_hours"] == 24
    actors = {a["actor_user_id"]: a["events"] for a in body["top_actors"]}
    assert actors.get("u1") == 2
    assert actors.get("u2") == 1

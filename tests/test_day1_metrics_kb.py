"""Day 1 — Prometheus metrics + Supervisor ErrorKB 폴백 + SelfLearning 자동인덱스.

DoD:
    - render_metrics() 가 ada_agent_duration_seconds 라벨을 노출
    - SupervisorAgent.retry>=1 + state.error 가 있으면 ErrorKB 조회 시도
    - SelfLearningAgent 가 distill 후 KBRAG.index_lesson 자동 호출
"""

from __future__ import annotations

from typing import Any

import pytest

from ada.core.state import PipelineState


# ----- 1) Prometheus exposition 에 ada_agent_duration_seconds 노출 ----------------
def test_metrics_exposes_agent_duration():
    from ada.observability.metrics import (
        ada_agent_duration_seconds,
        record_agent_run,
        render_metrics,
    )

    # 메트릭 한 번 기록
    record_agent_run("SupervisorAgent", 0.123, error_type=None)
    record_agent_run("SupervisorAgent", 1.5, error_type="ValueError")
    body = render_metrics()
    text = body.decode("utf-8")
    assert "ada_agent_duration_seconds" in text
    assert "SupervisorAgent" in text
    # 에러 카운터도 노출
    assert "ada_agent_errors_total" in text
    # ada_jobs_active gauge
    assert "ada_jobs_active" in text


# ----- 2) /metrics 엔드포인트가 정상 응답 -----------------------------------------
def test_metrics_endpoint_returns_text():
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from api.routes.metrics import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"ada_" in r.content or b"prometheus_client" in r.content  # 메트릭 또는 stub 메시지


# ----- 3) Supervisor — retry>=1 + state.error 시 _lookup_error_kb 호출 ------------
def test_supervisor_calls_error_kb_on_retry(monkeypatch):
    import asyncio

    from agents.supervisor import SupervisorAgent

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        retry_count=1,
        error="ValueError: invalid shape",
    )

    called: list[str] = []

    async def fake_lookup(self, msg):
        called.append(msg)
        return {
            "hash": "abc123",
            "kb_id": "kb-1",
            "confidence": 0.9,
            "recommended_recovery": "supervisor",
        }

    monkeypatch.setattr(SupervisorAgent, "_lookup_error_kb", fake_lookup)

    sup = SupervisorAgent()
    out = asyncio.run(sup(state))

    assert called and called[0] == "ValueError: invalid shape"
    # KB 인용이 state.kb_citations 에 누적
    assert any(c.startswith("error_kb:") for c in out.kb_citations)


# ----- 4) Supervisor — retry==0 일 때는 ErrorKB 조회 안 함 -----------------------
def test_supervisor_skips_kb_when_no_retry(monkeypatch):
    import asyncio

    from agents.supervisor import SupervisorAgent

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001", file_id="f.csv", category="tabular_ml", target_column="y"
    )

    called: list[Any] = []

    async def fake_lookup(self, msg):
        called.append(msg)
        return None

    monkeypatch.setattr(SupervisorAgent, "_lookup_error_kb", fake_lookup)

    # LLM 우회
    async def fake_llm(self, **k):
        return '{"task":"classification","reason":"x","confidence":0.9}'

    monkeypatch.setattr(SupervisorAgent, "_call_llm", fake_llm)

    sup = SupervisorAgent()
    out = asyncio.run(sup(state))
    assert called == []  # retry=0 이면 호출 안 됨
    assert out.task == "classification"


# ----- 5) SelfLearningAgent 가 index_lesson 자동 호출 -----------------------------
def test_self_learning_auto_indexes_lessons(monkeypatch):
    """distill_from_job 이 created_kb_ids+summaries 를 반환하면 KBRAG.index_lesson 이 호출된다."""
    import asyncio

    from agents.self_learning import SelfLearningAgent

    class FakeSession:
        async def add(self, *a, **k):
            return None

        async def flush(self):
            return None

        async def get(self, *a, **k):
            return None

        async def scalar(self, *a, **k):
            return None

    class FakeHarness:
        def __init__(self, session):
            self.session = session

        async def distill_from_job(self, job_id):
            return {"created_kb_ids": ["uuid-1"], "summaries": {"uuid-1": "이번 학습에서 SHAP 비대칭..."}}

    indexed: list[tuple] = []

    class FakeRAG:
        def __init__(self, session):
            self.session = session

        async def index_lesson(self, kb_id, summary):
            indexed.append((kb_id, summary))

    # 모듈 패치
    import agents.self_learning as sl

    monkeypatch.setattr("ada.harness.distiller.SelfLearningHarness", FakeHarness)
    monkeypatch.setattr("ada.harness.rag.KBRAG", FakeRAG)

    agent = SelfLearningAgent(session=FakeSession())  # type: ignore[arg-type]
    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001", file_id="f.csv", category="tabular_ml", target_column="y"
    )
    asyncio.run(agent(state))

    assert indexed == [("uuid-1", "이번 학습에서 SHAP 비대칭...")]

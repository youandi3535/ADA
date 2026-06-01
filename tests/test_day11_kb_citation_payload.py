"""Day 11 — AgentRun.payload['kb_citations'] 자동 기록 검증 (HJ).

설계:
    record_kb_citation() 호출 시 ContextVar 증가 → BaseAgent.log_agent_run finally
    에서 AgentRun.payload 에 누적값 기록. KP9 측정 정확도 위함.

검증 범위:
    1. ContextVar — record_kb_citation 후 get_kb_citation_count 증가
    2. reset_kb_citation_counter — 0 으로 초기화
    3. agent 종료 시 payload['kb_citations'] 기록 (session 있는 케이스)
    4. session 없으면 회귀 없음 (기존 supervisor 테스트 호환)
    5. 0 citation 시 payload 미기록 (None 유지)
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from ada.core.state import PipelineState

# ----- 1) ContextVar 기본 동작 ----------------------------------------------


def test_record_kb_citation_increments_contextvar():
    from ada.observability.metrics import (
        get_kb_citation_count,
        record_kb_citation,
        reset_kb_citation_counter,
    )

    reset_kb_citation_counter()
    assert get_kb_citation_count() == 0

    record_kb_citation(source="self_learning_kb")
    assert get_kb_citation_count() == 1

    record_kb_citation(source="error_kb")
    record_kb_citation(source="error_kb")
    assert get_kb_citation_count() == 3


def test_reset_kb_citation_counter():
    from ada.observability.metrics import (
        get_kb_citation_count,
        record_kb_citation,
        reset_kb_citation_counter,
    )

    record_kb_citation()
    record_kb_citation()
    assert get_kb_citation_count() >= 2

    reset_kb_citation_counter()
    assert get_kb_citation_count() == 0


# ----- 2) BaseAgent.log_agent_run — session 없을 때 회귀 없음 ---------------


def test_log_agent_run_without_session_does_not_crash():
    """기존 supervisor 테스트와 동일 — session 없으면 payload 기록 단계 스킵."""
    from agents.base import BaseAgent

    class _DummyAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state: PipelineState) -> PipelineState:
            async with self.log_agent_run(state):
                # KB 인용 시뮬레이션
                from ada.observability.metrics import record_kb_citation

                record_kb_citation()
            return state

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
    )
    agent = _DummyAgent(session=None)
    out = asyncio.run(agent(state))
    assert out.job_id == state.job_id  # 정상 종료


# ----- 3) BaseAgent.log_agent_run — session 있을 때 payload 기록 ------------


class _FakeAgentRun:
    """AgentRun row stub."""

    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.job_id = kwargs.get("job_id")
        self.agent_name = kwargs.get("agent_name")
        self.status = kwargs.get("status")
        self.duration_ms = kwargs.get("duration_ms")
        self.input_tokens = kwargs.get("input_tokens", 0)
        self.output_tokens = kwargs.get("output_tokens", 0)
        self.error = kwargs.get("error")
        self.gate = kwargs.get("gate")
        self.was_re_loop = kwargs.get("was_re_loop", False)
        self.payload = kwargs.get("payload")


class _FakeSession:
    """log_agent_run 가 호출하는 최소 인터페이스."""

    def __init__(self):
        self.added: list = []
        self.rows: dict = {}

    def add(self, obj):
        self.added.append(obj)
        # AgentRun 인스턴스를 row 로 저장
        self.rows[obj.id] = obj

    async def flush(self):
        return None

    async def get(self, cls, key):
        return self.rows.get(key)


def test_agent_run_payload_records_kb_citations(monkeypatch):
    """KB 인용 발생 → AgentRun.payload['kb_citations'] = N."""
    # AgentRun import 를 fake 으로 치환 — 본 테스트는 실제 SQLAlchemy 안 씀
    from ada.db import models as db_models
    from agents.base import BaseAgent

    monkeypatch.setattr(db_models, "AgentRun", _FakeAgentRun)

    captured_payloads: list = []

    class _CitingAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state: PipelineState) -> PipelineState:
            async with self.log_agent_run(state):
                from ada.observability.metrics import record_kb_citation

                # 3번 인용
                record_kb_citation(source="self_learning_kb")
                record_kb_citation(source="self_learning_kb")
                record_kb_citation(source="error_kb")
            return state

    session = _FakeSession()
    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000002",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
    )
    agent = _CitingAgent(session=session)
    asyncio.run(agent(state))

    # session.added 에 _FakeAgentRun 인스턴스가 있어야 함
    assert len(session.added) == 1
    row = session.added[0]
    assert row.payload is not None
    assert row.payload.get("kb_citations") == 3


def test_agent_run_payload_skipped_when_zero_citations(monkeypatch):
    """KB 인용 0 회 → payload 미기록 (None 유지)."""
    from ada.db import models as db_models
    from agents.base import BaseAgent

    monkeypatch.setattr(db_models, "AgentRun", _FakeAgentRun)

    class _NoCiteAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state: PipelineState) -> PipelineState:
            async with self.log_agent_run(state):
                pass  # 인용 없음
            return state

    session = _FakeSession()
    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000003",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
    )
    agent = _NoCiteAgent(session=session)
    asyncio.run(agent(state))

    row = session.added[0]
    assert row.payload is None  # 미기록


# ----- 4) Contextvar isolation — 두 agent 가 독립 카운트 -------------------


def test_two_agents_have_independent_counters(monkeypatch):
    """Agent A 가 카운트 후, Agent B 시작 시 리셋되어 독립적으로 카운트."""
    from ada.db import models as db_models
    from agents.base import BaseAgent

    monkeypatch.setattr(db_models, "AgentRun", _FakeAgentRun)

    class _AgentA(BaseAgent):
        uses_llm = False

        async def __call__(self, state: PipelineState) -> PipelineState:
            async with self.log_agent_run(state):
                from ada.observability.metrics import record_kb_citation

                record_kb_citation()
                record_kb_citation()
            return state

    class _AgentB(BaseAgent):
        uses_llm = False

        async def __call__(self, state: PipelineState) -> PipelineState:
            async with self.log_agent_run(state):
                from ada.observability.metrics import record_kb_citation

                record_kb_citation()
            return state

    session = _FakeSession()
    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000004",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
    )

    async def _run():
        await _AgentA(session=session)(state)
        await _AgentB(session=session)(state)

    asyncio.run(_run())

    assert len(session.added) == 2
    # A 가 먼저 추가됨 (citations=2), B 두번째 (citations=1)
    assert session.added[0].payload == {"kb_citations": 2}
    assert session.added[1].payload == {"kb_citations": 1}


# ----- 5) supervisor 동작 - record_kb_citation 호출 후 카운트 증가 ----------


def test_supervisor_error_kb_citation_recorded(monkeypatch):
    """기존 supervisor 시나리오 — ErrorKB 매칭 시 카운터 증가."""
    from agents.supervisor import SupervisorAgent

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000005",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        retry_count=1,
        error="ValueError: invalid shape",
    )

    async def fake_lookup(self, msg):
        return {"hash": "abc", "kb_id": "kb-1", "confidence": 0.9, "recommended_recovery": "error_recovery"}

    monkeypatch.setattr(SupervisorAgent, "_lookup_error_kb", fake_lookup)

    # ContextVar 리셋 후 supervisor 실행
    from ada.observability.metrics import reset_kb_citation_counter

    reset_kb_citation_counter()

    sup = SupervisorAgent()
    out = asyncio.run(sup(state))

    # state.kb_citations 누적 (기존 동작)
    assert any(c.startswith("error_kb:") for c in out.kb_citations)
    # 새 동작: contextvar 도 증가했어야 함 — 단, log_agent_run finally 에서
    # reset 되므로 외부에서 확인 불가. payload 기록은 session=None 이라 스킵.
    # 본 테스트는 회귀 없음만 확인.

"""ADR-006 Auto Error Resolution — Phase 1 단위/통합 테스트.

검증 항목:
    1. PipelineState 새 필드 (error_traceback, auto_fix_attempts 등)
    2. BaseAgent 예외 발생 시 _ada_state attach
    3. safe_node 어댑터의 예외→state 변환
    4. safe_node early-return (cascade 방지)
    5. route_after_supervisor — error 있으면 auto_error_handler, 한도 초과면 error_recovery
    6. route_after_auto_handler — error 클리어되면 supervisor, 살아있으면 error_recovery
    7. fingerprint 정규화 — Python 버전 같은 의미있는 숫자는 보존, line 번호만 제거
    8. AutoErrorHandlerAgent — session=None 시 graceful pass-through

본 테스트는 외부 의존성 (postgres, redis, ollama) 없이 그린.
실제 KB 매칭 / LLM 호출은 Phase 2 통합 테스트에서.
"""

from __future__ import annotations

import asyncio

import pytest

# =============================================================================
# Phase 1.1 — PipelineState
# =============================================================================


def test_state_has_new_fields():
    from ada.core.state import PipelineState

    s = PipelineState(job_id="t", file_id="f", category="tabular_ml")
    assert s.error_traceback is None
    assert s.error_classified_as is None
    assert s.error_fingerprint is None
    assert s.auto_fix_attempts == 0
    assert s.max_auto_fix_attempts == 2


def test_state_with_update_propagates_new_fields():
    from ada.core.state import PipelineState

    s = PipelineState(job_id="t", file_id="f", category="tabular_ml")
    s2 = s.with_update(
        error="boom",
        error_traceback="Traceback...",
        auto_fix_attempts=1,
    )
    assert s2.error == "boom"
    assert s2.error_traceback == "Traceback..."
    assert s2.auto_fix_attempts == 1
    # 원본 불변
    assert s.error is None


def test_state_to_dict_includes_new_fields():
    from ada.core.state import PipelineState

    s = PipelineState(job_id="t", file_id="f", category="tabular_ml")
    d = s.to_dict()
    for f in (
        "error_traceback",
        "error_classified_as",
        "error_fingerprint",
        "auto_fix_attempts",
        "max_auto_fix_attempts",
    ):
        assert f in d, f"to_dict 에 {f} 없음"


# =============================================================================
# Phase 1.2 — BaseAgent traceback 캡처
# =============================================================================


def test_base_agent_attaches_state_on_exception():
    from ada.core.state import PipelineState
    from agents.base import BaseAgent

    class CrashAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state):
            async with self.log_agent_run(state):
                raise ValueError("intentional")

    agent = CrashAgent(session=None)
    state = PipelineState(job_id="j", file_id="f", category="tabular_ml")

    with pytest.raises(ValueError):
        asyncio.run(agent(state))

    # 다시 호출해서 _ada_state 검증
    try:
        asyncio.run(agent(state))
    except ValueError as e:
        assert hasattr(e, "_ada_state")
        new_state = e._ada_state
        assert new_state.error is not None
        assert "intentional" in new_state.error
        assert new_state.error_traceback is not None
        assert new_state.auto_fix_attempts == 1
        assert new_state.next_agent == "auto_error_handler"


def test_base_agent_auto_fix_attempts_increments():
    from ada.core.state import PipelineState
    from agents.base import BaseAgent

    class CrashAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state):
            async with self.log_agent_run(state):
                raise RuntimeError("boom")

    agent = CrashAgent(session=None)
    state = PipelineState(job_id="j", file_id="f", category="tabular_ml")

    # 1차
    try:
        asyncio.run(agent(state))
    except RuntimeError as e1:
        state1 = e1._ada_state
        assert state1.auto_fix_attempts == 1

    # 2차 (state1 입력으로)
    try:
        asyncio.run(agent(state1))
    except RuntimeError as e2:
        state2 = e2._ada_state
        assert state2.auto_fix_attempts == 2


# =============================================================================
# Phase 1.3 — safe_node + 라우팅
# =============================================================================


def test_safe_node_catches_exception_returns_state():
    from ada.core.state import PipelineState
    from orchestrator.graph import safe_node

    async def crashy(state):
        raise RuntimeError("inner boom")

    wrapped = safe_node(crashy)
    state = PipelineState(job_id="t", file_id="f", category="tabular_ml")

    result = asyncio.run(wrapped(state))
    assert result.error is not None
    assert "RuntimeError" in result.error or "boom" in result.error
    assert result.auto_fix_attempts == 1
    assert result.next_agent == "auto_error_handler"


def test_safe_node_uses_ada_state_when_attached():
    """BaseAgent 가 _ada_state 첨부한 경우 그걸 우선 사용."""
    from ada.core.state import PipelineState
    from orchestrator.graph import safe_node

    custom_state = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="custom error from BaseAgent",
        auto_fix_attempts=5,
    )

    async def with_attached_state(state):
        err = ValueError("inner")
        err._ada_state = custom_state
        raise err

    wrapped = safe_node(with_attached_state)
    state = PipelineState(job_id="t", file_id="f", category="tabular_ml")
    result = asyncio.run(wrapped(state))

    assert result.error == "custom error from BaseAgent"
    assert result.auto_fix_attempts == 5  # custom 의 값 그대로


def test_safe_node_skips_if_error_already_set():
    """state.error 이미 있으면 노드 실행 안 함 (cascade 방지)."""
    from ada.core.state import PipelineState
    from orchestrator.graph import safe_node

    called = []

    async def should_not_run(state):
        called.append(True)
        return state

    wrapped = safe_node(should_not_run)
    state = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="previous error",
    )

    result = asyncio.run(wrapped(state))
    assert called == []
    assert result.error == "previous error"


def test_route_after_supervisor_no_error():
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_supervisor

    s = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        next_agent="data_profiler",
    )
    assert route_after_supervisor(s) == "data_profiler"


def test_route_after_supervisor_error_attempts_below_max():
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_supervisor

    s = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="x",
        auto_fix_attempts=0,
        max_auto_fix_attempts=2,
    )
    assert route_after_supervisor(s) == "auto_error_handler"


def test_route_after_supervisor_error_attempts_at_max():
    """무한루프 차단 — 한도 도달 시 즉시 error_recovery."""
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_supervisor

    s = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="x",
        auto_fix_attempts=2,
        max_auto_fix_attempts=2,
    )
    assert route_after_supervisor(s) == "error_recovery"


def test_route_after_auto_handler_resolved():
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_auto_handler

    s = PipelineState(job_id="t", file_id="f", category="tabular_ml", error=None)
    assert route_after_auto_handler(s) == "supervisor"


def test_route_after_auto_handler_unresolved():
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_auto_handler

    s = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="still failing",
    )
    assert route_after_auto_handler(s) == "error_recovery"


# =============================================================================
# Phase 1.5 — fingerprint 정규화
# =============================================================================


def test_fingerprint_different_python_versions_different_hash():
    """과대 정규화 (\\d+ 전체 제거) 회귀 방지."""
    from ada.error_handler.auto_handler import fingerprint

    fp_310 = fingerprint("ModuleNotFoundError in Python 3.10", "")
    fp_311 = fingerprint("ModuleNotFoundError in Python 3.11", "")
    assert fp_310["hash"] != fp_311["hash"]


def test_fingerprint_different_line_numbers_same_hash():
    """line 번호는 정규화 → 같은 코드 위치 변경에 안정."""
    from ada.error_handler.auto_handler import fingerprint

    fp_a = fingerprint(
        "ValueError: x",
        'File "foo.py", line 42, in bar\n    raise ValueError("x")',
    )
    fp_b = fingerprint(
        "ValueError: x",
        'File "foo.py", line 99, in bar\n    raise ValueError("x")',
    )
    assert fp_a["hash"] == fp_b["hash"]


def test_fingerprint_memory_addresses_normalized():
    from ada.error_handler.auto_handler import fingerprint

    fp_a = fingerprint("object at 0x7f1a2b3c4d", "")
    fp_b = fingerprint("object at 0xdeadbeef00", "")
    assert fp_a["hash"] == fp_b["hash"]


def test_fingerprint_uuids_normalized():
    from ada.error_handler.auto_handler import fingerprint

    fp_a = fingerprint("job 12345678-1234-5678-1234-567812345678 fail", "")
    fp_b = fingerprint("job abcdef12-3456-7890-abcd-ef1234567890 fail", "")
    assert fp_a["hash"] == fp_b["hash"]


def test_fingerprint_returns_signature_and_stack_top():
    from ada.error_handler.auto_handler import fingerprint

    fp = fingerprint("err", "f1\nf2\nf3\nf4\nf5\nf6\nf7\nf8")
    assert "hash" in fp
    assert "signature" in fp
    assert "stack_top" in fp
    # 6줄로 제한
    assert "f7" not in fp["stack_top"]


# =============================================================================
# Phase 1.4 — AutoErrorHandlerAgent
# =============================================================================


def test_auto_error_handler_agent_no_session_no_error():
    from ada.core.state import PipelineState
    from agents.auto_error_handler import AutoErrorHandlerAgent

    agent = AutoErrorHandlerAgent(session=None)
    state = PipelineState(job_id="t", file_id="f", category="tabular_ml")
    result = asyncio.run(agent(state))
    assert result.error is None


def test_auto_error_handler_agent_no_session_with_error_passes_through():
    """session 없으면 처리 못 함 — state 그대로 (graph 가 error_recovery 로 보냄)."""
    from ada.core.state import PipelineState
    from agents.auto_error_handler import AutoErrorHandlerAgent

    agent = AutoErrorHandlerAgent(session=None)
    state = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="some error",
    )
    result = asyncio.run(agent(state))
    assert result.error == "some error"


class _FullFakeSession:
    """BaseAgent.log_agent_run + AutoErrorHandler 가 호출하는 모든 메서드 stub."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def scalar(self, *a, **k):
        return None

    async def get(self, model, id_):
        # BaseAgent.log_agent_run finally 가 AgentRun row 갱신용으로 호출.
        # None 반환하면 row 갱신 skip (안전).
        return None


def test_auto_error_handler_agent_resolved_clears_error():
    """KB 매칭 성공 시 state.error 클리어 + supervisor 로 라우팅 신호."""
    from ada.core.state import PipelineState
    from agents.auto_error_handler import AutoErrorHandlerAgent

    class FakeAutoErrorHandler:
        def __init__(self, session):
            pass

        async def handle(self, log_row):
            return {"action": "auto_kb_match", "kb_id": "test-kb-id"}

    agent = AutoErrorHandlerAgent(session=_FullFakeSession())
    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f",
        category="tabular_ml",
        error="TestError: x",
        error_traceback="trace",
    )

    import ada.error_handler.auto_handler as auto_mod

    original = auto_mod.AutoErrorHandler
    auto_mod.AutoErrorHandler = FakeAutoErrorHandler  # type: ignore[misc]
    try:
        result = asyncio.run(agent(state))
    finally:
        auto_mod.AutoErrorHandler = original  # type: ignore[misc]

    assert result.error is None, "RESOLVED 시 error 클리어 안 됨"
    assert result.error_traceback is None
    assert result.next_agent == "supervisor"
    assert result.error_fingerprint is not None  # fingerprint 저장됨


def test_auto_error_handler_agent_patch_queued_keeps_error():
    """패치 큐 적재 시 state.error 유지 (적용 안 됐으니 재시도해도 실패)."""
    from ada.core.state import PipelineState
    from agents.auto_error_handler import AutoErrorHandlerAgent

    class FakeAutoErrorHandler:
        def __init__(self, session):
            pass

        async def handle(self, log_row):
            return {"action": "patch_queued_ollama", "patch_chars": 500}

    agent = AutoErrorHandlerAgent(session=_FullFakeSession())
    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000002",
        file_id="f",
        category="tabular_ml",
        error="TestError: y",
        error_traceback="trace",
    )

    import ada.error_handler.auto_handler as auto_mod

    original = auto_mod.AutoErrorHandler
    auto_mod.AutoErrorHandler = FakeAutoErrorHandler  # type: ignore[misc]
    try:
        result = asyncio.run(agent(state))
    finally:
        auto_mod.AutoErrorHandler = original  # type: ignore[misc]

    assert result.error == "TestError: y", "PATCH_QUEUED 시 error 가 클리어됨 (잘못)"
    assert result.error_fingerprint is not None

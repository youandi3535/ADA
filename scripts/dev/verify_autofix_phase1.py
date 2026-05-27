"""ADR-006 Auto Error Resolution — Phase 1 자체 검증 스크립트.

사용자가 PowerShell/Git Bash 에서 직접 실행해 진행 상황을 확인.
sandbox 환경에서 mount staleness 우회를 위한 보조 도구.

사용법:
    python scripts/dev/verify_autofix_phase1.py
    # 또는
    venv/Scripts/python.exe scripts/dev/verify_autofix_phase1.py

각 단계의 검증 결과를 컬러 출력. 실패 시 exit code 1.
"""

from __future__ import annotations

import ast
import sys
import traceback
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


# ANSI 컬러 (Windows 10+ 에서 작동)
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


_results: list[tuple[str, bool, str]] = []


def check(name: str) -> Callable:
    """검증 함수 데코레이터."""

    def deco(fn: Callable) -> Callable:
        try:
            fn()
            _results.append((name, True, ""))
            print(f"  {C.GREEN}✓{C.END} {name}")
        except AssertionError as e:
            _results.append((name, False, str(e)))
            print(f"  {C.RED}✗ {name}{C.END}")
            print(f"      {C.RED}{e}{C.END}")
        except Exception as e:
            _results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"  {C.RED}✗ {name}{C.END}")
            print(f"      {C.RED}{type(e).__name__}: {e}{C.END}")
            traceback.print_exc()
        return fn

    return deco


# =============================================================================
# Phase 1.1: PipelineState 필드 추가 검증
# =============================================================================

print(f"\n{C.BOLD}=== Phase 1.1: PipelineState 필드 추가 ==={C.END}")


@check("ada/core/state.py 가 UTF-8 strict 으로 디코딩됨")
def _():
    data = (REPO_ROOT / "ada/core/state.py").read_bytes()
    text = data.decode("utf-8", errors="strict")
    assert "PipelineState" in text


@check("ada/core/state.py 가 valid Python (AST parse)")
def _():
    src = (REPO_ROOT / "ada/core/state.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("PipelineState 가 import 가능")
def _():
    from ada.core.state import PipelineState

    assert PipelineState is not None


@check("PipelineState 에 error_traceback 필드 존재")
def _():
    from ada.core.state import PipelineState

    fields = PipelineState.model_fields
    assert "error_traceback" in fields, f"있는 필드: {list(fields.keys())}"
    assert fields["error_traceback"].default is None


@check("PipelineState 에 error_classified_as 필드 존재")
def _():
    from ada.core.state import PipelineState

    assert "error_classified_as" in PipelineState.model_fields


@check("PipelineState 에 error_fingerprint 필드 존재")
def _():
    from ada.core.state import PipelineState

    assert "error_fingerprint" in PipelineState.model_fields


@check("PipelineState 에 auto_fix_attempts 필드 (default=0)")
def _():
    from ada.core.state import PipelineState

    fld = PipelineState.model_fields["auto_fix_attempts"]
    assert fld.default == 0, f"default={fld.default}"


@check("PipelineState 에 max_auto_fix_attempts 필드 (default=2)")
def _():
    from ada.core.state import PipelineState

    fld = PipelineState.model_fields["max_auto_fix_attempts"]
    assert fld.default == 2, f"default={fld.default}"


@check("PipelineState 인스턴스 생성 가능 (기존 필드 호환)")
def _():
    from ada.core.state import PipelineState

    s = PipelineState(job_id="t1", file_id="f1", category="tabular_ml")
    assert s.error_traceback is None
    assert s.auto_fix_attempts == 0
    assert s.max_auto_fix_attempts == 2


@check("with_update 로 error_traceback 갱신 가능")
def _():
    from ada.core.state import PipelineState

    s = PipelineState(job_id="t1", file_id="f1", category="tabular_ml")
    s2 = s.with_update(error="boom", error_traceback="trace...", auto_fix_attempts=1)
    assert s2.error == "boom"
    assert s2.error_traceback == "trace..."
    assert s2.auto_fix_attempts == 1
    # 원본은 불변
    assert s.error is None
    assert s.auto_fix_attempts == 0


@check("to_dict 직렬화에 새 필드 포함")
def _():
    from ada.core.state import PipelineState

    s = PipelineState(job_id="t1", file_id="f1", category="tabular_ml")
    d = s.to_dict()
    for field in (
        "error_traceback",
        "error_classified_as",
        "error_fingerprint",
        "auto_fix_attempts",
        "max_auto_fix_attempts",
    ):
        assert field in d, f"to_dict 에 {field} 없음"


# =============================================================================
# Phase 1.2: BaseAgent traceback 자동 캡처
# =============================================================================

print(f"\n{C.BOLD}=== Phase 1.2: BaseAgent traceback 자동 캡처 ==={C.END}")


@check("agents/base.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "agents/base.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("agents/base.py 가 valid Python")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("agents/base.py 에 'import traceback' 있음")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert "import traceback" in src


@check("agents/base.py 에 '_ada_state' attach 코드 있음")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert "_ada_state" in src
    assert "auto_error_handler" in src


@check("실제 예외 발생 시 _ada_state 첨부 동작")
def _():
    import asyncio as _asyncio

    from ada.core.state import PipelineState
    from agents.base import BaseAgent

    class CrashAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state):  # type: ignore[override]
            async with self.log_agent_run(state):
                raise ValueError("intentional crash")

    agent = CrashAgent(session=None)
    state = PipelineState(job_id="test-job", file_id="test-file", category="tabular_ml")

    captured_exc = None
    try:
        _asyncio.run(agent(state))
    except Exception as e:
        captured_exc = e

    assert captured_exc is not None, "예외가 raise 되어야 함"
    assert isinstance(captured_exc, ValueError), f"got {type(captured_exc).__name__}"
    # _ada_state 가 첨부됐는지
    assert hasattr(captured_exc, "_ada_state"), "_ada_state attribute 없음"
    new_state = captured_exc._ada_state
    assert new_state.error is not None and "ValueError" in new_state.error
    assert new_state.error_traceback is not None
    assert "intentional crash" in new_state.error_traceback
    assert new_state.auto_fix_attempts == 1, f"got {new_state.auto_fix_attempts}"
    assert new_state.next_agent == "auto_error_handler"


@check("두 번 연속 raise 시 auto_fix_attempts 누적 (1 → 2)")
def _():
    import asyncio as _asyncio

    from ada.core.state import PipelineState
    from agents.base import BaseAgent

    class CrashAgent(BaseAgent):
        uses_llm = False

        async def __call__(self, state):  # type: ignore[override]
            async with self.log_agent_run(state):
                raise RuntimeError("boom")

    agent = CrashAgent(session=None)
    state = PipelineState(job_id="t", file_id="f", category="tabular_ml")

    # 1차 raise
    try:
        _asyncio.run(agent(state))
    except Exception as e1:
        state1 = e1._ada_state
        assert state1.auto_fix_attempts == 1

    # 2차 — state1 을 입력으로 다시 (graph 가 재시도하는 시나리오 시뮬레이션)
    try:
        _asyncio.run(agent(state1))
    except Exception as e2:
        state2 = e2._ada_state
        assert state2.auto_fix_attempts == 2, f"got {state2.auto_fix_attempts}"


# =============================================================================
# Phase 1.3: graph 에 safe_node + auto_error_handler 노드
# =============================================================================

print(f"\n{C.BOLD}=== Phase 1.3: graph.py safe_node + auto_error_handler ==={C.END}")


@check("orchestrator/graph.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "orchestrator/graph.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("orchestrator/graph.py 가 valid Python")
def _():
    src = (REPO_ROOT / "orchestrator/graph.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("graph.py 에 'safe_node' 함수 정의")
def _():
    src = (REPO_ROOT / "orchestrator/graph.py").read_text(encoding="utf-8")
    assert "def safe_node(" in src


@check("graph.py 에 'route_after_auto_handler' 함수 정의")
def _():
    src = (REPO_ROOT / "orchestrator/graph.py").read_text(encoding="utf-8")
    assert "def route_after_auto_handler(" in src


@check("graph.py 에 auto_error_handler 노드 등록")
def _():
    src = (REPO_ROOT / "orchestrator/graph.py").read_text(encoding="utf-8")
    assert 'g.add_node("auto_error_handler"' in src


@check("graph.py 에서 safe_node 로 노드들 감쌈")
def _():
    src = (REPO_ROOT / "orchestrator/graph.py").read_text(encoding="utf-8")
    # safe_node(SupervisorAgent()) 같은 패턴이 최소 10개는 있어야 함
    count = src.count("safe_node(")
    assert count >= 20, f"safe_node 호출 수={count}, 20 미만"


@check("import 및 모듈 로드 가능 (langgraph 없으면 graceful)")
def _():
    # langgraph 없는 환경에서는 build_graph 가 RuntimeError 던지지만 import 자체는 OK
    from orchestrator import graph as g

    assert hasattr(g, "safe_node")
    assert hasattr(g, "route_after_auto_handler")
    assert hasattr(g, "route_after_supervisor")


@check("safe_node 가 예외를 잡아서 state 반환")
def _():
    import asyncio as _asyncio

    from ada.core.state import PipelineState
    from orchestrator.graph import safe_node

    async def crashy(state):
        raise RuntimeError("inner boom")

    wrapped = safe_node(crashy)
    state = PipelineState(job_id="t", file_id="f", category="tabular_ml")

    result = _asyncio.run(wrapped(state))
    assert result.error is not None
    assert "inner boom" in result.error or "RuntimeError" in result.error
    assert result.auto_fix_attempts == 1
    assert result.next_agent == "auto_error_handler"


@check("safe_node early-return — state.error 이미 있으면 노드 실행 skip")
def _():
    import asyncio as _asyncio

    from ada.core.state import PipelineState
    from orchestrator.graph import safe_node

    called = []

    async def should_not_run(state):
        called.append(True)
        return state

    wrapped = safe_node(should_not_run)
    state = PipelineState(job_id="t", file_id="f", category="tabular_ml", error="prev")

    result = _asyncio.run(wrapped(state))
    assert called == [], "state.error 있어도 노드가 실행됨 (cascade 방지 실패)"
    assert result.error == "prev"


@check("route_after_auto_handler — error=None 이면 supervisor")
def _():
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_auto_handler

    s = PipelineState(job_id="t", file_id="f", category="tabular_ml", error=None)
    assert route_after_auto_handler(s) == "supervisor"


@check("route_after_auto_handler — error 있으면 error_recovery")
def _():
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_auto_handler

    s = PipelineState(job_id="t", file_id="f", category="tabular_ml", error="still bad")
    assert route_after_auto_handler(s) == "error_recovery"


@check("route_after_supervisor — error 있고 attempts < max 면 auto_error_handler")
def _():
    from ada.core.state import PipelineState
    from orchestrator.graph import route_after_supervisor

    s = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="x",
        auto_fix_attempts=1,
        max_auto_fix_attempts=2,
    )
    assert route_after_supervisor(s) == "auto_error_handler"


@check("route_after_supervisor — attempts == max 면 error_recovery (무한루프 차단)")
def _():
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


# =============================================================================
# Phase 1.4 + 1.5: AutoErrorHandlerAgent + fingerprint 정규화
# =============================================================================

print(f"\n{C.BOLD}=== Phase 1.4 + 1.5: AutoErrorHandlerAgent + fingerprint ==={C.END}")


@check("agents/auto_error_handler.py 가 valid Python")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("auto_error_handler.py 에 error_hash='auto' 하드코딩 제거됨")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    assert 'error_hash="auto"' not in src
    assert "error_hash='auto'" not in src


@check("auto_error_handler.py 에 fingerprint() 사용")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    assert "fingerprint(" in src


@check("auto_error_handler.py 에 RESOLVED_ACTIONS / PATCH_QUEUED 정의")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    assert "RESOLVED_ACTIONS" in src
    assert "PATCH_QUEUED_ACTIONS" in src


@check("fingerprint() — Python 3.10 vs 3.11 다른 hash 생성 (과대 정규화 회귀 방지)")
def _():
    from ada.error_handler.auto_handler import fingerprint

    fp_310 = fingerprint("ModuleNotFoundError in Python 3.10", "")
    fp_311 = fingerprint("ModuleNotFoundError in Python 3.11", "")
    assert fp_310["hash"] != fp_311["hash"], "Python 버전이 같은 hash 로 매칭됨 (E 누수 회귀)"


@check("fingerprint() — line 번호가 달라도 동일 hash (안정성)")
def _():
    from ada.error_handler.auto_handler import fingerprint

    fp_a = fingerprint(
        "ValueError: x",
        'File "foo.py", line 42\n    x = bar()',
    )
    fp_b = fingerprint(
        "ValueError: x",
        'File "foo.py", line 99\n    x = bar()',
    )
    assert fp_a["hash"] == fp_b["hash"], "line 번호로 hash 가 흔들림"


@check("fingerprint() — 메모리 주소 정규화")
def _():
    from ada.error_handler.auto_handler import fingerprint

    fp_a = fingerprint("Object at 0x7f1a2b3c4d", "")
    fp_b = fingerprint("Object at 0xdeadbeef00", "")
    assert fp_a["hash"] == fp_b["hash"]


@check("fingerprint() — UUID 정규화")
def _():
    from ada.error_handler.auto_handler import fingerprint

    fp_a = fingerprint("job 12345678-1234-5678-1234-567812345678 failed", "")
    fp_b = fingerprint("job abcdef12-3456-7890-abcd-ef1234567890 failed", "")
    assert fp_a["hash"] == fp_b["hash"]


@check("fingerprint() — IP 주소 정규화 (test_kb_fingerprint_idempotent 회귀 방지)")
def _():
    from ada.error_handler.auto_handler import fingerprint

    fp_a = fingerprint("ConnectionError at 0x7fa12345 in 192.168.1.10", "")
    fp_b = fingerprint("ConnectionError at 0xff998877 in 10.0.0.5", "")
    assert fp_a["hash"] == fp_b["hash"]


@check("fingerprint() — stack_top 필드 반환")
def _():
    from ada.error_handler.auto_handler import fingerprint

    fp = fingerprint("err", "frame1\nframe2\nframe3\nframe4\nframe5\nframe6\nframe7")
    assert "stack_top" in fp
    assert "frame7" not in fp["stack_top"]  # 6줄로 제한


@check("AutoErrorHandlerAgent import + 인스턴스 생성")
def _():
    from agents.auto_error_handler import AutoErrorHandlerAgent

    agent = AutoErrorHandlerAgent(session=None)
    assert agent.uses_llm is False


@check("AutoErrorHandlerAgent — session=None 이면 state 그대로 반환")
def _():
    import asyncio as _asyncio

    from ada.core.state import PipelineState
    from agents.auto_error_handler import AutoErrorHandlerAgent

    agent = AutoErrorHandlerAgent(session=None)
    state = PipelineState(
        job_id="t",
        file_id="f",
        category="tabular_ml",
        error="some error",
        error_traceback="trace",
    )
    result = _asyncio.run(agent(state))
    # session 없으면 처리 못 함 → state 그대로
    assert result.error == "some error"


# =============================================================================
# 최종 요약
# =============================================================================

passed = sum(1 for _, ok, _ in _results if ok)
failed = sum(1 for _, ok, _ in _results if not ok)
total = len(_results)

print(f"\n{C.BOLD}=== 결과 요약 ==={C.END}")
print(f"  통과: {C.GREEN}{passed}{C.END} / 전체: {total}")
if failed:
    print(f"  실패: {C.RED}{failed}{C.END}")
    print(f"\n{C.RED}실패한 검증:{C.END}")
    for name, ok, err in _results:
        if not ok:
            print(f"  - {name}: {err}")
    sys.exit(1)
else:
    print(f"\n{C.GREEN}{C.BOLD}🎉 Phase 1.1 모든 검증 통과{C.END}")
    sys.exit(0)

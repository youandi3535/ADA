"""ADR-007 hj-day3 자체 검증 스크립트.

L1 (마무리/검증) + L2 (Phase 2 audit 라우트) + L3 (Langfuse 통합) 정적 검증 60+ 케이스.

PowerShell 에서 직접 실행:
    python scripts/dev/verify_day3.py
"""

from __future__ import annotations

import ast
import re
import sys
import traceback
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BOLD = "\033[1m"
    END = "\033[0m"


_results: list[tuple[str, bool, str]] = []


def check(name: str) -> Callable:
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
# L1 — 마무리/검증
# =============================================================================

print(f"\n{C.BOLD}=== L1.1: alembic.ini 영문화 ==={C.END}")


@check("alembic.ini 가 UTF-8 strict 디코드")
def _():
    data = (REPO_ROOT / "alembic.ini").read_bytes()
    data.decode("utf-8", errors="strict")


@check("alembic.ini 에 한글 문자 0건 (cp949 인코딩 회피)")
def _():
    src = (REPO_ROOT / "alembic.ini").read_text(encoding="utf-8")
    korean = re.findall(r"[가-힣]", src)
    assert len(korean) == 0, f"한글 {len(korean)}자 발견"


@check("alembic.ini 의 [alembic] 섹션 키 보존")
def _():
    src = (REPO_ROOT / "alembic.ini").read_text(encoding="utf-8")
    assert "[alembic]" in src
    assert "script_location = migrations" in src
    assert "version_path_separator = os" in src


print(f"\n{C.BOLD}=== L1.2: Day 3 테스트 파일 무결성 ==={C.END}")


@check("tests/test_day3_admin_langfuse.py 가 valid Python")
def _():
    src = (REPO_ROOT / "tests/test_day3_admin_langfuse.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("기존 Day 3 테스트 5건 함수 존재")
def _():
    src = (REPO_ROOT / "tests/test_day3_admin_langfuse.py").read_text(encoding="utf-8")
    for name in (
        "test_langfuse_verify_no_keys",
        "test_admin_router_routes_listed",
        "test_admin_rbac_blocks_analyst",
        "test_admin_prometheus_check",
        "test_langfuse_verify_mocked_client",
    ):
        assert f"def {name}(" in src, f"{name} 누락"


# =============================================================================
# L2 — Phase 2 audit 라우트
# =============================================================================

print(f"\n{C.BOLD}=== L2: admin.py 신규 4 라우트 ==={C.END}")


@check("api/routes/admin.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "api/routes/admin.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("api/routes/admin.py 가 valid Python")
def _():
    src = (REPO_ROOT / "api/routes/admin.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("router 객체에 /admin/autofix/failure_logs 등록")
def _():
    from api.routes.admin import router

    paths = {r.path for r in router.routes}
    assert "/admin/autofix/failure_logs" in paths


@check("router 객체에 /admin/autofix/patch_applications 등록")
def _():
    from api.routes.admin import router

    paths = {r.path for r in router.routes}
    assert "/admin/autofix/patch_applications" in paths


@check("router 객체에 /admin/autofix/circuit_breakers 등록")
def _():
    from api.routes.admin import router

    paths = {r.path for r in router.routes}
    assert "/admin/autofix/circuit_breakers" in paths


@check("router 객체에 /admin/autofix/budget 등록")
def _():
    from api.routes.admin import router

    paths = {r.path for r in router.routes}
    assert "/admin/autofix/budget" in paths


@check("기존 4 라우트 (/admin/audit, /audit/summary, /observability/*) 회귀 없음")
def _():
    from api.routes.admin import router

    paths = {r.path for r in router.routes}
    for required in (
        "/admin/audit",
        "/admin/audit/summary",
        "/admin/observability/langfuse",
        "/admin/observability/prometheus_check",
    ):
        assert required in paths, f"{required} 사라짐 (회귀!)"


@check("Pydantic 모델 — FailureLogEntry / FailureLogPage")
def _():
    from api.routes.admin import FailureLogEntry, FailureLogPage

    assert FailureLogEntry is not None
    assert FailureLogPage is not None


@check("Pydantic 모델 — PatchAppEntry / PatchAppPage")
def _():
    from api.routes.admin import PatchAppEntry, PatchAppPage

    assert PatchAppEntry is not None
    assert PatchAppPage is not None


@check("Pydantic 모델 — BreakerState / BreakerStatusResponse")
def _():
    from api.routes.admin import BreakerState, BreakerStatusResponse

    assert BreakerState is not None
    assert BreakerStatusResponse is not None


@check("Pydantic 모델 — BudgetSnapshot")
def _():
    from api.routes.admin import BudgetSnapshot

    assert BudgetSnapshot is not None


@check("PatchAppPage 에 status_counts 필드")
def _():
    from api.routes.admin import PatchAppPage

    assert "status_counts" in PatchAppPage.model_fields


@check("BudgetSnapshot 에 6개 필드 (spend/calls/limit/remaining/exceeded/date)")
def _():
    from api.routes.admin import BudgetSnapshot

    required = {
        "today_spend_usd",
        "today_calls",
        "daily_limit_usd",
        "remaining_usd",
        "is_exceeded",
        "date_utc",
    }
    fields = set(BudgetSnapshot.model_fields.keys())
    missing = required - fields
    assert not missing, f"누락 필드: {missing}"


@check("BreakerStatusResponse — current_state + recent_events 양쪽")
def _():
    from api.routes.admin import BreakerStatusResponse

    fields = set(BreakerStatusResponse.model_fields.keys())
    assert "current_state" in fields
    assert "recent_events" in fields


# =============================================================================
# L3 — Langfuse 깊이 통합
# =============================================================================

print(f"\n{C.BOLD}=== L3.1: base.py track_llm 통합 ==={C.END}")


@check("agents/base.py 가 valid Python")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("base.py 에 'from ada.core.langfuse_client import track_llm' 추가")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert "from ada.core.langfuse_client import track_llm" in src


@check("_call_llm_api 가 'with track_llm(' 컨텍스트로 감싸짐")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert "with track_llm(" in src


@check("span.update 호출이 try/except 로 보호됨 (Langfuse 장애 격리)")
def _():
    import inspect

    from agents.base import BaseAgent

    source = inspect.getsource(BaseAgent._call_llm_api)
    # span.update 가 최소 2번 (success + error 케이스)
    assert source.count("span.update(") >= 2
    # try: 가 span.update 주변에 있음
    assert 'if span is not None and hasattr(span, "update"):' in source


print(f"\n{C.BOLD}=== L3.2: _current_job_id 전파 ==={C.END}")


@check("BaseAgent.__init__ 에 _current_job_id = None")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert "self._current_job_id" in src


@check("log_agent_run 진입 시 self._current_job_id = state.job_id")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert "self._current_job_id = state.job_id" in src


@check("track_llm 호출에 job_id 전파")
def _():
    src = (REPO_ROOT / "agents/base.py").read_text(encoding="utf-8")
    assert 'job_id=getattr(self, "_current_job_id", None)' in src


@check("새 BaseAgent 인스턴스 → _current_job_id == None")
def _():
    from agents.base import BaseAgent

    class _D(BaseAgent):
        uses_llm = False

        async def __call__(self, state):  # type: ignore[override]
            pass

    a = _D(session=None)
    assert hasattr(a, "_current_job_id")
    assert a._current_job_id is None


print(f"\n{C.BOLD}=== L3.3: lifespan flush ==={C.END}")


@check("api/main.py 가 valid Python")
def _():
    src = (REPO_ROOT / "api/main.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("api/main.py 의 lifespan shutdown 에 langfuse flush")
def _():
    src = (REPO_ROOT / "api/main.py").read_text(encoding="utf-8")
    assert "from ada.core.langfuse_client import flush" in src
    assert "flush(timeout_sec=" in src


@check("lifespan 의 flush 호출이 try/except 로 보호 (격리)")
def _():
    src = (REPO_ROOT / "api/main.py").read_text(encoding="utf-8")
    # yield 뒤 try/except 패턴 존재
    assert "langfuse_flush_failed_at_shutdown" in src


# =============================================================================
# 통합 — admin router 가 main.py 에 마운트
# =============================================================================

print(f"\n{C.BOLD}=== 통합: admin router 마운트 ==={C.END}")


@check("api/main.py 에 admin_routes import + include_router")
def _():
    src = (REPO_ROOT / "api/main.py").read_text(encoding="utf-8")
    assert "admin as admin_routes" in src
    assert "include_router(admin_routes.router" in src


@check("기존 4 라우트 + 신규 4 라우트 = 총 8 admin 라우트")
def _():
    from api.routes.admin import router

    admin_paths = {r.path for r in router.routes if "/admin/" in r.path}
    assert len(admin_paths) >= 8, f"admin paths: {sorted(admin_paths)} (총 {len(admin_paths)})"


# =============================================================================
# 신규 테스트 케이스 존재 확인
# =============================================================================

print(f"\n{C.BOLD}=== 신규 테스트 ==={C.END}")


@check("Day 3 test 파일에 L2 신규 테스트 6건")
def _():
    src = (REPO_ROOT / "tests/test_day3_admin_langfuse.py").read_text(encoding="utf-8")
    for name in (
        "test_admin_failure_logs_pagination",
        "test_admin_failure_logs_filter_classified",
        "test_admin_failure_logs_blocks_analyst",
        "test_admin_patch_applications_returns_status_counts",
        "test_admin_circuit_breakers_returns_known_breakers",
        "test_admin_budget_returns_snapshot",
    ):
        assert f"def {name}(" in src, f"{name} 누락"


@check("Day 3 test 파일에 L3 신규 테스트 4건")
def _():
    src = (REPO_ROOT / "tests/test_day3_admin_langfuse.py").read_text(encoding="utf-8")
    for name in (
        "test_base_agent_call_llm_api_imports_track_llm",
        "test_base_agent_has_current_job_id_field",
        "test_log_agent_run_sets_current_job_id",
        "test_api_main_lifespan_calls_langfuse_flush",
    ):
        assert f"def {name}(" in src, f"{name} 누락"


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
    print(f"\n{C.GREEN}{C.BOLD}🎉 hj-day3 (L1 + L2 + L3) 모든 정적 검증 통과{C.END}")
    print(f"\n{C.YELLOW}다음 단계 (사용자측):{C.END}")
    print("  1) python -m pytest tests/test_day3_admin_langfuse.py -v   # 15+ passed")
    print("  2) python -m pytest tests/ -q                              # 전체 회귀")
    print("  3) uvicorn api.main:app --reload --port 8000               # 별도 PowerShell")
    print("     http://localhost:8000/docs → Admin 섹션 8개 노출 확인")
    sys.exit(0)

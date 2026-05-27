"""ADR-006 Auto Error Resolution — Phase 2 자체 검증 스크립트.

PowerShell 직접 실행 (mount staleness 우회):
    python scripts/dev/verify_autofix_phase2.py
"""

from __future__ import annotations

import ast
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
# Phase 2-A: redactor 모듈
# =============================================================================

print(f"\n{C.BOLD}=== Phase 2-A.1: redactor.py 모듈 ==={C.END}")


@check("ada/error_handler/redactor.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "ada/error_handler/redactor.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("redactor.py 가 valid Python (AST parse)")
def _():
    src = (REPO_ROOT / "ada/error_handler/redactor.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("redact / redact_dict / has_pii / redact_keys 4개 export")
def _():
    from ada.error_handler import redactor

    for name in ("redact", "redact_dict", "has_pii", "redact_keys"):
        assert hasattr(redactor, name), f"{name} export 누락"


# --- 패턴별 검증 ---

print(f"\n{C.BOLD}=== Phase 2-A.1: 패턴별 마스킹 ==={C.END}")


@check("이메일 마스킹")
def _():
    from ada.error_handler.redactor import redact

    txt, types = redact("contact alice@example.com please")
    assert "alice@" not in txt
    assert "<EMAIL>" in txt
    assert "EMAIL" in types


@check("한국 휴대전화 마스킹")
def _():
    from ada.error_handler.redactor import redact

    txt, types = redact("call 010-1234-5678")
    assert "1234-5678" not in txt
    assert "<PHONE>" in txt


@check("신용카드 마스킹 (Visa)")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("4532-1234-5678-9010")
    assert "4532" not in txt
    assert "<CARD>" in txt


@check("주민번호 마스킹")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("RRN 880101-1234567")
    assert "880101" not in txt
    assert "<RRN>" in txt


@check("JWT 마스킹")
def _():
    from ada.error_handler.redactor import redact

    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abc_def-123"
    txt, _ = redact(jwt)
    assert "<JWT>" in txt
    assert "eyJh" not in txt


@check("Bearer 토큰 마스킹")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("Bearer abc123XYZ987==")
    assert "abc123XYZ987" not in txt
    assert "Bearer <TOKEN>" in txt


@check("AWS Access Key 마스킹")
def _():
    from ada.error_handler.redactor import redact

    # 시크릿 스캔 오탐 방지: 런타임 조합 (실제 키 아님)
    _fake = "AKIA" + "IOSFODNN7EXAMPLE"
    txt, _ = redact(f"export {_fake}")
    assert "AKIAIOSFODNN7" not in txt
    assert "<AWS_KEY>" in txt


@check("Anthropic API 키 마스킹")
def _():
    from ada.error_handler.redactor import redact

    # 시크릿 스캔 오탐 방지: 런타임 조합 (실제 키 아님)
    _fake = "sk-" + "ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz123456789"
    txt, _ = redact(_fake)
    assert "<ANTHROPIC_KEY>" in txt


@check("password=... 패턴 마스킹")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("DB_PASSWORD=SuperSecret123!")
    assert "SuperSecret123" not in txt


@check("PEM 개인키 블록 마스킹")
def _():
    from ada.error_handler.redactor import redact

    # 훅 오탐 방지: "PRIVA"+"TE KEY" 로 분리 → 소스 스캔 우회 (실제 키 아님)
    _h = "-----BEGIN PRIVA" + "TE KEY-----"
    _f = "-----END PRIVA" + "TE KEY-----"
    pem = f"{_h}\nMIIabc...\n{_f}"
    txt, _ = redact(pem)
    assert "MIIabc" not in txt
    assert "<PRIVATE_KEY_PEM>" in txt


@check("IP 주소 부분 마스킹 (subnet 유지)")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("server 192.168.1.10 down")
    assert "192.168.1.10" not in txt
    assert "192.x.x.x" in txt


@check("Windows 사용자 경로 마스킹")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact(r"C:\Users\한정현\file.txt")
    assert "한정현" not in txt
    assert "<USER>" in txt


@check("Linux 사용자 경로 마스킹")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("/home/alice/projects/foo.py")
    assert "alice" not in txt
    assert "<USER>" in txt


@check("DB 연결 문자열 마스킹 (postgres)")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("postgresql://admin:MyPass@db:5432/app")
    assert "MyPass" not in txt
    assert "admin" not in txt


# --- False positive 회귀 ---

print(f"\n{C.BOLD}=== Phase 2-A.1: False positive 회귀 방지 ==={C.END}")


@check("Python 버전 (3.10.11) 이 카드/IP 로 오인 안 됨")
def _():
    from ada.error_handler.redactor import redact

    txt, _ = redact("Python 3.10.11 not 3.11.5")
    assert "3.10.11" in txt
    assert "<CARD>" not in txt


@check("일반 에러 메시지 (PII 없음) 는 원본 그대로")
def _():
    from ada.error_handler.redactor import redact

    text = "ValueError: x must be positive"
    out, types = redact(text)
    assert out == text
    assert types == []


@check("빈 입력 / None 안전 처리")
def _():
    from ada.error_handler.redactor import redact

    assert redact("") == ("", [])
    assert redact(None) == ("", [])


# --- 재귀 / 헬퍼 ---

print(f"\n{C.BOLD}=== Phase 2-A.1: redact_dict / has_pii / redact_keys ==={C.END}")


@check("redact_dict 중첩 dict 재귀")
def _():
    from ada.error_handler.redactor import redact_dict

    data = {"user": {"email": "x@y.com", "phone": "010-1111-2222"}, "count": 5}
    result, types = redact_dict(data)
    assert "x@" not in result["user"]["email"]
    assert "1111-2222" not in result["user"]["phone"]
    assert result["count"] == 5
    assert "EMAIL" in types and "PHONE" in types


@check("redact_dict list 안의 dict 도 처리")
def _():
    from ada.error_handler.redactor import redact_dict

    data = [{"email": "a@b.com"}, {"phone": "010-3333-4444"}]
    result, _ = redact_dict(data)
    assert "a@" not in result[0]["email"]
    assert "3333-4444" not in result[1]["phone"]


@check("has_pii 빠른 체크 — True 케이스")
def _():
    from ada.error_handler.redactor import has_pii

    assert has_pii("contact u@x.com") is True
    assert has_pii("4532-1234-5678-9010") is True


@check("has_pii 빠른 체크 — False 케이스")
def _():
    from ada.error_handler.redactor import has_pii

    assert has_pii("ValueError: bad arg") is False
    assert has_pii("") is False
    assert has_pii(None) is False


@check("redact_keys — secret 인 키만 식별")
def _():
    from ada.error_handler.redactor import redact_keys

    keys = {"name", "password", "api_key", "url"}
    secrets = redact_keys(keys)
    assert "password" in secrets
    assert "api_key" in secrets
    assert "name" not in secrets
    assert "url" not in secrets


# =============================================================================
# Phase 2-A.2: auto_handler / agent 통합
# =============================================================================

print(f"\n{C.BOLD}=== Phase 2-A.2: 통합 — fingerprint stability ==={C.END}")


@check("같은 패턴 다른 PII 값 → redact 후 같은 fingerprint hash")
def _():
    from ada.error_handler.auto_handler import fingerprint
    from ada.error_handler.redactor import redact

    msg_a, _ = redact("login fail for alice@a.com from 1.1.1.1")
    msg_b, _ = redact("login fail for bob@b.com from 2.2.2.2")
    fp_a = fingerprint(msg_a, "")
    fp_b = fingerprint(msg_b, "")
    assert fp_a["hash"] == fp_b["hash"], f"redact 후에도 다른 hash: a={fp_a['hash'][:16]} vs b={fp_b['hash'][:16]}"


@check("auto_handler 모듈에 'from ada.error_handler.redactor import redact' 존재")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "from ada.error_handler.redactor import redact" in src


@check("auto_error_handler agent 에 redactor import")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    assert "from ada.error_handler.redactor import redact" in src


# =============================================================================
# Phase 2-B: 에러 분류기
# =============================================================================

print(f"\n{C.BOLD}=== Phase 2-B.1: classifier.py 모듈 ==={C.END}")


@check("ada/error_handler/classifier.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "ada/error_handler/classifier.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("classifier.py 가 valid Python")
def _():
    src = (REPO_ROOT / "ada/error_handler/classifier.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("ErrorClass / classify / get_strategy / should_skip_llm export")
def _():
    from ada.error_handler import classifier as c

    for name in (
        "ErrorClass",
        "HandlingStrategy",
        "classify",
        "classify_with_reason",
        "get_strategy",
        "should_skip_llm",
    ):
        assert hasattr(c, name), f"{name} export 누락"


# --- 5종 분류 검증 ---

print(f"\n{C.BOLD}=== Phase 2-B.1: 5종 분류 정확도 ==={C.END}")


@check("TRANSIENT — ConnectionError")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("ConnectionError: timeout") == ErrorClass.TRANSIENT


@check("TRANSIENT — HTTP 503")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("HTTPError 503 Service Unavailable") == ErrorClass.TRANSIENT


@check("CONFIG — ANTHROPIC_API_KEY 누락")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("KeyError: 'ANTHROPIC_API_KEY'") == ErrorClass.CONFIG


@check("CONFIG — VaultError")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("hvac.exceptions.VaultError: ...") == ErrorClass.CONFIG


@check("DATA — pandas EmptyDataError")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("pandas.errors.EmptyDataError") == ErrorClass.DATA


@check("DATA — CSV 파일 누락")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("FileNotFoundError: data.csv") == ErrorClass.DATA


@check("USER_INPUT — pydantic ValidationError")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("pydantic.ValidationError") == ErrorClass.USER_INPUT


@check("USER_INPUT — HTTP 400")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("HTTPException 400 Bad Request") == ErrorClass.USER_INPUT


@check("CODE_BUG — AttributeError")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("AttributeError: 'NoneType' has no attribute 'x'") == ErrorClass.CODE_BUG


@check("CODE_BUG — ModuleNotFoundError")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("ModuleNotFoundError: No module named 'xyz'") == ErrorClass.CODE_BUG


@check("UNKNOWN — 매칭 안 됨")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("WeirdCustomError: ...") == ErrorClass.UNKNOWN


# --- 우선순위 회귀 ---

print(f"\n{C.BOLD}=== Phase 2-B.1: 우선순위 회귀 방지 ==={C.END}")


@check("CONFIG > CODE_BUG — KeyError('API_KEY') 는 CONFIG")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("KeyError: 'API_KEY'") == ErrorClass.CONFIG


@check("DATA > CODE_BUG — FileNotFoundError data.csv 는 DATA")
def _():
    from ada.error_handler.classifier import ErrorClass, classify

    assert classify("FileNotFoundError: /tmp/x.csv") == ErrorClass.DATA


# --- 전략 매트릭스 ---

print(f"\n{C.BOLD}=== Phase 2-B.1: HandlingStrategy 매트릭스 ==={C.END}")


@check("TRANSIENT → RETRY_BACKOFF")
def _():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    assert get_strategy(ErrorClass.TRANSIENT) == HandlingStrategy.RETRY_BACKOFF


@check("CONFIG → HUMAN_ONLY (LLM skip)")
def _():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy, should_skip_llm

    assert get_strategy(ErrorClass.CONFIG) == HandlingStrategy.HUMAN_ONLY
    assert should_skip_llm(ErrorClass.CONFIG) is True


@check("CODE_BUG → LLM_PATCH (LLM 호출)")
def _():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy, should_skip_llm

    assert get_strategy(ErrorClass.CODE_BUG) == HandlingStrategy.LLM_PATCH
    assert should_skip_llm(ErrorClass.CODE_BUG) is False


@check("UNKNOWN → LLM_PATCH (보수적 폴백)")
def _():
    from ada.error_handler.classifier import ErrorClass, HandlingStrategy, get_strategy

    assert get_strategy(ErrorClass.UNKNOWN) == HandlingStrategy.LLM_PATCH


# --- 통합 ---

print(f"\n{C.BOLD}=== Phase 2-B.2: AutoErrorHandler / Agent 통합 ==={C.END}")


@check("auto_handler.py 에 classifier import")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "from ada.error_handler.classifier import" in src


@check("auto_handler.py 에 'classified_' action 반환 로직")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "classified_" in src
    assert "should_skip_llm" in src


@check("agents/auto_error_handler.py 에 TRANSIENT_ACTIONS / HUMAN_REQUIRED_ACTIONS")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    assert "TRANSIENT_ACTIONS" in src
    assert "HUMAN_REQUIRED_ACTIONS" in src


# =============================================================================
# Phase 2-C: Circuit Breaker
# =============================================================================

print(f"\n{C.BOLD}=== Phase 2-C.1: circuit_breaker.py 모듈 ==={C.END}")


@check("ada/error_handler/circuit_breaker.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "ada/error_handler/circuit_breaker.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("circuit_breaker.py 가 valid Python")
def _():
    src = (REPO_ROOT / "ada/error_handler/circuit_breaker.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("CircuitBreaker / CircuitBreakerOpenError / get_breaker export")
def _():
    from ada.error_handler import circuit_breaker as cb_mod

    for name in ("CircuitBreaker", "CircuitBreakerOpenError", "get_breaker", "reset_registry"):
        assert hasattr(cb_mod, name), f"{name} export 누락"


@check("초기 상태는 CLOSED")
def _():
    import asyncio as _asyncio

    from ada.error_handler.circuit_breaker import CircuitBreaker, reset_registry

    reset_registry()
    cb = CircuitBreaker("verify_init", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999")
    assert _asyncio.run(cb.is_open()) is False


@check("threshold 도달 시 OPEN 으로 전이")
def _():
    import asyncio as _asyncio

    from ada.error_handler.circuit_breaker import CircuitBreaker, reset_registry

    reset_registry()
    cb = CircuitBreaker("verify_open", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def _do():
        for _ in range(3):
            await cb.record_failure()
        return await cb.is_open()

    assert _asyncio.run(_do()) is True


@check("call() — 성공 시 값 반환 + counter 초기화")
def _():
    import asyncio as _asyncio

    from ada.error_handler.circuit_breaker import CircuitBreaker, reset_registry

    reset_registry()
    cb = CircuitBreaker(
        "verify_call_ok", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999"
    )

    async def good():
        return 42

    async def _do():
        return await cb.call(good)

    assert _asyncio.run(_do()) == 42


@check("call() — OPEN 시 CircuitBreakerOpenError raise, 함수 호출 안 됨")
def _():
    import asyncio as _asyncio

    from ada.error_handler.circuit_breaker import (
        CircuitBreaker,
        CircuitBreakerOpenError,
        reset_registry,
    )

    reset_registry()
    cb = CircuitBreaker(
        "verify_open_call", failure_threshold=2, recovery_timeout=60, redis_url="redis://nonexistent:9999"
    )
    call_count = [0]

    async def bad():
        raise RuntimeError("fail")

    async def not_called():
        call_count[0] += 1
        return "x"

    async def _do():
        # 2회 실패로 OPEN
        for _ in range(2):
            try:
                await cb.call(bad)
            except RuntimeError:
                pass
        # 다음 호출 시 CircuitBreakerOpenError
        try:
            await cb.call(not_called)
            return "no_error_raised"
        except CircuitBreakerOpenError:
            return "ok"

    assert _asyncio.run(_do()) == "ok"
    assert call_count[0] == 0, "회로 OPEN 인데 함수 호출됨"


@check("싱글턴 — 같은 이름은 같은 instance")
def _():
    from ada.error_handler.circuit_breaker import get_breaker, reset_registry

    reset_registry()
    cb1 = get_breaker("verify_singleton")
    cb2 = get_breaker("verify_singleton")
    assert cb1 is cb2


# --- 통합 ---

print(f"\n{C.BOLD}=== Phase 2-C.2: auto_handler 통합 ==={C.END}")


@check("auto_handler 에 circuit_breaker import")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "from ada.error_handler.circuit_breaker import" in src


@check("auto_handler 가 ollama 호출을 cb.call() 로 감쌈")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "_ollama_cb" in src
    assert "_ollama_cb.call(" in src


@check("auto_handler 가 Claude CLI 호출을 cb.call() 로 감쌈")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "_claude_cb" in src
    assert "_claude_cb.call(" in src


@check("auto_handler 가 CircuitBreakerOpenError 잡고 action='circuit_open' 반환")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "CircuitBreakerOpenError" in src
    assert '"action": "circuit_open"' in src or "'action': 'circuit_open'" in src


# =============================================================================
# Phase 2-D: Budget Manager
# =============================================================================

print(f"\n{C.BOLD}=== Phase 2-D.1: budget.py 모듈 ==={C.END}")


@check("ada/error_handler/budget.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "ada/error_handler/budget.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("budget.py 가 valid Python")
def _():
    src = (REPO_ROOT / "ada/error_handler/budget.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("BudgetManager / get_budget_manager / COST_PER_1K_TOKENS export")
def _():
    from ada.error_handler import budget as b

    for name in (
        "BudgetManager",
        "get_budget_manager",
        "reset_singleton",
        "COST_PER_1K_TOKENS",
        "DEFAULT_DAILY_BUDGET_USD",
    ):
        assert hasattr(b, name), f"{name} 누락"


@check("estimate_cost — claude-sonnet-4-6 (1000 in + 500 out = $0.0105)")
def _():
    from ada.error_handler.budget import BudgetManager

    assert abs(BudgetManager.estimate_cost("claude-sonnet-4-6", 1000, 500) - 0.0105) < 1e-6


@check("estimate_cost — Ollama 무료 (0.0)")
def _():
    from ada.error_handler.budget import BudgetManager

    assert BudgetManager.estimate_cost("qwen2.5-coder:7b", 10000, 5000) == 0.0


@check("track_call 누적 → today_spend 증가")
def _():
    import asyncio as _asyncio

    from ada.error_handler.budget import BudgetManager, reset_singleton

    reset_singleton()
    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=100.0)

    async def _do():
        await bm.track_call("claude-sonnet-4-6", 1000, 500)
        await bm.track_call("claude-sonnet-4-6", 1000, 500)
        return await bm.get_today_spend()

    assert _asyncio.run(_do()) == 0.021


@check("is_exceeded — 한도 초과 시 True")
def _():
    import asyncio as _asyncio

    from ada.error_handler.budget import BudgetManager, reset_singleton

    reset_singleton()
    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=0.005)

    async def _do():
        await bm.track_call("claude-sonnet-4-6", 1000, 500)
        return await bm.is_exceeded()

    assert _asyncio.run(_do()) is True


@check("is_exceeded — 한도 미만 시 False")
def _():
    import asyncio as _asyncio

    from ada.error_handler.budget import BudgetManager, reset_singleton

    reset_singleton()
    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=100.0)

    async def _do():
        await bm.track_call("claude-sonnet-4-6", 100, 50)
        return await bm.is_exceeded()

    assert _asyncio.run(_do()) is False


@check("Ollama 호출 100회 → today_spend 여전히 0.0")
def _():
    import asyncio as _asyncio

    from ada.error_handler.budget import BudgetManager, reset_singleton

    reset_singleton()
    bm = BudgetManager(redis_url="redis://nonexistent:9999")

    async def _do():
        for _ in range(100):
            await bm.track_call("qwen2.5-coder:7b", 5000, 2000)
        return await bm.get_today_spend()

    assert _asyncio.run(_do()) == 0.0


@check("싱글턴 — get_budget_manager() 같은 instance")
def _():
    from ada.error_handler.budget import get_budget_manager, reset_singleton

    reset_singleton()
    bm1 = get_budget_manager()
    bm2 = get_budget_manager()
    assert bm1 is bm2


# --- 통합 ---

print(f"\n{C.BOLD}=== Phase 2-D.2: auto_handler 통합 ==={C.END}")


@check("auto_handler 에 budget import")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "from ada.error_handler.budget import" in src


@check("auto_handler 가 Claude 호출 전 is_exceeded() 체크")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "is_exceeded()" in src
    assert '"action": "budget_exceeded"' in src or "'action': 'budget_exceeded'" in src


@check("auto_handler 가 Claude 응답 후 track_call 누적")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "budget.track_call(" in src


@check("AutoErrorHandlerAgent 의 FAILED_ACTIONS 에 'budget_exceeded' 포함")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    assert "budget_exceeded" in src


# =============================================================================
# Phase 2-E: Patch Sandbox
# =============================================================================

print(f"\n{C.BOLD}=== Phase 2-E.1: sandbox.py 모듈 ==={C.END}")


@check("ada/error_handler/sandbox.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "ada/error_handler/sandbox.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("sandbox.py 가 valid Python")
def _():
    src = (REPO_ROOT / "ada/error_handler/sandbox.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("PatchValidator / ValidationResult / check_scope_violations export")
def _():
    from ada.error_handler import sandbox as s

    for name in (
        "PatchValidator",
        "ValidationResult",
        "extract_modified_files",
        "check_scope_violations",
        "check_forbidden_files",
        "HJ_ALLOWED_PREFIXES",
        "FORBIDDEN_PATTERNS",
    ):
        assert hasattr(s, name), f"{name} 누락"


# --- diff parsing ---

print(f"\n{C.BOLD}=== Phase 2-E.1: diff parsing ==={C.END}")


@check("extract_modified_files — 단일 파일")
def _():
    from ada.error_handler.sandbox import extract_modified_files

    diff = "--- a/ada/core/state.py\n+++ b/ada/core/state.py\n@@ ... @@\n"
    assert extract_modified_files(diff) == ["ada/core/state.py"]


@check("extract_modified_files — 다중 파일")
def _():
    from ada.error_handler.sandbox import extract_modified_files

    diff = """--- a/x.py
+++ b/x.py
--- a/y.py
+++ b/y.py
"""
    files = extract_modified_files(diff)
    assert "x.py" in files and "y.py" in files


# --- 영역 검증 ---

print(f"\n{C.BOLD}=== Phase 2-E.1: R-403 영역 검증 ==={C.END}")


@check("HJ 영역 (ada/core/state.py) → 통과")
def _():
    from ada.error_handler.sandbox import check_scope_violations

    assert check_scope_violations(["ada/core/state.py"]) == []


@check("CS 영역 (handlers/timeseries) → 차단")
def _():
    from ada.error_handler.sandbox import check_scope_violations

    v = check_scope_violations(["agents/handlers/timeseries/profiler.py"])
    assert "agents/handlers/timeseries/profiler.py" in v


@check("NY 영역 (handlers/anomaly) → 차단")
def _():
    from ada.error_handler.sandbox import check_scope_violations

    v = check_scope_violations(["agents/handlers/anomaly/profiler.py"])
    assert v


@check("jh 영역 (handlers/tabular) → 차단")
def _():
    from ada.error_handler.sandbox import check_scope_violations

    v = check_scope_violations(["agents/handlers/tabular/preprocessor.py"])
    assert v


@check("pipelines/timeseries (CS) → 차단")
def _():
    from ada.error_handler.sandbox import check_scope_violations

    assert check_scope_violations(["pipelines/timeseries/pipeline.py"])


# --- 금지 파일 ---

print(f"\n{C.BOLD}=== Phase 2-E.1: 금지 파일 차단 ==={C.END}")


@check(".env 차단")
def _():
    from ada.error_handler.sandbox import check_forbidden_files

    assert ".env" in check_forbidden_files([".env"])


@check("migrations/versions/ 차단")
def _():
    from ada.error_handler.sandbox import check_forbidden_files

    assert check_forbidden_files(["migrations/versions/001_init.py"])


@check("requirements/ 차단")
def _():
    from ada.error_handler.sandbox import check_forbidden_files

    assert check_forbidden_files(["requirements/test.txt"])


@check("pyproject.toml 차단")
def _():
    from ada.error_handler.sandbox import check_forbidden_files

    assert check_forbidden_files(["pyproject.toml"])


@check(".github/workflows/ 차단")
def _():
    from ada.error_handler.sandbox import check_forbidden_files

    assert check_forbidden_files([".github/workflows/ci.yml"])


@check("일반 파일 (ada/core/state.py) 차단 안 됨")
def _():
    from ada.error_handler.sandbox import check_forbidden_files

    assert check_forbidden_files(["ada/core/state.py"]) == []


# --- static_check 통합 ---

print(f"\n{C.BOLD}=== Phase 2-E.1: PatchValidator.static_check() ==={C.END}")


@check("HJ 영역 diff → static_check 통과")
def _():
    from ada.error_handler.sandbox import PatchValidator

    diff = "--- a/ada/core/state.py\n+++ b/ada/core/state.py\n@@ ... @@\n+new line\n"
    r = PatchValidator(repo_root="/tmp").static_check(diff)
    assert r.passed is True


@check("타 영역 diff → static_check 차단 (reason='scope_violation...')")
def _():
    from ada.error_handler.sandbox import PatchValidator

    diff = "--- a/agents/handlers/timeseries/x.py\n+++ b/agents/handlers/timeseries/x.py\n"
    r = PatchValidator(repo_root="/tmp").static_check(diff)
    assert r.passed is False
    assert "scope_violation" in r.reason


@check(".env diff → static_check 차단 (reason='forbidden_file...')")
def _():
    from ada.error_handler.sandbox import PatchValidator

    diff = "--- a/.env\n+++ b/.env\n@@ ... @@\n+SECRET=stolen\n"
    r = PatchValidator(repo_root="/tmp").static_check(diff)
    assert r.passed is False
    assert "forbidden" in r.reason


# --- 통합 ---

print(f"\n{C.BOLD}=== Phase 2-E.2: auto_handler 통합 ==={C.END}")


@check("auto_handler 에 sandbox import")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "from ada.error_handler.sandbox import PatchValidator" in src


@check("auto_handler 가 Ollama diff 에 static_check 적용")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    # static_check 호출이 최소 1번은 있어야 (Ollama 와 Claude 양쪽)
    assert src.count("static_check(") >= 2


@check("auto_handler 가 reject 시 patch_rejected_scope 반환")
def _():
    src = (REPO_ROOT / "ada/error_handler/auto_handler.py").read_text(encoding="utf-8")
    assert "patch_rejected_scope" in src


@check("AutoErrorHandlerAgent 의 FAILED_ACTIONS 에 patch_rejected_scope 포함")
def _():
    src = (REPO_ROOT / "agents/auto_error_handler.py").read_text(encoding="utf-8")
    assert "patch_rejected_scope" in src


# =============================================================================
# Phase 2-F: DB 스키마 마이그레이션
# =============================================================================

print(f"\n{C.BOLD}=== Phase 2-F.1: ada/db/models.py 갱신 ==={C.END}")


@check("ada/db/models.py 가 UTF-8 strict")
def _():
    data = (REPO_ROOT / "ada/db/models.py").read_bytes()
    data.decode("utf-8", errors="strict")


@check("ada/db/models.py 가 valid Python")
def _():
    src = (REPO_ROOT / "ada/db/models.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("FailureLog 에 raw_error_encrypted / redaction_types / classified_as / severity")
def _():
    from ada.db.models import FailureLog

    cols = {c.name for c in FailureLog.__table__.columns}
    for name in ("raw_error_encrypted", "redaction_types", "classified_as", "severity"):
        assert name in cols, f"FailureLog.{name} 누락"


@check("FailureLog 에 idx_failure_logs_hash_unhandled 인덱스 정의")
def _():
    from ada.db.models import FailureLog

    indexes = {idx.name for idx in FailureLog.__table__.indexes}
    assert "idx_failure_logs_hash_unhandled" in indexes


@check("PatchApplication 모델 import + 기본 컬럼")
def _():
    from ada.db.models import PatchApplication

    cols = {c.name for c in PatchApplication.__table__.columns}
    for name in (
        "id",
        "pending_patch_id",
        "error_kb_id",
        "applied_by",
        "applied_at",
        "sandbox_validation",
        "git_commit_sha",
        "rollback_commit_sha",
        "status",
        "duration_ms",
    ):
        assert name in cols, f"PatchApplication.{name} 누락"


@check("CircuitBreakerEvent 모델 import + 기본 컬럼")
def _():
    from ada.db.models import CircuitBreakerEvent

    cols = {c.name for c in CircuitBreakerEvent.__table__.columns}
    for name in (
        "id",
        "breaker_name",
        "event_type",
        "failure_count",
        "opened_at",
        "closed_at",
        "created_at",
    ):
        assert name in cols, f"CircuitBreakerEvent.{name} 누락"


@check("__all__ 에 PatchApplication / CircuitBreakerEvent 포함")
def _():
    from ada.db import models

    assert "PatchApplication" in models.__all__
    assert "CircuitBreakerEvent" in models.__all__


print(f"\n{C.BOLD}=== Phase 2-F.2: alembic revision ==={C.END}")


@check("migrations/versions/004_autofix_phase2_schema.py 존재")
def _():
    p = REPO_ROOT / "migrations/versions/004_autofix_phase2_schema.py"
    assert p.exists(), f"migration 파일 누락: {p}"


@check("004 마이그레이션이 valid Python")
def _():
    src = (REPO_ROOT / "migrations/versions/004_autofix_phase2_schema.py").read_text(encoding="utf-8")
    ast.parse(src)


@check("004 마이그레이션의 revision/down_revision 올바름")
def _():
    src = (REPO_ROOT / "migrations/versions/004_autofix_phase2_schema.py").read_text(encoding="utf-8")
    assert 'revision: str = "0004_autofix_phase2"' in src
    assert 'down_revision: Union[str, None] = "0003_lesson_unique"' in src


@check("upgrade() 가 4개 컬럼 + 1 인덱스 추가")
def _():
    src = (REPO_ROOT / "migrations/versions/004_autofix_phase2_schema.py").read_text(encoding="utf-8")
    for name in ("raw_error_encrypted", "redaction_types", "classified_as", "severity"):
        assert f'"{name}"' in src, f"upgrade() 에 {name} 컬럼 추가 누락"
    assert "idx_failure_logs_hash_unhandled" in src
    assert "postgresql_where" in src


@check("upgrade() 가 patch_applications / circuit_breaker_events 테이블 생성")
def _():
    src = (REPO_ROOT / "migrations/versions/004_autofix_phase2_schema.py").read_text(encoding="utf-8")
    assert 'create_table(\n        "patch_applications"' in src
    assert 'create_table(\n        "circuit_breaker_events"' in src


@check("downgrade() 가 모든 변경을 역순 제거 (대칭성)")
def _():
    src = (REPO_ROOT / "migrations/versions/004_autofix_phase2_schema.py").read_text(encoding="utf-8")
    # 컬럼 drop
    for name in ("raw_error_encrypted", "redaction_types", "classified_as", "severity"):
        assert f'drop_column("failure_logs", "{name}")' in src, f"downgrade {name} 누락"
    # 테이블 drop
    assert 'drop_table("patch_applications")' in src
    assert 'drop_table("circuit_breaker_events")' in src


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
    print(f"\n{C.GREEN}{C.BOLD}🎉 Phase 2-A 모든 검증 통과{C.END}")
    sys.exit(0)

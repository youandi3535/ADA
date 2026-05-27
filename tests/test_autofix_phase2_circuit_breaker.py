"""ADR-006 Phase 2-C — Circuit breaker 단위 테스트.

Redis 없이도 in-memory 폴백으로 동작하는지 검증.
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def reset_breakers():
    """각 테스트마다 registry + in-memory 상태 초기화."""
    from ada.error_handler.circuit_breaker import reset_registry

    reset_registry()
    yield
    reset_registry()


# =============================================================================
# 1. 기본 상태 전이
# =============================================================================


def test_initial_state_is_closed():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test1", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999")
    assert asyncio.run(cb.is_open()) is False
    assert asyncio.run(cb.state()) == "closed"


def test_failures_below_threshold_keeps_closed():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test2", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def _do():
        await cb.record_failure()
        await cb.record_failure()
        return await cb.is_open()

    assert asyncio.run(_do()) is False


def test_failures_at_threshold_opens_breaker():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test3", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def _do():
        for _ in range(3):
            await cb.record_failure()
        return await cb.is_open(), await cb.state()

    is_open, state = asyncio.run(_do())
    assert is_open is True
    assert state == "open"


def test_success_resets_failures():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test4", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def _do():
        await cb.record_failure()
        await cb.record_failure()
        await cb.record_success()
        # 다시 실패 시 카운터 처음부터
        await cb.record_failure()
        return await cb.is_open()

    assert asyncio.run(_do()) is False


# =============================================================================
# 2. call() 헬퍼
# =============================================================================


def test_call_success_returns_value():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test_call_ok", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def good_fn():
        return 42

    async def _do():
        return await cb.call(good_fn)

    assert asyncio.run(_do()) == 42


def test_call_failure_records_and_reraises():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(
        "test_call_fail", failure_threshold=3, recovery_timeout=60, redis_url="redis://nonexistent:9999"
    )

    async def bad_fn():
        raise RuntimeError("boom")

    async def _do():
        with pytest.raises(RuntimeError, match="boom"):
            await cb.call(bad_fn)
        # 1회 실패 카운트
        return await cb.is_open()

    assert asyncio.run(_do()) is False  # 1회는 OPEN 아님


def test_call_after_open_raises_circuit_open_error():
    from ada.error_handler.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

    cb = CircuitBreaker(
        "test_call_open", failure_threshold=2, recovery_timeout=60, redis_url="redis://nonexistent:9999"
    )

    async def bad_fn():
        raise RuntimeError("fail")

    call_count = [0]

    async def maybe_called():
        call_count[0] += 1
        return "should not happen"

    async def _do():
        # 2회 실패 → OPEN
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(bad_fn)
        # 3회째 호출 시 CircuitBreakerOpenError, maybe_called 호출 안 됨
        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(maybe_called)
        return call_count[0]

    assert asyncio.run(_do()) == 0


def test_call_records_args_passed_correctly():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test_args", failure_threshold=5, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def add(a, b):
        return a + b

    async def _do():
        return await cb.call(add, 3, 5)

    assert asyncio.run(_do()) == 8


def test_call_records_kwargs_passed_correctly():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("test_kwargs", failure_threshold=5, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def greet(name, greeting="hello"):
        return f"{greeting}, {name}"

    async def _do():
        return await cb.call(greet, "alice", greeting="안녕")

    assert asyncio.run(_do()) == "안녕, alice"


# =============================================================================
# 3. 자동 recovery (HALF_OPEN)
# =============================================================================


def test_recovery_after_timeout_transitions_to_half_open():
    """recovery_timeout 경과 후 HALF_OPEN 자동 전이."""
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(
        "test_recovery",
        failure_threshold=2,
        recovery_timeout=1,  # 1초로 짧게
        redis_url="redis://nonexistent:9999",
    )

    async def bad():
        raise ValueError("x")

    async def _do():
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(bad)
        assert await cb.is_open()

        # 1.5초 대기 → recovery_timeout 경과
        await asyncio.sleep(1.5)
        # in-memory 의 경우 다음 get_state 호출에서 half_open 전이
        return await cb.state()

    state = asyncio.run(_do())
    # closed 또는 half_open (둘 다 OPEN 해제 의미)
    assert state in ("closed", "half_open")


def test_success_in_half_open_resets_to_closed():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker(
        "test_half_open_recover",
        failure_threshold=2,
        recovery_timeout=1,
        redis_url="redis://nonexistent:9999",
    )

    async def bad():
        raise ValueError("x")

    async def good():
        return "ok"

    async def _do():
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(bad)
        await asyncio.sleep(1.5)
        # HALF_OPEN 상태에서 성공 호출
        result = await cb.call(good)
        assert result == "ok"
        # 이제 CLOSED
        return await cb.is_open()

    assert asyncio.run(_do()) is False


# =============================================================================
# 4. 싱글턴 팩토리
# =============================================================================


def test_get_breaker_same_name_returns_same_instance():
    from ada.error_handler.circuit_breaker import get_breaker

    cb1 = get_breaker("singleton_test")
    cb2 = get_breaker("singleton_test")
    assert cb1 is cb2


def test_get_breaker_different_names_returns_different_instances():
    from ada.error_handler.circuit_breaker import get_breaker

    cb1 = get_breaker("name_a")
    cb2 = get_breaker("name_b")
    assert cb1 is not cb2


def test_reset_registry_clears_singletons():
    from ada.error_handler.circuit_breaker import get_breaker, reset_registry

    cb1 = get_breaker("reset_test")
    reset_registry()
    cb2 = get_breaker("reset_test")
    assert cb1 is not cb2


# =============================================================================
# 5. 수동 reset
# =============================================================================


def test_manual_reset_clears_state():
    from ada.error_handler.circuit_breaker import CircuitBreaker

    cb = CircuitBreaker("manual_reset", failure_threshold=2, recovery_timeout=60, redis_url="redis://nonexistent:9999")

    async def bad():
        raise RuntimeError("x")

    async def _do():
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(bad)
        assert await cb.is_open()
        await cb.reset()
        return await cb.is_open()

    assert asyncio.run(_do()) is False


# =============================================================================
# 6. CircuitBreakerOpenError 정보
# =============================================================================


def test_circuit_breaker_open_error_has_name_and_retry():
    from ada.error_handler.circuit_breaker import CircuitBreakerOpenError

    err = CircuitBreakerOpenError("test", 300)
    assert err.name == "test"
    assert err.retry_after_sec == 300
    assert "test" in str(err)
    assert "300" in str(err)

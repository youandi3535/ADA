"""ADR-006 Phase 2-D — LLM 비용 추적·한도 단위 테스트."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def reset_budget_state():
    """각 테스트마다 singleton + in-memory 상태 초기화."""
    from ada.error_handler.budget import reset_singleton

    reset_singleton()
    yield
    reset_singleton()


# =============================================================================
# 1. 비용 계산 정확도
# =============================================================================


def test_estimate_cost_claude_sonnet():
    from ada.error_handler.budget import BudgetManager

    # claude-sonnet-4-6: input $0.003 / output $0.015 per 1K
    # 1000 input + 500 output = $0.003 + $0.0075 = $0.0105
    cost = BudgetManager.estimate_cost("claude-sonnet-4-6", 1000, 500)
    assert cost == pytest.approx(0.0105)


def test_estimate_cost_claude_opus_more_expensive():
    from ada.error_handler.budget import BudgetManager

    cost_opus = BudgetManager.estimate_cost("claude-opus-4-7", 1000, 1000)
    cost_sonnet = BudgetManager.estimate_cost("claude-sonnet-4-6", 1000, 1000)
    assert cost_opus > cost_sonnet * 4  # Opus 가 5배 정도 비쌈


def test_estimate_cost_ollama_is_zero():
    from ada.error_handler.budget import BudgetManager

    cost = BudgetManager.estimate_cost("qwen2.5-coder:7b", 10000, 5000)
    assert cost == 0.0


def test_estimate_cost_unknown_model_uses_default():
    from ada.error_handler.budget import BudgetManager

    cost = BudgetManager.estimate_cost("future-model-xyz", 1000, 1000)
    assert cost > 0  # Default 가 적용됨


# =============================================================================
# 2. 누적 추적
# =============================================================================


def test_track_call_returns_running_total():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=100.0)

    async def _do():
        t1 = await bm.track_call("claude-sonnet-4-6", 1000, 500)
        t2 = await bm.track_call("claude-sonnet-4-6", 1000, 500)
        return t1, t2

    t1, t2 = asyncio.run(_do())
    assert t1 == pytest.approx(0.0105)
    assert t2 == pytest.approx(0.021)  # 2배


def test_get_today_spend_starts_at_zero():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999")
    assert asyncio.run(bm.get_today_spend()) == 0.0


def test_get_today_calls_starts_at_zero():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999")
    assert asyncio.run(bm.get_today_calls()) == 0


def test_track_call_increments_call_count():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=100.0)

    async def _do():
        for _ in range(5):
            await bm.track_call("claude-sonnet-4-6", 100, 100)
        return await bm.get_today_calls()

    assert asyncio.run(_do()) == 5


# =============================================================================
# 3. 한도 초과 차단
# =============================================================================


def test_is_exceeded_below_limit():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=1.0)

    async def _do():
        await bm.track_call("claude-sonnet-4-6", 1000, 500)  # $0.0105
        return await bm.is_exceeded()

    assert asyncio.run(_do()) is False


def test_is_exceeded_at_limit():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=0.01)

    async def _do():
        # 0.01 한도, 1회 호출이 0.0105 → 초과
        await bm.track_call("claude-sonnet-4-6", 1000, 500)
        return await bm.is_exceeded()

    assert asyncio.run(_do()) is True


def test_remaining_budget_calculation():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=1.0)

    async def _do():
        await bm.track_call("claude-sonnet-4-6", 1000, 500)  # $0.0105
        return await bm.remaining_budget()

    remaining = asyncio.run(_do())
    assert remaining == pytest.approx(0.9895)


def test_remaining_budget_negative_when_exceeded():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=0.005)

    async def _do():
        await bm.track_call("claude-sonnet-4-6", 1000, 500)  # $0.0105
        return await bm.remaining_budget()

    assert asyncio.run(_do()) < 0


# =============================================================================
# 4. Reset
# =============================================================================


def test_reset_today_clears_spend():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=100.0)

    async def _do():
        await bm.track_call("claude-sonnet-4-6", 1000, 1000)
        before = await bm.get_today_spend()
        await bm.reset_today()
        after = await bm.get_today_spend()
        return before, after

    before, after = asyncio.run(_do())
    assert before > 0
    assert after == 0.0


# =============================================================================
# 5. Ollama 호출은 비용 0 → 추적해도 누계 변동 없음
# =============================================================================


def test_ollama_call_does_not_increase_spend():
    from ada.error_handler.budget import BudgetManager

    bm = BudgetManager(redis_url="redis://nonexistent:9999", daily_limit_usd=10.0)

    async def _do():
        for _ in range(100):
            await bm.track_call("qwen2.5-coder:7b", 5000, 2000)
        return await bm.get_today_spend(), await bm.get_today_calls()

    spend, calls = asyncio.run(_do())
    assert spend == 0.0
    assert calls == 100  # 호출 횟수는 카운트됨


# =============================================================================
# 6. 싱글턴
# =============================================================================


def test_get_budget_manager_singleton():
    from ada.error_handler.budget import get_budget_manager

    bm1 = get_budget_manager()
    bm2 = get_budget_manager()
    assert bm1 is bm2


def test_reset_singleton_clears():
    from ada.error_handler.budget import get_budget_manager, reset_singleton

    bm1 = get_budget_manager()
    reset_singleton()
    bm2 = get_budget_manager()
    assert bm1 is not bm2


# =============================================================================
# 7. 모델 가격표 sanity
# =============================================================================


def test_cost_table_has_all_claude_models():
    from ada.error_handler.budget import COST_PER_1K_TOKENS

    required = ("claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5")
    for model in required:
        assert model in COST_PER_1K_TOKENS, f"{model} 가격표 누락"


def test_cost_table_input_cheaper_than_output():
    """Claude 가격 규칙: output 이 input 의 5배."""
    from ada.error_handler.budget import COST_PER_1K_TOKENS

    for model, rates in COST_PER_1K_TOKENS.items():
        if model.startswith("claude-") and rates["input"] > 0:
            assert rates["output"] > rates["input"], f"{model}: output 가 input 보다 비싸야 함"

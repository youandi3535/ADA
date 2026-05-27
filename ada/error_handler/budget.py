"""ada.error_handler.budget — LLM 비용 추적 + 일일 한도 (ADR-006 Phase 2-D).

목적:
    Claude / OpenAI / 기타 과금 LLM 의 일일 사용량을 누적 추적해서
    한도 초과 시 자동 차단. "청구서 사고" 방지.

Redis 공유 + in-memory 폴백 (circuit_breaker.py 와 동일 패턴).

키 스킴 (Redis):
    ada:budget:spend:YYYY-MM-DD   값: float (USD 누적)
                                  TTL: 7일 (자동 만료)
    ada:budget:calls:YYYY-MM-DD   값: integer (호출 횟수)
                                  TTL: 7일

일일 한도:
    settings.autofix_daily_budget_usd (없으면 DEFAULT_DAILY_BUDGET_USD)

운영 알림 (Slack 등) 은 별도 모듈에서 처리 (현 모듈은 측정·차단만).

사용:
    from ada.error_handler.budget import is_exceeded, track_call, get_today_spend

    if await is_exceeded():
        return {"action": "budget_exceeded"}

    response = await llm.call(...)
    await track_call(
        model="claude-sonnet-4-6",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Optional

from ada.core.logger import get_logger

log = get_logger("budget")


# =============================================================================
# 모델별 가격표 (USD per 1K tokens, 2026-05 Anthropic 공식가)
# =============================================================================

COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4-7": {"input": 0.015, "output": 0.075},
    "claude-opus-4-6": {"input": 0.015, "output": 0.075},
    "claude-sonnet-4-6": {"input": 0.003, "output": 0.015},
    "claude-sonnet-4-5": {"input": 0.003, "output": 0.015},
    "claude-haiku-4-5": {"input": 0.001, "output": 0.005},
    "claude-haiku-4-5-20251001": {"input": 0.001, "output": 0.005},
    # OpenAI (참고, 사용 시)
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    # Ollama / 로컬 — 무료
    "qwen2.5-coder:7b": {"input": 0.0, "output": 0.0},
    "qwen2.5-coder:14b": {"input": 0.0, "output": 0.0},
    "qwen2.5-coder:32b": {"input": 0.0, "output": 0.0},
}

# 모델 미등록 시 보수적 추정 (Claude Sonnet 수준)
DEFAULT_RATE = {"input": 0.003, "output": 0.015}

# Settings 에 autofix_daily_budget_usd 없으면 사용할 기본값 (USD)
DEFAULT_DAILY_BUDGET_USD = 50.0


# =============================================================================
# Backend (in-memory fallback)
# =============================================================================

_inmem_budget: dict[str, dict[str, Any]] = {}  # date_key → {spend, calls, expires_at}


class _InMemoryBackend:
    @staticmethod
    async def add_spend(date_key: str, cost: float, ttl_sec: int) -> float:
        rec = _inmem_budget.setdefault(date_key, {"spend": 0.0, "calls": 0})
        if rec.get("expires_at") and time.time() > rec["expires_at"]:
            rec.update({"spend": 0.0, "calls": 0})
        rec["spend"] += cost
        rec["calls"] += 1
        rec["expires_at"] = time.time() + ttl_sec
        return rec["spend"]

    @staticmethod
    async def get_spend(date_key: str) -> float:
        rec = _inmem_budget.get(date_key)
        if not rec:
            return 0.0
        if rec.get("expires_at") and time.time() > rec["expires_at"]:
            return 0.0
        return rec["spend"]

    @staticmethod
    async def get_calls(date_key: str) -> int:
        rec = _inmem_budget.get(date_key)
        if not rec:
            return 0
        if rec.get("expires_at") and time.time() > rec["expires_at"]:
            return 0
        return rec.get("calls", 0)

    @staticmethod
    async def reset_today(date_key: str) -> None:
        _inmem_budget.pop(date_key, None)


# =============================================================================
# Redis backend
# =============================================================================


class _RedisBackend:
    def __init__(self, redis_url: str) -> None:
        import redis.asyncio as aioredis  # noqa

        self._url = redis_url
        self._client: Optional[Any] = None

    async def _get_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self._url)
        return self._client

    def _key_spend(self, date_key: str) -> str:
        return f"ada:budget:spend:{date_key}"

    def _key_calls(self, date_key: str) -> str:
        return f"ada:budget:calls:{date_key}"

    async def add_spend(self, date_key: str, cost: float, ttl_sec: int) -> float:
        r = await self._get_client()
        key = self._key_spend(date_key)
        new_total = await r.incrbyfloat(key, cost)
        await r.expire(key, ttl_sec)
        # 호출 카운터도 증가
        ck = self._key_calls(date_key)
        await r.incr(ck)
        await r.expire(ck, ttl_sec)
        return float(new_total)

    async def get_spend(self, date_key: str) -> float:
        r = await self._get_client()
        v = await r.get(self._key_spend(date_key))
        if v is None:
            return 0.0
        return float(v)

    async def get_calls(self, date_key: str) -> int:
        r = await self._get_client()
        v = await r.get(self._key_calls(date_key))
        if v is None:
            return 0
        return int(v)

    async def reset_today(self, date_key: str) -> None:
        r = await self._get_client()
        await r.delete(self._key_spend(date_key), self._key_calls(date_key))


# =============================================================================
# Budget 매니저
# =============================================================================


class BudgetManager:
    """일일 한도 추적 매니저 — 싱글턴 권장 (전역 1개)."""

    def __init__(self, *, redis_url: Optional[str] = None, daily_limit_usd: Optional[float] = None) -> None:
        self._redis_url = redis_url
        self._daily_limit_usd = daily_limit_usd
        self._backend: Any = None
        self._init_lock = asyncio.Lock()

    async def _backend_or_init(self) -> Any:
        if self._backend is not None:
            return self._backend
        async with self._init_lock:
            if self._backend is not None:
                return self._backend
            try:
                url = self._redis_url
                if url is None:
                    from ada.core.config import settings

                    url = getattr(settings, "redis_url", "redis://localhost:6379")
                backend = _RedisBackend(url)
                client = await backend._get_client()
                await client.ping()
                self._backend = backend
                log.info("budget_backend", backend="redis")
            except Exception as e:
                log.warning("budget_fallback_inmemory", error=str(e))
                self._backend = _InMemoryBackend()
        return self._backend

    def _today_key(self) -> str:
        """UTC 기준 오늘 날짜 (YYYY-MM-DD).

        UTC 사용 이유: 다중 인스턴스 (VPS + 백업) 가 같은 키 공유.
        """
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _daily_limit(self) -> float:
        if self._daily_limit_usd is not None:
            return float(self._daily_limit_usd)
        try:
            from ada.core.config import settings

            v = getattr(settings, "autofix_daily_budget_usd", None)
            if v is not None:
                return float(v)
        except Exception:
            pass
        return float(DEFAULT_DAILY_BUDGET_USD)

    @staticmethod
    def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        """모델·토큰 → USD 비용 계산."""
        rate = COST_PER_1K_TOKENS.get(model, DEFAULT_RATE)
        return (input_tokens * rate["input"] + output_tokens * rate["output"]) / 1000.0

    async def track_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """LLM 호출 1건 누적 → 오늘 누계 USD 반환."""
        cost = self.estimate_cost(model, input_tokens, output_tokens)
        backend = await self._backend_or_init()
        new_total = await backend.add_spend(self._today_key(), cost, ttl_sec=86400 * 7)
        log.info(
            "llm_cost_tracked",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 4),
            today_total_usd=round(new_total, 4),
        )
        return new_total

    async def get_today_spend(self) -> float:
        backend = await self._backend_or_init()
        return await backend.get_spend(self._today_key())

    async def get_today_calls(self) -> int:
        backend = await self._backend_or_init()
        return await backend.get_calls(self._today_key())

    async def is_exceeded(self) -> bool:
        """오늘 누계가 한도 초과인지."""
        spend = await self.get_today_spend()
        limit = self._daily_limit()
        return spend >= limit

    async def remaining_budget(self) -> float:
        """오늘 남은 예산 (음수면 초과)."""
        return self._daily_limit() - await self.get_today_spend()

    async def reset_today(self) -> None:
        """오늘 누계 reset (운영 도구 / 테스트)."""
        backend = await self._backend_or_init()
        await backend.reset_today(self._today_key())


# =============================================================================
# 싱글턴
# =============================================================================

_INSTANCE: Optional[BudgetManager] = None


def get_budget_manager() -> BudgetManager:
    """전역 BudgetManager 싱글턴."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = BudgetManager()
    return _INSTANCE


def reset_singleton() -> None:
    """테스트용 — 싱글턴 + in-memory 상태 초기화."""
    global _INSTANCE
    _INSTANCE = None
    _inmem_budget.clear()


__all__ = [
    "BudgetManager",
    "get_budget_manager",
    "reset_singleton",
    "COST_PER_1K_TOKENS",
    "DEFAULT_DAILY_BUDGET_USD",
]

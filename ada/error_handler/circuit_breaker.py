"""ada.error_handler.circuit_breaker — Redis 공유 비동기 circuit breaker (ADR-006 Phase 2-C).

목적:
    Ollama / Claude API / Vault 등 외부 의존성이 장애 시 무한 호출을
    차단해서 graceful degradation 보장.

기존 `ada/core/breaker.py` (pybreaker) 와 차이:
    - pybreaker = in-memory, 프로세스 1개 안에서만 상태 공유
    - 본 모듈   = Redis 공유, 다중 worker / 다중 인스턴스 (VPS+백업) 상태 동기화

상태 전이:
    CLOSED → (failure_threshold 회 연속 실패) → OPEN
    OPEN   → (recovery_timeout 경과)          → HALF_OPEN
    HALF_OPEN → (1회 성공) → CLOSED
    HALF_OPEN → (1회 실패) → OPEN (재차단)

Redis 미연결 시:
    in-memory 폴백 (per-process). 개발 환경 안전망.

Redis key 스킴:
    ada:cb:{name}:state   값: "open" | "half_open" | (absent=closed)
                          TTL: recovery_timeout 초 (자동 expiration → half_open 전환)
    ada:cb:{name}:fails   값: integer counter
                          TTL: 2 * recovery_timeout (오래된 실패는 자동 reset)

사용:
    cb = get_breaker("ollama", failure_threshold=3, recovery_timeout=300)
    try:
        result = await cb.call(_ollama_coder_fix_async, signature, stack)
    except CircuitBreakerOpenError:
        # 회로 OPEN → 빠른 폴백
        return {"action": "circuit_open"}
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional

from ada.core.logger import get_logger

log = get_logger("circuit_breaker")


class CircuitBreakerOpenError(Exception):
    """회로 OPEN 상태에서 호출 시도."""

    def __init__(self, name: str, retry_after_sec: int) -> None:
        self.name = name
        self.retry_after_sec = retry_after_sec
        super().__init__(f"Circuit breaker '{name}' is OPEN — retry after {retry_after_sec}s")


# =============================================================================
# In-memory fallback (Redis 없을 때)
# =============================================================================

# 프로세스 단위 상태 (개발 환경 한정)
_inmem_state: dict[str, dict[str, Any]] = {}


class _InMemoryBackend:
    """Redis 없을 때 폴백 — 단일 프로세스 안에서만 동작.

    ⚠️ 다중 워커(worker-pipeline / worker-training / worker-harness) 환경:
        Redis 가 다운되면 각 워커가 독립된 _InMemoryBackend 를 가지므로 회로 상태가
        프로세스 간에 동기화되지 않는다. 즉 ollama/claude 가 죽어도 워커마다 따로
        carrier 호출이 카운트돼 각자 OPEN 까지 도달한다 → 트래픽 ×N 발생.
        운영에서는 Redis 가용성을 SLO 로 관리하고 본 폴백은 개발 환경 안전망용.
    """

    @staticmethod
    async def get_state(name: str) -> Optional[str]:
        rec = _inmem_state.get(name)
        if not rec:
            return None
        # state expiration 시뮬레이션
        if rec.get("expires_at") and time.time() > rec["expires_at"]:
            rec["state"] = "half_open"
            rec["expires_at"] = None
        return rec.get("state")

    @staticmethod
    async def set_state(name: str, state: str, ttl_sec: int) -> None:
        _inmem_state[name] = {
            "state": state,
            "expires_at": time.time() + ttl_sec if ttl_sec else None,
        }

    @staticmethod
    async def clear_state(name: str) -> None:
        _inmem_state.pop(name, None)

    @staticmethod
    async def incr_fails(name: str, ttl_sec: int) -> int:
        rec = _inmem_state.setdefault(name, {})
        # fails counter expiration
        if rec.get("fails_expires_at") and time.time() > rec["fails_expires_at"]:
            rec["fails"] = 0
        n = rec.get("fails", 0) + 1
        rec["fails"] = n
        rec["fails_expires_at"] = time.time() + ttl_sec
        return n

    @staticmethod
    async def clear_fails(name: str) -> None:
        rec = _inmem_state.get(name)
        if rec:
            rec.pop("fails", None)
            rec.pop("fails_expires_at", None)


# =============================================================================
# Redis backend
# =============================================================================


class _RedisBackend:
    """Redis 기반 공유 상태."""

    def __init__(self, redis_url: str) -> None:
        # lazy import — redis 없으면 ImportError 즉시 폴백
        import redis.asyncio as aioredis  # noqa

        self._url = redis_url
        self._client: Optional[Any] = None

    async def _get_client(self) -> Any:
        if self._client is None:
            import redis.asyncio as aioredis

            self._client = aioredis.from_url(self._url)
        return self._client

    def _key_state(self, name: str) -> str:
        return f"ada:cb:{name}:state"

    def _key_fails(self, name: str) -> str:
        return f"ada:cb:{name}:fails"

    async def get_state(self, name: str) -> Optional[str]:
        r = await self._get_client()
        v = await r.get(self._key_state(name))
        if v is None:
            return None
        return v.decode() if isinstance(v, bytes) else v

    async def set_state(self, name: str, state: str, ttl_sec: int) -> None:
        r = await self._get_client()
        if ttl_sec > 0:
            await r.set(self._key_state(name), state, ex=ttl_sec)
        else:
            await r.set(self._key_state(name), state)

    async def clear_state(self, name: str) -> None:
        r = await self._get_client()
        await r.delete(self._key_state(name), self._key_fails(name))

    async def incr_fails(self, name: str, ttl_sec: int) -> int:
        r = await self._get_client()
        key = self._key_fails(name)
        n = await r.incr(key)
        # 첫 increment 일 때만 TTL 설정 (이후 TTL 갱신 안 함 — 슬라이딩 윈도우 X)
        if n == 1:
            await r.expire(key, ttl_sec)
        return n

    async def clear_fails(self, name: str) -> None:
        r = await self._get_client()
        await r.delete(self._key_fails(name))


# =============================================================================
# CircuitBreaker
# =============================================================================


class CircuitBreaker:
    """이름별 회로차단기.

    Args:
        name: 식별자 (예: "ollama", "claude_cli", "vault")
        failure_threshold: 이 횟수 연속 실패하면 OPEN
        recovery_timeout: OPEN 유지 시간 (초). 경과 후 HALF_OPEN.
        redis_url: Redis URL. None 이면 settings.redis_url 사용. 연결 실패 시 in-memory 폴백.
    """

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: int = 300,
        redis_url: Optional[str] = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._backend: Any = None
        self._init_lock = asyncio.Lock()
        self._redis_url = redis_url

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
                # 연결 테스트
                client = await backend._get_client()
                await client.ping()
                self._backend = backend
                log.info("circuit_breaker_backend", name=self.name, backend="redis")
            except Exception as e:
                log.warning(
                    "circuit_breaker_fallback_inmemory",
                    name=self.name,
                    error=str(e),
                )
                self._backend = _InMemoryBackend()
        return self._backend

    async def is_open(self) -> bool:
        """현재 OPEN 상태인지."""
        backend = await self._backend_or_init()
        state = await backend.get_state(self.name)
        return state == "open"

    async def state(self) -> str:
        """현재 상태: closed | open | half_open"""
        backend = await self._backend_or_init()
        s = await backend.get_state(self.name)
        return s or "closed"

    async def record_success(self) -> None:
        """성공 기록 — 모든 카운터 reset, 회로 닫기."""
        backend = await self._backend_or_init()
        await backend.clear_state(self.name)
        await backend.clear_fails(self.name)
        log.info("circuit_breaker_closed", name=self.name)

    async def record_failure(self) -> int:
        """실패 기록 — 카운터 증가, threshold 도달 시 OPEN.

        Returns:
            현재 실패 카운트
        """
        backend = await self._backend_or_init()
        n = await backend.incr_fails(self.name, ttl_sec=self.recovery_timeout * 2)
        if n >= self.failure_threshold:
            await backend.set_state(self.name, "open", ttl_sec=self.recovery_timeout)
            log.warning(
                "circuit_breaker_opened",
                name=self.name,
                failure_count=n,
                recovery_in_sec=self.recovery_timeout,
            )
        return n

    async def call(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """회로 보호 호출.

        - OPEN 상태면 즉시 CircuitBreakerOpenError raise (호출 자체 안 함)
        - 호출 성공 → record_success
        - 호출 실패 → record_failure → 원본 예외 re-raise
        """
        if await self.is_open():
            raise CircuitBreakerOpenError(self.name, self.recovery_timeout)
        try:
            result = await async_fn(*args, **kwargs)
            await self.record_success()
            return result
        except Exception:
            await self.record_failure()
            raise

    async def reset(self) -> None:
        """수동 reset (테스트 / 운영 도구용)."""
        backend = await self._backend_or_init()
        await backend.clear_state(self.name)
        await backend.clear_fails(self.name)


# =============================================================================
# 싱글턴 팩토리 (이름별 1개)
# =============================================================================

_REGISTRY: dict[str, CircuitBreaker] = {}


def get_breaker(
    name: str,
    *,
    failure_threshold: int = 5,
    recovery_timeout: int = 300,
) -> CircuitBreaker:
    """이름별 singleton CircuitBreaker.

    Note:
        같은 name 으로 다른 threshold / timeout 요청해도 첫 호출의 설정이 유지됨.
        설정 변경하려면 reset_registry() 호출.
    """
    if name not in _REGISTRY:
        _REGISTRY[name] = CircuitBreaker(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout,
        )
    return _REGISTRY[name]


def reset_registry() -> None:
    """싱글턴 등록 초기화 (테스트용)."""
    _REGISTRY.clear()
    _inmem_state.clear()


__all__ = [
    "CircuitBreaker",
    "CircuitBreakerOpenError",
    "get_breaker",
    "reset_registry",
]

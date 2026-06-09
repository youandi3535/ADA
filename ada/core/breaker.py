"""ada.core.breaker — pybreaker 회로차단기 팩토리 (R-709).

외부 의존(Anthropic, MLflow, MinIO, Vault, Langfuse) 호출에서 적용.
"""

from __future__ import annotations

from typing import Any

try:
    import pybreaker
except Exception:  # pragma: no cover - 개발 환경에 미설치
    pybreaker = None  # type: ignore

_REGISTRY: dict[str, Any] = {}


def get_breaker(
    name: str,
    *,
    fail_max: int = 5,
    reset_timeout: int = 60,
) -> Any:
    """이름별 싱글턴 CircuitBreaker. pybreaker 미설치 환경에서는 no-op 데코레이터.

    예시:
        bk = get_breaker("anthropic", fail_max=3, reset_timeout=30)
        @bk
        def call_llm(...): ...
    """
    if pybreaker is None:
        # 사용 불가 환경 — pass-through 데코레이터
        class _NoopBreaker:
            def __call__(self, fn):  # type: ignore[no-untyped-def]
                return fn

            def call(self, fn, *a, **kw):
                return fn(*a, **kw)

        return _NoopBreaker()

    if name in _REGISTRY:
        return _REGISTRY[name]
    bk = pybreaker.CircuitBreaker(
        fail_max=fail_max,
        reset_timeout=reset_timeout,
        name=name,
    )
    _REGISTRY[name] = bk
    return bk

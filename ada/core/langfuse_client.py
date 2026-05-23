"""ada.core.langfuse_client — Langfuse 옵저버빌리티 클라이언트 (R-1001 + Day 3 강화).

운영 환경에서 LANGFUSE_* 환경변수가 비어 있으면 자동 no-op.
Day 3:
    - 헬스체크 (verify_connection)
    - LLM 호출 컨텍스트 매니저 (track_llm) — agents.base 에서 사용 가능
    - flush() 노출 — graceful shutdown 시 호출
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from ada.core.config import settings
from ada.core.logger import get_logger

_log = get_logger("langfuse")

_client: Optional[Any] = None


def get_langfuse_client() -> Optional[Any]:
    """싱글턴 Langfuse 클라이언트 — 키 없으면 None."""
    global _client
    if _client is not None:
        return _client
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return None
    try:
        from langfuse import Langfuse  # type: ignore

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host or "https://cloud.langfuse.com",
        )
        _log.info("langfuse_initialized", host=settings.langfuse_host)
        return _client
    except Exception as e:
        _log.warning("langfuse_init_failed", error=str(e))
        return None


def trace(name: str, **metadata: Any) -> Optional[Any]:
    """편의 — 새 trace 시작 (없으면 None)."""
    client = get_langfuse_client()
    if client is None:
        return None
    try:
        return client.trace(name=name, metadata=metadata)
    except Exception as e:
        _log.warning("langfuse_trace_failed", error=str(e))
        return None


def verify_connection() -> dict[str, Any]:
    """Day 3 — Langfuse 서버 도달성 검증. 헬스 endpoint 또는 keys 핑.

    반환: {"connected": bool, "host": str, "reason": str}
    """
    client = get_langfuse_client()
    if client is None:
        return {"connected": False, "host": settings.langfuse_host or "", "reason": "keys_missing_or_init_failed"}
    try:
        # langfuse SDK 0.6+ 은 auth_check() 또는 v2 client.api.health() 보유
        auth_fn = getattr(client, "auth_check", None) or getattr(getattr(client, "api", None), "health", None)
        if callable(auth_fn):
            auth_fn()
        return {"connected": True, "host": settings.langfuse_host or "", "reason": "ok"}
    except Exception as e:
        return {"connected": False, "host": settings.langfuse_host or "", "reason": str(e)[:200]}


@contextmanager
def track_llm(name: str, model: str, **metadata: Any) -> Iterator[Optional[Any]]:
    """LLM 호출 컨텍스트. yield 된 span 에 ``.update(output=..., usage=...)`` 호출 가능."""
    client = get_langfuse_client()
    if client is None:
        yield None
        return
    span = None
    try:
        span = client.trace(name=name, metadata={"model": model, **metadata})
        yield span
    except Exception as e:
        _log.warning("langfuse_track_failed", error=str(e))
        yield None
    finally:
        try:
            if span is not None and hasattr(span, "end"):
                span.end()
        except Exception:
            pass


def flush(timeout_sec: float = 5.0) -> None:
    """graceful shutdown — 버퍼링된 span 강제 전송."""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        if hasattr(client, "flush"):
            client.flush()
    except Exception as e:
        _log.warning("langfuse_flush_failed", error=str(e))

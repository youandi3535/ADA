"""ada.core.langfuse_client — Langfuse 옵저버빌리티 클라이언트 (R-1001).

운영 환경에서 LANGFUSE_* 환경변수가 비어 있으면 자동 no-op.
"""
from __future__ import annotations

from typing import Any, Optional

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
    except Exception as e:  # pragma: no cover
        _log.warning("langfuse_init_failed", error=str(e))
        return None


def trace(name: str, **metadata: Any) -> Optional[Any]:
    """편의 — 새 trace 시작 (없으면 None)."""
    client = get_langfuse_client()
    if client is None:
        return None
    try:
        return client.trace(name=name, metadata=metadata)
    except Exception as e:  # pragma: no cover
        _log.warning("langfuse_trace_failed", error=str(e))
        return None

"""orchestrator.checkpoint — LangGraph PostgresSaver 헬퍼 (Day04 v2 §2)."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from ada.core.config import settings


@lru_cache(maxsize=1)
def get_checkpointer() -> Any:
    """PostgresSaver 싱글턴. langgraph 0.1.x 호환."""
    try:
        from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "langgraph.checkpoint.postgres 가 필요합니다. pip install langgraph[postgres]"
        ) from e

    saver = PostgresSaver.from_conn_string(settings.database_url)
    try:
        saver.setup()  # 1회 멱등 — langgraph_checkpoints 테이블 생성
    except Exception:
        pass
    return saver

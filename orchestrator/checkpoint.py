"""orchestrator.checkpoint — LangGraph PostgresSaver 헬퍼 (Day04 v2 §2)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ada.core.config import settings

_CM_KEEPALIVE: list = []  # from_conn_string 컨텍스트(연결)를 앱 생명주기 동안 유지


@lru_cache(maxsize=1)
def get_checkpointer() -> Any:
    """PostgresSaver 싱글턴.

    langgraph-checkpoint-postgres 1.0.x 의 ``from_conn_string`` 은 @contextmanager
    (``Iterator[PostgresSaver]``) 라 직접 saver 가 아니다 → enter 해서 실제 saver 를 얻고,
    싱글턴이므로 컨텍스트(DB 연결)를 앱 생명주기 동안 유지한다.
    이게 있어야 HITL 게이트의 ``interrupt_after`` 가 동작한다(없으면 게이트에서 안 멈추고 END 까지 직진).
    """
    try:
        from langgraph.checkpoint.postgres import PostgresSaver  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "langgraph.checkpoint.postgres 가 필요합니다. "
            "pip install 'langgraph-checkpoint-postgres>=1.0,<2' 'psycopg[binary]'"
        ) from e

    cm = PostgresSaver.from_conn_string(settings.database_url)
    saver = cm.__enter__()  # 연결 오픈 → 싱글턴으로 유지
    _CM_KEEPALIVE.append(cm)  # GC 로 연결이 닫히지 않도록 참조 유지
    try:
        saver.setup()  # 멱등 — langgraph_checkpoints 테이블 생성
    except Exception:
        pass
    return saver

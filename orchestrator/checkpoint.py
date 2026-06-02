"""orchestrator.checkpoint — CompatMemorySaver + Redis cross-task 직렬화.

langgraph-checkpoint 2.x 는 aput(config, checkpoint, metadata, new_versions) 로
4인수를 요구하지만, langgraph 0.2~0.3.x pregel 은 3인수(new_versions 없음)로 호출한다.
CompatMemorySaver 가 new_versions 를 optional 로 만들어 버전 충돌을 해소한다.

cross-task HITL (run_pipeline_task → resume_pipeline_task):
- task 종료 시 storage/writes 를 pickle → base64 → Redis SET
- 다음 task 시작 시 Redis 에서 복원 → CompatMemorySaver 에 주입
"""

from __future__ import annotations

import base64
import pickle
from typing import Any

from ada.core.config import settings


# ---------------------------------------------------------------------------
# CompatMemorySaver
# ---------------------------------------------------------------------------
class CompatMemorySaver:
    """langgraph pregel 3-arg aput ↔ checkpoint 2.x 4-arg aput 브릿지."""

    def __init__(self) -> None:
        from langgraph.checkpoint.memory import MemorySaver  # type: ignore

        self._inner = MemorySaver()

    # ── 위임 속성 ────────────────────────────────────────────────────────────
    @property
    def storage(self):
        return self._inner.storage

    @property
    def writes(self):
        return self._inner.writes

    # ── 핵심 인터페이스 (new_versions 를 optional 로 완화) ────────────────────
    def put(self, config, checkpoint, metadata, new_versions=None):
        return self._inner.put(config, checkpoint, metadata, new_versions or {})

    async def aput(self, config, checkpoint, metadata, new_versions=None):
        return await self._inner.aput(config, checkpoint, metadata, new_versions or {})

    def put_writes(self, config, writes, task_id):
        return self._inner.put_writes(config, writes, task_id)

    async def aput_writes(self, config, writes, task_id):
        return await self._inner.aput_writes(config, writes, task_id)

    # ── 읽기 인터페이스 ──────────────────────────────────────────────────────
    def get_tuple(self, config):
        return self._inner.get_tuple(config)

    async def aget_tuple(self, config):
        return await self._inner.aget_tuple(config)

    def list(self, config, *, filter=None, before=None, limit=None):
        return self._inner.list(config, filter=filter, before=before, limit=limit)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        return self._inner.alist(config, filter=filter, before=before, limit=limit)

    # ── 구형 langgraph 0.1.x 호환 위임 ──────────────────────────────────────
    def get(self, config):
        return self._inner.get(config)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


# ---------------------------------------------------------------------------
# Redis 직렬화 헬퍼 (cross-task HITL)
# ---------------------------------------------------------------------------
def _get_redis():
    import redis  # noqa: WPS433

    return redis.Redis.from_url(settings.redis_url)


_CHECKPOINT_TTL = 86400  # 24시간


def save_checkpoint(saver: CompatMemorySaver, job_id: str) -> None:
    """task 종료 시 MemorySaver 상태를 Redis 에 저장."""
    try:
        data = {
            "storage": dict(saver.storage),
            "writes": dict(saver.writes),
        }
        raw = base64.b64encode(pickle.dumps(data)).decode()
        _get_redis().set(f"ada:checkpoint:{job_id}", raw, ex=_CHECKPOINT_TTL)
    except Exception:  # noqa: BLE001
        pass


def load_checkpoint(saver: CompatMemorySaver, job_id: str) -> None:
    """task 시작 시 Redis 에서 MemorySaver 상태 복원."""
    try:
        raw = _get_redis().get(f"ada:checkpoint:{job_id}")
        if raw:
            data = pickle.loads(base64.b64decode(raw))
            saver.storage.update(data.get("storage", {}))
            saver.writes.update(data.get("writes", {}))
    except Exception:  # noqa: BLE001
        pass

"""orchestrator.harness_tasks — Harness 큐 + Day 2 AutoErrorHandler 데몬 태스크.

Celery beat 가 30초마다 ``ada.error_handler.scan`` 을 호출.
beat 스케줄은 :func:`register_error_handler_beat` 로 등록 (runner 가 호출).
"""

from __future__ import annotations

import asyncio
from typing import Any

from orchestrator.runner import celery_app


@celery_app.task(name="ada.harness.distill", queue="harness")
def distill_job(job_id: str) -> dict[str, Any]:
    async def _do() -> dict[str, Any]:
        from ada.db.session import AsyncSessionLocal
        from ada.harness.distiller import SelfLearningHarness

        async with AsyncSessionLocal() as s:
            return await SelfLearningHarness(s).distill_from_job(job_id)

    return asyncio.run(_do())


@celery_app.task(name="ada.harness.decay", queue="harness")
def decay_kb() -> dict[str, int]:
    async def _do() -> dict[str, int]:
        from ada.db.session import AsyncSessionLocal
        from ada.harness.distiller import SelfLearningHarness

        async with AsyncSessionLocal() as s:
            n = await SelfLearningHarness(s).decay_unused()
            return {"decayed": n}

    return asyncio.run(_do())


@celery_app.task(name="ada.harness.retract", queue="harness")
def retract_kb() -> dict[str, int]:
    async def _do() -> dict[str, int]:
        from ada.db.session import AsyncSessionLocal
        from ada.harness.distiller import SelfLearningHarness

        async with AsyncSessionLocal() as s:
            n = await SelfLearningHarness(s).retract_low_confidence()
            return {"retracted": n}

    return asyncio.run(_do())


# ---------------------------------------------------------------------------
# Day 2 — AutoErrorHandler 데몬 태스크 (Celery beat 30초 폴링)
# ---------------------------------------------------------------------------


@celery_app.task(name="ada.error_handler.scan", queue="harness")
def scan_failures() -> dict[str, Any]:
    """auto_handled_by_kb=False 인 FailureLog 를 폴링하고 처리."""
    from ada.error_handler.daemon import scan_new_failures

    return scan_new_failures()


def register_error_handler_beat(beat_schedule: dict[str, Any] | None = None) -> dict[str, Any]:
    """beat schedule dict 에 Day 2 데몬 스케줄을 머지해 반환.

    runner 의 ``celery_app.conf.beat_schedule`` 에 이 결과를 대입.
    """
    schedule = dict(beat_schedule or {})
    schedule["ada-error-handler-scan"] = {
        "task": "ada.error_handler.scan",
        "schedule": 30.0,  # 30 초
        "options": {"queue": "harness"},
    }
    return schedule

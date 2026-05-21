"""orchestrator.harness_tasks — Harness 큐 Celery 태스크 (Day09/Day19)."""
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

"""orchestrator.harness_tasks — Harness 큐 + Day 2 AutoErrorHandler 데몬 태스크.

Celery beat 가 30초마다 ``ada.error_handler.scan`` 을 호출.
beat 스케줄은 :func:`register_error_handler_beat` 로 등록 (runner 가 호출).
"""

from __future__ import annotations

import asyncio
from typing import Any

from orchestrator.runner import celery_app


async def _capture(error_message: str, stack_trace: str, source: str) -> None:
    """harness 태스크 예외를 AutoErrorHandler 로 위임하는 내부 헬퍼."""
    try:
        from ada.error_handler.auto_handler import capture_and_handle

        await capture_and_handle(error_message=error_message, stack_trace=stack_trace, source=source)
    except Exception:  # noqa: BLE001
        pass


@celery_app.task(name="ada.harness.distill", queue="harness")
def distill_job(job_id: str) -> dict[str, Any]:
    async def _do() -> dict[str, Any]:
        from ada.db.session import AsyncSessionLocal
        from ada.harness.distiller import SelfLearningHarness

        async with AsyncSessionLocal() as s:
            return await SelfLearningHarness(s).distill_from_job(job_id)

    try:
        return asyncio.run(_do())
    except Exception as e:
        import traceback as _tb

        from ada.core.logger import get_logger as _log

        _log("harness_tasks").error("distill_job_failed", job_id=job_id, error=str(e))
        asyncio.run(_capture("distill_job_failed: " + str(e), _tb.format_exc(), source="harness"))
        return {"error": str(e)}


@celery_app.task(name="ada.harness.decay", queue="harness")
def decay_kb() -> dict[str, int]:
    async def _do() -> dict[str, int]:
        from ada.db.session import AsyncSessionLocal
        from ada.harness.distiller import SelfLearningHarness

        async with AsyncSessionLocal() as s:
            n = await SelfLearningHarness(s).decay_unused()
            return {"decayed": n}

    try:
        return asyncio.run(_do())
    except Exception as e:
        import traceback as _tb

        from ada.core.logger import get_logger as _log

        _log("harness_tasks").error("decay_kb_failed", error=str(e))
        asyncio.run(_capture("decay_kb_failed: " + str(e), _tb.format_exc(), source="harness"))
        return {"decayed": 0, "error": str(e)}


@celery_app.task(name="ada.harness.retract", queue="harness")
def retract_kb() -> dict[str, int]:
    async def _do() -> dict[str, int]:
        from ada.db.session import AsyncSessionLocal
        from ada.harness.distiller import SelfLearningHarness

        async with AsyncSessionLocal() as s:
            n = await SelfLearningHarness(s).retract_low_confidence()
            return {"retracted": n}

    try:
        return asyncio.run(_do())
    except Exception as e:
        import traceback as _tb

        from ada.core.logger import get_logger as _log

        _log("harness_tasks").error("retract_kb_failed", error=str(e))
        asyncio.run(_capture("retract_kb_failed: " + str(e), _tb.format_exc(), source="harness"))
        return {"retracted": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# Day 2 — AutoErrorHandler 데몬 태스크 (Celery beat 30초 폴링)
# ---------------------------------------------------------------------------


@celery_app.task(name="ada.error_handler.scan", queue="harness")
def scan_failures() -> dict[str, Any]:
    """auto_handled_by_kb=False 인 FailureLog 를 폴링하고 처리."""
    from ada.error_handler.daemon import scan_new_failures

    return scan_new_failures()


@celery_app.task(name="ada.error_handler.promote_fixers", queue="harness")
def promote_fixers() -> dict[str, Any]:
    """반복 오류 패턴을 감지해 Tier 0 fixer 로 자동 승격 (1일 1회)."""
    from ada.error_handler.fixer_promoter import run_sync

    return run_sync()


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

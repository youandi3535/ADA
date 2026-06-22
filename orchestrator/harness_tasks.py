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


def _analysis_active() -> bool:
    """분석이 진행 중이면 True — harness 데몬이 RAM(임베더 ~1GB)·CPU 를 분석에 양보하도록 스캔을 건너뛴다.

    HJ 2026-06-22 — 저사양 VPS(7.9GB)는 Ollama 모델(4.7GB)+harness 임베더가 동시에 못 올라가 모델이
    swap → prompt_eval 파국. runner.publish_progress 가 분석 중 ada:analysis_active 를 90s TTL 로
    refresh 하므로, 그 키가 있으면 분석 중으로 보고 스캔을 건너뛴다. 키 없음/조회 실패 시엔 정상 수행
    (자가치유 우선). TTL 만료로 비정상 종료 시에도 자동 해제 → harness 가 영구 차단되지 않는다.
    """
    try:
        from orchestrator.runner import _get_redis

        return bool(_get_redis().exists("ada:analysis_active"))
    except Exception:  # noqa: BLE001
        return False


@celery_app.task(
    name="ada.error_handler.scan",
    queue="harness",
    soft_time_limit=240,
    time_limit=300,
)
def scan_failures() -> dict[str, Any]:
    """auto_handled_by_kb=False 인 FailureLog 를 폴링하고 처리.

    HJ 2026-06-22 — 글로벌 task_time_limit(pipeline_timeout_min 기준, 수십 분)을 이 task 만 짧게
    덮어쓴다. MAX_BATCH=5 × ~25s ≈ 125s 가 정상치. soft 240s 초과 시 graceful 종료, hard 300s 에 강제
    종료 → 한 scan 이 워커·메모리를 길게 점유(누수 인질·peg)하지 못하게 상한. 중단돼도 daemon 의
    handle-전-커밋 덕에 무한 재처리는 없다(처리분은 durable 마킹됨).

    HJ 2026-06-22 — 분석 중에는 건너뛴다(RAM 양보). 자가치유는 분석 유휴 시 이어서 처리(백로그 보존).
    """
    if _analysis_active():
        return {"skipped": "analysis_active"}
    from ada.error_handler.daemon import scan_new_failures

    return scan_new_failures()


@celery_app.task(name="ada.error_handler.promote_fixers", queue="harness")
def promote_fixers() -> dict[str, Any]:
    """반복 오류 패턴을 감지해 Tier 0 fixer 로 자동 승격 (1일 1회)."""
    if _analysis_active():
        return {"skipped": "analysis_active"}
    from ada.error_handler.fixer_promoter import run_sync

    return run_sync()


@celery_app.task(name="ada.harness.stalled_jobs_scan", queue="harness")
def scan_stalled_jobs() -> dict[str, Any]:
    """정체 잡(running 인데 일정 시간 진행 없음)을 failed + failure_logs 로 자동 기록 (HJ 2026-06-19).

    hang·워커 사망·하드 time_limit kill 등 in-process 핸들러가 못 잡는 '미완료'를 포착하는 최종 그물.
    → 멈춤도 '오류'로 failure_logs 에 남겨 자가치유 루프(scan_failures)에 다시 먹이를 공급한다.

    안전(게이트 대기 정상 잡 보호): 임계값을 task 하드 time_limit(=pipeline_timeout_min) + 30분 으로 둔다.
      활성 처리 중 task 는 time_limit 에서 강제 종료되므로, 그보다 오래 'running' 인 잡은 이미 고아이거나
      게이트에서 30분 이상 방치된 세션 → failed 처리해도 정상 진행 중인 잡을 죽이지 않는다.

    HJ 2026-06-22 — 분석 중에는 건너뛴다: (1) RAM 양보(harness child 재활용 트리거 회피), (2) 느리지만
      정상 진행 중인 활성 잡을 watchdog 가 성급히 죽이지 않게. 분석 유휴 시 다음 폴에서 고아 잡 정리 재개.
    """
    if _analysis_active():
        return {"swept": 0, "skipped": "analysis_active"}

    async def _do() -> dict[str, Any]:
        import hashlib
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import select

        from ada.core.config import settings
        from ada.db.models import FailureLog, Job
        from ada.db.session import AsyncSessionLocal

        stale_sec = settings.pipeline_timeout_min * 60 + 1800  # 하드 타임아웃 + 30분
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_sec)
        swept = 0
        async with AsyncSessionLocal() as s:
            jobs = (await s.scalars(select(Job).where(Job.status == "running", Job.updated_at < cutoff))).all()
            for job in jobs:
                err = (
                    f"stalled: 파이프라인 진행 정지 (gate={job.current_gate or '-'}, "
                    f"last_update={job.updated_at}, threshold={stale_sec // 60}min)"
                )
                s.add(
                    FailureLog(
                        job_id=job.id,
                        error_hash=hashlib.sha256(f"stalled:{job.id}".encode()).hexdigest(),
                        error_message=err[:2000],
                        stack_trace="[stalled_jobs_watchdog] 진행 정지로 자동 종료 처리",
                        error_category="stalled",
                    )
                )
                job.status = "failed"
                job.error_message = err[:2000]
                swept += 1
            if swept:
                await s.commit()
        return {"swept": swept, "stale_min": stale_sec // 60}

    try:
        return asyncio.run(_do())
    except Exception as e:
        import traceback as _tb

        from ada.core.logger import get_logger as _log

        _log("harness_tasks").error("scan_stalled_jobs_failed", error=str(e))
        asyncio.run(_capture("scan_stalled_jobs_failed: " + str(e), _tb.format_exc(), source="harness"))
        return {"swept": 0, "error": str(e)}


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

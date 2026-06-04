"""orchestrator.runner — Celery 4 큐 + LangGraph 인보크 (Day04 v2).

큐 토폴로지:
    pipeline  ← run_pipeline_task / resume_pipeline_task
    training  ← train_model_task (Day08)
    output    ← generate_output_task (Day12)
    harness   ← distill_kb_task / decay_kb_task (Day09)
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
from typing import Any

from celery import Celery

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.core.state import PipelineState

log = get_logger("runner")

# ---------------------------------------------------------------------------
# Celery 앱
# ---------------------------------------------------------------------------
celery_app = Celery(
    "ada",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # R-202 Bulkhead
    task_time_limit=settings.pipeline_timeout_min * 60,
    task_soft_time_limit=settings.pipeline_timeout_min * 60 - 60,
    task_routes={
        "ada.pipeline.run": {"queue": "pipeline"},
        "ada.pipeline.resume": {"queue": "pipeline"},
        "ada.training.*": {"queue": "training"},
        "ada.output.*": {"queue": "output"},
        "ada.harness.*": {"queue": "harness"},
    },
    # ── Celery Beat 주기 스케줄 ──────────────────────────────────────────
    # decay  : R-505 — 60일 미사용 KB confidence 0.9× (1일 1회)
    # retract: R-504 — confidence < 0.20 KB 비활성화 (1일 1회)
    # error-handler-scan: Day02 AutoErrorHandler 폴링 (30초)
    beat_schedule={
        "ada-kb-decay-daily": {
            "task": "ada.harness.decay",
            "schedule": 86400.0,  # 24시간
            "options": {"queue": "harness"},
        },
        "ada-kb-retract-daily": {
            "task": "ada.harness.retract",
            "schedule": 86400.0,  # 24시간
            "options": {"queue": "harness"},
        },
        "ada-error-handler-scan": {
            "task": "ada.error_handler.scan",
            "schedule": 30.0,  # 30초
            "options": {"queue": "harness"},
        },
        "ada-fixer-promote-daily": {
            "task": "ada.error_handler.promote_fixers",
            "schedule": 86400.0,  # 24시간
            "options": {"queue": "harness"},
        },
    },
)


# ---------------------------------------------------------------------------
# Redis pub/sub progress
# ---------------------------------------------------------------------------
AGENT_PROGRESS_MAP: dict[str, int] = {
    "supervisor": 3,
    "intent_elicitor": 5,
    "data_profiler": 8,
    "schema_validator": 10,
    "gate_direction": 15,
    "eda_agent": 25,
    "gate_methodology": 30,
    "preprocessing_strategist": 33,
    "feature_engineer": 38,
    "preprocessing_choice": 40,
    "gate_model_strategy": 45,
    "model_selection": 50,
    "hyperparameter_tuner": 55,
    "training_executor": 65,
    "training_monitor": 70,
    "metrics_aggregator": 75,
    "gate_best_model": 78,
    "fine_tune_executor": 82,
    "eval_agent": 86,
    "explainability": 90,
    "insight": 93,
    "gate_outputs": 95,
    "report_composer": 98,
    "self_learning_dispatch": 99,
    "error_recovery": 50,
    "END": 100,
}


def _get_redis() -> Any:
    import redis  # noqa: WPS433

    return redis.Redis.from_url(settings.redis_url)


def publish_progress(
    job_id: str,
    current_agent: str,
    message: str = "",
    *,
    pipeline_status: str | None = None,
    error: str | None = None,
) -> None:
    """대시보드 SSE / WebSocket 채널.

    pipeline_status: ``running``/``completed``/``failed`` — 워커 종료 신호.
        프론트는 이 값을 보고 폴링을 종료한다 (`error_recovery`가 보이는데도
        진행률이 멈춰 있는 좀비 상태 방지).
    error: 실패 시 사용자 안내용 메시지 (PII 마스킹 후 저장).
    """
    r = _get_redis()
    payload: dict[str, Any] = {
        "agent": current_agent,
        "progress": AGENT_PROGRESS_MAP.get(current_agent, 0),
        "ts": time.time(),
        "message": message,
    }
    if pipeline_status:
        payload["status"] = pipeline_status
    if error:
        # R-103 — PII 마스킹 후 영속화
        try:
            from ada.core.logger import _pii_mask  # noqa: WPS433

            payload["error"] = _pii_mask(str(error))[:1000]
        except Exception:  # noqa: BLE001
            payload["error"] = str(error)[:1000]
    body = json.dumps(payload)
    r.publish(f"ada:pipeline:{job_id}", body)
    # 마지막 진행상황 영속화 — /pipeline/gate 가 실제 진행률/현재 에이전트를 읽어 표시
    try:
        r.set(f"ada:progress:{job_id}", body, ex=3600)
    except Exception:  # noqa: BLE001
        pass


async def _set_job_terminal(job_id: str, status: str, error: str | None = None) -> None:
    """워커 종료 시 DB Job.status 갱신 (running/completed/failed).

    이 함수가 없으면 `_invoke` 가 예외로 종료해도 DB 의 status 가 그대로
    'pending' 으로 남아 프론트가 끝없이 폴링한다.
    """
    try:
        import uuid as _uuid

        from sqlalchemy import select  # noqa: WPS433

        from ada.core.logger import _pii_mask  # noqa: WPS433
        from ada.db.models import Job  # noqa: WPS433
        from ada.db.session import AsyncSessionLocal  # noqa: WPS433

        async with AsyncSessionLocal() as session:
            job = await session.scalar(select(Job).where(Job.id == _uuid.UUID(job_id)))
            if job is None:
                return
            job.status = status
            if error is not None:
                job.error_message = _pii_mask(str(error))[:2000]
            await session.commit()
    except Exception as e:  # noqa: BLE001
        log.warning("set_job_terminal_failed", job_id=job_id, error=str(e))


# ---------------------------------------------------------------------------
# 메인 태스크
# ---------------------------------------------------------------------------
def _get_callbacks() -> list:
    """LangSmith / Langfuse 콜백 — 키 없으면 빈 리스트."""
    callbacks: list = []
    if settings.langsmith_api_key:
        try:
            from langchain.callbacks.tracers import LangChainTracer  # type: ignore
            from langsmith import Client  # type: ignore

            callbacks.append(
                LangChainTracer(
                    project_name=settings.langsmith_project,
                    client=Client(api_key=settings.langsmith_api_key),
                )
            )
        except Exception:
            pass
    if settings.langfuse_public_key:
        try:
            from langfuse.callback import CallbackHandler  # type: ignore

            callbacks.append(
                CallbackHandler(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
            )
        except Exception:
            pass
    return callbacks


@celery_app.task(bind=True, name="ada.pipeline.run", max_retries=3)
def run_pipeline_task(self: Any, job_id: str, initial_state: dict) -> dict:
    """파이프라인 시작 — 첫 인터럽트(G1)까지 진행 후 대기 상태로 반환."""
    log.info("pipeline_start", job_id=job_id)
    publish_progress(job_id, "supervisor", "파이프라인 시작")

    # Pydantic 검증 실패 시 Job 이 "pending" 으로 영원히 남지 않도록 보호
    try:
        state = PipelineState(**initial_state)
    except Exception as e:
        import traceback as _tb

        err_msg = f"state_init: {e}"
        tb = _tb.format_exc()
        log.error("pipeline_state_init_failed", job_id=job_id, error=err_msg)

        async def _handle_state_init_failure() -> None:
            from ada.error_handler.auto_handler import capture_and_handle

            await capture_and_handle(error_message=err_msg, stack_trace=tb, job_id=job_id, source="runner")
            await _set_job_terminal(job_id, "failed", error=err_msg)

        asyncio.run(_handle_state_init_failure())
        publish_progress(job_id, "error_recovery", err_msg, pipeline_status="failed", error=err_msg)
        return {"status": "failed", "error": err_msg}

    return asyncio.run(_invoke(job_id=job_id, state=state, resume=False))


@celery_app.task(bind=True, name="ada.pipeline.resume", max_retries=3)
def resume_pipeline_task(self: Any, job_id: str, gate_response: dict) -> dict:
    """게이트 응답 후 재개."""
    log.info("pipeline_resume", job_id=job_id, gate=gate_response.get("gate"))
    return asyncio.run(_resume(job_id=job_id, gate_response=gate_response))


@celery_app.task(name="ada.meta.ping")
def ping() -> str:
    return "pong"


# ---------------------------------------------------------------------------
# Internal async runners
# ---------------------------------------------------------------------------
def _save_gate_data(job_id: str, final_dict: dict) -> None:
    """게이트 인터럽트 시 proposals 등 핵심 데이터를 Redis 에 직접 저장.

    API gate 엔드포인트가 matplotlib 등 워커 전용 패키지 없이도
    graph.get_state() 없이 이 키에서 데이터를 읽을 수 있다.
    """
    gate = final_dict.get("current_gate")
    if not gate:
        return
    gr = final_dict.get("gate_responses") or {}
    gate_entry = gr.get(gate) or {}
    try:
        r = _get_redis()
        payload = {
            "gate": gate,
            "proposals": gate_entry.get("proposals") or [],
            "category": final_dict.get("category"),
            "target_column": final_dict.get("target_column"),
            "insights": final_dict.get("insights"),
            "data_profile": final_dict.get("data_profile"),
        }
        r.set(f"ada:gate_data:{job_id}", json.dumps(payload, ensure_ascii=False, default=str), ex=86400)
    except Exception:  # noqa: BLE001
        pass


def _final_to_dict(final) -> dict | None:
    """LangGraph ainvoke 반환값(PipelineState 또는 AddableValuesDict) → dict 변환."""
    if final is None:
        return None
    if hasattr(final, "to_dict"):
        return final.to_dict()
    return dict(final)


async def _invoke(*, job_id: str, state: PipelineState, resume: bool) -> dict:
    from orchestrator.checkpoint import CompatMemorySaver, load_checkpoint, save_checkpoint
    from orchestrator.graph import build_graph

    # checkpointer 를 None 으로 초기화 → finally 에서 안전하게 조건 분기
    checkpointer: Any = None
    try:
        # ── 셋업 코드도 try 안에 ── build_graph()/DB 실패 시 except 로 흘러야 함
        checkpointer = CompatMemorySaver()
        load_checkpoint(checkpointer, job_id)
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": job_id}, "callbacks": _get_callbacks()}
        await _set_job_terminal(job_id, "running")

        final = await graph.ainvoke(state, config=config) if not resume else None
        final_dict = _final_to_dict(final)

        # 그래프가 완료됐지만 state.error 가 잔존하는 경우 감지 (마지막 안전망)
        # report_composer/self_learning_dispatch 조건부 엣지로 대부분 잡히지만
        # 예상치 못한 경로로 END 에 도달했을 때를 대비
        if final_dict and final_dict.get("error"):
            _leftover_err = str(final_dict.get("error", ""))
            _leftover_tb = str(final_dict.get("error_traceback", ""))
            log.warning("pipeline_ended_with_error", error=_leftover_err[:200])
            try:
                from ada.error_handler.auto_handler import capture_and_handle

                await capture_and_handle(
                    error_message=_leftover_err,
                    stack_trace=_leftover_tb,
                    job_id=job_id,
                    source="runner_end_state",
                )
            except Exception:  # noqa: BLE001
                pass
            publish_progress(job_id, "error_recovery", _leftover_err, pipeline_status="failed", error=_leftover_err)
            await _set_job_terminal(job_id, "failed", error=_leftover_err)
            return {"status": "failed", "error": _leftover_err}

        is_terminal = bool(final_dict) and not (final_dict.get("current_gate"))
        if is_terminal:
            publish_progress(job_id, "END", "complete", pipeline_status="completed")
            await _set_job_terminal(job_id, "completed")
        else:
            gate = final_dict.get("current_gate") or "gate_wait"
            publish_progress(job_id, gate, "awaiting user input", pipeline_status="awaiting_user")
            _save_gate_data(job_id, final_dict)
            # resume 시 full state 복원을 위해 별도 저장 (aupdate_state partial 누락 방지)
            try:
                _get_redis().set(
                    f"ada:full_state:{job_id}",
                    json.dumps(final_dict, ensure_ascii=False, default=str),
                    ex=86400,
                )
            except Exception:  # noqa: BLE001
                pass
        return {"status": "completed", "final": final_dict}
    except Exception as e:
        tb = traceback.format_exc()
        err_msg = repr(e) if not str(e) else str(e)
        log.error("pipeline_error", error=err_msg, traceback=tb)

        # safe_node 가 못 잡은 그래프 크래시 → AutoErrorHandler Tier 0~3
        # (RESOLVED_ACTIONS = "KB 기록 존재" 이지 "코드 수정됨" 이 아니므로 재시도 없음)
        try:
            from ada.error_handler.auto_handler import capture_and_handle

            await capture_and_handle(
                error_message=err_msg,
                stack_trace=tb,
                job_id=job_id,
                source="runner",
            )
        except Exception as _inner:  # noqa: BLE001
            log.warning("runner_capture_failed", error=str(_inner))

        publish_progress(
            job_id,
            "error_recovery",
            f"error: {err_msg}",
            pipeline_status="failed",
            error=err_msg,
        )
        await _set_job_terminal(job_id, "failed", error=err_msg)
        return {"status": "failed", "error": err_msg}
    finally:
        if checkpointer is not None:
            save_checkpoint(checkpointer, job_id)


async def _resume(*, job_id: str, gate_response: dict) -> dict:
    from orchestrator.checkpoint import CompatMemorySaver, load_checkpoint, save_checkpoint
    from orchestrator.graph import build_graph

    checkpointer: Any = None
    try:
        # ── 셋업 코드도 try 안에 ── build_graph()/DB 실패 시 except 로 흘러야 함
        checkpointer = CompatMemorySaver()
        load_checkpoint(checkpointer, job_id)
        graph = build_graph(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": job_id}}
        await _set_job_terminal(job_id, "running")

        gate_code = gate_response.get("gate", "G?")

        # full_state 를 Redis 에서 먼저 로드 (aupdate_state partial 누락 방지)
        full_state_dict: dict = {}
        try:
            _raw_fs = _get_redis().get(f"ada:full_state:{job_id}")
            if _raw_fs:
                full_state_dict = json.loads(_raw_fs)
        except Exception:  # noqa: BLE001
            pass

        # gate_responses 는 snap.values 에서 읽는 것이 최신 (full_state 보다 우선)
        snap = await graph.aget_state(config)
        cur = snap.values
        existing = cur.get("gate_responses", {}) if isinstance(cur, dict) else getattr(cur, "gate_responses", {})
        if not existing and full_state_dict:
            existing = full_state_dict.get("gate_responses", {})
        new_responses = dict(existing)
        new_responses[gate_code] = {
            **new_responses.get(gate_code, {}),
            "user_choice": gate_response.get("choice"),
        }

        # snap.values 를 base 로 사용해 EDA 등 계산된 필드를 보존
        # full_state_dict 는 job_id 등 누락 필드 보완용으로만 사용
        snap_dict: dict = {}
        if isinstance(cur, dict):
            snap_dict = dict(cur)
        elif hasattr(cur, "model_dump"):
            snap_dict = cur.model_dump()
        elif hasattr(cur, "__dict__"):
            snap_dict = dict(vars(cur))
        base_state = {**full_state_dict, **snap_dict}  # snap 이 stale full_state 를 덮어씀
        update_payload = {**base_state, "gate_responses": new_responses, "current_gate": None}
        await graph.aupdate_state(config, update_payload)
        final = await graph.ainvoke(None, config=config)
        final_dict = _final_to_dict(final)
        has_error = bool(final_dict.get("error"))
        is_terminal = bool(final_dict) and not final_dict.get("current_gate")
        if is_terminal and has_error:
            # 에러로 인해 게이트가 스킵된 경우 — completed 가 아닌 failed 로 처리
            _err = final_dict.get("error", "unknown error")
            publish_progress(job_id, "error_recovery", _err, pipeline_status="failed", error=_err)
            await _set_job_terminal(job_id, "failed", error=_err)
        elif is_terminal:
            publish_progress(job_id, "END", "complete", pipeline_status="completed")
            await _set_job_terminal(job_id, "completed")
        else:
            gate = final_dict.get("current_gate") or "gate_wait"
            publish_progress(job_id, gate, "awaiting user input", pipeline_status="awaiting_user")
            _save_gate_data(job_id, final_dict)
            # 다음 resume 를 위해 최신 full_state 저장 (stale 상태 덮어쓰기 방지)
            try:
                _get_redis().set(
                    f"ada:full_state:{job_id}",
                    json.dumps(final_dict, ensure_ascii=False, default=str),
                    ex=86400,
                )
            except Exception:  # noqa: BLE001
                pass
        return {"status": "completed", "final": final_dict}
    except Exception as e:
        tb = traceback.format_exc()
        err_msg = repr(e) if not str(e) else str(e)
        log.error("pipeline_resume_error", error=err_msg, traceback=tb)

        # 게이트 재개 레벨 크래시 → AutoErrorHandler Tier 0~3
        try:
            from ada.error_handler.auto_handler import capture_and_handle

            await capture_and_handle(
                error_message=err_msg,
                stack_trace=tb,
                job_id=job_id,
                source="resume",
            )
        except Exception as _inner:  # noqa: BLE001
            log.warning("resume_capture_failed", error=str(_inner))

        publish_progress(
            job_id,
            "error_recovery",
            f"error: {err_msg}",
            pipeline_status="failed",
            error=err_msg,
        )
        await _set_job_terminal(job_id, "failed", error=err_msg)
        return {"status": "failed", "error": err_msg}
    finally:
        if checkpointer is not None:
            save_checkpoint(checkpointer, job_id)

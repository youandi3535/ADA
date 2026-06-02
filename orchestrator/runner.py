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


def publish_progress(job_id: str, current_agent: str, message: str = "") -> None:
    """대시보드 SSE / WebSocket 채널."""
    r = _get_redis()
    payload = {
        "agent": current_agent,
        "progress": AGENT_PROGRESS_MAP.get(current_agent, 0),
        "ts": time.time(),
        "message": message,
    }
    body = json.dumps(payload)
    r.publish(f"ada:pipeline:{job_id}", body)
    # 마지막 진행상황 영속화 — /pipeline/gate 가 실제 진행률/현재 에이전트를 읽어 표시
    try:
        r.set(f"ada:progress:{job_id}", body, ex=3600)
    except Exception:  # noqa: BLE001
        pass


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

    state = PipelineState(**initial_state)
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
def _final_to_dict(final) -> dict | None:
    """LangGraph ainvoke 반환값(PipelineState 또는 AddableValuesDict) → dict 변환."""
    if final is None:
        return None
    if hasattr(final, "to_dict"):
        return final.to_dict()
    return dict(final)


async def _invoke(*, job_id: str, state: PipelineState, resume: bool) -> dict:
    from orchestrator.graph import get_pipeline_graph

    graph = get_pipeline_graph()
    config = {"configurable": {"thread_id": job_id}, "callbacks": _get_callbacks()}

    try:
        final = await graph.ainvoke(state, config=config) if not resume else None
        publish_progress(job_id, "END", "complete")
        return {"status": "completed", "final": _final_to_dict(final)}
    except Exception as e:
        log.error("pipeline_error", error=str(e))
        publish_progress(job_id, "error_recovery", f"error: {e}")
        return {"status": "failed", "error": str(e)}


async def _resume(*, job_id: str, gate_response: dict) -> dict:
    from orchestrator.graph import get_pipeline_graph

    graph = get_pipeline_graph()
    config = {"configurable": {"thread_id": job_id}}

    # 사용자 응답을 state 의 gate_responses 에 머지
    snap = await graph.aget_state(config)
    cur = snap.values  # LangGraph returns dict for Pydantic state
    gate_code = gate_response.get("gate", "G?")
    existing = cur["gate_responses"] if isinstance(cur, dict) else cur.gate_responses
    new_responses = dict(existing)
    new_responses[gate_code] = {**new_responses.get(gate_code, {}), "user_choice": gate_response.get("choice")}
    await graph.aupdate_state(config, {"gate_responses": new_responses, "current_gate": None})
    final = await graph.ainvoke(None, config=config)
    return {"status": "completed", "final": _final_to_dict(final)}

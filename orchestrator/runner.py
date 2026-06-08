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
    # 워커가 시작될 때 추가 모듈을 import 해 task 데코레이터가 등록되도록 한다.
    # 본 파일에 모든 task 가 있지 않으므로 (harness_tasks, training_tasks 분리)
    # 명시적으로 include 하지 않으면 worker-harness / worker-training 가 task 미등록
    # 상태로 idle 이 된다 (NY 가 보고한 정확한 증상).
    include=[
        "orchestrator.harness_tasks",
        "orchestrator.training_tasks",
    ],
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
# A 트랙(2026-06-04): agent 단위 단일 마일스톤(고정 %) 에서 phase 단위 (start, end) 범위로 확장.
# BaseAgent 가 진입(start) → LLM 호출 전(llm_start) → LLM 호출 후(llm_end) → 종료(end) 4 시점에
# publish_progress(progress=계산값) 를 호출하여 실제 시간 비례에 가깝게 진행률 보고.
# (start, end) 폭은 그 agent 의 평균 작업 비중에 비례. 데이터 크기/방법에 따라 LLM 호출 시간이
# 달라져도 phase 단위 4회 보고로 클라이언트가 시간 비례 화면을 그릴 수 있다.
AGENT_PHASE_MAP: dict[str, tuple[int, int]] = {
    "supervisor": (1, 3),
    "intent_elicitor": (3, 5),
    "data_profiler": (5, 12),
    "schema_validator": (12, 14),
    "gate_direction": (14, 18),
    "eda_agent": (18, 28),
    "gate_methodology": (28, 33),
    "preprocessing_strategist": (33, 38),
    "feature_engineer": (38, 43),
    "preprocessing_choice": (43, 45),
    "gate_model_strategy": (45, 50),
    "model_selection": (50, 55),
    "hyperparameter_tuner": (55, 65),
    "training_executor": (65, 75),
    "training_monitor": (75, 78),
    "metrics_aggregator": (78, 82),
    "gate_best_model": (82, 85),
    "fine_tune_executor": (85, 88),
    "eval_agent": (88, 92),
    "explainability": (92, 95),
    "insight": (95, 97),
    "gate_outputs": (97, 98),
    "report_composer": (98, 99),
    "self_learning_dispatch": (99, 100),
    "error_recovery": (50, 50),
}
# 호환: 기존 호출자들이 참조하는 AGENT_PROGRESS_MAP — 각 agent 의 end 값으로 자동 생성.
AGENT_PROGRESS_MAP: dict[str, int] = {k: v[1] for k, v in AGENT_PHASE_MAP.items()}
AGENT_PROGRESS_MAP["END"] = 100

# 게이트 인터럽트(사용자 입력 대기) 시 표시할 진행률.
# proposals 로드 완료 신호 → 프론트는 100% 로 올리므로 이 값은 "로딩 완료 직전" 수준.
GATE_WAIT_PROGRESS: dict[str, int] = {
    "G2": 18,
    "G3": 33,
    "G4": 50,
    "G5": 85,
    "G6": 98,
}


def agent_phase_progress(agent_key: str, phase: str) -> int:
    """phase 별 진행률 계산. phase ∈ {start, llm_start, llm_end, end}.
    LLM 호출이 없는 agent 도 start/end 만 publish 하면 자연스러운 두 시점 보고.
    """
    rng = AGENT_PHASE_MAP.get(agent_key)
    if rng is None:
        return AGENT_PROGRESS_MAP.get(agent_key, 0)
    lo, hi = rng
    width = hi - lo
    if phase == "start":
        return lo
    if phase == "llm_start":
        return int(lo + width * 0.25)
    if phase == "llm_end":
        return int(lo + width * 0.75)
    return hi  # "end" 또는 알 수 없는 phase


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
    progress: int | None = None,
) -> None:
    """대시보드 SSE / WebSocket 채널.

    pipeline_status: ``running``/``completed``/``failed`` — 워커 종료 신호.
        프론트는 이 값을 보고 폴링을 종료한다 (`error_recovery`가 보이는데도
        진행률이 멈춰 있는 좀비 상태 방지).
    error: 실패 시 사용자 안내용 메시지 (PII 마스킹 후 저장).
    progress: 명시 진행률(0~100). 지정 시 그 값으로 발행, None 이면 AGENT_PROGRESS_MAP
        의 agent 별 end 값으로 폴백(기존 호환). BaseAgent 는 phase 단위로 이 인자를
        채워 호출해 시간 비례 진행을 구현한다.
    """
    r = _get_redis()
    pct = progress if progress is not None else AGENT_PROGRESS_MAP.get(current_agent, 0)
    pct = max(0, min(100, int(pct)))
    payload: dict[str, Any] = {
        "agent": current_agent,
        "progress": pct,
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
    """파이프라인 시작 — 첫 인터럽트(G2)까지 진행 후 대기 상태로 반환."""
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
    """게이트 응답 후 재개. 동일 job 의 concurrent resume 를 Redis 락으로 차단."""
    lock_key = f"ada:resume_lock:{job_id}"
    r = _get_redis()
    # NX=True: 락이 없을 때만 SET, ex=300: 5분 후 자동 해제
    acquired = r.set(lock_key, "1", nx=True, ex=300)
    if not acquired:
        log.warning("resume_skipped_concurrent", job_id=job_id, gate=gate_response.get("gate"))
        return {"status": "skipped", "reason": "concurrent resume in progress"}
    try:
        log.info("pipeline_resume", job_id=job_id, gate=gate_response.get("gate"))
        return asyncio.run(_resume(job_id=job_id, gate_response=gate_response))
    finally:
        r.delete(lock_key)


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

    각 게이트 화면에서 직전 단계 결과를 표시하려면 그 결과 필드가
    gate_data 안에 있어야 한다. 예:
      - G3 (방법론): eda_summary (EDA 결과)
      - G5 (모델 선택): best_model (학습 결과)
      - G6 (산출물): eval_result + best_model + insights (학습평가 리포트)
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
            # G3 이후 화면이 EDA 결과를 보여주기 위함
            "eda_summary": final_dict.get("eda_summary"),
            # G5 이후 화면이 학습 결과(최적 모델)를 표시하기 위함
            "best_model": final_dict.get("best_model"),
            # G6 화면이 학습·평가 리포트를 표시하기 위함
            "eval_result": final_dict.get("eval_result"),
            # G6/G7 산출물 영역을 즉시 표시
            "requested_outputs": final_dict.get("requested_outputs") or [],
            "output_paths": final_dict.get("output_paths") or {},
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
            publish_progress(
                job_id,
                gate,
                "awaiting user input",
                pipeline_status="awaiting_user",
                progress=GATE_WAIT_PROGRESS.get(gate),
            )
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

        # 재개 시 이전 실행의 stale progress·agent 를 덮어씀.
        # (예: G3 응답 후 재개 시 이전 97%·하이퍼파라미터 튜닝이 G4 로딩 화면에 잔존하는 버그 방지)
        _NEXT_AGENT_AFTER_GATE: dict[str, str] = {
            "G2": "eda_agent",
            "G3": "preprocessing_strategist",
            "G4": "model_selection",
            "G5": "eval_agent",
            "G6": "report_composer",
        }
        _next_agent = _NEXT_AGENT_AFTER_GATE.get(gate_code, "supervisor")
        publish_progress(job_id, _next_agent, "파이프라인 재개", progress=GATE_WAIT_PROGRESS.get(gate_code, 0))

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

        # proposals 보존: snap 이 stale 하여 해당 gate 의 proposals 가 없으면
        # full_state_dict 에서 fallback — BaseGate 재진입 시 _apply_choice 에 필요
        fs_gate_entry = full_state_dict.get("gate_responses", {}).get(gate_code, {})
        snap_gate_entry = new_responses.get(gate_code, {})
        new_responses[gate_code] = {
            **fs_gate_entry,  # full_state proposals 를 base 로
            **snap_gate_entry,  # snap 이 더 최신이면 덮어씀
            "user_choice": gate_response.get("choice"),  # 사용자 선택 항상 최우선
        }

        from orchestrator.graph import GATE_NODES as _GN  # noqa: WPS433

        _gate_cls = next((cls for cls in _GN.values() if getattr(cls, "gate_code", None) == gate_code), None)

        # 제출된 게이트보다 뒤에 있는 gate_responses 제거 + 다운스트림 상태 초기화
        _gnum = int(gate_code[1]) if len(gate_code) == 2 and gate_code[0] == "G" and gate_code[1].isdigit() else 0
        if _gnum > 0:
            for _k in [
                k for k in list(new_responses) if len(k) == 2 and k[0] == "G" and k[1:].isdigit() and int(k[1]) > _gnum
            ]:
                del new_responses[_k]
            full_state_dict = {
                **full_state_dict,
                "preprocessing_plan": None,
                "preprocessed_data_id": None,
                "eda_charts": [],
                "eda_summary": None,
                "model_candidates": [],
                "best_params": {},
                "trained_models": [],
                "training_warnings": [],
                "best_model": None,
                "eval_result": None,
                "explanations": None,
                "insights": None,
                "output_paths": {},
                "retry_count": 0,
                "re_loop_count": 0,
                "error": None,
                "error_traceback": None,
                "error_fingerprint": None,
                "error_classified_as": None,
                "next_agent": None,
            }
            try:
                _get_redis().delete(f"ada:gate_data:{job_id}")
            except Exception:  # noqa: BLE001
                pass

        # full_state_dict 가 비어 있으면 snap.values 로 보완 (jh 방식의 견고한 추출 적용)
        if not full_state_dict.get("job_id"):
            snap_dict: dict = {}
            if isinstance(cur, dict):
                snap_dict = dict(cur)
            elif hasattr(cur, "model_dump"):
                snap_dict = cur.model_dump()
            elif hasattr(cur, "__dict__"):
                snap_dict = dict(vars(cur))
            full_state_dict = {**snap_dict, **full_state_dict}

        # _apply_choice 를 미리 적용 (fresh invocation 의 게이트 통과 시 중복 적용되지만 멱등)
        if _gate_cls:
            try:
                from ada.core.state import PipelineState as _PS  # noqa: WPS433

                _base = {**full_state_dict, "gate_responses": new_responses}
                _ps_fields = getattr(_PS, "model_fields", None) or _PS.__fields__
                _temp = _PS(**{k: _base[k] for k in _ps_fields if k in _base})
                _applied = _gate_cls()._apply_choice(
                    _temp,
                    gate_response.get("choice", {}),
                    new_responses.get(gate_code, {}).get("proposals") or [],
                )
                for _f in _ps_fields:
                    _orig, _new = getattr(_temp, _f, None), getattr(_applied, _f, None)
                    if _new != _orig:
                        full_state_dict = {**full_state_dict, _f: _new}
            except Exception as _e:  # noqa: BLE001
                log.warning("resume_apply_choice_failed", gate=gate_code, error=str(_e))

        update_payload = {**full_state_dict, "gate_responses": new_responses, "current_gate": None}

        # 항상 fresh invocation — 체크포인트 실행 위치에 의존하지 않음
        fresh_cp = CompatMemorySaver()
        fresh_graph = build_graph(checkpointer=fresh_cp)
        from ada.core.state import PipelineState as _PS_r  # noqa: WPS433

        _ps_r_fields = getattr(_PS_r, "model_fields", None) or _PS_r.__fields__
        # None 값은 제외해서 Pydantic 기본값(예: task="auto")이 적용되도록 한다.
        # update_payload 에 task=None 이 들어오면 str 필드 검증 실패 → ValidationError.
        _fresh = _PS_r(**{k: v for k, v in update_payload.items() if k in _ps_r_fields and v is not None})
        final = await fresh_graph.ainvoke(_fresh, config=config)
        final_dict = _final_to_dict(final)

        # interrupt_after 는 pass-through 게이트에도 발화 → current_gate=None 이고
        # 실제 완료 신호가 없으면 다음 게이트까지 ainvoke 반복.
        #
        # ❗ best_model 체크 제거 (2026-06-04):
        #   best_model 은 metrics_aggregator 가 G5 (gate_best_model) 직전에 세팅한다.
        #   G5 resume 시 _apply_choice 가 best_model 을 다시 채우는데, 이 체크가 살아 있으면
        #   loop 가 G5 인터럽트 직후 종료되어 eval_agent → explainability → insight →
        #   gate_outputs(G6) 까지 못 가고 is_terminal=True 로 잘못 완료 처리된다.
        #   "정말 완료" 신호는 output_paths (report_composer 가 채움) 만으로 충분.
        _passes = len(_GN) + 2
        while (
            _passes > 0
            and final_dict is not None
            and not final_dict.get("current_gate")
            and not final_dict.get("error")
            and not final_dict.get("output_paths")
        ):
            final = await fresh_graph.ainvoke(None, config=config)
            final_dict = _final_to_dict(final)
            _passes -= 1

        checkpointer = fresh_cp
        log.info(
            "resume_fresh_invocation",
            gate=gate_code,
            current_gate=final_dict.get("current_gate") if final_dict else None,
        )

        # 에러 잔존 시 failed 처리
        if final_dict and final_dict.get("error"):
            _leftover_err = str(final_dict.get("error", ""))
            _leftover_tb = str(final_dict.get("error_traceback", ""))
            log.warning("resume_ended_with_error", error=_leftover_err[:200])
            try:
                from ada.error_handler.auto_handler import capture_and_handle

                await capture_and_handle(
                    error_message=_leftover_err,
                    stack_trace=_leftover_tb,
                    job_id=job_id,
                    source="runner_resume_end_state",
                )
            except Exception:  # noqa: BLE001
                pass
            _save_gate_data(job_id, final_dict)
            publish_progress(job_id, "error_recovery", _leftover_err, pipeline_status="failed", error=_leftover_err)
            await _set_job_terminal(job_id, "failed", error=_leftover_err)
            return {"status": "failed", "error": _leftover_err}

        is_terminal = bool(final_dict) and not final_dict.get("current_gate")
        if is_terminal:
            publish_progress(job_id, "END", "complete", pipeline_status="completed")
            await _set_job_terminal(job_id, "completed")
            # 완료 시 gate_data 갱신: gate 제거 + requested_outputs / best_model 보존
            try:
                _r = _get_redis()
                _gd_raw = _r.get(f"ada:gate_data:{job_id}")
                _gd: dict = json.loads(_gd_raw) if _gd_raw else {}
                _gd.pop("gate", None)
                _gd["pipeline_status"] = "completed"
                _gd["requested_outputs"] = final_dict.get("requested_outputs") or []
                _gd["output_paths"] = final_dict.get("output_paths") or {}
                if final_dict.get("best_model"):
                    _gd["best_model"] = final_dict["best_model"]
                if final_dict.get("insights"):
                    _gd["insights"] = final_dict["insights"]
                # G7 완료 화면이 평가 결과·EDA 요약까지 표시하도록 보존
                if final_dict.get("eval_result"):
                    _gd["eval_result"] = final_dict["eval_result"]
                if final_dict.get("eda_summary"):
                    _gd["eda_summary"] = final_dict["eda_summary"]
                _r.set(f"ada:gate_data:{job_id}", json.dumps(_gd, ensure_ascii=False, default=str), ex=86400)
            except Exception:  # noqa: BLE001
                pass
        else:
            gate = final_dict.get("current_gate") or "gate_wait"
            publish_progress(
                job_id,
                gate,
                "awaiting user input",
                pipeline_status="awaiting_user",
                progress=GATE_WAIT_PROGRESS.get(gate),
            )
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

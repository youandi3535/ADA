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
    # G1 (0~18, 폭 18) — gate_direction(AnalysisProposerAgent) 이 LLM 호출 무거워 압도적
    "supervisor": (0, 1),  # ~1초
    "intent_elicitor": (1, 2),  # ~5초
    "data_profiler": (2, 6),  # ~30초
    "schema_validator": (6, 7),  # ~5초
    "gate_direction": (7, 18),  # ~90초 ← G1 시간의 절반 이상
    # G2 (18~33, 폭 15)
    "eda_agent": (18, 30),  # ~60초
    "gate_methodology": (30, 33),  # ~15초
    # G3 (33~50, 폭 17)
    "preprocessing_strategist": (33, 40),  # ~30초
    "feature_engineer": (40, 45),  # ~20초
    "preprocessing_choice": (45, 46),  # ~5초
    "gate_model_strategy": (46, 50),  # ~20초
    # G4 (50~85, 폭 35) — 학습 단계, 가장 무거움
    "model_selection": (50, 52),  # ~15초
    "hyperparameter_tuner": (52, 64),  # ~120초
    "training_executor": (64, 82),  # ~180초 ← G4 핵심
    "training_monitor": (82, 83),  # ~10초
    "metrics_aggregator": (83, 84),  # ~10초
    "gate_best_model": (84, 85),  # ~15초
    # G5 (85~98, 폭 13)
    "fine_tune_executor": (85, 90),  # ~60초
    "eval_agent": (90, 93),  # ~30초
    "explainability": (93, 95),  # ~30초
    "insight": (95, 97),  # ~20초
    "gate_outputs": (97, 98),  # ~10초
    # G6 (98~100, 폭 2)
    "report_composer": (98, 99),  # ~30초
    "self_learning_dispatch": (99, 100),  # ~5초
    # 특수 — 변경 없음
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


# ---------------------------------------------------------------------------
# 단계별 ETA — DB 실측(agent_runs.duration_ms) 기반 (사용자 1순위 — 환경별 정확도)
# ---------------------------------------------------------------------------
# agents/base.py 가 매 agent 실행마다 duration_ms 를 agent_runs 에 기록한다.
# 이 실측값은 LLM·CPU·네트워크 같은 환경별 차이를 이미 반영한 진짜 ETA 소스 —
# 별도의 EWMA bucket 학습이나 LLM ping 보정 계층 없이 이것만으로 충분하다.
STAGE_AGENTS: dict[str, list[str]] = {
    "G1": [
        "SupervisorAgent",
        "IntentElicitorAgent",
        "DataProfilerAgent",
        "SchemaValidatorAgent",
        "AnalysisProposerAgent",
    ],
    "G2": ["EDAAgent", "MethodologyProposerAgent"],
    "G3": [
        "PreprocessingStrategistAgent",
        "FeatureEngineerAgent",
        "PreprocessingChoiceAgent",
        "ModelStrategyProposerAgent",
    ],
    "G4": [
        "ModelSelectionAgent",
        "HyperparameterTunerAgent",
        "TrainingExecutorAgent",
        "TrainingMonitorAgent",
        "MetricsAggregatorAgent",
        "ModelComparisonReporterAgent",
    ],
    "G5": ["FineTuneExecutorAgent", "EvalAgent", "ExplainabilityAgent", "InsightAgent", "OutputTypeSelectorAgent"],
    "G6": ["ReportComposerAgent", "SelfLearningAgent"],
}

_STAGE_AVG_CACHE_TTL = 300  # Redis 캐시 5분 — DB 부하 경감
_STAGE_AVG_LOOKBACK_DAYS = 30


async def _stage_avg_duration_sec(stage: str) -> int | None:
    """단계 구성 agent 들의 최근 30일 평균 duration_ms 합산(초) — ETA 1순위 소스.

    agent_runs 에 단계 구성 agent 의 절반을 초과하는 실측 데이터가 있을 때만 값을 반환한다.
    그렇지 않으면 None — 호출자(``_stage_eta_now``)가 ``estimate_stage_eta`` 폴백을 사용.
    캐시: ``ada:stage_avg:{stage}`` (TTL 5분, Redis).
    """
    r = _get_redis()
    cache_key = f"ada:stage_avg:{stage}"
    try:
        cached = r.get(cache_key)
        if cached is not None:
            return json.loads(cached).get("sec")
    except Exception:  # noqa: BLE001
        pass

    agents = STAGE_AGENTS.get(stage, [])
    if not agents:
        return None
    try:
        from datetime import datetime, timedelta, timezone  # noqa: WPS433

        from sqlalchemy import func, select  # noqa: WPS433

        from ada.db.models import AgentRun  # noqa: WPS433
        from ada.db.session import AsyncSessionLocal  # noqa: WPS433

        since = datetime.now(timezone.utc) - timedelta(days=_STAGE_AVG_LOOKBACK_DAYS)

        async def _query() -> dict[str, float]:
            async with AsyncSessionLocal() as session:
                rows = await session.execute(
                    select(AgentRun.agent_name, func.avg(AgentRun.duration_ms))
                    .where(
                        AgentRun.agent_name.in_(agents),
                        AgentRun.status == "completed",
                        AgentRun.created_at >= since,
                    )
                    .group_by(AgentRun.agent_name)
                )
                return {name: float(avg_ms) for name, avg_ms in rows.all() if avg_ms is not None}

        averages = await _query()
    except Exception as e:  # noqa: BLE001
        log.warning("stage_avg_duration_query_failed", stage=stage, error=str(e))
        return None

    # 절반 이상 비어있으면(=실측 보유 agent 가 절반 이하) 신뢰 불가 — 폴백 baseline 사용
    if len(averages) * 2 <= len(agents):
        return None

    total_sec = int(round(sum(averages.values()) / 1000))
    log.info(
        "stage_avg_duration",
        stage=stage,
        agents_known=len(averages),
        agents_total=len(agents),
        sec=total_sec,
    )
    try:
        r.setex(cache_key, _STAGE_AVG_CACHE_TTL, json.dumps({"sec": total_sec}))
    except Exception:  # noqa: BLE001
        pass
    return total_sec


def estimate_stage_eta(
    stage: str,
    file_size_bytes: int | None = None,
    n_rows: int | None = None,
    n_cols: int | None = None,
    text_col_ratio: float | None = None,
    missing_ratio: float | None = None,
) -> int:
    """단계별 ETA(초) 폴백 baseline — file_size + rows + cols + dtype 가중치.

    ``_stage_eta_now`` 가 DB 실측(``_stage_avg_duration_sec``) 을 우선 사용하고,
    학습 데이터가 부족할 때만(예: 운영 초기) 이 함수로 추정한다.
    text_col_ratio·missing_ratio 가 주어지면 더 정밀해진다.
    """
    mb = (file_size_bytes or 0) / (1024 * 1024)
    rows = n_rows or 0
    cols = n_cols or 0
    txt = max(0.0, min(1.0, float(text_col_ratio or 0.0)))
    miss = max(0.0, min(1.0, float(missing_ratio or 0.0)))
    if stage == "G1":  # supervisor + intent + profile + schema + gate_direction
        base = 30
        if mb > 5:
            base += 15
        if mb > 50:
            base += 30
        if mb > 200:
            base += 60
        return base
    if stage == "G2":  # EDA + gate_methodology
        base = 45
        if rows > 100_000:
            base += 20
        if cols > 50:
            base += 10
        base += int(txt * 15)  # 텍스트 컬럼 많을수록 EDA 길어짐
        return base
    if stage == "G3":  # preprocessing + feature_engineer + preprocessing_choice + gate
        base = 60
        if cols > 20:
            base += min(cols, 200)  # 컬럼당 ~1초, 200초 cap
        base += int(miss * 30)  # 결측 처리 시간
        base += int(txt * 20)  # 텍스트 인코딩 시간
        return base
    if stage == "G4":  # model_selection + tuning + training + monitor + metrics + gate
        base = 180
        if rows > 10_000:
            base += 60
        if rows > 100_000:
            base += 120
        return base
    if stage == "G5":  # fine_tune + eval + explain + insight + gate_outputs
        base = 60
        if rows > 50_000:
            base += 30
        return base
    if stage == "G6":  # report_composer + self_learning_dispatch
        return 45
    return 60


def publish_stage_partial(job_id: str, partial: dict[str, Any]) -> None:
    """HJ 2026-06-10 — 단계 2~6 의 long-phase agent 가 인크리멘털 결과를 publish 하는 헬퍼.

    1단계 G1 의 ``ada:domain_partial:{job_id}`` 와 동일한 구조 — 단, 모든 후행 단계가 공용 사용.
    Redis 키: ``ada:stage_partial:{job_id}`` (TTL 600s).
    저장 형식: 누적 dict — 호출 시 기존 값과 머지.

    예) eda_agent: ``{"eda_status": "차트 생성 중", "eda_progress": 1}``
        methodology_proposer: ``{"methodology_status": "LLM 호출 중", "candidates_partial": [...]}``

    누수 방지: Redis 실패 시에도 본 agent 흐름에 영향 없음 (try/except 외부 격리는 호출자 책임).
    """
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        r = _get_redis()
        existing: dict[str, Any] = {}
        try:
            raw = r.get(f"ada:stage_partial:{job_id}")
            if raw:
                existing = json.loads(raw)
        except Exception:  # noqa: BLE001
            existing = {}
        existing.update(partial)
        r.setex(
            f"ada:stage_partial:{job_id}",
            600,
            json.dumps(existing, ensure_ascii=False, default=str),
        )
    except Exception:  # noqa: BLE001
        pass


def publish_progress(
    job_id: str,
    current_agent: str,
    message: str = "",
    *,
    pipeline_status: str | None = None,
    error: str | None = None,
    progress: int | None = None,
    eta_sec: int | None = None,
    extra: dict | None = None,
) -> None:
    """대시보드 SSE / WebSocket 채널.

    pipeline_status: ``running``/``completed``/``failed`` — 워커 종료 신호.
        프론트는 이 값을 보고 폴링을 종료한다 (`error_recovery`가 보이는데도
        진행률이 멈춰 있는 좀비 상태 방지).
    error: 실패 시 사용자 안내용 메시지 (PII 마스킹 후 저장).
    progress: 명시 진행률(0~100). 지정 시 그 값으로 발행, None 이면 AGENT_PROGRESS_MAP
        의 agent 별 end 값으로 폴백(기존 호환). BaseAgent 는 phase 단위로 이 인자를
        채워 호출해 시간 비례 진행을 구현한다.
    eta_sec: 단계 baseline 잔여 시간(초). 단계 시작 시점에 ``_stage_eta_now`` 로 계산해
        publish — 프론트는 이 값을 (현재시각 - eta_base_ts) 만큼 감소시켜 표시한다.
        None 이면 ETA 필드를 갱신하지 않는다(보간 publish).
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
    if eta_sec is not None:
        payload["eta_sec"] = max(0, int(eta_sec))
        payload["eta_base_ts"] = time.time()
    if pipeline_status:
        payload["status"] = pipeline_status
    # HJ 2026-06-09 G1 단축 γ — partial domain 등 보조 정보 전달 (frontend G1 화면 점진 표시).
    if extra and isinstance(extra, dict):
        for k, v in extra.items():
            if k not in payload:  # 핵심 필드 덮어쓰기 금지
                payload[k] = v
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


def _get_file_meta(file_id: str | None) -> tuple[int | None, str | None]:
    """업로드 메타 — (size_bytes, extension). 캐시 키는 file_id.

    캐시(`ada:file_meta:{file_id}`) 우선, 없으면 DB 1회 조회 후 캐시 (TTL 6시간).
    """
    if not file_id:
        return None, None
    r = _get_redis()
    ck = f"ada:file_meta:{file_id}"
    try:
        cached = r.get(ck)
        if cached:
            data = json.loads(cached)
            return data.get("size"), data.get("ext")
    except Exception:  # noqa: BLE001
        pass
    try:
        from pathlib import Path as _Path  # noqa: WPS433

        from sqlalchemy import select  # noqa: WPS433

        from ada.db.models import Upload  # noqa: WPS433
        from ada.db.session import AsyncSessionLocal  # noqa: WPS433

        async def _lookup() -> tuple[int | None, str | None]:
            async with AsyncSessionLocal() as session:
                row = await session.scalar(select(Upload).where(Upload.file_id == file_id))
                if row is None:
                    return None, None
                size = int(row.size_bytes or 0) if row.size_bytes else None
                ext = _Path(row.filename or "").suffix.lower() or None
                return size, ext

        size, ext = asyncio.run(_lookup())
        try:
            r.setex(ck, 6 * 3600, json.dumps({"size": size, "ext": ext}))
        except Exception:  # noqa: BLE001
            pass
        return size, ext
    except Exception as e:  # noqa: BLE001
        log.warning("file_meta_lookup_failed", error=str(e))
        return None, None


async def _stage_eta_now(
    stage: str,
    file_size_bytes: int | None = None,
    n_rows: int | None = None,
    n_cols: int | None = None,
    text_col_ratio: float | None = None,
    missing_ratio: float | None = None,
) -> int:
    """단계 ETA(초) — DB 실측 평균(``_stage_avg_duration_sec``) 우선, 부족하면 baseline 폴백."""
    learned = await _stage_avg_duration_sec(stage)
    if learned is not None:
        return learned
    return estimate_stage_eta(
        stage,
        file_size_bytes=file_size_bytes,
        n_rows=n_rows,
        n_cols=n_cols,
        text_col_ratio=text_col_ratio,
        missing_ratio=missing_ratio,
    )


@celery_app.task(bind=True, name="ada.pipeline.run", max_retries=3)
def run_pipeline_task(self: Any, job_id: str, initial_state: dict) -> dict:
    """파이프라인 시작 — 첫 인터럽트(G2)까지 진행 후 대기 상태로 반환.

    ETA: agent_runs 실측 평균(``_stage_eta_now``) 우선, 학습 데이터 부족 시
    file_size + 확장자 기반 baseline 으로 폴백 — 첫 publish 에 사용.
    """
    log.info("pipeline_start", job_id=job_id)
    file_id = initial_state.get("file_id") if isinstance(initial_state, dict) else None
    file_size, _ext = _get_file_meta(file_id)

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

    async def _start() -> dict:
        # G1 baseline — DB 실측 평균 우선, 부족하면 file_size + 확장자 기반 baseline.
        # _invoke 와 동일 이벤트 루프에서 계산해야 DB 커넥션 풀이 루프 간에 어긋나지 않는다.
        g1_eta = None
        try:
            g1_eta = await _stage_eta_now("G1", file_size_bytes=file_size)
        except Exception as e:  # noqa: BLE001
            log.warning("g1_baseline_failed", error=str(e))
        publish_progress(job_id, "supervisor", "파이프라인 시작", eta_sec=g1_eta)
        return await _invoke(job_id=job_id, state=state, resume=False)

    return asyncio.run(_start())


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


# HJ 2026-06-12 — C′-1: EDA 윤색 인사이트 선계산 (worker; pandas·matplotlib 보유).
#   api 컨테이너엔 pandas 가 없어 EDA 선계산을 못 하므로 worker 로 위임한다.
#   2단계 주제 선택 중 백그라운드 실행 → resume 시 eda_agent 노드가 캐시 재사용해
#   _dynamic_insights(120~160초)를 스킵. 무거운 import 는 전부 함수 안(지연) — runner 모듈은 api 도 import 함.
@celery_app.task(name="ada.g2.eda_prefetch")
def g2_eda_prefetch_task(job_id: str) -> dict:
    try:
        return asyncio.run(_g2_eda_prefetch_async(job_id))
    except Exception as e:  # noqa: BLE001
        log.warning("g2_eda_prefetch_task_failed", job_id=job_id, error=str(e))
        return {"status": "error"}


async def _g2_eda_prefetch_async(job_id: str) -> dict:
    import json as _json

    from ada.core.state import PipelineState
    from agents.eda_agent import (
        EDAAgent,
        _eda_insights_cache_get,
        _eda_insights_cache_set,
        compute_eda_rule_insights,
    )
    from agents.handlers.common.shared import load_dataframe_from_state

    r = _get_redis()
    raw = r.get(f"ada:full_state:{job_id}")
    if not raw:
        return {"status": "no_state"}
    state = PipelineState(**_json.loads(raw))
    # 이미 캐시돼 있으면 skip
    if _eda_insights_cache_get(state.job_id, state.category, state.target_column):
        return {"status": "already_cached"}
    df = load_dataframe_from_state(state)
    insights = compute_eda_rule_insights(df, state.target_column)
    if not insights:
        return {"status": "no_insights"}
    upgraded = await EDAAgent()._dynamic_insights(
        insights, backend="ollama", context=f"G2 EDA·{state.category}", job_id=None, key=None
    )
    _eda_insights_cache_set(state.job_id, state.category, state.target_column, upgraded)
    log.info("g2_eda_prefetch_done", job_id=job_id, n=len(upgraded))
    return {"status": "done", "n": len(upgraded)}


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
        # CS 2026-06-10 — schema_validator 가 미리 저장한 topic_proposals / g2_pending 보존.
        # 백그라운드 prefetch task 가 patch 한 값을 _save_gate_data 가 덮어쓰지 않도록 기존 값 읽음.
        _prev: dict = {}
        try:
            _raw_prev = r.get(f"ada:gate_data:{job_id}")
            if _raw_prev:
                _prev = json.loads(_raw_prev) or {}
        except Exception:  # noqa: BLE001
            _prev = {}
        payload = {
            "gate": gate,
            "proposals": gate_entry.get("proposals") or [],
            # 보존 필드 — schema_validator 백그라운드 task 가 patch 한 값 보존
            # CS 2026-06-10 — G2 흐름 재설계: AnalysisProposerAgent.__call__ 이
            # state.gate_responses[G2].topic_proposals 에 저장 → 여기서 forward.
            # _prev (Redis) 는 백그라운드 prefetch 시절 fallback (제거됨).
            "topic_proposals": gate_entry.get("topic_proposals") or _prev.get("topic_proposals"),
            "g2_pending": _prev.get("g2_pending"),
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
            # HJ 2026-06-11 — G3~G6 모달의 풍부한 분석 데이터 forward.
            # PipelineState 에 이미 채워진 필드들을 frontend 가 받지 못하던 문제 해결.
            # 사용자가 게이트 화면에서 직전 단계 분석 결과를 라이브로 확인 가능.
            "chosen_recipe": final_dict.get("chosen_recipe"),  # G2 선택 = G3 화면 표시
            "user_intent": final_dict.get("user_intent"),  # G1 사용자 의도 — G2 이후 모든 화면
            "preprocessing_strategy": final_dict.get("preprocessing_strategy"),  # G3 결과 = G4 화면 표시
            "feature_engineering": final_dict.get("feature_engineering"),  # G3 결과 = G4 화면 표시
            "preprocessing_plan": final_dict.get("preprocessing_plan"),  # G3 plan steps
            "candidate_models": final_dict.get("candidate_models"),  # G4 결과 = G5 화면 표시
            "best_params": final_dict.get("best_params"),  # G4 튜닝 결과 = G5 화면 표시
            "explainability": final_dict.get("explainability"),  # G5 결과 = G6 화면 표시
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

        # 다음 단계 baseline ETA — 사용자가 G{n} 응답하면 G{n+1} 단계로 진입.
        # DB 실측 평균(_stage_eta_now) 우선, 부족하면 full_state 의 rows/cols + dtype 기반 baseline.
        next_stage = None
        if gate_code in ("G2", "G3", "G4", "G5"):
            next_stage = f"G{int(gate_code[1]) + 1}"
        elif gate_code == "G6":
            next_stage = "G6"
        next_eta = None
        if next_stage:
            try:
                _fs_raw = _get_redis().get(f"ada:full_state:{job_id}")
                _fs = json.loads(_fs_raw) if _fs_raw else {}
                _prof = (_fs.get("profile") or {}) if isinstance(_fs, dict) else {}
                _shape = (_prof.get("shape") or {}) if isinstance(_prof, dict) else {}
                _rows = int(_shape.get("rows") or 0) or None
                _cols = int(_shape.get("cols") or 0) or None
                # dtype 분포 — profile.dtypes 가 {col: dtype_str} 형태라고 가정. 없으면 폴백 0.
                _dtypes = _prof.get("dtypes") if isinstance(_prof, dict) else None
                _text_ratio = None
                if isinstance(_dtypes, dict) and _dtypes:
                    _text_n = sum(
                        1 for v in _dtypes.values() if isinstance(v, str) and ("object" in v or "string" in v)
                    )
                    _text_ratio = _text_n / max(1, len(_dtypes))
                _missing_ratio = _prof.get("missing_ratio") if isinstance(_prof, dict) else None
                _file_id = _fs.get("file_id") if isinstance(_fs, dict) else None
                _next_size: int | None = None
                if _file_id:
                    _next_size, _ = _get_file_meta(_file_id)
                next_eta = await _stage_eta_now(
                    next_stage,
                    file_size_bytes=_next_size,
                    n_rows=_rows,
                    n_cols=_cols,
                    text_col_ratio=_text_ratio,
                    missing_ratio=_missing_ratio,
                )
            except Exception as _e:  # noqa: BLE001
                log.warning("resume_baseline_eta_failed", error=str(_e))

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
        publish_progress(
            job_id,
            "supervisor",
            "파이프라인 재개",
            progress=GATE_WAIT_PROGRESS.get(gate_code, 0),
            eta_sec=next_eta,
        )

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
                # HJ 2026-06-11 — resume 시 user_intent 누적 초기화.
                #   user_intent 는 각 게이트가 선택을 append 로 쌓는 비멱등 필드다.
                #   리셋하지 않으면 (a) 재진행(이전 게이트 되감기) 시 옛 방향·방법론·전략이 남아
                #   새 카드 선택이 오염되고, (b) pre-apply + fresh invocation 이중 적용으로
                #   정상 전진에서도 "분석 방향: X (분석 방향: X)" 중복이 생긴다.
                #   None 으로 비우면 fresh invocation 이 유지된 게이트(G2→…)를 재통과하며 깨끗이 재구축.
                #   (사용자가 직접 입력한 원본 질문은 user_question 에 별도 보존되므로 유실 없음)
                "user_intent": None,
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
                    # HJ 2026-06-11 — user_intent 는 pre-apply 에서 seed 하지 않는다.
                    #   fresh invocation 의 게이트 재통과에서만 누적 → pre-apply 가 미리 채우면
                    #   같은 선택이 두 번 append 되어 중복. category·target 등 overwrite 필드는 그대로.
                    if _f == "user_intent":
                        continue
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

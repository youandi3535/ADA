"""api.routes.pipeline — 파이프라인 라우터 (Day06).

POST /pipeline/start         → 새 job 시작
GET  /pipeline/status/{job}  → 진행 상황
POST /pipeline/resume/{job}  → 5게이트 응답 후 재개
GET  /pipeline/result/{job}  → 최종 결과
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.state import PipelineState
from ada.db.models import Job, Output, Upload
from ada.db.session import get_db
from api.schemas.pipeline import (
    PipelineResumeRequest,
    PipelineStartRequest,
    PipelineStartResponse,
    PipelineStatusResponse,
)

router = APIRouter()


@router.post("/start", response_model=PipelineStartResponse)
async def start_pipeline(req: PipelineStartRequest, db: AsyncSession = Depends(get_db)) -> PipelineStartResponse:
    upload = await db.scalar(select(Upload).where(Upload.file_id == req.file_id))
    if upload is None:
        raise HTTPException(404, detail="file_id not found")

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        file_id=req.file_id,
        category=req.category or "pending",
        target_column=req.target_column,
        user_question=req.user_question,
        user_intent=req.user_intent,
        requested_outputs=req.requested_outputs,
        status="pending",
    )
    db.add(job)
    await db.flush()

    # Celery enqueue
    from orchestrator.runner import run_pipeline_task

    state = PipelineState(
        job_id=str(job_id),
        file_id=req.file_id,
        category=req.category or "pending",
        target_column=req.target_column,
        user_question=req.user_question,
        user_intent=req.user_intent,
        requested_outputs=list(req.requested_outputs),
        max_retries=req.max_retries,
    )
    run_pipeline_task.apply_async(args=[str(job_id), state.to_dict()], queue="pipeline")

    return PipelineStartResponse(
        job_id=str(job_id),
        status="pending",
        created_at=job.created_at or datetime.utcnow(),
        estimated_duration_min=10,
    )


@router.get("/status/{job_id}", response_model=PipelineStatusResponse)
async def status(job_id: str, db: AsyncSession = Depends(get_db)) -> PipelineStatusResponse:
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")

    # progress_pct 는 Redis 의 마지막 publish 메시지에서 읽어오는게 정확하지만,
    # 여기선 잡 상태 기반 단순 매핑.
    prog = 100 if job.status == "completed" else (50 if job.status == "running" else 0)
    return PipelineStatusResponse(
        job_id=str(job.id),
        status=job.status,
        category=job.category,
        target_column=job.target_column,
        current_agent=None,
        current_gate=job.current_gate,
        progress_pct=prog,
        error=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        requested_outputs=job.requested_outputs or [],
    )


@router.post("/resume/{job_id}")
async def resume(job_id: str, req: PipelineResumeRequest, db: AsyncSession = Depends(get_db)) -> dict:
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")
    from orchestrator.runner import resume_pipeline_task

    resume_pipeline_task.apply_async(
        args=[job_id, {"gate": req.gate, "choice": req.choice}],
        queue="pipeline",
    )
    return {"job_id": job_id, "gate": req.gate, "queued": True}


@router.get("/result/{job_id}")
async def result(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")
    return {
        "job_id": str(job.id),
        "status": job.status,
        "outputs": job.requested_outputs or [],
    }


@router.get("/gate/{job_id}")
async def gate_detail(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """현재 게이트의 추천(proposals) + 분석 결과(insights·eval·best_model·eda·산출물)를
    LangGraph 체크포인트 state 에서 읽어 노출 (read-only). state 미가용 시 빈 값으로 degrade."""
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")

    data: dict = {
        "gate": job.current_gate,
        "category": job.category,
        "target_column": job.target_column,
        "proposals": [],
        "user_choice": None,
        "insights": None,
        "eval_result": None,
        "best_model": None,
        "eda_summary": None,
        "output_paths": {},
    }

    def _read_state() -> dict | None:
        from orchestrator.graph import get_pipeline_graph

        graph = get_pipeline_graph()
        snap = graph.get_state({"configurable": {"thread_id": job_id}})
        vals = getattr(snap, "values", None)
        if vals is None:
            return None
        return vals if isinstance(vals, dict) else vals.to_dict()

    try:
        cur = await asyncio.to_thread(_read_state)
    except Exception as e:  # noqa: BLE001
        cur = None
        data["_state_error"] = str(e)

    if isinstance(cur, dict):
        gr = cur.get("gate_responses") or {}
        gate = cur.get("current_gate") or job.current_gate
        data["gate"] = gate
        if gate and isinstance(gr.get(gate), dict):
            data["proposals"] = gr[gate].get("proposals") or []
            data["user_choice"] = gr[gate].get("user_choice")
        for k in ("insights", "eval_result", "best_model", "eda_summary", "output_paths", "category", "target_column"):
            v = cur.get(k)
            if v is not None:
                data[k] = v

    try:
        rows = (await db.scalars(select(Output).where(Output.job_id == job.id))).all()
        if rows:
            data["output_paths"] = {o.output_code: o.minio_path for o in rows}
    except Exception:  # noqa: BLE001
        pass

    # 실시간 진행률/현재 에이전트 — runner.publish_progress 가 Redis 에 저장한 마지막 값
    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings as _settings

        rc = _redis.Redis.from_url(_settings.redis_url)
        raw = rc.get(f"ada:progress:{job_id}")
        if raw:
            pr = _json.loads(raw)
            data["current_agent"] = pr.get("agent")
            data["progress_pct"] = pr.get("progress")
            data["progress_ts"] = pr.get("ts")
    except Exception:  # noqa: BLE001
        pass

    return data

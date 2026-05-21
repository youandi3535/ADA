"""api.routes.pipeline — 파이프라인 라우터 (Day06).

POST /pipeline/start         → 새 job 시작
GET  /pipeline/status/{job}  → 진행 상황
POST /pipeline/resume/{job}  → 5게이트 응답 후 재개
GET  /pipeline/result/{job}  → 최종 결과
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.state import PipelineState
from ada.db.models import Job, Upload
from ada.db.session import get_db
from api.schemas.pipeline import (
    PipelineResumeRequest,
    PipelineStartRequest,
    PipelineStartResponse,
    PipelineStatusResponse,
)

router = APIRouter()


@router.post("/start", response_model=PipelineStartResponse)
async def start_pipeline(
    req: PipelineStartRequest, db: AsyncSession = Depends(get_db)
) -> PipelineStartResponse:
    upload = await db.scalar(select(Upload).where(Upload.file_id == req.file_id))
    if upload is None:
        raise HTTPException(404, detail="file_id not found")

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        file_id=req.file_id,
        category=req.category,
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
        category=req.category,
        target_column=req.target_column,
        user_question=req.user_question,
        user_intent=req.user_intent,
        requested_outputs=list(req.requested_outputs),
        max_retries=req.max_retries,
    )
    run_pipeline_task.apply_async(args=[str(job_id), state.to_dict()],
                                  queue="pipeline")

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
    prog = 100 if job.status == "completed" else (
        50 if job.status == "running" else 0
    )
    return PipelineStatusResponse(
        job_id=str(job.id),
        status=job.status,
        current_agent=None,
        current_gate=job.current_gate,
        progress_pct=prog,
        error=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        requested_outputs=job.requested_outputs or [],
    )


@router.post("/resume/{job_id}")
async def resume(job_id: str, req: PipelineResumeRequest,
                 db: AsyncSession = Depends(get_db)) -> dict:
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")
    from orchestrator.runner import resume_pipeline_task

    resume_pipeline_task.apply_async(
        args=[job_id, {"gate": req.gate, "choice": req.choice}], queue="pipeline",
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

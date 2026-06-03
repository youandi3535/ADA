"""api.routes.pipeline — 파이프라인 라우터 (Day06).

POST /pipeline/start         → 새 job 시작
GET  /pipeline/status/{job}  → 진행 상황
POST /pipeline/resume/{job}  → 5게이트 응답 후 재개
GET  /pipeline/result/{job}  → 최종 결과
GET  /pipeline/gate/{job}    → 현재 게이트 proposals + 실시간 진행률
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.core.state import PipelineState
from ada.db.models import Job, Output, Upload
from ada.db.session import get_db
from api.schemas.pipeline import (
    OutputItem,
    PipelineResultResponse,
    PipelineResumeRequest,
    PipelineStartRequest,
    PipelineStartResponse,
    PipelineStatusResponse,
)

log = get_logger("api.pipeline")


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------
def _key_from_minio_path(minio_path: str, bucket: str) -> str:
    """``s3://{bucket}/{key}`` → ``{key}``  (그 외 형식은 그대로 통과)."""
    if minio_path.startswith("s3://"):
        rest = minio_path[len("s3://") :]
        if rest.startswith(f"{bucket}/"):
            return rest[len(bucket) + 1 :]
        return rest.split("/", 1)[1] if "/" in rest else rest
    return minio_path


router = APIRouter()


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------
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


@router.get("/result/{job_id}", response_model=PipelineResultResponse)
async def result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    expiry: int = 3600,
) -> PipelineResultResponse:
    """파이프라인 결과 — Output 테이블 + MinIO presigned URL."""
    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")

    rows = (
        await db.scalars(select(Output).where(Output.job_id == uuid.UUID(job_id)).order_by(Output.created_at.asc()))
    ).all()

    items: list[OutputItem] = []

    mc = None
    if rows:
        try:
            from tools.minio_tool import get_minio_client

            mc = get_minio_client()
        except Exception as e:
            log.warning("minio_client_unavailable", error=str(e))

    for row in rows:
        key = _key_from_minio_path(row.minio_path, settings.minio_bucket)
        filename = Path(key).name or "(unnamed)"
        url: str | None = None
        if mc is not None:
            try:
                url = mc.get_presigned_url(key, expiry=expiry)
            except Exception as e:
                log.warning(
                    "presigned_url_failed",
                    output_code=row.output_code,
                    minio_path=row.minio_path,
                    error=str(e),
                )

        items.append(
            OutputItem(
                code=row.output_code,
                filename=filename,
                minio_path=row.minio_path,
                size_bytes=row.file_size_bytes,
                generation_ms=row.generation_ms,
                status=row.status or "completed",
                url=url,
                url_expires_in=expiry,
            )
        )

    return PipelineResultResponse(
        job_id=str(job.id),
        status=job.status,
        outputs=items,
        requested_outputs=list(job.requested_outputs or []),
    )


@router.get("/gate/{job_id}")
async def gate_detail(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """현재 게이트 proposals + 실시간 진행률/에이전트.

    runner._save_gate_data() 가 Redis 에 저장한 ada:gate_data:{job_id} 를 직접 읽어
    graph.get_state() 와 워커 전용 패키지(matplotlib 등) 없이 동작한다.
    """
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

    try:
        import json as _json2

        import redis as _redis2

        from ada.core.config import settings as _s2

        _rc2 = _redis2.Redis.from_url(_s2.redis_url)
        _raw_gate = _rc2.get(f"ada:gate_data:{job_id}")
        if _raw_gate:
            _gd = _json2.loads(_raw_gate)
            data["gate"] = _gd.get("gate") or job.current_gate
            data["proposals"] = _gd.get("proposals") or []
            for k in ("category", "target_column", "insights", "data_profile"):
                v = _gd.get(k)
                if v is not None:
                    data[k] = v
    except Exception:  # noqa: BLE001
        pass

    try:
        rows = (await db.scalars(select(Output).where(Output.job_id == job.id))).all()
        if rows:
            data["output_paths"] = {o.output_code: o.minio_path for o in rows}
    except Exception:  # noqa: BLE001
        pass

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
            if pr.get("status"):
                data["pipeline_status"] = pr.get("status")
            if pr.get("error"):
                data["pipeline_error"] = pr.get("error")
    except Exception:  # noqa: BLE001
        pass

    if job.status in ("failed", "completed") and not data.get("pipeline_status"):
        data["pipeline_status"] = job.status
        if job.status == "failed" and job.error_message:
            data["pipeline_error"] = job.error_message

    return data

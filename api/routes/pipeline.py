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

from pathlib import Path

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


# ----- 헬퍼: s3:// URI → MinIO Key 파싱 -----
def _key_from_minio_path(minio_path: str, bucket: str) -> str:
    """``s3://{bucket}/{key}`` → ``{key}``  (그 외 형식은 그대로 통과)."""
    if minio_path.startswith("s3://"):
        # s3://bucket/outputs/OUT-04/{job_id}/file.html
        rest = minio_path[len("s3://"):]
        # bucket/ 접두 제거
        if rest.startswith(f"{bucket}/"):
            return rest[len(bucket) + 1:]
        # 다른 버킷이면 첫 / 이후를 키로
        return rest.split("/", 1)[1] if "/" in rest else rest
    return minio_path

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


@router.get("/result/{job_id}", response_model=PipelineResultResponse)
async def result(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    expiry: int = 3600,
) -> PipelineResultResponse:
    """파이프라인 결과 — Output 테이블 + presigned URL.

    동작 원리
    ---------
    1) Job 조회 (없으면 404)
    2) Output 테이블에서 job_id 의 모든 산출물 행 SELECT
       (output_code, minio_path, file_size_bytes, generation_ms, status)
    3) 각 행의 minio_path 에서 Key 를 파싱해 ``get_presigned_url(key, expiry)`` 발급
       — MinIO 가 일시적인 공개 URL 을 만들어주므로 브라우저가 직접 받아갈 수 있음
       — 발급 자체는 서명 연산만이라 빠르고 부담 없음
    4) 응답 스키마 ``PipelineResultResponse`` 로 직렬화

    Notes
    -----
    - ``expiry`` 쿼리 파라미터로 만료시간 조절 가능 (기본 1h).
    - presigned URL 호스트는 ``settings.minio_endpoint`` 기준. 브라우저가 닿을 수
      있는 호스트여야 하므로 운영에서는 ``.env`` 의 ``MINIO_ENDPOINT`` 를
      외부 도메인(또는 nginx 경유 경로)으로 두는 것이 정석. 도커 내부망 이름
      (``minio:9000``) 그대로면 사용자 브라우저에서는 못 받음.
    """

    job = await db.scalar(select(Job).where(Job.id == uuid.UUID(job_id)))
    if job is None:
        raise HTTPException(404, detail="job not found")

    rows = (
        await db.scalars(
            select(Output).where(Output.job_id == uuid.UUID(job_id)).order_by(Output.created_at.asc())
        )
    ).all()

    items: list[OutputItem] = []

    # MinIO 클라이언트는 lazy import (테스트 환경에서 boto3 의존 회피)
    mc = None
    if rows:
        try:
            from tools.minio_tool import get_minio_client

            mc = get_minio_client()
        except Exception as e:
            log.warning("minio_client_unavailable", error=str(e))
            mc = None

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

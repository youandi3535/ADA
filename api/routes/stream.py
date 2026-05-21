"""api.routes.stream — SSE 진행률 / 결과 스트리밍 (Day13)."""
from __future__ import annotations

from fastapi import APIRouter

from api.middleware import make_sse_response

router = APIRouter()


@router.get("/progress/{job_id}")
async def progress(job_id: str):
    return make_sse_response(job_id)

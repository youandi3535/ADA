"""api.routes.stream — SSE 진행률 / 결과 스트리밍 (Day13)."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from api.middleware import make_sse_response

router = APIRouter()


@router.get(
    "/progress/{job_id}",
    # SSE 는 Pydantic 응답 모델을 가지지 않으므로 response_model 을 None 으로 명시.
    # response_class 로 swagger UI 에 streaming 응답임을 알린다.
    response_model=None,
    response_class=StreamingResponse,
    summary="파이프라인 진행률 SSE",
    description=(
        "Server-Sent Events 로 ada:pipeline:{job_id} Redis 채널을 스트리밍한다. "
        "각 이벤트는 publish_progress() 가 발행한 JSON. "
        "프론트는 EventSource API 로 구독한다."
    ),
)
async def progress(job_id: str) -> StreamingResponse:
    return make_sse_response(job_id)

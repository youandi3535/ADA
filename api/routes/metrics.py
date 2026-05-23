"""api.routes.metrics — Prometheus /metrics 엔드포인트 (Day 1).

Prometheus 스크레이프 타겟. CONTENT_TYPE_LATEST 으로 응답.
인증은 비활성 (네트워크 레벨에서 ingress 차단 권장).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from ada.observability.metrics import render_metrics

router = APIRouter()

try:
    from prometheus_client import CONTENT_TYPE_LATEST  # type: ignore
except Exception:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus exposition. 인증 없이 노출 (내부망 가정)."""
    body = render_metrics()
    return Response(content=body, media_type=CONTENT_TYPE_LATEST)

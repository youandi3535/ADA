"""api.routes.admin — Day 3 관리자 전용 라우터.

엔드포인트:
    GET /admin/audit                          최근 SecurityAuditLog 페이지네이션
    GET /admin/audit/summary                   event_type 별 카운트
    GET /admin/observability/langfuse          Langfuse 연결 헬스체크
    GET /admin/observability/prometheus_check  /metrics endpoint smoke check

모두 RBAC: admin 또는 service 역할만 허용.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.session import get_db
from ada.security.rbac import require_perm

router = APIRouter()

# 'admin' 권한 — RBAC 매트릭스에서 admin/service 만 허용
_admin_only = require_perm("admin.audit.read")


class AuditEntry(BaseModel):
    id: str
    event_type: str
    actor_user_id: Optional[str] = None
    actor_role: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    result: Optional[str] = None
    ip_address: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None


class AuditPage(BaseModel):
    items: list[AuditEntry]
    total: int
    page: int
    page_size: int


@router.get("/admin/audit", response_model=AuditPage, tags=["Admin"])
async def get_audit_log(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    event_type: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    result: Optional[str] = None,
    since_hours: Optional[int] = Query(None, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> AuditPage:
    """SecurityAuditLog 페이지네이션 — admin 전용."""
    from ada.db.models import SecurityAuditLog

    where_clauses = []
    if event_type:
        where_clauses.append(SecurityAuditLog.event_type == event_type)
    if result:
        where_clauses.append(SecurityAuditLog.result == result)
    if actor_user_id:
        where_clauses.append(SecurityAuditLog.actor_user_id == actor_user_id)
    if since_hours:
        where_clauses.append(SecurityAuditLog.created_at >= datetime.utcnow() - timedelta(hours=since_hours))

    base_q = select(SecurityAuditLog)
    if where_clauses:
        for c in where_clauses:
            base_q = base_q.where(c)

    # total count
    count_q = select(func.count()).select_from(base_q.subquery())
    total = int((await db.execute(count_q)).scalar() or 0)

    rows = (
        await db.scalars(
            base_q.order_by(desc(SecurityAuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items = [
        AuditEntry(
            id=str(r.id),
            event_type=r.event_type,
            actor_user_id=str(r.actor_user_id) if r.actor_user_id else None,
            actor_role=r.actor_role,
            resource=r.resource,
            action=r.action,
            result=r.result,
            ip_address=r.ip_address,
            details=r.details if isinstance(r.details, dict) else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return AuditPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/admin/audit/summary", tags=["Admin"])
async def get_audit_summary(
    since_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """event_type × result 별 누적 카운트 (최근 N 시간)."""
    from ada.db.models import SecurityAuditLog

    since = datetime.utcnow() - timedelta(hours=since_hours)
    rows = await db.execute(
        select(
            SecurityAuditLog.event_type,
            SecurityAuditLog.result,
            func.count().label("n"),
        )
        .where(SecurityAuditLog.created_at >= since)
        .group_by(SecurityAuditLog.event_type, SecurityAuditLog.result)
    )
    summary: dict[str, dict[str, int]] = {}
    for et, res, n in rows:
        summary.setdefault(et or "?", {})[res or "?"] = int(n)
    return {"since_hours": since_hours, "summary": summary}


@router.get("/admin/observability/langfuse", tags=["Admin"])
async def langfuse_health(_user: dict = Depends(_admin_only)) -> dict[str, Any]:
    """Day 3 — Langfuse 연결 헬스체크."""
    from ada.core.langfuse_client import verify_connection

    return verify_connection()


@router.get("/admin/observability/prometheus_check", tags=["Admin"])
async def prometheus_check(_user: dict = Depends(_admin_only)) -> dict[str, Any]:
    """Prometheus 메트릭 노출 smoke check."""
    from ada.observability.metrics import render_metrics

    body = render_metrics()
    text = body.decode("utf-8", errors="ignore")
    return {
        "available": "ada_agent_duration_seconds" in text or "ada_jobs_active" in text,
        "size_bytes": len(body),
        "sample_lines": text.splitlines()[:5],
    }

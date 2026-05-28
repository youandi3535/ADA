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


# =============================================================================
# ADR-007 L2 — ADR-006 Phase 2 audit 라우트 확장
# =============================================================================


class FailureLogEntry(BaseModel):
    id: str
    job_id: Optional[str] = None
    error_hash: str
    error_category: Optional[str] = None
    classified_as: Optional[str] = None
    severity: Optional[str] = None
    redaction_types: Optional[list[str]] = None
    auto_handled_by_kb: bool
    error_kb_id: Optional[str] = None
    error_message_redacted: Optional[str] = None
    created_at: Optional[str] = None


class FailureLogPage(BaseModel):
    items: list[FailureLogEntry]
    total: int
    page: int
    page_size: int


@router.get("/admin/autofix/failure_logs", response_model=FailureLogPage, tags=["Admin", "AutoFix"])
async def get_autofix_failure_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    classified_as: Optional[str] = Query(None, description="transient|code_bug|config|data|user_input|unknown"),
    severity: Optional[str] = Query(None, description="low|normal|high|critical"),
    auto_handled_by_kb: Optional[bool] = None,
    since_hours: Optional[int] = Query(None, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> FailureLogPage:
    """ADR-006 Phase 2-F — FailureLog 페이지네이션 + 분류 필터."""
    from ada.db.models import FailureLog

    where_clauses = []
    if classified_as:
        where_clauses.append(FailureLog.classified_as == classified_as)
    if severity:
        where_clauses.append(FailureLog.severity == severity)
    if auto_handled_by_kb is not None:
        where_clauses.append(FailureLog.auto_handled_by_kb == auto_handled_by_kb)
    if since_hours:
        where_clauses.append(FailureLog.created_at >= datetime.utcnow() - timedelta(hours=since_hours))

    base_q = select(FailureLog)
    for c in where_clauses:
        base_q = base_q.where(c)

    total = int((await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0)

    rows = (
        await db.scalars(base_q.order_by(desc(FailureLog.created_at)).offset((page - 1) * page_size).limit(page_size))
    ).all()

    items = [
        FailureLogEntry(
            id=str(r.id),
            job_id=str(r.job_id) if r.job_id else None,
            error_hash=r.error_hash,
            error_category=r.error_category,
            classified_as=r.classified_as,
            severity=r.severity,
            redaction_types=r.redaction_types if isinstance(r.redaction_types, list) else None,
            auto_handled_by_kb=bool(r.auto_handled_by_kb),
            error_kb_id=str(r.error_kb_id) if r.error_kb_id else None,
            error_message_redacted=(r.error_message or "")[:500] if r.error_message else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return FailureLogPage(items=items, total=total, page=page, page_size=page_size)


# ---------- patch_applications ----------


class PatchAppEntry(BaseModel):
    id: str
    pending_patch_id: Optional[str] = None
    error_kb_id: Optional[str] = None
    applied_by: Optional[str] = None
    applied_at: Optional[str] = None
    status: Optional[str] = None
    git_commit_sha: Optional[str] = None
    rollback_commit_sha: Optional[str] = None
    duration_ms: Optional[int] = None
    validation_passed: Optional[bool] = None
    tests_run: Optional[int] = None


class PatchAppPage(BaseModel):
    items: list[PatchAppEntry]
    total: int
    page: int
    page_size: int
    status_counts: dict[str, int]


@router.get("/admin/autofix/patch_applications", response_model=PatchAppPage, tags=["Admin", "AutoFix"])
async def get_patch_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None, description="success|rolled_back|failed"),
    applied_by: Optional[str] = None,
    since_hours: int = Query(24, ge=1, le=24 * 90),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> PatchAppPage:
    """ADR-006 Phase 2-F — 패치 적용 audit log."""
    from ada.db.models import PatchApplication

    since = datetime.utcnow() - timedelta(hours=since_hours)
    where = [PatchApplication.applied_at >= since]
    if status:
        where.append(PatchApplication.status == status)
    if applied_by:
        where.append(PatchApplication.applied_by == applied_by)

    base_q = select(PatchApplication)
    for c in where:
        base_q = base_q.where(c)

    total = int((await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar() or 0)

    # status 분포
    status_q = select(PatchApplication.status, func.count())
    for c in where:
        status_q = status_q.where(c)
    status_q = status_q.group_by(PatchApplication.status)
    status_rows = await db.execute(status_q)
    status_counts: dict[str, int] = {(s or "?"): int(n) for s, n in status_rows}

    rows = (
        await db.scalars(
            base_q.order_by(desc(PatchApplication.applied_at)).offset((page - 1) * page_size).limit(page_size)
        )
    ).all()

    items = []
    for r in rows:
        sv = r.sandbox_validation if isinstance(r.sandbox_validation, dict) else {}
        items.append(
            PatchAppEntry(
                id=str(r.id),
                pending_patch_id=str(r.pending_patch_id) if r.pending_patch_id else None,
                error_kb_id=str(r.error_kb_id) if r.error_kb_id else None,
                applied_by=r.applied_by,
                applied_at=r.applied_at.isoformat() if r.applied_at else None,
                status=r.status,
                git_commit_sha=r.git_commit_sha,
                rollback_commit_sha=r.rollback_commit_sha,
                duration_ms=r.duration_ms,
                validation_passed=sv.get("passed") if sv else None,
                tests_run=sv.get("tests_run") if sv else None,
            )
        )
    return PatchAppPage(items=items, total=total, page=page, page_size=page_size, status_counts=status_counts)


# ---------- circuit_breakers ----------


class BreakerState(BaseModel):
    name: str
    state: str
    failure_threshold: int
    recovery_timeout: int


class BreakerEventEntry(BaseModel):
    id: str
    breaker_name: str
    event_type: Optional[str] = None
    failure_count: Optional[int] = None
    opened_at: Optional[str] = None
    closed_at: Optional[str] = None
    created_at: Optional[str] = None


class BreakerStatusResponse(BaseModel):
    current_state: dict[str, BreakerState]
    recent_events: list[BreakerEventEntry]


@router.get(
    "/admin/autofix/circuit_breakers",
    response_model=BreakerStatusResponse,
    tags=["Admin", "AutoFix"],
)
async def get_circuit_breakers(
    event_limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> BreakerStatusResponse:
    """ADR-006 Phase 2-C — 회로 차단기 현재 상태 + 최근 이벤트."""
    from ada.db.models import CircuitBreakerEvent
    from ada.error_handler.circuit_breaker import get_breaker

    known_breakers = ["ollama", "claude_cli", "anthropic"]
    current_state: dict[str, BreakerState] = {}
    for name in known_breakers:
        cb = get_breaker(name)
        try:
            state_val = await cb.state()
        except Exception:
            state_val = "unknown"
        current_state[name] = BreakerState(
            name=name,
            state=state_val,
            failure_threshold=cb.failure_threshold,
            recovery_timeout=cb.recovery_timeout,
        )

    rows = (
        await db.scalars(select(CircuitBreakerEvent).order_by(desc(CircuitBreakerEvent.created_at)).limit(event_limit))
    ).all()
    recent = [
        BreakerEventEntry(
            id=str(r.id),
            breaker_name=r.breaker_name,
            event_type=r.event_type,
            failure_count=r.failure_count,
            opened_at=r.opened_at.isoformat() if r.opened_at else None,
            closed_at=r.closed_at.isoformat() if r.closed_at else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]

    return BreakerStatusResponse(current_state=current_state, recent_events=recent)


# ---------- budget ----------


class BudgetSnapshot(BaseModel):
    today_spend_usd: float
    today_calls: int
    daily_limit_usd: float
    remaining_usd: float
    is_exceeded: bool
    date_utc: str


@router.get("/admin/autofix/budget", response_model=BudgetSnapshot, tags=["Admin", "AutoFix"])
async def get_autofix_budget(_user: dict = Depends(_admin_only)) -> BudgetSnapshot:
    """ADR-006 Phase 2-D — 오늘 LLM 비용 누계."""
    from ada.error_handler.budget import get_budget_manager

    bm = get_budget_manager()
    spend = await bm.get_today_spend()
    calls = await bm.get_today_calls()
    limit = bm._daily_limit()
    remaining = await bm.remaining_budget()
    exceeded = await bm.is_exceeded()

    return BudgetSnapshot(
        today_spend_usd=round(spend, 4),
        today_calls=calls,
        daily_limit_usd=float(limit),
        remaining_usd=round(remaining, 4),
        is_exceeded=exceeded,
        date_utc=bm._today_key(),
    )

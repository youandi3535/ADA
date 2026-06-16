"""api.routes.admin — Day 3 관리자 전용 라우터.

엔드포인트:
    GET /admin/audit                          최근 SecurityAuditLog 페이지네이션
    GET /admin/audit/summary                   event_type 별 카운트
    GET /admin/observability/langfuse          Langfuse 연결 헬스체크
    GET /admin/observability/prometheus_check  /metrics endpoint smoke check
    GET /admin/autofix/failure_logs            Phase 2 failure_logs 페이지네이션
    GET /admin/autofix/patch_applications      패치 적용 status 집계
    GET /admin/autofix/circuit_breakers        회로 차단기 현재 상태 + 최근 이벤트
    GET /admin/autofix/budget                  오늘 LLM 예산 스냅샷

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
# ADR-008 L4 — PII 마스킹 통계
# =============================================================================


class PIIHourlyBucket(BaseModel):
    hour: str
    events: int
    tokens: int


class PIITopActor(BaseModel):
    actor_user_id: str
    events: int


class PIIStatsResponse(BaseModel):
    total_tokens_masked: int
    total_events: int
    by_hour: list[PIIHourlyBucket]
    top_actors: list[PIITopActor]
    since_hours: int


@router.get("/admin/security/pii", response_model=PIIStatsResponse, tags=["Admin", "Security"])
async def get_pii_stats(
    since_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> PIIStatsResponse:
    """ADR-008 L4 — SecurityAuditLog 의 pii_anonymized 이벤트 집계."""
    from sqlalchemy import desc, select

    from ada.db.models import SecurityAuditLog

    since = datetime.utcnow() - timedelta(hours=since_hours)

    rows = (
        await db.scalars(
            select(SecurityAuditLog)
            .where(SecurityAuditLog.action == "pii_anonymized")
            .where(SecurityAuditLog.created_at >= since)
            .order_by(desc(SecurityAuditLog.created_at))
        )
    ).all()

    total_tokens = 0
    total_events = 0
    by_hour: dict[str, dict[str, int]] = {}
    actor_count: dict[str, int] = {}

    for r in rows:
        total_events += 1
        n = (r.details or {}).get("n_tokens", 0) if isinstance(r.details, dict) else 0
        total_tokens += int(n)

        hour_key = r.created_at.strftime("%Y-%m-%dT%H") if r.created_at else "unknown"
        bucket = by_hour.setdefault(hour_key, {"events": 0, "tokens": 0})
        bucket["events"] += 1
        bucket["tokens"] += int(n)

        actor = str(r.actor_user_id) if r.actor_user_id else "anonymous"
        actor_count[actor] = actor_count.get(actor, 0) + 1

    return PIIStatsResponse(
        total_tokens_masked=total_tokens,
        total_events=total_events,
        by_hour=[PIIHourlyBucket(hour=h, events=v["events"], tokens=v["tokens"]) for h, v in sorted(by_hour.items())],
        top_actors=sorted(
            [PIITopActor(actor_user_id=a, events=c) for a, c in actor_count.items()],
            key=lambda x: x.events,
            reverse=True,
        )[:10],
        since_hours=since_hours,
    )


# =============================================================================
# ADR-006 Phase 2 — Autofix 운영 모니터링 라우트
# =============================================================================

_KNOWN_BREAKERS = ["ollama", "claude_cli", "anthropic"]


class FailureLogItem(BaseModel):
    id: str
    error_hash: Optional[str] = None
    classified_as: Optional[str] = None
    severity: Optional[str] = None
    created_at: Optional[str] = None


class FailureLogPage(BaseModel):
    items: list[FailureLogItem]
    total: int
    page: int
    page_size: int


@router.get("/admin/autofix/failure_logs", tags=["Admin"])
async def get_failure_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=500),
    classified_as: Optional[str] = None,
    severity: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> FailureLogPage:
    """Phase 2 failure_logs 페이지네이션 — admin 전용."""
    from ada.db.models import FailureLog

    base_q = select(FailureLog)
    if classified_as:
        base_q = base_q.where(FailureLog.classified_as == classified_as)
    if severity:
        base_q = base_q.where(FailureLog.severity == severity)

    count_q = select(func.count()).select_from(base_q.subquery())
    total = int((await db.execute(count_q)).scalar() or 0)

    rows = (
        await db.scalars(base_q.order_by(desc(FailureLog.created_at)).offset((page - 1) * page_size).limit(page_size))
    ).all()

    items = [
        FailureLogItem(
            id=str(r.id),
            error_hash=r.error_hash,
            classified_as=r.classified_as,
            severity=r.severity,
            created_at=r.created_at.isoformat() if r.created_at else None,
        )
        for r in rows
    ]
    return FailureLogPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/admin/autofix/patch_applications", tags=["Admin"])
async def get_patch_applications(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """patch_applications status 집계 — admin 전용."""
    from ada.db.models import PatchApplication

    result = await db.execute(
        select(PatchApplication.status, func.count().label("n")).group_by(PatchApplication.status)
    )
    status_counts: dict[str, int] = {}
    for row in result:
        status_counts[row[0] or "unknown"] = int(row[1])
    return {"total": sum(status_counts.values()), "status_counts": status_counts}


@router.get("/admin/autofix/circuit_breakers", tags=["Admin"])
async def get_circuit_breakers(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """회로 차단기 현재 상태 + 최근 이벤트 — admin 전용."""
    from ada.db.models import CircuitBreakerEvent
    from ada.error_handler.circuit_breaker import _InMemoryBackend

    current_state: dict[str, dict[str, Any]] = {}
    for name in _KNOWN_BREAKERS:
        state = await _InMemoryBackend.get_state(name)
        current_state[name] = {"state": state or "unknown"}

    recent_rows = (
        await db.scalars(select(CircuitBreakerEvent).order_by(desc(CircuitBreakerEvent.created_at)).limit(50))
    ).all()
    recent_events = [
        {
            "id": str(r.id),
            "breaker_name": r.breaker_name,
            "event_type": r.event_type,
            "failure_count": r.failure_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recent_rows
    ]
    return {"current_state": current_state, "recent_events": recent_events}


@router.get("/admin/autofix/budget", tags=["Admin"])
async def get_budget_snapshot(
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """오늘 LLM 예산 현황 스냅샷 — admin 전용."""
    from ada.error_handler.budget import get_budget_manager

    bm = get_budget_manager()
    today_spend = await bm.get_today_spend()
    today_calls = await bm.get_today_calls()
    daily_limit = bm._daily_limit()
    exceeded = await bm.is_exceeded()
    remaining = await bm.remaining_budget()

    return {
        "today_spend_usd": round(today_spend, 4),
        "today_calls": today_calls,
        "daily_limit_usd": daily_limit,
        "remaining_usd": round(remaining, 4),
        "is_exceeded": exceeded,
        "date_utc": datetime.utcnow().date().isoformat(),
    }


@router.get("/admin/metrics/dashboard", tags=["Admin"])
async def get_metrics_dashboard(
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """데이터 저장·활용 현황 집계 — admin 전용 (관리자 대시보드용)."""
    from ada.db.models import ConversationLog, FailureLog, SelfLearningKB

    failures_total = await db.scalar(select(func.count()).select_from(FailureLog)) or 0
    failures_auto = (
        await db.scalar(select(func.count()).select_from(FailureLog).where(FailureLog.auto_handled_by_kb.is_(True)))
        or 0
    )
    kb_total = await db.scalar(select(func.count()).select_from(SelfLearningKB)) or 0
    qa_total = await db.scalar(select(func.count()).select_from(ConversationLog)) or 0
    qa_processed = (
        await db.scalar(select(func.count()).select_from(ConversationLog).where(ConversationLog.processed.is_(True)))
        or 0
    )
    kb_by_type: dict[str, int] = {}
    for _row in (await db.execute(select(SelfLearningKB.kb_type, func.count()).group_by(SelfLearningKB.kb_type))).all():
        kb_by_type[str(_row[0])] = int(_row[1])

    return {
        "failures_total": int(failures_total),
        "failures_auto_handled": int(failures_auto),
        "auto_handle_rate": (round(int(failures_auto) / int(failures_total) * 100, 1) if failures_total else 0.0),
        "kb_total": int(kb_total),
        "kb_by_type": kb_by_type,
        "qa_total": int(qa_total),
        "qa_processed": int(qa_processed),
    }

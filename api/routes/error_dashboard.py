"""api.routes.error_dashboard — 오류 자동처리 & KB 모니터링 대시보드 API.

엔드포인트:
    GET  /errors/dashboard/summary        요약 통계 (카드 4개 + 시계열 + 파이차트 데이터)
    GET  /errors/dashboard/recent         최근 오류 목록 (N건)
    GET  /errors/dashboard/patches        패치 대기 목록
    PATCH /errors/dashboard/patches/{id}  패치 승인/거부
"""

from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.session import get_db
from ada.security.rbac import require_perm

router = APIRouter(prefix="/errors/dashboard", tags=["ErrorDashboard"])

# 관리자 전용 — admin/service 역할만 허용 (admin.py·observability.py 와 동일 패턴)
_admin_only = require_perm("admin.audit.read")


# =============================================================================
# GET /errors/dashboard/summary
# =============================================================================


@router.get("/summary")
async def get_error_summary(
    since_hours: int = Query(24, ge=1, le=24 * 30),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """오류 대시보드 요약 통계.

    반환:
        summary     — 카드 4개 (total / auto_resolved / pending_patches / kb_patterns)
        hourly_errors — 시간별 오류 건수 (line chart 용)
        by_category   — 오류 카테고리별 비율 (pie chart 용)
        kb_by_type    — KB 유형별 학습 현황 (bar chart 용)
    """
    from ada.db.models import ErrorKB, FailureLog, PendingPatch, SelfLearningKB

    since = datetime.utcnow() - timedelta(hours=since_hours)

    # ── 카드 4개 ──────────────────────────────────────────────────
    total_errors = int((await db.scalar(select(func.count(FailureLog.id)))) or 0)
    auto_resolved = int(
        (await db.scalar(select(func.count(FailureLog.id)).where(FailureLog.auto_handled_by_kb.is_(True)))) or 0
    )
    pending_patches = int(
        (await db.scalar(select(func.count(PendingPatch.id)).where(PendingPatch.review_status == "pending"))) or 0
    )
    kb_patterns = int((await db.scalar(select(func.count(ErrorKB.id)))) or 0)

    # ── 시간별 오류 (line chart) ──────────────────────────────────
    # text('hour') 로 리터럴 처리 → asyncpg 파라미터 바인딩 충돌 방지
    _hour = func.date_trunc(text("'hour'"), FailureLog.created_at)
    hourly_rows = await db.execute(
        select(
            _hour.label("hour"),
            func.count().label("n"),
        )
        .where(FailureLog.created_at >= since)
        .group_by(_hour)
        .order_by(_hour)
    )
    hourly = [{"hour": str(r.hour), "count": int(r.n)} for r in hourly_rows]

    # ── 오류 카테고리별 (pie chart) ───────────────────────────────
    cat_rows = await db.execute(
        select(
            FailureLog.error_category,
            func.count().label("n"),
        ).group_by(FailureLog.error_category)
    )
    by_category = [{"category": r.error_category or "unknown", "count": int(r.n)} for r in cat_rows]

    # ── KB 유형별 학습 현황 (bar chart) ──────────────────────────
    kb_rows = await db.execute(
        select(
            SelfLearningKB.kb_type,
            func.count().label("n"),
        ).group_by(SelfLearningKB.kb_type)
    )
    kb_by_type = [{"kb_type": r.kb_type or "unknown", "count": int(r.n)} for r in kb_rows]

    # ── ErrorKB 신뢰도 분포 (상위 10) ────────────────────────────
    ekb_rows = await db.execute(
        select(
            ErrorKB.error_signature,
            ErrorKB.success_count,
            ErrorKB.fail_count,
            ErrorKB.confidence,
        )
        .order_by(desc(ErrorKB.success_count))
        .limit(10)
    )
    top_kb = [
        {
            "signature": (r.error_signature or "")[:80],
            "success_count": int(r.success_count or 0),
            "fail_count": int(r.fail_count or 0),
            "confidence": round(float(r.confidence or 0.0), 3),
        }
        for r in ekb_rows
    ]

    return {
        "since_hours": since_hours,
        "summary": {
            "total_errors": total_errors,
            "auto_resolved": auto_resolved,
            "pending_patches": pending_patches,
            "kb_patterns": kb_patterns,
            "auto_resolve_rate": round(auto_resolved / total_errors, 3) if total_errors else 0.0,
        },
        "hourly_errors": hourly,
        "by_category": by_category,
        "kb_by_type": kb_by_type,
        "top_kb": top_kb,
    }


# =============================================================================
# GET /errors/dashboard/recent
# =============================================================================


@router.get("/recent")
async def get_recent_errors(
    limit: int = Query(20, ge=1, le=200),
    only_unhandled: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """최근 오류 목록.

    only_unhandled=true 이면 auto_handled_by_kb=False 만 반환.
    """
    from ada.db.models import FailureLog

    q = select(FailureLog).order_by(desc(FailureLog.created_at)).limit(limit)
    if only_unhandled:
        q = q.where(FailureLog.auto_handled_by_kb.is_(False))

    rows = (await db.scalars(q)).all()

    items = [
        {
            "id": str(r.id),
            "job_id": str(r.job_id) if r.job_id else None,
            "error_category": r.error_category or "unknown",
            "error_message": (r.error_message or "")[:200],
            "auto_handled": bool(r.auto_handled_by_kb),
            "has_kb_match": r.error_kb_id is not None,
            "severity": _calc_severity(r),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}


def _calc_severity(row: Any) -> str:
    """오류 심각도 분류.

    CRITICAL : KB 매칭 없음 + 자동해결 실패
    HIGH     : 패치 대기 중
    MEDIUM   : KB 매칭됐으나 자동처리 실패
    INFO     : 자동처리 완료
    """
    if row.auto_handled_by_kb:
        return "INFO"
    if row.error_kb_id:
        return "MEDIUM"
    return "CRITICAL"


# =============================================================================
# GET /errors/dashboard/patches
# =============================================================================


@router.get("/patches")
async def get_patches(
    status: Optional[str] = Query(None, description="pending | approved | rejected"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """패치 목록 (기본: 전체, status 필터 가능)."""
    from ada.db.models import PendingPatch

    q = select(PendingPatch).order_by(desc(PendingPatch.created_at)).limit(limit)
    if status:
        q = q.where(PendingPatch.review_status == status)

    rows = (await db.scalars(q)).all()

    items = [
        {
            "id": str(r.id),
            "error_kb_id": str(r.error_kb_id) if r.error_kb_id else None,
            "confidence": round(float(r.confidence or 0.0), 3),
            "review_status": r.review_status or "pending",
            "reviewer": r.reviewer,
            "patch_preview": (r.patch_diff or "")[:300],
            "test_plan": (r.test_plan or "")[:200],
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"items": items, "total": len(items)}


# =============================================================================
# PATCH /errors/dashboard/patches/{patch_id}
# =============================================================================


class PatchAction(BaseModel):
    action: str  # "approve" | "reject"
    reviewer: str = "dashboard"


@router.patch("/patches/{patch_id}")
async def update_patch_status(
    patch_id: str,
    body: PatchAction,
    db: AsyncSession = Depends(get_db),
    _user: dict = Depends(_admin_only),
) -> dict[str, Any]:
    """패치 승인(approve) 또는 거부(reject)."""
    from ada.db.models import PendingPatch

    if body.action not in ("approve", "reject"):
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")

    try:
        pid = _uuid.UUID(patch_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid patch_id format")

    row = await db.scalar(select(PendingPatch).where(PendingPatch.id == pid))
    if not row:
        raise HTTPException(status_code=404, detail="patch not found")

    row.review_status = "approved" if body.action == "approve" else "rejected"
    row.reviewer = body.reviewer
    await db.commit()

    return {"id": patch_id, "review_status": row.review_status, "reviewer": row.reviewer}

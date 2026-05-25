"""api.routes.conversation_kb — 팀 Q&A 수집 & 조회 API.

엔드포인트:
    POST  /kb/conversation              Q&A 1쌍 수신 (Stop 훅 → 웹서버)
    GET   /kb/conversation/unprocessed  미처리 Q&A 목록 (리눅스 서버 동기화용)
    PATCH /kb/conversation/{id}/done    처리 완료 표시 (리눅스 서버 → 웹서버)
    GET   /kb/conversation/stats        수집 현황 통계

인증:
    X-KB-Secret 헤더 — .env 의 KB_COLLECT_SECRET 값과 일치해야 함
    (JWT 없이 내부망 API 키 방식, 팀원 전체 공유)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.db.session import get_db

router = APIRouter(prefix="/kb/conversation", tags=["ConversationKB"])


# =============================================================================
# 인증 — X-KB-Secret 헤더 (경량 API 키)
# =============================================================================


def _verify_secret(x_kb_secret: str = Header(default="")) -> None:
    """KB_COLLECT_SECRET 환경변수와 비교. 미설정이면 개발 모드로 통과."""
    expected = getattr(settings, "kb_collect_secret", "") or ""
    if not expected:
        return  # .env 에 KB_COLLECT_SECRET 없으면 개발 모드 허용
    if x_kb_secret != expected:
        raise HTTPException(status_code=401, detail="invalid KB secret")


# =============================================================================
# 스키마
# =============================================================================


class ConversationIn(BaseModel):
    """Stop 훅 스크립트가 전송하는 Q&A 1쌍."""

    question: str = Field(min_length=2, max_length=10_000)
    answer: str = Field(min_length=2, max_length=50_000)
    team_member: Optional[str] = Field(default=None, max_length=128)
    session_id: Optional[str] = Field(default=None, max_length=64)
    project: Optional[str] = Field(default=None, max_length=255)
    source: str = Field(default="claude_code", max_length=32)


class ConversationOut(BaseModel):
    id: str
    team_member: Optional[str]
    question: str
    answer: str
    session_id: Optional[str]
    project: Optional[str]
    source: str
    processed: bool
    created_at: Optional[str]


class ProcessedIn(BaseModel):
    kb_id: Optional[str] = None  # 연결된 SelfLearningKB id (옵션)


# =============================================================================
# POST /kb/conversation  — Q&A 수신
# =============================================================================


@router.post("", status_code=201)
async def submit_conversation(
    body: ConversationIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """VS Code Stop 훅 → 웹서버: Q&A 1쌍 저장."""
    from ada.db.models import ConversationLog

    row = ConversationLog(
        id=uuid.uuid4(),
        team_member=body.team_member,
        question=body.question,
        answer=body.answer,
        session_id=body.session_id,
        project=body.project,
        source=body.source,
        processed=False,
    )
    db.add(row)
    await db.commit()

    return {"id": str(row.id), "status": "saved"}


# =============================================================================
# GET /kb/conversation/unprocessed  — 리눅스 서버 동기화용
# =============================================================================


@router.get("/unprocessed")
async def get_unprocessed(
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """임베딩 미완료 Q&A 목록 — 리눅스 서버가 3회/일 호출."""
    from ada.db.models import ConversationLog

    rows = (
        await db.scalars(
            select(ConversationLog)
            .where(ConversationLog.processed.is_(False))
            .order_by(ConversationLog.created_at.asc())
            .limit(limit)
        )
    ).all()

    return {
        "items": [
            {
                "id": str(r.id),
                "team_member": r.team_member,
                "question": r.question,
                "answer": r.answer,
                "session_id": r.session_id,
                "project": r.project,
                "source": r.source,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": len(rows),
    }


# =============================================================================
# PATCH /kb/conversation/{id}/done  — 처리 완료 표시
# =============================================================================


@router.patch("/{conv_id}/done")
async def mark_processed(
    conv_id: str,
    body: ProcessedIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """리눅스 서버가 임베딩 완료 후 호출 → processed=True 표시."""
    from ada.db.models import ConversationLog

    try:
        cid = uuid.UUID(conv_id)
    except ValueError:
        raise HTTPException(400, detail="invalid conv_id")

    row = await db.scalar(select(ConversationLog).where(ConversationLog.id == cid))
    if not row:
        raise HTTPException(404, detail="conversation not found")

    row.processed = True
    if body.kb_id:
        try:
            row.kb_id = uuid.UUID(body.kb_id)
        except ValueError:
            pass

    await db.commit()
    return {"id": conv_id, "processed": True}


# =============================================================================
# GET /kb/conversation/stats  — 수집 현황 통계
# =============================================================================


@router.get("/stats")
async def get_stats(
    since_days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """수집 현황 통계 — 대시보드용."""
    from ada.db.models import ConversationLog

    since = datetime.utcnow() - timedelta(days=since_days)

    total = int((await db.scalar(select(func.count(ConversationLog.id)))) or 0)
    pending = int(
        (await db.scalar(select(func.count(ConversationLog.id)).where(ConversationLog.processed.is_(False)))) or 0
    )
    recent = int(
        (await db.scalar(select(func.count(ConversationLog.id)).where(ConversationLog.created_at >= since))) or 0
    )

    # 팀원별 기여 건수
    member_rows = await db.execute(
        select(ConversationLog.team_member, func.count().label("n"))
        .where(ConversationLog.created_at >= since)
        .group_by(ConversationLog.team_member)
        .order_by(desc(func.count()))
    )
    by_member = [{"team_member": r.team_member or "unknown", "count": int(r.n)} for r in member_rows]

    return {
        "since_days": since_days,
        "total_collected": total,
        "pending_embed": pending,
        "recent_collected": recent,
        "by_member": by_member,
    }

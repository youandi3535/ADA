"""api.routes.conversation_kb — 팀 Q&A 수집 & 자동 학습 루프.

자동 학습 루프 (이 파일의 핵심):
┌─────────────────────────────────────────────────────────────────┐
│  VS Code 질문 → KB 미스 → Ollama 미스 → Claude 답변             │
│       │                                                         │
│       ▼ (Stop 훅 자동 실행)                                      │
│  POST /kb/conversation                                          │
│       │                                                         │
│  ① conversation_log 저장 (processed=False)   ← 즉시 응답        │
│       │                                                         │
│  ② BackgroundTask: _embed_and_index_conv()   ← 응답 후 비동기   │
│       ├─ SentenceTransformer 임베딩 생성 (768-d)                 │
│       ├─ self_learning_kb INSERT (kb_type='qa_pair')             │
│       │   ON CONFLICT(hash) DO NOTHING  ← 중복 방지             │
│       └─ conversation_log.processed=True, kb_id 연결            │
│                                                                 │
│  ③ 다음 유사 질문 → pgvector 코사인 유사도 ≥ 0.82               │
│       → **[팀 KB 답변]**  (Claude 답변이 KB로 자동 승격)         │
└─────────────────────────────────────────────────────────────────┘

엔드포인트:
    POST  /kb/conversation              Q&A 1쌍 수신 → 즉시 임베딩 & KB 인덱싱
    GET   /kb/conversation/unprocessed  미처리 Q&A 목록 (수동 재처리·모니터링용)
    PATCH /kb/conversation/{id}/done    처리 완료 표시 (외부 스크립트 재처리용)
    GET   /kb/conversation/stats        수집 현황 통계

인증:
    X-KB-Secret 헤더 — .env 의 KB_COLLECT_SECRET 값과 일치해야 함
    (JWT 없이 내부망 API 키 방식, 팀원 전체 공유)
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.db.session import get_db

router = APIRouter(prefix="/kb/conversation", tags=["ConversationKB"])
log = get_logger("conversation_kb")


# =============================================================================
# 인증
# =============================================================================


def _verify_secret(x_kb_secret: str = Header(default="")) -> None:
    """KB_COLLECT_SECRET 환경변수와 비교. 미설정이면 개발 모드로 통과."""
    expected = getattr(settings, "kb_collect_secret", "") or ""
    if not expected:
        return
    if x_kb_secret != expected:
        raise HTTPException(status_code=401, detail="invalid KB secret")


# =============================================================================
# 임베딩 (지연 초기화 싱글턴 — kb_search 와 동일 모델, 동일 프로세스 내 공유)
# =============================================================================

_embedder = None


def _get_embedder():
    global _embedder  # noqa: PLW0603
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            _embedder = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
        except Exception:  # noqa: BLE001
            return None
    return _embedder


def _embed(question: str) -> list[float] | None:
    model = _get_embedder()
    if model is None:
        return None
    vec = model.encode(question, normalize_embeddings=True)
    return vec.tolist()


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
    kb_id: Optional[str] = None


# =============================================================================
# 자동 학습 백그라운드 태스크
# =============================================================================


async def _embed_and_index_conv(
    conv_id: str,
    question: str,
    answer: str,
    team_member: str | None,
    project: str | None,
    source: str,
) -> None:
    """conversation_log → self_learning_kb (qa_pair) 자동 임베딩 & 인덱싱.

    - 동일 질문 중복 방지: question SHA256 hash 기준 ON CONFLICT DO NOTHING
    - 임베딩 실패 시 conversation_log.processed 는 False 로 유지
      → /kb/conversation/unprocessed 로 수동 재처리 가능
    """
    import asyncio

    # ── 1. 임베딩 생성 (CPU-bound → thread pool) ───────────────────────
    try:
        embedding: list[float] | None = await asyncio.to_thread(_embed, question)
    except Exception as e:  # noqa: BLE001
        log.warning("embed_failed", conv_id=conv_id, error=str(e))
        return

    if embedding is None:
        log.warning("embed_skipped_no_embedder", conv_id=conv_id)
        return

    # ── 2. pgvector 문자열 변환 ────────────────────────────────────────
    emb_str = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"

    # ── 3. 중복 방지 hash (질문 원문 SHA256) ──────────────────────────
    q_hash = hashlib.sha256(question.strip().encode("utf-8")).hexdigest()

    # ── 4. DB 작업 (새 세션 — 요청 세션과 독립) ───────────────────────
    try:
        from ada.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            # self_learning_kb INSERT (중복 시 무시)
            new_kb_id = str(uuid.uuid4())
            result = await session.execute(
                text(
                    """
                    INSERT INTO self_learning_kb
                        (id, kb_type, hash, payload, embedding,
                         confidence, success_count, created_at, updated_at)
                    VALUES (
                        CAST(:id AS uuid),
                        'qa_pair',
                        :hash,
                        CAST(:payload AS jsonb),
                        CAST(:emb AS vector),
                        0.8,
                        1,
                        NOW(),
                        NOW()
                    )
                    ON CONFLICT (hash) DO NOTHING
                    RETURNING id
                    """
                ).bindparams(
                    id=new_kb_id,
                    hash=q_hash,
                    payload=json.dumps(
                        {
                            "question": question,
                            "answer": answer,
                            "team_member": team_member,
                            "project": project,
                            "source": source,
                        },
                        ensure_ascii=False,
                    ),
                    emb=emb_str,
                )
            )
            inserted = result.fetchone()

            # 실제로 삽입된 ID (중복 시 None → 기존 row 의 id 조회)
            if inserted:
                kb_id = str(inserted[0])
                log.info(
                    "kb_qa_indexed",
                    conv_id=conv_id,
                    kb_id=kb_id,
                    team_member=team_member,
                    project=project,
                )
            else:
                # 동일 질문 중복 → 기존 kb_id 조회
                existing = await session.execute(
                    text("SELECT id FROM self_learning_kb WHERE hash=:hash AND kb_type='qa_pair'").bindparams(
                        hash=q_hash
                    )
                )
                row = existing.fetchone()
                kb_id = str(row[0]) if row else None
                log.info("kb_qa_duplicate", conv_id=conv_id, kb_id=kb_id)

            # conversation_log.processed=True, kb_id 연결
            await session.execute(
                text(
                    """
                    UPDATE conversation_logs
                    SET processed = TRUE,
                        kb_id     = CAST(:kb_id AS uuid)
                    WHERE id = CAST(:conv_id AS uuid)
                    """
                ).bindparams(kb_id=kb_id, conv_id=conv_id)
            )
            await session.commit()

    except Exception as e:  # noqa: BLE001
        log.warning("embed_and_index_failed", conv_id=conv_id, error=str(e))


# =============================================================================
# POST /kb/conversation  — Q&A 수신 + 즉시 임베딩 트리거
# =============================================================================


@router.post("", status_code=201)
async def submit_conversation(
    body: ConversationIn,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """VS Code Stop 훅 → Q&A 저장 + 백그라운드 임베딩 & KB 인덱싱.

    응답은 즉시 반환 (Stop 훅 블로킹 최소화).
    임베딩·인덱싱은 응답 후 비동기 실행.
    """
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

    # 응답 후 비동기로 임베딩 & self_learning_kb 인덱싱
    background_tasks.add_task(
        _embed_and_index_conv,
        str(row.id),
        body.question,
        body.answer,
        body.team_member,
        body.project,
        body.source,
    )

    return {"id": str(row.id), "status": "saved"}


# =============================================================================
# GET /kb/conversation/unprocessed  — 수동 재처리·모니터링용
# =============================================================================


@router.get("/unprocessed")
async def get_unprocessed(
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """임베딩 미완료 Q&A 목록.

    자동 루프 실패 시 수동 재처리 또는 모니터링에 사용.
    정상 운영 중에는 이 목록이 비어 있어야 함.
    """
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
# PATCH /kb/conversation/{id}/done  — 외부 스크립트 재처리용
# =============================================================================


@router.patch("/{conv_id}/done")
async def mark_processed(
    conv_id: str,
    body: ProcessedIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """수동 재처리 완료 표시 (자동 루프 실패 복구용)."""
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
# GET /kb/conversation/stats  — 수집·학습 현황 통계
# =============================================================================


@router.get("/stats")
async def get_stats(
    since_days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """수집 현황 통계 — 학습 루프 모니터링용."""
    from ada.db.models import ConversationLog

    since = datetime.utcnow() - timedelta(days=since_days)

    total = int((await db.scalar(select(func.count(ConversationLog.id)))) or 0)
    pending = int(
        (await db.scalar(select(func.count(ConversationLog.id)).where(ConversationLog.processed.is_(False)))) or 0
    )
    recent = int(
        (await db.scalar(select(func.count(ConversationLog.id)).where(ConversationLog.created_at >= since))) or 0
    )

    member_rows = await db.execute(
        select(ConversationLog.team_member, func.count().label("n"))
        .where(ConversationLog.created_at >= since)
        .group_by(ConversationLog.team_member)
        .order_by(desc(func.count()))
    )
    by_member = [{"team_member": r.team_member or "unknown", "count": int(r.n)} for r in member_rows]

    # KB 인덱싱 성공률
    indexed = total - pending
    index_rate = round(indexed / total * 100, 1) if total > 0 else 0.0

    return {
        "since_days": since_days,
        "total_collected": total,
        "pending_embed": pending,
        "indexed": indexed,
        "index_rate_pct": index_rate,
        "recent_collected": recent,
        "by_member": by_member,
    }

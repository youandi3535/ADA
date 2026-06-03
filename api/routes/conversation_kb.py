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
import re
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

# KB 저장 최소 품질 점수 (0.0~1.0). 이 값 미만은 임베딩·인덱싱 건너뜀.
_MIN_QUALITY_SCORE = 0.45


# =============================================================================
# 품질 게이트 — 오답/거부/빈 답변이 KB에 쌓이는 것 방지
# =============================================================================

# 거부·실패 패턴 (이 패턴이 포함된 답변은 KB에 저장하지 않음)
_REFUSAL_PATTERNS = [
    re.compile(r"죄송(합니다|해요|해서)", re.I),
    re.compile(r"(잘\s*모르|알\s*수\s*없|답\s*변\s*할\s*수\s*없)", re.I),
    re.compile(r"I\s+(don'?t\s+know|can'?t|cannot|am\s+not\s+able)", re.I),
    re.compile(r"(I'?m\s+sorry|I\s+apologize)", re.I),
    re.compile(r"\((오류|에러|Error).*(발생|occurred)\)", re.I),
    re.compile(r"\(Claude\s+응답\s+없음\)", re.I),
    re.compile(r"\(Ollama\s+응답\s+없음\)", re.I),
    re.compile(r"폴백\s+실패", re.I),
    re.compile(r"모든\s+폴백\s+비활성화", re.I),
]


def _quality_score(question: str, answer: str) -> float:
    """답변 품질 점수 (0.0~1.0).

    판단 기준:
      - 너무 짧은 답변 패널티
      - 거부/실패 패턴 → 즉시 낮은 점수
      - 코드 블록·구체적 내용 포함 시 보너스
    """
    score = 1.0

    # 1. 길이 기반
    ans_len = len(answer.strip())
    if ans_len < 30:
        score *= 0.2
    elif ans_len < 80:
        score *= 0.6
    elif ans_len < 150:
        score *= 0.85

    # 2. 거부/실패 패턴
    for pat in _REFUSAL_PATTERNS:
        if pat.search(answer):
            score *= 0.15
            break

    # 3. 구체적 내용 보너스
    if "```" in answer:
        score = min(1.0, score * 1.25)  # 코드 블록
    elif any(kw in answer for kw in ("def ", "class ", "import ", "return ", "async ")):
        score = min(1.0, score * 1.10)  # 코드 키워드

    return round(score, 3)


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
# 임베딩 — kb_search 의 싱글턴을 공유 (이중 초기화 방지)
# =============================================================================


def _embed(question: str) -> list[float] | None:
    """kb_search 모듈의 _embed 를 위임 — 동일 프로세스 내 싱글턴 모델 공유."""
    try:
        from api.routes.kb_search import _embed as _kb_embed  # noqa: PLC0415

        return _kb_embed(question)
    except Exception:  # noqa: BLE001
        return None


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


# Day24 — 팀원 자동수정 사례 누적용 스키마
class ErrorFixIn(BaseModel):
    """팀원이 Claude Code / Cowork 에서 해결한 에러 사례 1건.

    Stop 훅 / VS Code extension 이 에러 + 수정 diff 를 추출해 전송한다.
    수신되면 즉시 SelfLearningKB.failure_lesson 으로 적재 + 임베딩 색인 →
    이후 동일 / 유사 에러는 ada-serving 의 Tier 1.5 에서 자동 재사용.
    """

    error_signature: str = Field(min_length=4, max_length=2_000)
    # 호출자가 fingerprint hash 를 모르면 stack_top 만 보내고 서버가 계산
    error_hash: Optional[str] = Field(default=None, max_length=64)
    stack_top: Optional[str] = Field(default=None, max_length=4_000)
    fix_diff: str = Field(min_length=10, max_length=20_000)
    explanation: Optional[str] = Field(default=None, max_length=1_000)
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    team_member: Optional[str] = Field(default=None, max_length=128)
    session_id: Optional[str] = Field(default=None, max_length=64)
    project: Optional[str] = Field(default=None, max_length=255)
    source: str = Field(default="team_manual", max_length=32)


class ErrorFixOut(BaseModel):
    kb_id: Optional[str]
    error_hash: str
    status: str  # "recorded" | "duplicate_updated" | "rejected"
    reason: Optional[str] = None


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

    # ── 0. 품질 게이트 — 오답/거부/빈 답변 KB 저장 방지 ──────────────────
    q_score = _quality_score(question, answer)
    if q_score < _MIN_QUALITY_SCORE:
        log.info(
            "kb_skipped_low_quality",
            conv_id=conv_id,
            quality_score=q_score,
            answer_preview=answer[:80],
        )
        return

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
        import traceback as _tb

        log.warning("embed_and_index_failed", conv_id=conv_id, error=str(e))
        try:
            from ada.error_handler.auto_handler import capture_and_handle

            await capture_and_handle(
                error_message=f"embed_and_index_conv: {e}",
                stack_trace=_tb.format_exc(),
                source="api_background",
            )
        except Exception:  # noqa: BLE001
            pass


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


# =============================================================================
# POST /kb/conversation/error_fix  — Day24 팀원 자동수정 사례 수집
# =============================================================================


@router.post("/error_fix", status_code=201, response_model=ErrorFixOut)
async def submit_error_fix(
    body: ErrorFixIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """팀원이 Claude Code / Cowork 에서 해결한 에러 + 수정 diff 누적 학습 진입점.

    동작:
        1) error_hash 가 없으면 (signature + stack_top) 기반 SHA256 계산
        2) SelfLearningKB.failure_lesson 으로 적재 (ON CONFLICT(hash) DO UPDATE)
        3) 임베딩 자동 색인 (lesson_embeddings) — 이후 Tier 1.5 시맨틱 매칭에서 즉시 활용
        4) 결과 반환

    이 엔드포인트로 들어온 사례는 ada-serving 의 auto_handler.Tier 1.5 에서
    추후 동일/유사 에러 발생 시 자동 재사용된다 (LLM 비용 0).
    """
    from agents.self_learning import record_error_fix, stable_hash_for_signature

    # hash 계산 (호출자가 안 보낸 경우)
    error_hash = (body.error_hash or "").strip()
    if not error_hash:
        error_hash = stable_hash_for_signature(body.error_signature, body.stack_top or "")

    # 품질 게이트 — diff 가 단순 공백 / 미니 패치가 아닌지 검사
    diff_lines = [ln for ln in body.fix_diff.splitlines() if ln.strip()]
    has_hunk = any(ln.startswith(("--- ", "+++ ", "@@")) for ln in diff_lines)
    if not has_hunk:
        log.info(
            "error_fix_rejected_no_hunk",
            team_member=body.team_member,
            error_hash=error_hash[:16],
        )
        return {
            "kb_id": None,
            "error_hash": error_hash,
            "status": "rejected",
            "reason": "diff_missing_hunk_headers",
        }

    # 적재
    kb_id = await record_error_fix(
        db,
        error_hash=error_hash,
        error_signature=body.error_signature,
        fix_diff=body.fix_diff,
        source=body.source or "team_manual",
        confidence=body.confidence,
        explanation=body.explanation or "",
        team_member=body.team_member,
        project=body.project,
        extra={"session_id": body.session_id} if body.session_id else None,
    )

    await db.commit()

    if kb_id is None:
        return {
            "kb_id": None,
            "error_hash": error_hash,
            "status": "rejected",
            "reason": "record_failed",
        }

    log.info(
        "error_fix_team_recorded",
        kb_id=kb_id,
        team_member=body.team_member,
        project=body.project,
        source=body.source,
    )
    return {
        "kb_id": kb_id,
        "error_hash": error_hash,
        "status": "recorded",
        "reason": None,
    }


# =============================================================================
# GET /kb/conversation/failure_lessons  — Day24 크로스팀 동기화용 dump
# =============================================================================


@router.get("/failure_lessons")
async def list_failure_lessons(
    since: Optional[str] = Query(default=None, description="ISO timestamp (updated_at >= since)"),
    limit: int = Query(default=200, ge=1, le=2000),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """SelfLearningKB.failure_lesson dump endpoint for cross-team sync.

    팀원의 linux_kb_sync.py (--pull-failure-lessons) 가 주기적으로 호출.
    Returns: {"items": [{kb_id, error_hash, payload, confidence, success_count,
              created_at, updated_at}, ...], "total": N}
    """
    sql = (
        "SELECT id::text AS kb_id, hash AS error_hash, payload, "
        "       confidence, success_count, "
        "       created_at, updated_at "
        "FROM self_learning_kb "
        "WHERE kb_type = 'failure_lesson' "
    )
    params: dict[str, Any] = {"limit": limit}
    if since:
        sql += " AND updated_at >= CAST(:since AS timestamptz) "
        params["since"] = since
    sql += " ORDER BY updated_at DESC LIMIT :limit"

    rows = (await db.execute(text(sql).bindparams(**params))).mappings().all()
    items = []
    for r in rows:
        items.append(
            {
                "kb_id": r["kb_id"],
                "error_hash": r["error_hash"],
                "payload": r["payload"],
                "confidence": float(r["confidence"]) if r["confidence"] is not None else 0.0,
                "success_count": int(r["success_count"] or 0),
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None,
            }
        )

    return {"items": items, "total": len(items), "since": since}

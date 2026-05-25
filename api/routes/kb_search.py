"""api.routes.kb_search — 팀 Q&A 지식 검색 라우터 (1순위 KB, 2순위 Claude).

엔드포인트:
    POST /kb/search     질문 입력 → KB 검색 후 답변 반환 (또는 Claude 폴백)
    GET  /kb/search/health  KB 상태 확인

동작 흐름:
    1. 질문 텍스트 임베딩 (paraphrase-multilingual-mpnet-base-v2)
    2. self_learning_kb WHERE kb_type='qa_pair' 에서 코사인 유사도 검색
    3. 유사도 >= threshold (기본 0.82) → KB 답변 반환 + 출처 표시
    4. 미달 시 → Claude API 호출 (폴백)

인증:
    X-KB-Secret 헤더 (conversation_kb 와 동일 키)
"""

from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.db.session import get_db

router = APIRouter(prefix="/kb/search", tags=["KBSearch"])

# 코사인 유사도 기준: 이 값 이상이면 KB 답변 반환
_DEFAULT_THRESHOLD = 0.82
_TOP_K = 5  # 최대 검색 후보 수


# =============================================================================
# 인증 (conversation_kb 와 동일)
# =============================================================================


def _verify_secret(x_kb_secret: str = Header(default="")) -> None:
    expected = getattr(settings, "kb_collect_secret", "") or ""
    if not expected:
        return  # 개발 모드
    if x_kb_secret != expected:
        raise HTTPException(status_code=401, detail="invalid KB secret")


# =============================================================================
# 스키마
# =============================================================================


class SearchIn(BaseModel):
    question: str = Field(min_length=2, max_length=8_000)
    threshold: float = Field(default=_DEFAULT_THRESHOLD, ge=0.0, le=1.0)
    use_claude_fallback: bool = Field(default=True)


class KBHit(BaseModel):
    kb_id: str
    question: str
    answer: str
    team_member: Optional[str]
    project: Optional[str]
    similarity: float
    source: str = "team_kb"


class SearchOut(BaseModel):
    answered_by: str  # "team_kb" | "claude_fallback"
    answer: str
    similarity: Optional[float]  # KB 히트 시 유사도
    hits: list[KBHit]  # 검색된 KB 후보 (최대 _TOP_K)
    elapsed_ms: int


# =============================================================================
# 임베딩 (지연 초기화 싱글턴)
# =============================================================================

_embedder = None


def _get_embedder():
    global _embedder  # noqa: PLW0603
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            _embedder = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
        except Exception:  # noqa: BLE001  — ImportError, OSError(torch 손상), 모델 미존재 등 모두 처리
            return None
    return _embedder


def _embed(question: str) -> list[float] | None:
    embedder = _get_embedder()
    if embedder is None:
        return None
    vec = embedder.encode(question, normalize_embeddings=True)
    return vec.tolist()


# =============================================================================
# pgvector 코사인 유사도 검색
# =============================================================================


async def _vector_search(
    db: AsyncSession,
    embedding: list[float],
    threshold: float,
    top_k: int,
) -> list[dict[str, Any]]:
    """self_learning_kb 에서 가장 유사한 qa_pair 검색."""
    emb_str = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"

    rows = (
        await db.execute(
            text(
                "SELECT id, "
                "       payload->>'question'    AS question, "
                "       payload->>'answer'      AS answer, "
                "       payload->>'team_member' AS team_member, "
                "       payload->>'project'     AS project, "
                "       1 - (embedding <=> CAST(:emb AS vector)) AS similarity "
                "FROM   self_learning_kb "
                "WHERE  kb_type = 'qa_pair' "
                "  AND  embedding IS NOT NULL "
                "  AND  1 - (embedding <=> CAST(:emb AS vector)) >= :threshold "
                "ORDER  BY embedding <=> CAST(:emb AS vector) "
                "LIMIT  :top_k"
            ).bindparams(emb=emb_str, threshold=threshold, top_k=top_k)
        )
    ).fetchall()

    return [
        {
            "kb_id": str(r.id),
            "question": r.question or "",
            "answer": r.answer or "",
            "team_member": r.team_member,
            "project": r.project,
            "similarity": float(r.similarity),
        }
        for r in rows
    ]


# =============================================================================
# Claude 폴백
# =============================================================================


async def _claude_fallback(question: str) -> str:
    """Claude API 로 답변 생성 (KB 미스 시)."""
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",  # 폴백은 경량 모델
            max_tokens=2048,
            messages=[{"role": "user", "content": question}],
        )
        return msg.content[0].text if msg.content else "(Claude 응답 없음)"
    except Exception as e:  # noqa: BLE001
        return f"(Claude 폴백 실패: {e})"


# =============================================================================
# POST /kb/search
# =============================================================================


@router.post("", response_model=SearchOut)
async def search_kb(
    body: SearchIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> SearchOut:
    """질문 → KB 우선 검색, 미스 시 Claude 폴백."""
    t0 = time.monotonic()

    # 1. 임베딩
    embedding = _embed(body.question)
    if embedding is None:
        # sentence_transformers 미설치 환경: 바로 Claude 폴백
        answer = await _claude_fallback(body.question) if body.use_claude_fallback else "(임베딩 모델 없음)"
        return SearchOut(
            answered_by="claude_fallback",
            answer=answer,
            similarity=None,
            hits=[],
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # 2. 벡터 검색
    hits_raw = await _vector_search(db, embedding, body.threshold, _TOP_K)
    hits = [KBHit(**h) for h in hits_raw]

    # 3. 충분한 유사도의 히트가 있으면 KB 답변
    if hits:
        best = hits[0]
        return SearchOut(
            answered_by="team_kb",
            answer=best.answer,
            similarity=best.similarity,
            hits=hits,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # 4. 미스 → Claude 폴백
    if body.use_claude_fallback:
        answer = await _claude_fallback(body.question)
    else:
        answer = "(KB 검색 결과 없음 — 폴백 비활성화)"

    return SearchOut(
        answered_by="claude_fallback",
        answer=answer,
        similarity=None,
        hits=[],
        elapsed_ms=int((time.monotonic() - t0) * 1000),
    )


# =============================================================================
# GET /kb/search/health
# =============================================================================


@router.get("/health")
async def kb_health(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """KB 현황 확인."""
    total_qa = (await db.scalar(text("SELECT COUNT(*) FROM self_learning_kb WHERE kb_type='qa_pair'"))) or 0
    has_embedder = _get_embedder() is not None

    return {
        "status": "ok",
        "qa_pairs": int(total_qa),
        "embedder": "loaded" if has_embedder else "not_loaded",
        "threshold": _DEFAULT_THRESHOLD,
    }

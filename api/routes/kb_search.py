"""api.routes.kb_search — 팀 Q&A 지식 검색 라우터.

3단계 폴백 체계:
    1순위  팀 KB (pgvector 코사인 유사도 ≥ threshold)
    2순위  Ollama 로컬 LLM (qwen2.5:7b, 호스트 실행)
    3순위  Claude Opus (클라우드, 최후 수단)

엔드포인트:
    POST /kb/search          질문 입력 → 3단계 폴백으로 답변 반환
    GET  /kb/search/health   KB + Ollama + Embedder 상태 확인

인증:
    X-KB-Secret 헤더 (conversation_kb 와 동일 키)
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
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
    use_ollama_fallback: bool = Field(default=True)
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
    answered_by: str  # "team_kb" | "ollama_local" | "claude_opus" | "error"
    answer: str
    similarity: Optional[float]  # KB 히트 시 유사도
    hits: list[KBHit]  # 검색된 KB 후보 (최대 _TOP_K)
    elapsed_ms: int
    model_used: Optional[str]  # 사용된 모델명 (Ollama/Claude)


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
        except Exception:  # noqa: BLE001  — ImportError, OSError(torch 손상) 모두 처리
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
# Ollama 로컬 LLM 폴백 (2순위)
# =============================================================================


def _check_ollama_ready() -> bool:
    """Ollama 서버가 응답하는지 확인."""
    base_url = getattr(settings, "ollama_base_url", "http://localhost:11434").rstrip("/")
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            return True
    except Exception:  # noqa: BLE001
        return False


def _ollama_answer_sync(question: str) -> tuple[str, str]:
    """Ollama /api/chat 호출 (동기). (answer, model_used) 반환."""
    base_url = getattr(settings, "ollama_base_url", "http://localhost:11434").rstrip("/")
    model = getattr(settings, "ollama_model", "qwen2.5:7b")

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "당신은 ADA 프로젝트(AutoAI 분석 플랫폼)의 전문 어시스턴트입니다. "
                        "팀원의 질문에 정확하고 간결하게 한국어로 답변하세요."
                    ),
                },
                {"role": "user", "content": question},
            ],
            "stream": False,
            "options": {
                "num_predict": 512,  # 최대 생성 토큰 (512 = ~71s@7t/s, timeout 120s 여유)
                "temperature": 0.3,  # 낮은 temperature → 사실적 답변
                "top_p": 0.9,
                "num_gpu": 0,  # CPU 전용 강제
                # GTX 1060 3GB < 모델 4.7GB → 부분 오프로드 시 PCIe 병목으로 오히려 1.3t/s
                # CPU 전용(Ryzen 7 3800XT 16T) = 7.2t/s → 5.5배 빠름
                "num_thread": 14,  # 16스레드 중 14개 사용 (2개는 OS/Docker 여유)
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=120) as resp:  # 로컬 모델은 최대 2분 허용
        data = json.loads(resp.read())

    answer = data.get("message", {}).get("content", "") or "(Ollama 응답 없음)"
    return answer, model


async def _ollama_fallback(question: str) -> tuple[str, str]:
    """Ollama 비동기 래퍼. (answer, model_used) 반환."""
    import asyncio

    try:
        answer, model = await asyncio.to_thread(_ollama_answer_sync, question)
        return answer, model
    except urllib.error.URLError:
        raise  # 연결 실패 → 상위에서 Claude Opus 로 전환
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Ollama 오류: {e}") from e


# =============================================================================
# Claude Opus 최후 폴백 (3순위)
# =============================================================================


async def _claude_opus_fallback(question: str) -> str:
    """Claude Opus-4-7 API 호출 (Ollama 실패 시 최후 수단)."""
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            messages=[{"role": "user", "content": question}],
        )
        return msg.content[0].text if msg.content else "(Claude 응답 없음)"
    except Exception as e:  # noqa: BLE001
        return f"(Claude Opus 폴백 실패: {e})"


# =============================================================================
# POST /kb/search
# =============================================================================


@router.post("", response_model=SearchOut)
async def search_kb(
    body: SearchIn,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> SearchOut:
    """3단계 폴백으로 질문에 답변.

    1순위: 팀 KB (pgvector)
    2순위: Ollama qwen2.5:7b (로컬)
    3순위: Claude Opus (클라우드)
    """
    t0 = time.monotonic()

    # ── 1. 임베딩 ─────────────────────────────────────────────────────────
    embedding = _embed(body.question)

    if embedding is None:
        # sentence_transformers 미설치 → 바로 Ollama/Claude 폴백
        answer, model_used, answered_by = await _run_fallbacks(
            body.question, body.use_ollama_fallback, body.use_claude_fallback
        )
        return SearchOut(
            answered_by=answered_by,
            answer=answer,
            similarity=None,
            hits=[],
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            model_used=model_used,
        )

    # ── 2. 벡터 검색 ──────────────────────────────────────────────────────
    hits_raw = await _vector_search(db, embedding, body.threshold, _TOP_K)
    hits = [KBHit(**h) for h in hits_raw]

    # ── 3. KB 히트 ────────────────────────────────────────────────────────
    if hits:
        best = hits[0]
        return SearchOut(
            answered_by="team_kb",
            answer=best.answer,
            similarity=best.similarity,
            hits=hits,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            model_used=None,
        )

    # ── 4. KB 미스 → Ollama → Claude Opus ────────────────────────────────
    answer, model_used, answered_by = await _run_fallbacks(
        body.question, body.use_ollama_fallback, body.use_claude_fallback
    )

    return SearchOut(
        answered_by=answered_by,
        answer=answer,
        similarity=None,
        hits=[],
        elapsed_ms=int((time.monotonic() - t0) * 1000),
        model_used=model_used,
    )


async def _run_fallbacks(
    question: str,
    use_ollama: bool,
    use_claude: bool,
) -> tuple[str, str | None, str]:
    """(answer, model_used, answered_by) 반환."""
    # 2순위: Ollama 로컬
    if use_ollama:
        try:
            answer, model = await _ollama_fallback(question)
            return answer, model, "ollama_local"
        except (urllib.error.URLError, RuntimeError):
            pass  # Ollama 불가 → Claude Opus 로 계속

    # 3순위: Claude Opus
    if use_claude:
        answer = await _claude_opus_fallback(question)
        return answer, "claude-opus-4-7", "claude_opus"

    return "(모든 폴백 비활성화됨)", None, "error"


# =============================================================================
# GET /kb/search/health
# =============================================================================


@router.get("/health")
async def kb_health(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verify_secret),
) -> dict[str, Any]:
    """KB + Ollama + Embedder 상태 확인."""
    total_qa = (await db.scalar(text("SELECT COUNT(*) FROM self_learning_kb WHERE kb_type='qa_pair'"))) or 0
    has_embedder = _get_embedder() is not None
    ollama_ok = _check_ollama_ready()

    ollama_model = getattr(settings, "ollama_model", "qwen2.5:7b")
    ollama_base_url = getattr(settings, "ollama_base_url", "http://localhost:11434")

    # Ollama 설치 모델 목록 (가능하면)
    ollama_models: list[str] = []
    if ollama_ok:
        try:
            req = urllib.request.Request(f"{ollama_base_url.rstrip('/')}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                ollama_models = [m.get("name", "") for m in data.get("models", [])]
        except Exception:  # noqa: BLE001
            pass

    return {
        "status": "ok",
        "qa_pairs": int(total_qa),
        "embedder": "loaded" if has_embedder else "not_loaded",
        "threshold": _DEFAULT_THRESHOLD,
        "ollama": {
            "status": "online" if ollama_ok else "offline",
            "base_url": ollama_base_url,
            "model": ollama_model,
            "model_ready": ollama_model in ollama_models,
            "available_models": ollama_models,
        },
        "fallback_chain": [
            "1st: team_kb (pgvector cosine)",
            f"2nd: ollama_local ({ollama_model})",
            "3rd: claude_opus (claude-opus-4-7)",
        ],
    }

"""api.routes.kb_search — 팀 Q&A 지식 검색 라우터.

3단계 폴백 체계:
    1순위  팀 KB (pgvector 코사인 유사도 ≥ threshold)
    2순위  Ollama 로컬 LLM (qwen2.5:7b, 호스트 실행)
    3순위  Claude Opus (클라우드, 최후 수단)

다중 게이트 (KB 히트 시 모두 통과해야 KB 답변 반환):
    - 코사인 유사도 ≥ threshold (기본 0.82)
    - success_count ≥ min_hit_count (기본 0, 훅에서는 3)
    - 단어 겹침 비율 ≥ min_word_overlap (기본 0.0, 훅에서는 0.5)
    - 예외: 유사도 ≥ 0.98 (사실상 동일 문장) → hit_count/overlap 게이트 면제

엔드포인트:
    POST /kb/search          질문 입력 → 3단계 폴백으로 답변 반환
    GET  /kb/search/health   KB + Ollama + Embedder 상태 확인

인증:
    X-KB-Secret 헤더 (conversation_kb 와 동일 키)
"""

from __future__ import annotations

import json
import re
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

_SOURCE_BADGE: dict[str, str] = {
    "team_kb": "1순위 🗂️ Team KB  |  💚 무료",
    "ollama_local": "2순위 🤖 Ollama   |  💚 무료",
    "claude_opus": "3순위 ☁️ Claude   |  💸 유료",
    "error": "❌ 폴백 오류",
}


def _with_badge(answered_by: str, answer: str, *, extra: str = "") -> str:
    label = _SOURCE_BADGE.get(answered_by, answered_by)
    if extra:
        label = f"{label}  |  {extra}"
    return f"[{label}]\n\n{answer}"


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
    # 다중 게이트 파라미터
    min_hit_count: int = Field(default=0, ge=0, description="최소 success_count (훅에서는 3 권장)")
    min_word_overlap: float = Field(default=0.0, ge=0.0, le=1.0, description="단어 겹침 비율 (훅에서는 0.5 권장)")


class KBHit(BaseModel):
    kb_id: str
    question: str
    answer: str
    team_member: Optional[str]
    project: Optional[str]
    similarity: float
    success_count: int = 1
    source: str = "team_kb"


# =============================================================================
# 단어 겹침 비율 (다중 게이트 보조)
# =============================================================================


def _word_overlap_ratio(q1: str, q2: str) -> float:
    """두 질문의 의미 단어(2글자 이상) 겹침 비율.

    분모: min(len(words1), len(words2)) — 짧은 쪽 기준 → 관대하게 계산.
    """
    words1 = set(re.findall(r"\w{2,}", q1.lower()))
    words2 = set(re.findall(r"\w{2,}", q2.lower()))
    if not words1 or not words2:
        return 0.0
    return len(words1 & words2) / min(len(words1), len(words2))


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
    """self_learning_kb 에서 가장 유사한 qa_pair 검색.

    success_count 도 반환 — 다중 게이트 필터링에 사용.
    """
    emb_str = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"

    rows = (
        await db.execute(
            text(
                "SELECT id, "
                "       payload->>'question'    AS question, "
                "       payload->>'answer'      AS answer, "
                "       payload->>'team_member' AS team_member, "
                "       payload->>'project'     AS project, "
                "       COALESCE(success_count, 1) AS success_count, "
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
            "success_count": int(r.success_count),
            "similarity": float(r.similarity),
        }
        for r in rows
    ]


async def _increment_success_count(db: AsyncSession, kb_id: str) -> None:
    """KB 히트 시 success_count 증가 (학습 누적)."""
    from ada.core.logger import get_logger as _gl

    _log = _gl("kb_search")
    try:
        await db.execute(
            text(
                "UPDATE self_learning_kb "
                "SET success_count = COALESCE(success_count, 1) + 1, "
                "    updated_at = NOW() "
                "WHERE id = CAST(:kb_id AS uuid)"
            ).bindparams(kb_id=kb_id)
        )
        await db.commit()
    except Exception as e:  # noqa: BLE001
        _log.warning("kb_success_count_update_failed", kb_id=kb_id, error=str(e))


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
    """Claude Opus 최후 폴백 — R-004 준수.

    직접 anthropic SDK 를 호출하지 않고 BaseAgent._call_llm() 단일 진입점을
    경유한다 (서킷 브레이커 + Langfuse 트레이싱 + 토큰 메트릭이 자동 적용됨).
    """
    try:
        from agents.base import BaseAgent

        class _KBFallbackAgent(BaseAgent):
            """KB 검색 폴백 전용 경량 에이전트 (페르소나 미등록 → 프리픽스 없음)."""

            model_name = "claude-opus-4-7"

            async def __call__(self, state):  # pragma: no cover - 진입점 미사용
                raise NotImplementedError

        agent = _KBFallbackAgent()
        return await agent._call_llm(
            system_prompt="당신은 ADA 팀 지식베이스 어시스턴트입니다. 한국어로 간결하고 정확하게 답하세요.",
            user_prompt=question,
            max_tokens=4096,
        )
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
            answer=_with_badge(answered_by, answer, extra=model_used or ""),
            similarity=None,
            hits=[],
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            model_used=model_used,
        )

    # ── 2. 벡터 검색 ──────────────────────────────────────────────────────
    hits_raw = await _vector_search(db, embedding, body.threshold, _TOP_K)

    # ── 3. 다중 게이트 필터 ───────────────────────────────────────────────
    # 유사도 ≥ 0.98 (사실상 동일 문장) → hit_count / overlap 게이트 면제
    _EXACT_SIM = 0.98
    filtered: list[dict[str, Any]] = []
    for h in hits_raw:
        sim = h["similarity"]
        is_exact = sim >= _EXACT_SIM

        if not is_exact:
            # hit_count 게이트
            if body.min_hit_count > 0 and h["success_count"] < body.min_hit_count:
                continue
            # 단어 겹침 게이트
            if body.min_word_overlap > 0.0:
                overlap = _word_overlap_ratio(body.question, h["question"])
                if overlap < body.min_word_overlap:
                    continue

        filtered.append(h)

    hits = [KBHit(**h) for h in filtered]

    # ── 4. KB 히트 ────────────────────────────────────────────────────────
    if hits:
        best = hits[0]
        # success_count 증가 (비동기, 응답 차단 없음)
        import asyncio

        asyncio.create_task(_increment_success_count(db, best.kb_id))
        return SearchOut(
            answered_by="team_kb",
            answer=_with_badge("team_kb", best.answer, extra=f"유사도 {best.similarity:.3f}"),
            similarity=best.similarity,
            hits=hits,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            model_used=None,
        )

    # ── 5. KB 미스 → Ollama → Claude Opus ────────────────────────────────
    answer, model_used, answered_by = await _run_fallbacks(
        body.question, body.use_ollama_fallback, body.use_claude_fallback
    )

    return SearchOut(
        answered_by=answered_by,
        answer=_with_badge(answered_by, answer, extra=model_used or ""),
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
    from ada.core.logger import get_logger as _gl

    _log = _gl("kb_search")

    # 2순위: Ollama 로컬
    if use_ollama:
        try:
            answer, model = await _ollama_fallback(question)
            return answer, model, "ollama_local"
        except (urllib.error.URLError, RuntimeError) as e:
            _log.warning("ollama_fallback_failed", error=str(e))

    # 3순위: Claude Opus
    if use_claude:
        answer = await _claude_opus_fallback(question)
        return answer, "claude-opus-4-7", "claude_opus"

    # 모든 폴백 비활성화 — KB-only 모드(훅)이면 정상, 그 외엔 에러
    if use_ollama or use_claude:
        # 최소 하나는 켜져 있었는데 모두 실패한 경우 → 진짜 장애
        err_msg = "kb_search_all_fallbacks_failed"
        _log.error(err_msg, question_len=len(question))
        try:
            import traceback as _tb

            from ada.error_handler.auto_handler import capture_and_handle

            await capture_and_handle(
                error_message=err_msg,
                stack_trace=_tb.format_stack()[-1],
                source="api_kb_search",
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        # use_ollama=False, use_claude=False → KB-only 의도 모드 (훅 패스스루)
        _log.debug("kb_search_kb_only_miss", question_len=len(question))
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

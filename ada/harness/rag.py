"""ada.harness.rag — pgvector 기반 RAG (Day09 Stack 3).

dataset_embeddings / intent_embeddings / lesson_embeddings 3 컬렉션.
임베딩 모델: SentenceTransformer (KB 인용 R-501).
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.logger import get_logger
from ada.db.models import (
    SelfLearningKB,
)

log = get_logger("rag")


class KBRAG:
    """pgvector 코사인 유사도 검색 + 인용 강제."""

    EMBED_DIM = 768

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._embedder: Optional[Any] = None

    # ------------------------------------------------------------------
    def _get_embedder(self) -> Any:
        if self._embedder is not None:
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            self._embedder = SentenceTransformer("sentence-transformers/paraphrase-multilingual-mpnet-base-v2")
        except Exception as e:
            # 임베더 미설치/로드 실패 → 0 벡터 폴백. silent 가 아니라 명시적으로 경고한다
            # (KB 벡터검색이 무력화되어 R-501 인용 품질이 보장되지 않는 상태 신호).
            self._embedder = None
            log.warning(
                "rag_embedder_unavailable",
                error=str(e),
                impact="zero-vector fallback — KB vector search unreliable, citations not guaranteed",
            )
        return self._embedder

    def embed(self, text_in: str) -> list[float]:
        emb_model = self._get_embedder()
        if emb_model is None:
            # 임베더 없으면 0 벡터 (개발 환경 fallback)
            return [0.0] * self.EMBED_DIM
        vec = emb_model.encode(text_in, convert_to_numpy=True)
        if vec.shape[0] != self.EMBED_DIM:
            # 차원 맞추기 (paraphrase-mpnet은 768)
            vec = np.resize(vec, self.EMBED_DIM)
        return vec.astype(float).tolist()

    # ------------------------------------------------------------------
    async def search_lessons(self, query: str, top_k: int = 5, *, cite: bool = True) -> list[dict[str, Any]]:
        """failure_lesson 검색."""
        emb = self.embed(query)
        sql = text(
            """
            SELECT le.kb_id, kb.payload, kb.confidence, kb.success_count,
                   1 - (le.embedding <=> CAST(:emb AS vector)) AS similarity
            FROM lesson_embeddings le
            JOIN self_learning_kb kb ON kb.id = le.kb_id
            WHERE kb.kb_type = 'failure_lesson'
              AND COALESCE((kb.payload ->> 'retracted')::boolean, false) = false
            ORDER BY le.embedding <=> CAST(:emb AS vector)
            LIMIT :k
            """
        )
        try:
            rows = await self.session.execute(sql, {"emb": str(emb), "k": top_k})
            results = [dict(r._mapping) for r in rows]
        except Exception as e:
            log.warning("rag_search_failed", error=str(e))
            return []
        # Day11/KP9 — 관련 매칭(유사도>=0.7)을 KB 인용으로 카운트 (RAG 공통 단일 집계점)
        if cite and results:
            try:
                from ada.observability.metrics import record_kb_citation

                for _r in results:
                    if float(_r.get("similarity") or 0.0) >= 0.7:
                        record_kb_citation(source="lessons_kb")
            except Exception:
                pass
        return results

    async def search_recipes(self, category: str, top_k: int = 5, *, cite: bool = True) -> list[dict[str, Any]]:
        """category 기반 recipe 검색 (pgvector 없이 단순 정렬)."""
        rows = await self.session.scalars(
            select(SelfLearningKB)
            .where(
                SelfLearningKB.kb_type == "recipe",
                SelfLearningKB.category == category,
            )
            .order_by(SelfLearningKB.success_count.desc())
            .limit(top_k)
        )
        results = [
            {"hash": r.hash, "payload": r.payload, "confidence": r.confidence, "success_count": r.success_count}
            for r in rows
            # R-504 — retracted KB 제외 (폐기된 레시피는 인용 금지)
            if not (isinstance(r.payload, dict) and r.payload.get("retracted"))
        ]
        # Day11/KP9 — 반환 레시피를 KB 인용으로 카운트
        if cite and results:
            try:
                from ada.observability.metrics import record_kb_citation

                for _ in results:
                    record_kb_citation(source="recipes_kb")
            except Exception:
                pass
        return results

    # ------------------------------------------------------------------
    async def fetch_warm_start_map(self, category: str) -> dict[str, dict[str, Any]]:
        """hpo_warm_start KB → {model_name: best_params}. 인용은 실제 적용 시 호출측에서."""
        try:
            rows = await self.session.scalars(
                select(SelfLearningKB)
                .where(
                    SelfLearningKB.kb_type == "hpo_warm_start",
                    SelfLearningKB.category == category,
                    SelfLearningKB.confidence >= 0.20,
                )
                .order_by(SelfLearningKB.success_count.desc())
            )
        except Exception as e:  # noqa: BLE001
            log.warning("warm_start_fetch_failed", error=str(e))
            return {}
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            pl = r.payload if isinstance(r.payload, dict) else {}
            if pl.get("retracted"):
                continue
            model = pl.get("model")
            params = pl.get("best_params")
            if model and isinstance(params, dict) and params and model not in out:
                out[model] = params  # 동일 모델은 success_count 최상위 1건
        return out

    async def fetch_eda_template(self, category: str, *, cite: bool = True) -> dict[str, Any] | None:
        """eda_template KB(카테고리) 최상위 1건 payload. cite=True 면 인용 카운트."""
        try:
            row = await self.session.scalar(
                select(SelfLearningKB)
                .where(
                    SelfLearningKB.kb_type == "eda_template",
                    SelfLearningKB.category == category,
                    SelfLearningKB.confidence >= 0.20,
                )
                .order_by(SelfLearningKB.success_count.desc())
                .limit(1)
            )
        except Exception as e:  # noqa: BLE001
            log.warning("eda_template_fetch_failed", error=str(e))
            return None
        if row is None or not isinstance(row.payload, dict) or row.payload.get("retracted"):
            return None
        if cite:
            try:
                from ada.observability.metrics import record_kb_citation

                record_kb_citation(source="eda_template_kb")
            except Exception:
                pass
        return row.payload

    async def fetch_success_patterns(self, category: str, top_k: int = 3, *, cite: bool = True) -> list[dict[str, Any]]:
        """success_pattern KB(카테고리) 상위 N건 payload. cite=True 면 사용분만큼 인용."""
        try:
            rows = await self.session.scalars(
                select(SelfLearningKB)
                .where(
                    SelfLearningKB.kb_type == "success_pattern",
                    SelfLearningKB.category == category,
                    SelfLearningKB.confidence >= 0.20,
                )
                .order_by(SelfLearningKB.success_count.desc())
                .limit(top_k)
            )
        except Exception as e:  # noqa: BLE001
            log.warning("success_pattern_fetch_failed", error=str(e))
            return []
        out = [r.payload for r in rows if isinstance(r.payload, dict) and not r.payload.get("retracted")]
        if cite and out:
            try:
                from ada.observability.metrics import record_kb_citation

                for _ in out:
                    record_kb_citation(source="success_pattern_kb")
            except Exception:
                pass
        return out

    async def index_lesson(self, kb_id: Any, summary: str) -> None:
        emb = self.embed(summary)
        # ON CONFLICT (kb_id) DO UPDATE — 같은 kb_id 재색인 시 덮어쓰기 (중복 방지)
        await self.session.execute(
            text(
                """
            INSERT INTO lesson_embeddings (kb_id, target, embedding)
            VALUES (:kb_id, :target, CAST(:emb AS vector))
            ON CONFLICT (kb_id) DO UPDATE
                SET target    = EXCLUDED.target,
                    embedding = EXCLUDED.embedding
            """
            ),
            {"kb_id": str(kb_id), "target": summary[:1000], "emb": str(emb)},
        )

    async def index_intent(self, job_id: Any, intent_text: str) -> None:
        emb = self.embed(intent_text)
        await self.session.execute(
            text(
                """
            INSERT INTO intent_embeddings (job_id, target, embedding)
            VALUES (:job_id, :target, CAST(:emb AS vector))
            """
            ),
            {"job_id": str(job_id), "target": intent_text[:1000], "emb": str(emb)},
        )

    async def index_dataset(self, upload_id: Any, summary: str) -> None:
        emb = self.embed(summary)
        await self.session.execute(
            text(
                """
            INSERT INTO dataset_embeddings (upload_id, target, embedding)
            VALUES (:u, :t, CAST(:emb AS vector))
            """
            ),
            {"u": str(upload_id), "t": summary[:1000], "emb": str(emb)},
        )

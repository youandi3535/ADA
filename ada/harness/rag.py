"""ada.harness.rag — pgvector 기반 RAG (Day09 Stack 3).

dataset_embeddings / intent_embeddings / lesson_embeddings 3 컬렉션.
임베딩 모델: SentenceTransformer (KB 인용 R-501).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.logger import get_logger
from ada.db.models import (
    DatasetEmbedding,
    IntentEmbedding,
    LessonEmbedding,
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
            self._embedder = SentenceTransformer(
                "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
            )
        except Exception:
            self._embedder = None
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
    async def search_lessons(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """failure_lesson 검색."""
        emb = self.embed(query)
        sql = text(
            """
            SELECT le.kb_id, kb.payload, kb.confidence, kb.success_count,
                   1 - (le.embedding <=> CAST(:emb AS vector)) AS similarity
            FROM lesson_embeddings le
            JOIN self_learning_kb kb ON kb.id = le.kb_id
            WHERE kb.kb_type = 'failure_lesson'
            ORDER BY le.embedding <=> CAST(:emb AS vector)
            LIMIT :k
            """
        )
        try:
            rows = await self.session.execute(sql, {"emb": str(emb), "k": top_k})
            return [dict(r._mapping) for r in rows]
        except Exception as e:
            log.warning("rag_search_failed", error=str(e))
            return []

    async def search_recipes(self, category: str, top_k: int = 5) -> list[dict[str, Any]]:
        """category 기반 recipe 검색 (pgvector 없이 단순 정렬)."""
        rows = await self.session.scalars(
            select(SelfLearningKB).where(
                SelfLearningKB.kb_type == "recipe",
                SelfLearningKB.category == category,
            ).order_by(SelfLearningKB.success_count.desc()).limit(top_k)
        )
        return [{"hash": r.hash, "payload": r.payload,
                 "confidence": r.confidence, "success_count": r.success_count}
                for r in rows]

    # ------------------------------------------------------------------
    async def index_lesson(self, kb_id: Any, summary: str) -> None:
        emb = self.embed(summary)
        await self.session.execute(text(
            """
            INSERT INTO lesson_embeddings (kb_id, target, embedding)
            VALUES (:kb_id, :target, CAST(:emb AS vector))
            """
        ), {"kb_id": str(kb_id), "target": summary[:1000], "emb": str(emb)})

    async def index_intent(self, job_id: Any, intent_text: str) -> None:
        emb = self.embed(intent_text)
        await self.session.execute(text(
            """
            INSERT INTO intent_embeddings (job_id, target, embedding)
            VALUES (:job_id, :target, CAST(:emb AS vector))
            """
        ), {"job_id": str(job_id), "target": intent_text[:1000], "emb": str(emb)})

    async def index_dataset(self, upload_id: Any, summary: str) -> None:
        emb = self.embed(summary)
        await self.session.execute(text(
            """
            INSERT INTO dataset_embeddings (upload_id, target, embedding)
            VALUES (:u, :t, CAST(:emb AS vector))
            """
        ), {"u": str(upload_id), "t": summary[:1000], "emb": str(emb)})

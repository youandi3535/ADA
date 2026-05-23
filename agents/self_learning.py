"""agents.self_learning — SelfLearningAgent (Day09 + Day 1 자동 KB 인덱싱).

job 종료 시:
    1) SelfLearningHarness.distill_from_job(job_id) — 사후 학습 (KB row 생성)
    2) Day 1 추가: distill 결과의 lesson_summary 가 있으면
       KBRAG.index_lesson 을 자동 호출해 pgvector 임베딩 색인.
"""

from __future__ import annotations

from ada.core.state import PipelineState
from agents.base import BaseAgent


class SelfLearningAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            if self.session is None:
                return state.with_update(next_agent="END")

            distill_result: dict | None = None
            try:
                from ada.harness.distiller import SelfLearningHarness

                h = SelfLearningHarness(self.session)
                distill_result = await h.distill_from_job(state.job_id)
            except Exception as e:
                self.logger.warning("distill_failed", error=str(e))

            # Day 1 — distill 결과를 RAG 에 자동 색인
            if distill_result:
                await self._auto_index_lessons(distill_result)

            return state.with_update(next_agent="END")

    # ------------------------------------------------------------------
    async def _auto_index_lessons(self, distill_result: dict) -> None:
        """distill 결과의 created_kb_ids 를 KBRAG 로 pgvector 색인.

        distill_result 예상 키 (best-effort):
            - "created_kb_ids": list[uuid]   — 새로 만든 KB row id 목록
            - "summaries": dict[uuid, str]    — KB id → 요약 텍스트 (없으면 KB 조회)
        """
        try:
            from sqlalchemy import select

            from ada.db.models import SelfLearningKB
            from ada.harness.rag import KBRAG

            kb_ids: list = list(distill_result.get("created_kb_ids") or [])
            if not kb_ids:
                return
            summaries: dict = dict(distill_result.get("summaries") or {})

            rag = KBRAG(self.session)
            for kb_id in kb_ids:
                summary = summaries.get(kb_id) or summaries.get(str(kb_id))
                if not summary:
                    try:
                        row = await self.session.scalar(  # type: ignore[attr-defined]
                            select(SelfLearningKB).where(SelfLearningKB.id == kb_id)
                        )
                        if row is not None and isinstance(row.payload, dict):
                            summary = (
                                row.payload.get("lesson_summary")
                                or row.payload.get("summary")
                                or row.payload.get("description")
                                or ""
                            )
                    except Exception:
                        summary = ""
                if not summary:
                    continue
                try:
                    await rag.index_lesson(kb_id, summary)
                except Exception as e:
                    self.logger.warning("kb_index_failed", kb_id=str(kb_id), error=str(e))
        except Exception as e:
            self.logger.warning("auto_index_lessons_failed", error=str(e))

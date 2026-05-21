"""agents.report_composer — ReportComposerAgent (Day12).

requested_outputs (G5 응답) 에 따라 5종 산출물을 병렬 생성.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent
from outputs import GENERATORS


class ReportComposerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            requested = state.requested_outputs or list(GENERATORS.keys())
            results: dict[str, str] = {}

            async def _gen(code: str) -> tuple[str, str | None]:
                try:
                    gen_cls = GENERATORS.get(code)
                    if gen_cls is None:
                        return code, None
                    gen = gen_cls(state.job_id)
                    path = await asyncio.to_thread(
                        gen.generate,
                        insights=state.insights or "",
                        best_model=state.best_model or {},
                        eda_charts=state.eda_charts,
                        category=state.category,
                        user_intent=state.user_intent or state.user_question or "",
                        eval_result=state.eval_result,
                    )
                    return code, path
                except Exception as e:
                    self.logger.warning("output_failed", code=code, error=str(e))
                    return code, None

            done = await asyncio.gather(*[_gen(c) for c in requested])
            for code, path in done:
                if path:
                    results[code] = path
                    if self.session is not None:
                        await self._save_output_row(state.job_id, code, path)

            return state.with_update(output_paths=results,
                                     next_agent="self_learning_dispatch")

    async def _save_output_row(self, job_id: str, code: str, minio_path: str) -> None:
        try:
            import uuid as _uuid
            from ada.db.models import Output
            self.session.add(Output(
                job_id=_uuid.UUID(job_id),
                output_code=code,
                minio_path=minio_path,
            ))
            await self.session.flush()
        except Exception as e:
            self.logger.warning("output_db_save_failed", error=str(e))

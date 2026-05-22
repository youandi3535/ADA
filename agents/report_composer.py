"""agents.report_composer — Day 0 dispatcher 패턴.

카테고리별 추가 자산은 ``handlers/{cat}/output_extras.assets(state)`` 에서 가져옴.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import asyncio
import uuid as _uuid
from typing import Any

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from outputs import GENERATORS


class ReportComposerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            requested = state.requested_outputs or list(GENERATORS.keys())

            # 카테고리별 추가 자산 (Day 9 에 generator 들이 활용)
            extras: dict[str, Any] = {}
            assets_handler = get_handler(state.category, "assets")
            if assets_handler is not None:
                try:
                    extras = assets_handler(state) or {}
                except Exception as e:
                    self.logger.warning("report_extras_failed", category=state.category, error=str(e))

            cat_extras = {**state.category_extras}
            cat_extras.setdefault(state.category, {}).update(extras)

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

            return state.with_update(
                output_paths=results, category_extras=cat_extras, next_agent="self_learning_dispatch"
            )

    async def _save_output_row(self, job_id: str, code: str, minio_path: str) -> None:
        try:
            from ada.db.models import Output

            self.session.add(
                Output(
                    job_id=_uuid.UUID(job_id),
                    output_code=code,
                    minio_path=minio_path,
                )
            )
            await self.session.flush()
        except Exception as e:
            self.logger.warning("output_db_save_failed", error=str(e))

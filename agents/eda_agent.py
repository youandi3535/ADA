"""agents.eda_agent — Day 0 dispatcher 패턴.

카테고리별 차트 생성은 ``handlers/{cat}/eda.charts(df, state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import load_dataframe_from_state


class EDAAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            charts: list[str] = []
            try:
                df = load_dataframe_from_state(state)
            except Exception as e:
                self.logger.warning("eda_load_failed", error=str(e))
                return state.with_update(next_agent="gate_methodology")

            handler = get_handler(state.category, "charts")
            if handler is not None:
                try:
                    charts = handler(df, state) or []
                except Exception as e:
                    self.logger.warning("eda_handler_failed", category=state.category, error=str(e))

            summary = f"행수={len(df):,}, 열수={df.shape[1]:,}, 카테고리={state.category}, 생성 차트 {len(charts)}종."
            return state.with_update(
                eda_charts=charts,
                eda_summary=summary,
                next_agent="gate_methodology",
            )

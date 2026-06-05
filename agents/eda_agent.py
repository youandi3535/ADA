"""agents.eda_agent — Day 0 dispatcher 패턴.

카테고리별 차트 생성은 ``handlers/{cat}/eda.charts(df, state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).

HJ-2 보강 (2026-06-05) — eda_summary union (dict | str).
카테고리 핸들러 (`charts`) 가 `last_eda_summary` 속성에 dict 를 부착했으면
str 요약 대신 그 dict 를 state.eda_summary 로 전달. CS handlers/timeseries/eda.py
설계와 정합 (line 17 의 "부수효과로 charts.last_eda_summary 에 dict 부착 →
dispatcher 가 state.eda_summary 로 전달").
"""

from __future__ import annotations

from typing import Any

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
                df = load_dataframe_from_state(state, prefer_processed=False)
            except Exception as e:
                self.logger.warning("eda_load_failed", error=str(e))
                return state.with_update(next_agent="gate_methodology")

            handler = get_handler(state.category, "charts")
            if handler is not None:
                try:
                    charts = handler(df, state) or []
                except Exception as e:
                    self.logger.warning("eda_handler_failed", category=state.category, error=str(e))

            # HJ-2 보강 — 핸들러가 부수효과로 dict 요약 부착했으면 우선 사용 (CS handlers/timeseries/eda.py).
            # state.eda_summary 는 Optional[dict | str] union 이므로 둘 다 허용.
            summary: Any = (
                f"행수={len(df):,}, 열수={df.shape[1]:,}, 카테고리={state.category}, 생성 차트 {len(charts)}종."
            )
            if handler is not None:
                dict_summary = getattr(handler, "last_eda_summary", None)
                if isinstance(dict_summary, dict) and dict_summary:
                    summary = dict_summary

            return state.with_update(
                eda_charts=charts,
                eda_summary=summary,
                next_agent="gate_methodology",
            )

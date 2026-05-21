"""agents.data_profiler — DataProfilerAgent (Day 0 dispatcher 패턴).

본 파일은 **얇은 dispatcher** 다. 카테고리별 보강 로직은
``agents/handlers/{cat}/profiler.py`` 의 ``profile(df, state)`` 가 처리.

수정 권한: **HJ 단독** (dispatcher 자체). 카테고리 보강은 각 멤버.
"""
from __future__ import annotations

from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import (
    basic_dataframe_profile,
    load_dataframe_from_state,
)
# import side-effects 로 handlers 자동 등록
import agents.handlers.timeseries  # noqa: F401
import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401


class DataProfilerAgent(BaseAgent):
    """4 카테고리 공통 dispatcher."""

    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                df = load_dataframe_from_state(state)
            except Exception as e:
                return state.with_update(
                    error=f"파일 로딩 실패: {e}",
                    validation={"is_valid": False, "errors": [str(e)], "warnings": []},
                    next_agent="error_recovery",
                )

            profile = basic_dataframe_profile(df, target_column=state.target_column)

            handler = get_handler(state.category, "profile")
            if handler is not None:
                try:
                    extra = handler(df, state)
                    if isinstance(extra, dict):
                        profile.update(extra)
                except Exception as e:
                    self.logger.warning("profiler_handler_failed",
                                        category=state.category, error=str(e))

            return state.with_update(data_profile=profile,
                                     next_agent="schema_validator")

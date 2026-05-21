"""agents.feature_engineer — Day 0 dispatcher 패턴.

카테고리별 step 적용은 ``handlers/{cat}/preprocessor.apply(df, plan, state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).
"""
from __future__ import annotations

import uuid

from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import load_dataframe_from_state
from tools.minio_tool import get_minio_client
import agents.handlers.timeseries  # noqa: F401
import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401


class FeatureEngineerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                df = load_dataframe_from_state(state)
            except Exception as e:
                return state.with_update(error=f"데이터 로딩 실패: {e}",
                                         next_agent="error_recovery")

            handler = get_handler(state.category, "apply")
            if handler is not None:
                try:
                    df = handler(df, state.preprocessing_plan or [], state)
                except Exception as e:
                    self.logger.warning("feature_engineer_handler_failed",
                                        category=state.category, error=str(e))

            object_name = f"processed/{state.job_id}/{uuid.uuid4().hex}.parquet"
            get_minio_client().save_dataframe(df, object_name, fmt="parquet")
            return state.with_update(preprocessed_data_id=object_name,
                                     next_agent="gate_model_strategy")

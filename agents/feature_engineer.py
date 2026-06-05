"""agents.feature_engineer — Day 0 dispatcher 패턴.

카테고리별 step 적용은 ``handlers/{cat}/preprocessor.apply(df, plan, state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import uuid

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import load_dataframe_from_state
from tools.minio_tool import get_minio_client


class FeatureEngineerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                df = load_dataframe_from_state(state, prefer_processed=False)
            except Exception as e:
                return state.with_update(error=f"데이터 로딩 실패: {e}", next_agent="error_recovery")

            handler = get_handler(state.category, "apply")
            if handler is not None:
                try:
                    result = handler(df, state.preprocessing_plan or [], state)
                    if isinstance(result, tuple) and len(result) == 2:
                        df, state = result
                    else:
                        df = result
                except Exception as e:
                    self.logger.warning("feature_engineer_handler_failed", category=state.category, error=str(e))

            object_name = f"processed/{state.job_id}/{uuid.uuid4().hex}.parquet"
            get_minio_client().save_dataframe(df, object_name, fmt="parquet")
            new_state = state.with_update(preprocessed_data_id=object_name, next_agent="gate_model_strategy")

            # Phase 1.4 — ReportContext ④ features 적립.
            # 핸들러가 명시 created 리스트를 안 주므로 최종 컬럼 수만 적립.
            try:
                final_count = int(df.shape[1])
                schema_after = {str(c): str(df[c].dtype) for c in df.columns}
                new_state = self.contribute_to_context(
                    new_state,
                    "features",
                    {"final_feature_count": final_count},
                )
                # 전처리 schema_after 보강
                new_state = self.contribute_to_context(
                    new_state,
                    "preprocessing",
                    {"schema_after": schema_after},
                )
            except Exception as e:
                self.logger.warning("contribute_features_failed", error=str(e))
            return new_state

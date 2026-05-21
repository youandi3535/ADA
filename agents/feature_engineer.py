"""agents.feature_engineer — FeatureEngineerAgent (Day10).

PreprocessingStrategist 의 plan 을 실행한다. 결과 DataFrame 은
MinIO 에 parquet 저장 후 ``state.preprocessed_data_id`` 에 기록.
"""
from __future__ import annotations

import uuid
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent
from tools.minio_tool import get_minio_client


class FeatureEngineerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            mc = get_minio_client()
            try:
                df = mc.load_dataframe(state.file_id,
                                       fmt=state.file_id.rsplit(".", 1)[-1].lower())
            except Exception as e:
                return state.with_update(error=f"데이터 로딩 실패: {e}",
                                         next_agent="error_recovery")

            df = self._apply_plan(df, state.preprocessing_plan or [],
                                  target=state.target_column,
                                  category=state.category)

            object_name = f"processed/{state.job_id}/{uuid.uuid4().hex}.parquet"
            preprocessed_path = mc.save_dataframe(df, object_name, fmt="parquet")
            return state.with_update(preprocessed_data_id=object_name,
                                     next_agent="gate_model_strategy")

    # ------------------------------------------------------------------
    def _apply_plan(self, df: Any, plan: list[dict[str, Any]],
                    *, target: str | None, category: str) -> Any:
        import numpy as np
        import pandas as pd

        out = df.copy()

        for step in plan:
            name = step.get("name")
            try:
                if name == "impute_numeric":
                    num_cols = out.select_dtypes(include=[np.number]).columns
                    strategy = step.get("strategy", "median")
                    for c in num_cols:
                        if strategy == "median":
                            out[c] = out[c].fillna(out[c].median())
                        else:
                            out[c] = out[c].fillna(0)
                elif name == "impute_categorical":
                    cat_cols = out.select_dtypes(include=["object", "category"]).columns
                    for c in cat_cols:
                        m = out[c].mode(dropna=True)
                        out[c] = out[c].fillna(m.iloc[0] if not m.empty else "missing")
                elif name == "encode_categorical":
                    cat_cols = out.select_dtypes(include=["object", "category"]).columns
                    threshold = step.get("high_card_threshold", 50)
                    for c in cat_cols:
                        if c == target:
                            continue
                        nun = out[c].nunique(dropna=True)
                        if nun <= threshold:
                            dummies = pd.get_dummies(out[c], prefix=str(c), drop_first=True)
                            out = pd.concat([out.drop(columns=[c]), dummies], axis=1)
                        else:
                            # 단순 frequency encoding (target_encoding 대체)
                            freq = out[c].value_counts(normalize=True)
                            out[c] = out[c].map(freq).fillna(0.0)
                elif name == "scale_numeric":
                    from sklearn.preprocessing import RobustScaler, StandardScaler
                    method = step.get("method", "robust")
                    num_cols = [c for c in out.select_dtypes(include=[np.number]).columns
                                if c != target]
                    scaler = RobustScaler() if method == "robust" else StandardScaler()
                    if num_cols:
                        out[num_cols] = scaler.fit_transform(out[num_cols])
                elif name == "lag_features" and category == "timeseries" and target:
                    for lag in step.get("lags", [1, 7, 14]):
                        out[f"{target}_lag{lag}"] = out[target].shift(lag)
                elif name == "rolling_mean" and category == "timeseries" and target:
                    for w in step.get("windows", [7, 14]):
                        out[f"{target}_rmean{w}"] = (
                            out[target].shift(1).rolling(w).mean()
                        )
                elif name == "winsorize":
                    q = step.get("quantile", 0.05)
                    num_cols = out.select_dtypes(include=[np.number]).columns
                    for c in num_cols:
                        lo, hi = out[c].quantile(q), out[c].quantile(1 - q)
                        out[c] = out[c].clip(lo, hi)
                elif name == "standard_scale":
                    from sklearn.preprocessing import StandardScaler
                    num_cols = [c for c in out.select_dtypes(include=[np.number]).columns
                                if c != target]
                    if num_cols:
                        out[num_cols] = StandardScaler().fit_transform(out[num_cols])
            except Exception as e:
                self.logger.warning("preprocess_step_failed", step=name, error=str(e))

        return out

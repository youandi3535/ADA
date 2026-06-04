"""agents.training_executor — TrainingExecutorAgent (Day08 + Day 6 best_params 연결).

4 카테고리에 따라 PipelineFactory 로 파이프라인을 선택하고,
ModelSelectionAgent 가 선정한 후보 3종을 학습한다.

Day 6 계약: state.best_params[model] 가 있으면 그 값을 params 로 흘려준다.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ada.core.state import PipelineState
from agents.base import BaseAgent
from pipelines.factory import PipelineFactory


def _split_xy(df: Any, target: str | None) -> tuple[Any, Any]:
    if target and target in df.columns:
        X = df.drop(columns=[target])
        y = df[target]
        return X.select_dtypes(include=[np.number, "bool"]).fillna(0).values, y.values
    return df.select_dtypes(include=[np.number]).fillna(0).values, np.zeros(len(df))


class TrainingExecutorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                from agents.handlers.common.shared import load_dataframe_from_state

                df = load_dataframe_from_state(state)
            except Exception as e:
                return state.with_update(error=f"학습 데이터 로딩 실패: {e}", next_agent="error_recovery")

            X, y = _split_xy(df, state.target_column)
            # train/val split — 시계열은 시간순 split, 그 외 random
            if state.category == "timeseries":
                split = int(len(X) * 0.8)
                X_tr, X_val = X[:split], X[split:]
                y_tr, y_val = y[:split], y[split:]
            else:
                from sklearn.model_selection import train_test_split

                X_tr, X_val, y_tr, y_val = train_test_split(
                    X,
                    y,
                    test_size=0.2,
                    random_state=42,
                    stratify=y
                    if state.category in ("tabular_ml", "tabular_dl") and len(set(y.tolist())) <= 20
                    else None,
                )

            pipeline = PipelineFactory.create(state.category)
            task = (
                "classification"
                if state.category in ("tabular_ml", "tabular_dl") and len(set(y.tolist())) <= 20
                else "regression"
            )
            if state.category == "timeseries":
                task = "forecasting"
            if state.category == "anomaly_detection":
                task = "anomaly_detection"

            trained: list[dict[str, Any]] = []
            for model_name in state.model_candidates:
                # Day 6 계약: HyperparameterTuner 가 채운 best_params 우선 사용.
                params = (state.best_params or {}).get(model_name, {}) or {}
                try:
                    model = pipeline.train(X_tr, y_tr, model_name=model_name, params=params)
                    metrics = pipeline.evaluate(model, X_val, y_val, task=task)
                    info: dict[str, Any] = {
                        "model_name": model_name,
                        "metrics": metrics,
                        "mlflow_run_id": pipeline.mlflow_run_id,
                        "params_used": params,
                    }
                    if state.category == "tabular_ml":
                        save = pipeline.save_model(model, state.job_id, model_name)
                        info.update(save)
                    trained.append(info)
                except Exception as e:
                    self.logger.warning("train_failed", model=model_name, error=str(e))
            return state.with_update(trained_models=trained, next_agent="training_monitor")

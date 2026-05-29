"""agents.metrics_aggregator — MetricsAggregatorAgent (Day08).

후보별 메트릭 정규화 후 best_model 선정.
classification : val_f1 최대
regression     : val_r2 최대
forecasting    : val_rmse 최소
anomaly        : val_auc 최대
"""
from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

CATEGORY_OBJECTIVE = {
    "tabular_ml": ("val_f1", "max"),
    "tabular_dl": ("val_f1", "max"),
    "timeseries": ("val_rmse", "min"),
    "anomaly_detection": ("val_auc", "max"),
}


class MetricsAggregatorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            metric_key, direction = CATEGORY_OBJECTIVE.get(state.category, ("val_f1", "max"))
            scored: list[tuple[float, dict[str, Any]]] = []
            for m in state.trained_models:
                v = (m.get("metrics") or {}).get(metric_key)
                if v is None:
                    continue
                scored.append((float(v), m))
            if not scored:
                return state.with_update(
                    error=f"no model scored {metric_key}",
                    next_agent="error_recovery",
                )
            scored.sort(key=lambda x: x[0], reverse=(direction == "max"))
            best = dict(scored[0][1])
            best["is_best"] = True
            best["objective_metric"] = metric_key
            best["objective_value"] = scored[0][0]
            new_extras = dict(state.category_extras or {})
            if state.category in ("tabular_ml", "tabular_dl"):
                tab = dict(new_extras.get("tabular", {}) or {})
                pbm = tab.get("predictions_by_model") or {}
                best_pred = pbm.get(best.get("model_name"))
                if best_pred and any(
                    best_pred.get(k) is not None for k in ("y_true", "y_pred", "y_prob")
                ):
                    tab["predictions"] = best_pred
                    new_extras["tabular"] = tab
            return state.with_update(
                best_model=best, category_extras=new_extras, next_agent="gate_best_model"
            )

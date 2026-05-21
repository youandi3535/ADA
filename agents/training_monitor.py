"""agents.training_monitor — TrainingMonitorAgent (Day08).

발산/NaN/과적합 신호 조기 감지. 발견 시 next_agent='error_recovery'.
"""
from __future__ import annotations

import math
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent


class TrainingMonitorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            warnings: list[str] = list(state.training_warnings)
            bad = 0
            for m in state.trained_models:
                metrics = m.get("metrics") or {}
                for k, v in metrics.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        warnings.append(f"{m['model_name']} NaN/Inf in {k}")
                        bad += 1
            if bad >= len(state.trained_models or [1]):
                return state.with_update(training_warnings=warnings,
                                         next_agent="error_recovery",
                                         error="모든 학습 모델에서 NaN/Inf")
            return state.with_update(training_warnings=warnings,
                                     next_agent="metrics_aggregator")

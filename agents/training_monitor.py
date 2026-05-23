"""agents.training_monitor — TrainingMonitorAgent (Day 7 본격화).

발산 / NaN / 시간 초과 / 메모리 압박 신호를 조기 감지하고,
심각도 따라 warning 적재 또는 next_agent='error_recovery'.

심각도 정책:
    - NaN/Inf 가 전 모델에서 발견되면 → error_recovery
    - val 메트릭이 3 연속 하락 (history 보유 시) → error_recovery
    - 학습 시간 임계치 초과 → error_recovery (config: timeout_min)
    - 메모리 사용률 ≥ 80% → 경고만 (warning) — 학습은 진행 가능

state.training_warnings 에 사람이 읽을 수 있는 한국어 라인 누적.
"""

from __future__ import annotations

import math
from typing import Any

from ada.core.config import settings
from ada.core.state import PipelineState
from agents.base import BaseAgent

# 모델 평가 기준 메트릭 (낮을수록 좋은 메트릭 vs 높을수록 좋은 메트릭)
HIGHER_IS_BETTER: tuple[str, ...] = (
    "val_accuracy",
    "val_f1",
    "val_precision",
    "val_recall",
    "val_roc_auc",
    "val_r2",
    "val_auc",
    "val_pr_at_10",
)
LOWER_IS_BETTER: tuple[str, ...] = ("val_rmse", "val_mae", "val_mape", "val_loss")


def _memory_percent() -> float | None:
    """현재 프로세스 또는 시스템 메모리 사용률(%) — psutil 없으면 None."""
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().percent)
    except Exception:
        return None


def _is_diverging(history: list[float], min_len: int = 3) -> bool:
    """history 가 모두 단조 하락인지 (higher-is-better 메트릭 기준)."""
    if len(history) < min_len:
        return False
    last = history[-min_len:]
    return all(last[i] > last[i + 1] for i in range(len(last) - 1))


class TrainingMonitorAgent(BaseAgent):
    uses_llm = False

    def __init__(
        self,
        *args: Any,
        timeout_min: int | None = None,
        memory_warn_pct: float = 80.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # 기본은 settings.pipeline_timeout_min
        self.timeout_min = timeout_min or settings.pipeline_timeout_min
        self.memory_warn_pct = memory_warn_pct

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            warnings: list[str] = list(state.training_warnings)
            nan_count = 0
            div_count = 0
            total_models = max(len(state.trained_models or []), 1)

            for m in state.trained_models:
                mn = m.get("model_name", "?")
                metrics = m.get("metrics") or {}

                # (1) NaN / Inf 체크
                for k, v in metrics.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        warnings.append(f"{mn} 의 {k} 가 NaN/Inf 입니다")
                        nan_count += 1

                # (2) 발산 체크 — metrics_history (있으면) 또는 epoch_log
                history: list[float] = []
                hist_field = m.get("val_history") or m.get("metrics_history") or m.get("epoch_log") or []
                if isinstance(hist_field, list) and hist_field:
                    # higher_is_better 키 우선
                    target_key = next((k for k in HIGHER_IS_BETTER if k in metrics), None)
                    if target_key:
                        for ep in hist_field:
                            if isinstance(ep, dict) and target_key in ep:
                                try:
                                    history.append(float(ep[target_key]))
                                except Exception:
                                    pass
                    if _is_diverging(history):
                        warnings.append(f"{mn} 의 {target_key} 가 3 epoch 연속 하락 — 발산 의심")
                        div_count += 1

            # (3) 학습 시간 초과 — state.started_at 기준 (개략)
            try:
                from datetime import datetime, timezone

                started = state.started_at
                if started.tzinfo is None:
                    elapsed = (datetime.utcnow() - started).total_seconds() / 60.0
                else:
                    elapsed = (datetime.now(timezone.utc) - started).total_seconds() / 60.0
                if elapsed > self.timeout_min:
                    warnings.append(f"학습 경과 시간 {elapsed:.1f}분 — 타임아웃 {self.timeout_min}분 초과")
                    return state.with_update(
                        training_warnings=warnings,
                        error="학습 타임아웃 초과",
                        next_agent="error_recovery",
                    )
            except Exception:
                pass

            # (4) 메모리 80% 경고 — fail 아닌 warning
            mem_pct = _memory_percent()
            if mem_pct is not None and mem_pct >= self.memory_warn_pct:
                warnings.append(f"메모리 사용률 {mem_pct:.1f}% — 임계 {self.memory_warn_pct:.0f}% 초과")

            # 심각도 결정
            if nan_count >= total_models:
                return state.with_update(
                    training_warnings=warnings,
                    error="모든 학습 모델에서 NaN/Inf",
                    next_agent="error_recovery",
                )
            if div_count >= total_models:
                return state.with_update(
                    training_warnings=warnings,
                    error="모든 학습 모델에서 val 메트릭 발산",
                    next_agent="error_recovery",
                )

            return state.with_update(training_warnings=warnings, next_agent="metrics_aggregator")

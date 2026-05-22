"""agents.handlers.timeseries.preprocessor — 시계열 전처리 (CS 담당).

- plan(state): LLM 실패시 fallback 계획
- apply(df, plan, state): lag·rolling 등 시계열 step 적용

Day 1 (CS): diff·boxcox·exog 추가 예정.
"""

from __future__ import annotations

from typing import Any


def plan(state: Any) -> list[dict[str, Any]]:
    """시계열 기본 전처리 계획. 시간 누설 가드 포함."""
    return [
        {"name": "lag_features", "lags": [1, 7, 14], "needs_review": False, "leakage_safe": True},
        {"name": "rolling_mean", "windows": [7, 14], "needs_review": False, "leakage_safe": True},
    ]


def apply(df: Any, plan_steps: list[dict[str, Any]], state: Any) -> Any:
    """시계열 전용 step 적용 — 미래값 누설 금지 (shift(1) 후 rolling)."""
    out = df.copy()
    target = state.target_column
    if not target or target not in out.columns:
        return out

    for step in plan_steps:
        name = step.get("name")
        try:
            if name == "lag_features":
                for lag in step.get("lags", [1, 7, 14]):
                    out[f"{target}_lag{lag}"] = out[target].shift(lag)
            elif name == "rolling_mean":
                for w in step.get("windows", [7, 14]):
                    out[f"{target}_rmean{w}"] = out[target].shift(1).rolling(w).mean()
        except Exception:
            continue
    return out

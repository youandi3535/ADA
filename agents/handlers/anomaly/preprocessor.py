"""agents.handlers.anomaly.preprocessor — 이상탐지 전처리 (NY 담당)."""

from __future__ import annotations

from typing import Any


def plan(state: Any) -> list[dict[str, Any]]:
    """기본: 표준화 + Winsorize 5%."""
    return [
        {"name": "standard_scale", "needs_review": False},
        {"name": "winsorize", "quantile": 0.05, "needs_review": False},
    ]


def apply(df: Any, plan_steps: list[dict[str, Any]], state: Any) -> Any:
    """이상탐지 전용 step. 표준화 + winsorize."""
    import numpy as np  # noqa: WPS433
    from sklearn.preprocessing import StandardScaler

    out = df.copy()
    target = state.target_column

    for step in plan_steps:
        name = step.get("name")
        try:
            if name == "standard_scale":
                num_cols = [c for c in out.select_dtypes(include=[np.number]).columns if c != target]
                if num_cols:
                    out[num_cols] = StandardScaler().fit_transform(out[num_cols])
            elif name == "winsorize":
                q = step.get("quantile", 0.05)
                num_cols = [c for c in out.select_dtypes(include=[np.number]).columns if c != target]
                for c in num_cols:
                    lo, hi = out[c].quantile(q), out[c].quantile(1 - q)
                    out[c] = out[c].clip(lo, hi)
        except Exception:
            continue
    return out

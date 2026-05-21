"""agents.handlers.tabular.preprocessor — 정형 ML/DL 전처리 (C 담당).

Day 2 (C): target_encoding 정교화 + SMOTE 옵션 + VIF 기반 drop.
"""
from __future__ import annotations

from typing import Any


def plan(state: Any) -> list[dict[str, Any]]:
    return [
        {"name": "impute_numeric", "strategy": "median", "needs_review": False},
        {"name": "impute_categorical", "strategy": "most_frequent", "needs_review": False},
        {"name": "encode_categorical", "method": "one_hot",
         "high_card_threshold": 50, "needs_review": True},
        {"name": "scale_numeric", "method": "robust", "needs_review": False},
    ]


def apply(df: Any, plan_steps: list[dict[str, Any]], state: Any) -> Any:
    """impute/encode/scale 정형 step."""
    import numpy as np  # noqa: WPS433
    import pandas as pd  # noqa: WPS433

    out = df.copy()
    target = state.target_column

    for step in plan_steps:
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
        except Exception:
            continue
    return out

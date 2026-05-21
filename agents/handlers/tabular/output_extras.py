"""agents.handlers.tabular.output_extras — 정형 산출물 추가 (C 담당)."""
from __future__ import annotations

from typing import Any


def assets(state: Any) -> dict[str, Any]:
    color = "#2563eb" if state.category == "tabular_ml" else "#0891b2"
    label = "정형 ML" if state.category == "tabular_ml" else "정형 DL"
    return {
        "category_label": label,
        "category_color": color,
        "extra_charts": [],   # Day 9 (C): ROC + Calibration + Confusion Matrix
        "extra_tables": [],
    }

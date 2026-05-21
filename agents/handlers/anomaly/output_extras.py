"""agents.handlers.anomaly.output_extras — 이상탐지 산출물 추가 (B 담당)."""
from __future__ import annotations

from typing import Any


def assets(state: Any) -> dict[str, Any]:
    return {
        "category_label": "이상탐지",
        "category_color": "#dc2626",   # 빨강 (v2 4색)
        "extra_charts": [],            # Day 9 에서 top-N 이상치 분포 추가
        "extra_tables": [],            # Day 9 에서 top-N 이상치 표 추가
    }

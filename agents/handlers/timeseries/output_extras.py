"""agents.handlers.timeseries.output_extras — 시계열 산출물 추가 자산 (CS 담당).

OUT-01(PPT) / OUT-04(HTML) 에 임베드할 시계열 전용 차트 / 표.
Day 9 (CS): 예측 곡선 + 신뢰구간 + STL 4단 그래프.
"""

from __future__ import annotations

from typing import Any


def assets(state: Any) -> dict[str, Any]:
    """ReportComposer 가 각 산출물 생성기에 전달하는 추가 자산."""
    return {
        "category_label": "시계열",
        "category_color": "#16a34a",  # 초록 (v2 4색)
        "extra_charts": [],  # Day 9 에서 실제 forecast plot 채움
        "extra_tables": [],
    }

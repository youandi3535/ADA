"""outputs.plotly_chart — OUT-04 HTML 대시보드용 Plotly 차트 (Day15 R-1008).

OUT-04 가 Plotly inline HTML 을 옵션으로 사용할 수 있게 한다.
Chart.js 가 기본이며, 데이터가 크면 Plotly로 자동 분기.
"""

from __future__ import annotations

import json


def metrics_bar_html(metrics: dict[str, float], accent: str = "#2563eb") -> str:
    """Plotly bar chart inline JSON 만 반환 (대시보드에서 plotly.js 로 렌더)."""
    labels = [k for k, v in metrics.items() if isinstance(v, (int, float))]
    values = [round(float(metrics[k]), 4) for k in labels]
    data = [
        {
            "type": "bar",
            "x": labels,
            "y": values,
            "marker": {"color": accent},
        }
    ]
    return json.dumps(data)


def has_plotly() -> bool:
    try:
        import plotly  # noqa: WPS433, F401

        return True
    except Exception:
        return False

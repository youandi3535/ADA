"""agents.handlers.timeseries.eda — 시계열 EDA 차트 (CS 담당).

기본: 시계열 plot + 결측 막대.
Day 1 (CS): ACF/PACF/STL/seasonality heatmap 추가 예정.
"""

from __future__ import annotations

from typing import Any


def charts(df: Any, state: Any) -> list[str]:
    """시계열 차트 PNG 경로 목록."""
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    from agents.handlers.common.shared import save_chart_to_minio

    paths: list[str] = []
    target = state.target_column

    # 1) 결측 막대
    try:
        miss = df.isnull().mean().sort_values(ascending=False).head(20)
        if not miss.empty:
            fig, ax = plt.subplots(figsize=(8, 4))
            miss.plot(kind="barh", ax=ax)
            ax.set_title("Missing rate (top 20) — timeseries")
            paths.append(save_chart_to_minio(fig, kind="timeseries/missing", job_id=state.job_id))
    except Exception:
        pass

    # 2) 시계열 line
    if target and target in df.columns:
        try:
            fig, ax = plt.subplots(figsize=(10, 3))
            df[target].plot(ax=ax)
            ax.set_title(f"{target} over time")
            paths.append(save_chart_to_minio(fig, kind="timeseries/line", job_id=state.job_id))
        except Exception:
            pass

    return paths

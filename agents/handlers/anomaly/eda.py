"""agents.handlers.anomaly.eda — 이상탐지 EDA (NY 담당)."""

from __future__ import annotations

from typing import Any


def charts(df: Any, state: Any) -> list[str]:
    """이상탐지 차트 — 결측 + 박스플롯."""
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433
    import numpy as np  # noqa: WPS433

    from agents.handlers.common.shared import save_chart_to_minio

    paths: list[str] = []

    # 1) 결측
    try:
        miss = df.isnull().mean().sort_values(ascending=False).head(20)
        if not miss.empty:
            fig, ax = plt.subplots(figsize=(8, 4))
            miss.plot(kind="barh", ax=ax)
            ax.set_title("Missing rate (top 20) — anomaly")
            paths.append(save_chart_to_minio(fig, kind="anomaly/missing", job_id=state.job_id))
    except Exception:
        pass

    # 2) 박스플롯 — outlier 시각화 (수치 컬럼 top6)
    num_cols = df.select_dtypes(include=[np.number]).columns[:6]
    if len(num_cols) >= 1:
        try:
            fig, ax = plt.subplots(figsize=(10, 4))
            df[num_cols].plot(kind="box", ax=ax, vert=True)
            ax.set_title("Boxplot (outlier 시각화)")
            ax.tick_params(axis="x", rotation=30)
            paths.append(save_chart_to_minio(fig, kind="anomaly/box", job_id=state.job_id))
        except Exception:
            pass

    return paths

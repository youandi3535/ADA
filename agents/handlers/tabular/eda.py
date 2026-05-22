"""agents.handlers.tabular.eda — 정형 EDA (jh 담당)."""

from __future__ import annotations

from typing import Any


def charts(df: Any, state: Any) -> list[str]:
    """결측 / 분포 / 상관 3종."""
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    from agents.handlers.common.shared import save_chart_to_minio

    paths: list[str] = []

    # 1) 결측
    try:
        miss = df.isnull().mean().sort_values(ascending=False).head(20)
        if not miss.empty:
            fig, ax = plt.subplots(figsize=(8, 4))
            miss.plot(kind="barh", ax=ax)
            ax.set_title("Missing rate (top 20) — tabular")
            paths.append(save_chart_to_minio(fig, kind="tabular/missing", job_id=state.job_id))
    except Exception:
        pass

    # 2) 수치형 분포 grid
    num_cols = df.select_dtypes(include="number").columns[:6]
    if len(num_cols):
        try:
            fig, axes = plt.subplots(2, 3, figsize=(12, 6))
            for i, c in enumerate(num_cols):
                ax = axes[i // 3, i % 3]
                df[c].plot(kind="hist", ax=ax, bins=30)
                ax.set_title(str(c))
            fig.tight_layout()
            paths.append(save_chart_to_minio(fig, kind="tabular/hist", job_id=state.job_id))
        except Exception:
            pass

    # 3) 상관관계 히트맵
    if len(num_cols) >= 2:
        try:
            corr = df[num_cols].corr()
            fig, ax = plt.subplots(figsize=(6, 5))
            im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu")
            ax.set_xticks(range(len(corr.columns)))
            ax.set_yticks(range(len(corr.columns)))
            ax.set_xticklabels(corr.columns, rotation=45, ha="right")
            ax.set_yticklabels(corr.columns)
            fig.colorbar(im, ax=ax)
            ax.set_title("Correlation")
            paths.append(save_chart_to_minio(fig, kind="tabular/corr", job_id=state.job_id))
        except Exception:
            pass

    return paths

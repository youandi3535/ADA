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

    # 4) Day 11 (jh) — target ↔ feature 관계 차트
    #    분류 : class별 boxplot grid (수치 피처 6개)
    #    회귀 : scatter + 회귀선 grid (수치 피처 6개)
    target = getattr(state, "target_column", None)
    if target and target in df.columns and len(num_cols):
        try:
            paths.append(_build_target_feature_chart(df, target, num_cols, state))
        except Exception:
            pass

    return [p for p in paths if p]


def _build_target_feature_chart(df: Any, target: str, num_cols: Any, state: Any) -> str | None:
    """target ↔ feature 관계 차트 — 분류면 boxplot, 회귀면 scatter+회귀선."""
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    from agents.handlers.common.shared import save_chart_to_minio

    # target 이 num_cols 에 들어가있을 수 있음 → 제외
    feature_cols = [c for c in num_cols if c != target][:6]
    if not feature_cols:
        return None

    # 분류/회귀 추정 — target unique 수
    try:
        n_unique = int(df[target].nunique(dropna=True))
        is_classification = n_unique <= 20
    except Exception:
        is_classification = False

    n_cols = 3
    n_rows = (len(feature_cols) + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(12, n_rows * 3.5), dpi=100)
    axes_flat = axes.ravel() if len(feature_cols) > 1 else [axes]

    for i, col in enumerate(feature_cols):
        ax = axes_flat[i]
        try:
            if is_classification:
                # class 별 boxplot
                groups = []
                labels = []
                for cls, sub in df.groupby(target)[col]:
                    vals = sub.dropna().values
                    if len(vals) > 0:
                        groups.append(vals)
                        labels.append(str(cls))
                if groups:
                    ax.boxplot(groups, labels=labels, patch_artist=True,
                               boxprops=dict(facecolor="#dbeafe", edgecolor="#2563eb"),
                               medianprops=dict(color="#dc2626"))
                ax.set_title(f"{col} by {target}")
                ax.tick_params(axis="x", rotation=30)
            else:
                # scatter + 회귀선
                x = df[col].dropna()
                y = df[target].loc[x.index]
                ax.scatter(x, y, alpha=0.4, s=12, color="#2563eb")
                # 회귀선
                if len(x) >= 2 and x.std() > 0:
                    slope, intercept = np.polyfit(x, y, 1)
                    xs = np.linspace(x.min(), x.max(), 100)
                    ax.plot(xs, slope * xs + intercept, color="#dc2626", lw=1.5)
                ax.set_xlabel(col)
                ax.set_ylabel(target)
                ax.set_title(f"{col} vs {target}")
            ax.grid(True, alpha=0.3)
        except Exception:
            ax.set_visible(False)

    # 빈 axes 숨김
    for j in range(len(feature_cols), len(axes_flat)):
        axes_flat[j].set_visible(False)

    fig.suptitle(f"Target ↔ Feature 관계 ({'분류' if is_classification else '회귀'})", fontsize=12)
    fig.tight_layout()
    return save_chart_to_minio(fig, kind="tabular/target_feature", job_id=state.job_id)

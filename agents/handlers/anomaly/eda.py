"""agents.handlers.anomaly.eda — 이상탐지 EDA (NY 담당, Day 3 v3).

3 차트:
  ① feature 분포 (수치 컬럼 top 6 히스토그램)
  ② PCA 산점 (Day 2 X_processed top 2 PC) — PCA skip 시 fallback (D6)
  ③ 시간축 anomaly score (미니 IForest n_estimators=50, D2)

진입함수 (dispatcher 자동 등록):
  - charts(df, state) -> list[str]   MinIO 경로 list (0~3)

DoD: MinIO `eda/anomaly/{job}/*.png` 3 종 + pytest 그린.

의심 검증 결정 6 (셜록홈즈):
  D1 차트 3 종 (팀10일 그대로)
  D2 시간축 점수: 미니 IForest n_estimators=50
  D3 matplotlib
  D4 PNG
  D5 MinIO 경로
  D6 PCA skip fallback: Day 1 isolation top 2 + RobustScaler
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
CHART_DPI = 100
CHART_FIGSIZE_WIDE = (12, 4)
CHART_FIGSIZE_SQUARE = (8, 6)
FEATURE_DIST_TOP_K = 6
MINI_IFOREST_N_ESTIMATORS = 50  # ★ D2
MINI_IFOREST_RANDOM_STATE = 42
SCATTER_POINT_SIZE = 10
SCATTER_ALPHA = 0.6


# ── 헬퍼: matplotlib Agg 백엔드 강제 ──────────────────────────────
def _ensure_matplotlib_agg():
    import matplotlib

    matplotlib.use("Agg")


# ── ① feature 분포 ───────────────────────────────────────────────
def _chart_feature_distribution(df: Any, job_id: str) -> str | None:
    """수치 컬럼 top K 의 히스토그램 (분산 큰 순)."""
    import matplotlib.pyplot as plt
    import numpy as np

    from agents.handlers.common.shared import save_chart_to_minio

    num_cols = df.select_dtypes(include=[np.number]).columns
    if len(num_cols) == 0:
        return None

    variances = df[num_cols].var().nlargest(FEATURE_DIST_TOP_K)
    cols = variances.index.tolist()

    n = len(cols)
    n_cols_subplot = min(3, n)
    n_rows_subplot = (n + n_cols_subplot - 1) // n_cols_subplot

    fig, axes = plt.subplots(
        n_rows_subplot,
        n_cols_subplot,
        figsize=(4 * n_cols_subplot, 3 * n_rows_subplot),
        dpi=CHART_DPI,
    )
    axes = axes.flatten() if n > 1 else [axes]

    for i, c in enumerate(cols):
        s = df[c].dropna()
        bins = max(10, int(np.ceil(np.log2(max(len(s), 2)) + 1)))
        axes[i].hist(s, bins=bins, color="steelblue", alpha=0.7)
        axes[i].set_title(f"{c} (var={variances[c]:.2f})", fontsize=10)
        axes[i].grid(axis="y", alpha=0.3)

    for j in range(n, len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("Feature Distribution (top variance)", fontsize=12)
    fig.tight_layout()

    return save_chart_to_minio(fig, kind="anomaly/feature_dist", job_id=job_id)


# ── ② PCA 산점 (Day 2 결과 사용) ──────────────────────────────────
def _chart_pca_scatter(df: Any, state: Any, job_id: str) -> str | None:
    """Day 2 의 X_processed[:, 0:2] 산점. PCA skip 시 fallback (D6)."""
    import matplotlib.pyplot as plt
    from sklearn.ensemble import IsolationForest

    from agents.handlers.common.shared import save_chart_to_minio

    pp = state.category_extras.get("anomaly", {}).get("preprocessing", {}) or {}
    X = pp.get("X_processed")
    pca = pp.get("pca")

    if pca is None or X is None or X.shape[1] < 2:
        return _chart_pca_scatter_fallback(df, state, job_id)

    iso = IsolationForest(
        n_estimators=MINI_IFOREST_N_ESTIMATORS,
        random_state=MINI_IFOREST_RANDOM_STATE,
        contamination="auto",
    )
    iso.fit(X)
    is_anomaly = iso.predict(X) == -1

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE_SQUARE, dpi=CHART_DPI)
    ax.scatter(
        X[~is_anomaly, 0],
        X[~is_anomaly, 1],
        s=SCATTER_POINT_SIZE,
        alpha=SCATTER_ALPHA,
        c="steelblue",
        label="normal",
    )
    ax.scatter(
        X[is_anomaly, 0],
        X[is_anomaly, 1],
        s=SCATTER_POINT_SIZE * 2,
        alpha=0.8,
        c="crimson",
        label="anomaly (mini IForest)",
    )
    ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]:.1%})")
    ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]:.1%})")
    ax.set_title("PCA Scatter (top 2 components)")
    ax.legend(loc="best", fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()

    return save_chart_to_minio(fig, kind="anomaly/pca_scatter", job_id=job_id)


# ── ② fallback ★ D6 ────────────────────────────────────────────────
def _chart_pca_scatter_fallback(df: Any, state: Any, job_id: str) -> str | None:
    """PCA skip 시 fallback: Day 1 isolation top 2 dim + 자체 RobustScaler."""
    import matplotlib.pyplot as plt
    from sklearn.preprocessing import RobustScaler

    from agents.handlers.common.shared import save_chart_to_minio

    profile = getattr(state, "data_profile", None) or {}
    iso_depth = profile.get("isolation_depth_per_dim", {})
    if len(iso_depth) < 2:
        return None

    top2 = sorted(iso_depth.items(), key=lambda x: x[1], reverse=True)[:2]
    cols = [c for c, _ in top2]

    X = df[cols].dropna().values
    if len(X) < 2:
        return None
    X_scaled = RobustScaler().fit_transform(X)

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE_SQUARE, dpi=CHART_DPI)
    ax.scatter(
        X_scaled[:, 0],
        X_scaled[:, 1],
        s=SCATTER_POINT_SIZE,
        alpha=SCATTER_ALPHA,
        c="steelblue",
    )
    ax.set_xlabel(f"{cols[0]} (scaled, Day 1 anomaly top-1)")
    ax.set_ylabel(f"{cols[1]} (scaled, Day 1 anomaly top-2)")
    ax.set_title("Anomaly Scatter (PCA skip fallback)")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    return save_chart_to_minio(fig, kind="anomaly/pca_scatter_fallback", job_id=job_id)


# ── ③ 시간축 anomaly ★ D2 ────────────────────────────────────────
def _chart_time_anomaly(df: Any, state: Any, job_id: str) -> str | None:
    """시간축 anomaly score (미니 IForest n_estimators=50)."""
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import IsolationForest

    from agents.handlers.common.shared import save_chart_to_minio

    profile = getattr(state, "data_profile", None) or {}
    if not profile.get("has_time_column"):
        return None
    # profiler emits `time_column_candidates` (list), NOT `time_column` — use first element
    _candidates = profile.get("time_column_candidates") or []
    time_col = _candidates[0] if _candidates else None
    if time_col is None or time_col not in df.columns:
        return None

    num_df = df.select_dtypes(include=[np.number]).dropna()
    if len(num_df) < 10:
        return None

    iso = IsolationForest(
        n_estimators=MINI_IFOREST_N_ESTIMATORS,
        random_state=MINI_IFOREST_RANDOM_STATE,
        contamination="auto",
    )
    iso.fit(num_df)
    scores = -iso.decision_function(num_df)

    time_series = pd.to_datetime(df.loc[num_df.index, time_col])
    sort_idx = time_series.argsort()
    time_sorted = time_series.iloc[sort_idx]
    scores_sorted = scores[sort_idx.values]

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE_WIDE, dpi=CHART_DPI)
    ax.plot(time_sorted, scores_sorted, color="crimson", linewidth=0.8)
    ax.set_xlabel("Time")
    ax.set_ylabel("Anomaly Score (mini IForest)")
    ax.set_title("Time-series Anomaly Score (Day 3 EDA mini IForest)")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()

    return save_chart_to_minio(fig, kind="anomaly/time_anomaly", job_id=job_id)


# ── 공개 진입점 ───────────────────────────────────────────────────
def charts(df: Any, state: Any) -> list[str]:
    """3 차트 생성 + MinIO 업로드 + 경로 list 반환.

    한 차트 실패가 전체 실패로 번지지 않게 try/except 보장.
    """
    _ensure_matplotlib_agg()

    job_id = getattr(state, "job_id", "unknown")
    paths: list[str] = []

    try:
        p = _chart_feature_distribution(df, job_id)
        if p:
            paths.append(p)
    except Exception:
        pass

    try:
        p = _chart_pca_scatter(df, state, job_id)
        if p:
            paths.append(p)
    except Exception:
        pass

    try:
        p = _chart_time_anomaly(df, state, job_id)
        if p:
            paths.append(p)
    except Exception:
        pass

    return paths

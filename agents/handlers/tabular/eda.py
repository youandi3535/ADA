"""agents.handlers.tabular.eda — 정형 EDA (jh 담당).

2026-06-11 — charts() 가 (paths, meta) 튜플 반환으로 확장.
meta 는 EDAChart 필드 (x/finding/numbers/title_ko/chart_type) 로,
eda_agent 가 ReportContext ⑤ eda.charts 에 적립 → PPT skeleton 이
"Feature 1" 플레이스홀더 대신 실제 피처명·수치를 인용.
"""

from __future__ import annotations

from typing import Any


def charts(df: Any, state: Any) -> tuple[list[str], list[dict]]:
    """결측 / 분포 / 상관 / target 관계 4종 — (paths, meta) 반환."""
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    from agents.handlers.common.shared import save_chart_to_minio

    paths: list[str] = []
    meta: list[dict] = []

    # 1) 결측
    try:
        miss_all = df.isnull().mean().sort_values(ascending=False)
        miss = miss_all.head(20)
        if not miss.empty:
            fig, ax = plt.subplots(figsize=(8, 4))
            miss.plot(kind="barh", ax=ax)
            ax.set_title("Missing rate (top 20) — tabular")
            p = save_chart_to_minio(fig, kind="tabular/missing", job_id=state.job_id)
            if p:
                paths.append(p)
                top = miss_all[miss_all > 0].head(3)
                if not top.empty:
                    finding = " · ".join(f"{c} {v:.1%}" for c, v in top.items()) + " 결측"
                    x_col = str(top.index[0])
                else:
                    finding = "전 컬럼 결측 0% — 결측 처리 불필요"
                    x_col = None
                meta.append(
                    {
                        "path": p,
                        "chart_type": "bar",
                        "x": x_col,
                        "title_ko": "결측률 상위 피처",
                        "finding": finding,
                        "numbers": [{"name": str(c), "value": round(float(v), 4)} for c, v in top.items()],
                    }
                )
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
            p = save_chart_to_minio(fig, kind="tabular/hist", job_id=state.job_id)
            if p:
                paths.append(p)
                meta.append(_hist_meta(df, num_cols, p))
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
            p = save_chart_to_minio(fig, kind="tabular/corr", job_id=state.job_id)
            if p:
                paths.append(p)
                meta.append(_corr_meta(corr, p))
        except Exception:
            pass

    # 4) Day 11 (jh) — target ↔ feature 관계 차트
    target = getattr(state, "target_column", None)
    if target and target in df.columns and len(num_cols):
        try:
            p = _build_target_feature_chart(df, target, num_cols, state)
            if p:
                paths.append(p)
                meta.append(_target_meta(df, target, num_cols, p))
        except Exception:
            pass

    # 5) P2-1 (2026-06-16) — 이상치 진단 (IQR 1.5 기준 피처별 이상치 비율)
    try:
        p = _build_outlier_chart(df, state)
        if p:
            paths.append(p)
            meta.append(_outlier_meta(df, p))
    except Exception:
        pass

    paths = [p for p in paths if p]
    meta = [m for m in meta if m.get("path") in set(paths)]
    return paths, meta


# ==============================================================
# meta 계산 — 차트별 실수치 finding (2026-06-11 jh)
# ==============================================================


def _hist_meta(df: Any, num_cols: Any, path: str) -> dict:
    """분포 grid — 왜도 최대 피처를 대표로."""
    finding = f"수치 피처 {len(num_cols)}개 분포"
    x_col = str(num_cols[0])
    numbers: list[dict] = []
    try:
        skews = df[num_cols].skew(numeric_only=True).abs().sort_values(ascending=False)
        top = skews.index[0]
        x_col = str(top)
        s = df[top]
        finding = f"{top} 분포 비대칭 (왜도 {df[top].skew():.1f}) — 중앙값 {s.median():.3g} vs 평균 {s.mean():.3g}"
        numbers = [
            {"name": f"{top} median", "value": round(float(s.median()), 3)},
            {"name": f"{top} mean", "value": round(float(s.mean()), 3)},
            {"name": f"{top} skew", "value": round(float(s.skew()), 2)},
        ]
    except Exception:
        pass
    return {
        "path": path,
        "chart_type": "hist",
        "x": x_col,
        "title_ko": "수치형 분포",
        "finding": finding,
        "numbers": numbers,
    }


def _corr_meta(corr: Any, path: str) -> dict:
    """상관 히트맵 — |r| 최대 쌍."""
    finding = "수치 피처 간 상관 구조"
    x_col = None
    numbers: list[dict] = []
    try:
        pairs = []
        cols = list(corr.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                r = float(corr.iloc[i, j])
                if r == r:  # NaN 제외
                    pairs.append((abs(r), r, cols[i], cols[j]))
        pairs.sort(reverse=True)
        if pairs:
            _, r, a, b = pairs[0]
            x_col = str(a)
            finding = f"{a} ↔ {b} 상관 최대 (r={r:.2f})"
            numbers = [{"name": f"{a}↔{b}", "value": round(rr, 2)} for _, rr, a, b in pairs[:3]]
    except Exception:
        pass
    return {
        "path": path,
        "chart_type": "corr_heatmap",
        "x": x_col,
        "title_ko": "변수 간 상관",
        "finding": finding,
        "numbers": numbers,
    }


def _target_meta(df: Any, target: str, num_cols: Any, path: str) -> dict:
    """target 관계 — 분류면 그룹별 격차 최대 신호 (범주형 포함), 회귀면 최대 상관."""
    finding = f"{target} 와 피처 관계"
    x_col = None
    numbers: list[dict] = []
    try:
        n_unique = int(df[target].nunique(dropna=True))
        is_classification = n_unique <= 20

        if is_classification and n_unique == 2:
            # 이진 분류 — 범주형 피처 중 양성률 격차 최대 (예: Sex 74% vs 19%)
            pos = sorted(df[target].dropna().unique())[-1]
            best = None
            cat_cols = [
                c
                for c in df.columns
                if c != target and df[c].nunique(dropna=True) <= 10 and not str(df[c].dtype).startswith("float")
            ]
            for c in cat_cols:
                try:
                    rates = df.groupby(c)[target].apply(lambda s: (s == pos).mean())
                    counts = df[c].value_counts()
                    rates = rates[counts[rates.index] >= max(10, len(df) * 0.01)]
                    if len(rates) >= 2:
                        gap = float(rates.max() - rates.min())
                        if best is None or gap > best[0]:
                            best = (gap, c, rates)
                except Exception:
                    continue
            if best:
                gap, c, rates = best
                hi, lo = rates.idxmax(), rates.idxmin()
                x_col = str(c)
                finding = f"{c} 가 최대 격차 — {hi} {rates.max():.0%} vs {lo} {rates.min():.0%} ({gap * 100:.0f}%p)"
                numbers = [{"name": f"{c}={k}", "value": round(float(v), 3)} for k, v in rates.items()][:4]
        elif not is_classification:
            # 회귀 — target 과 상관 최대 수치 피처
            feats = [c for c in num_cols if c != target]
            if feats:
                corr_t = df[feats + [target]].corr()[target].drop(target).dropna()
                if not corr_t.empty:
                    top = corr_t.abs().idxmax()
                    x_col = str(top)
                    finding = f"{top} 가 {target} 와 최대 상관 (r={corr_t[top]:.2f})"
                    numbers = [
                        {"name": str(k), "value": round(float(v), 2)}
                        for k, v in corr_t.abs().sort_values(ascending=False).head(3).items()
                    ]
    except Exception:
        pass
    return {
        "path": path,
        "chart_type": "box" if x_col else "scatter",
        "x": x_col,
        "y": target,
        "title_ko": f"{target} 결정 요인",
        "finding": finding,
        "numbers": numbers,
    }


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
                    ax.boxplot(
                        groups,
                        labels=labels,
                        patch_artist=True,
                        boxprops=dict(facecolor="#dbeafe", edgecolor="#2563eb"),
                        medianprops=dict(color="#dc2626"),
                    )
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


# ==============================================================
# P2-1 (2026-06-16) — 이상치 진단 (IQR 1.5)
# ==============================================================


def _outlier_ratios(df: Any) -> dict[str, float]:
    """수치 피처별 IQR(1.5) 밖 비율. iqr=0(상수성)은 0.0, 표본<4는 제외."""
    ratios: dict[str, float] = {}
    for c in df.select_dtypes(include="number").columns:
        s = df[c].dropna()
        if len(s) < 4:
            continue
        q1 = float(s.quantile(0.25))
        q3 = float(s.quantile(0.75))
        iqr = q3 - q1
        if iqr <= 0:
            ratios[str(c)] = 0.0
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        ratios[str(c)] = float(((s < lo) | (s > hi)).mean())
    return ratios


def _build_outlier_chart(df: Any, state: Any) -> str | None:
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433
    import pandas as pd  # noqa: WPS433

    from agents.handlers.common.shared import save_chart_to_minio

    ratios = _outlier_ratios(df)
    if not ratios:
        return None
    sr = pd.Series(ratios).sort_values(ascending=False).head(15)
    if float(sr.sum()) == 0.0:
        return None  # 이상치 0 → 차트 생략(노이즈 방지)
    fig, ax = plt.subplots(figsize=(8, 4))
    sr.iloc[::-1].plot(kind="barh", ax=ax, color="#f59e0b")
    ax.set_title("Outlier rate by feature (IQR 1.5) — tabular")
    ax.set_xlabel("outlier ratio")
    fig.tight_layout()
    return save_chart_to_minio(fig, kind="tabular/outlier", job_id=state.job_id)


def _outlier_meta(df: Any, path: str) -> dict:
    finding = "IQR(1.5) 기반 이상치 진단"
    x_col = None
    numbers: list[dict] = []
    try:
        import pandas as pd  # noqa: WPS433

        ratios = _outlier_ratios(df)
        if ratios:
            sr = pd.Series(ratios).sort_values(ascending=False)
            top = str(sr.index[0])
            x_col = top
            if float(sr.iloc[0]) > 0:
                finding = f"{top} 이상치 {sr.iloc[0]:.1%} (IQR 1.5) — 상위 피처 점검·윈저라이즈 권고"
            else:
                finding = "IQR 1.5 기준 이상치 거의 없음 — 분포 안정"
            numbers = [{"name": k, "value": round(float(v), 4)} for k, v in sr.head(3).items()]
    except Exception:
        pass
    return {
        "path": path,
        "chart_type": "bar",
        "x": x_col,
        "title_ko": "이상치 진단(IQR)",
        "finding": finding,
        "numbers": numbers,
    }

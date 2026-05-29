"""agents.handlers.tabular.eda — EDA 차트 카탈로그 12종 (jh Day 3)."""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Any, Callable

_PLACEHOLDER_MSG: dict[str, str] = {
    "no_numeric": "수치형 컬럼이 부족합니다 (≥ 2 필요)",
    "no_target": "타겟 컬럼이 없습니다 (unsupervised)",
    "data_too_small": "데이터가 너무 적습니다 (n_rows ≥ 50 필요)",
    "single_class": "단일 클래스만 존재 (학습 불가)",
    "not_applicable": "이 task type에는 해당하지 않습니다",
    "import_failed": "필요한 라이브러리를 불러올 수 없습니다",
    "timed_out": "차트 생성 시간 초과",
}


@dataclass
class ChartSpec:
    name: str
    category: str
    trigger_fn: Callable[..., bool]
    score_fn: Callable[..., float]
    render_fn: Callable[..., Any]
    file_suffix: str
    fallback_on_fail: str = "skip"
    version: str = "1.0"


CHART_REGISTRY: dict[str, ChartSpec] = {}


def _reg(spec: ChartSpec) -> None:
    CHART_REGISTRY[spec.name] = spec


# ── context helpers ──────────────────────────────────────────────────────────


def _get_profile(state: Any) -> dict:
    p = getattr(state, "data_profile", None)
    return p if isinstance(p, dict) else {}


def _get_hints(state: Any) -> dict:
    h = getattr(state, "eda_hints", None)
    return h if isinstance(h, dict) else {}


def _get_artifacts(state: Any) -> dict:
    extras = getattr(state, "category_extras", {}) or {}
    return extras.get("tabular", {}).get("preprocess_artifacts", {})


def _is_classification(state: Any) -> bool:
    task = getattr(state, "task", "auto") or "auto"
    if task == "classification":
        return True
    if task == "regression":
        return False
    return state.target_column is not None


def _num_cols(df: Any, exclude: str | None = None) -> list[str]:
    import numpy as np

    cols = list(df.select_dtypes(include=[np.number]).columns)
    if exclude and exclude in cols:
        cols = [c for c in cols if c != exclude]
    return cols


def _high_card_cat_cols(df: Any, threshold: int = 10) -> list[str]:
    return [
        c for c in df.select_dtypes(include=["object", "category"]).columns if df[c].nunique(dropna=True) > threshold
    ]


def _rs(state: Any, hints: dict) -> int:
    ov = hints.get("random_state_override")
    return int(ov) if ov is not None else hash(str(state.job_id)) % (2**31)


def _le_map(state: Any) -> dict | None:
    return _get_artifacts(state).get("label_encoder")


# ── figure helpers ───────────────────────────────────────────────────────────


def _placeholder_fig(name: str, msg_key: str) -> Any:
    import matplotlib.pyplot as plt

    msg = _PLACEHOLDER_MSG.get(msg_key, msg_key)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.text(0.5, 0.5, f"{name}\n\n{msg}", ha="center", va="center", transform=ax.transAxes, fontsize=11, wrap=True)
    ax.set_title(f"[Placeholder] {name}")
    ax.axis("off")
    return fig


def _save_close(fig: Any, kind: str, job_id: str) -> str:
    import matplotlib.pyplot as plt

    from agents.handlers.common.shared import save_chart_to_minio

    try:
        return save_chart_to_minio(fig, kind=kind, job_id=job_id)
    finally:
        plt.close(fig)


# ── Chart 1: correlation_heatmap ─────────────────────────────────────────────


def _heatmap_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    return len(_num_cols(df)) >= 2


def _heatmap_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    n = len(_num_cols(df))
    if n < 5:
        return 0.6
    return 0.9 if n < 20 else 0.85


def _heatmap_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt

    num_c = _num_cols(df)
    target = state.target_column
    if target and target in df.columns and df[target].dtype.kind in "iuf" and target not in num_c:
        num_c = [target] + num_c

    n_cols = len(num_c)
    figsize_px = max(800, n_cols * 60)

    annot_thr = hints.get("heatmap_annot_threshold_override")
    if annot_thr is None:
        annot_thr = 15 if figsize_px / n_cols >= 40 else 15

    cap = hints.get("heatmap_cols_cap_override")
    if cap is None:
        cap = min(n_cols, int(figsize_px / 30))
    cap = max(cap, 2)

    clusters = profile.get("correlation_clusters")
    if clusters and isinstance(clusters, dict):
        ordered: list[str] = []
        for cl in sorted(clusters.keys()):
            for c in clusters[cl]:
                if c in num_c and c not in ordered:
                    ordered.append(c)
        for c in num_c:
            if c not in ordered:
                ordered.append(c)
        num_c = ordered

    if n_cols > cap:
        top_v = df[num_c].var().nlargest(cap)
        num_c = list(top_v.index)
        if target and target in df.columns and df[target].dtype.kind in "iuf" and target not in num_c:
            num_c = [target] + num_c[: cap - 1]
        warnings.warn(f"heatmap: capped to {cap} columns", stacklevel=2)

    sub = df[num_c].dropna(axis=1, how="all")
    sub = sub[[c for c in sub.columns if sub[c].var() > 0]]
    if sub.shape[1] < 2:
        return _placeholder_fig("correlation_heatmap", "no_numeric")

    corr = sub.corr()
    n = corr.shape[0]
    size = max(8.0, n * 0.55)
    fig, ax = plt.subplots(figsize=(size, size * 0.85))
    annot = n <= annot_thr

    try:
        import seaborn as sns

        sns.heatmap(
            corr, ax=ax, vmin=-1, vmax=1, cmap="RdBu_r", annot=annot, fmt=".2f" if annot else "", linewidths=0.3
        )
    except Exception:
        im = ax.imshow(corr.values, vmin=-1, vmax=1, cmap="RdBu_r", aspect="auto")
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(corr.columns, fontsize=8)
        fig.colorbar(im, ax=ax)

    ax.set_title("Correlation Heatmap")
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "correlation_heatmap",
        "correlation",
        _heatmap_trigger,
        _heatmap_score,
        _heatmap_render,
        "correlation_heatmap",
        fallback_on_fail="placeholder",
    )
)


# ── Chart 2: target_boxplot ──────────────────────────────────────────────────


def _boxplot_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    if not state.target_column:
        return False
    return len(_num_cols(df, exclude=state.target_column)) >= 1


def _boxplot_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.8


def _boxplot_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import pandas as pd

    target = state.target_column
    if not target or target not in df.columns:
        return _placeholder_fig("target_boxplot", "no_target")

    feat_cols = _num_cols(df, exclude=target)
    if not feat_cols:
        return _placeholder_fig("target_boxplot", "no_numeric")

    n_feats = len(feat_cols)
    top_n = hints.get("boxplot_top_n_override")
    if top_n is None:
        top_n = min(n_feats, math.ceil(2 * math.sqrt(n_feats)))
    top_n = max(1, int(top_n))

    try:
        t_series = pd.to_numeric(df[target], errors="coerce")
        corrs = df[feat_cols].corrwith(t_series).abs()
        feat_cols = corrs.nlargest(top_n).index.tolist()
    except Exception:
        vif_top = profile.get("vif_top") or []
        feat_cols = [c for c in vif_top if c in feat_cols][:top_n] or feat_cols[:top_n]

    if not feat_cols:
        return _placeholder_fig("target_boxplot", "no_numeric")

    ncols = min(4, len(feat_cols))
    nrows = math.ceil(len(feat_cols) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 3.5, nrows * 3), squeeze=False)
    axes_flat = axes.flatten()

    is_clf = _is_classification(state)
    le_map = _le_map(state)

    if is_clf:
        top_class_thr = hints.get("boxplot_multiclass_top_class", 10)
        classes = sorted(df[target].dropna().unique())
        if len(classes) > top_class_thr:
            classes = classes[:top_class_thr]
        for i, feat in enumerate(feat_cols):
            ax = axes_flat[i]
            data_grps = [df[df[target] == c][feat].dropna().values for c in classes]
            ax.boxplot(data_grps, patch_artist=True)
            labels = [str(le_map.get(c, c)) if le_map else str(c) for c in classes]
            ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=7)
            ax.set_title(str(feat), fontsize=9)
    else:
        try:
            df2 = df.copy()
            df2["_bin"] = pd.qcut(df2[target].dropna(), q=4, duplicates="drop")
            bin_labels = sorted(df2["_bin"].dropna().unique(), key=lambda x: x.left)
        except Exception:
            try:
                df2 = df.copy()
                df2["_bin"] = pd.cut(df2[target].dropna(), bins=2)
                bin_labels = sorted(df2["_bin"].dropna().unique(), key=lambda x: x.left)
            except Exception:
                return _placeholder_fig("target_boxplot", "no_target")

        for i, feat in enumerate(feat_cols):
            ax = axes_flat[i]
            grps = [df2[df2["_bin"] == b][feat].dropna().values for b in bin_labels]
            ax.boxplot(grps, patch_artist=True)
            ax.set_xticklabels([str(b) for b in bin_labels], rotation=45, ha="right", fontsize=6)
            ax.set_title(str(feat), fontsize=9)

    for j in range(len(feat_cols), len(axes_flat)):
        axes_flat[j].set_visible(False)

    fig.suptitle(f"Target Boxplot — {target}", fontsize=11)
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "target_boxplot",
        "target_relation",
        _boxplot_trigger,
        _boxplot_score,
        _boxplot_render,
        "target_boxplot",
        fallback_on_fail="placeholder",
    )
)


# ── Chart 3: class_distribution ──────────────────────────────────────────────


def _classdist_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    return bool(state.target_column) and _is_classification(state)


def _classdist_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    ratio = profile.get("class_imbalance_ratio") or 1.0
    return 0.9 if float(ratio) > 3.0 else 0.7


def _classdist_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import numpy as np

    target = state.target_column
    if not target or target not in df.columns:
        return _placeholder_fig("class_distribution", "no_target")

    counts = df[target].value_counts()
    if len(counts) <= 1:
        return _placeholder_fig("class_distribution", "single_class")

    le_map = _le_map(state)
    top_n = int(hints.get("boxplot_multiclass_top_class", 10))
    classes = counts.index.tolist()
    if len(classes) > top_n:
        counts_plot = counts[classes[:top_n]].copy()
        counts_plot["other"] = counts[classes[top_n:]].sum()
    else:
        counts_plot = counts

    labels = []
    for c in counts_plot.index:
        if c == "other":
            labels.append("other")
        else:
            labels.append(str(le_map.get(c, c)) if le_map else str(c))

    p = counts / counts.sum()
    h = float(-np.sum(p.values * np.log2(p.values.clip(1e-10))))
    h_max = math.log2(max(len(counts), 2))
    entropy_ratio = h / h_max if h_max > 0 else 1.0

    smote_meta = arts.get("smote_meta")
    fig, axes = plt.subplots(2, 2, figsize=(11, 9))

    axes[0, 0].bar(range(len(counts_plot)), counts_plot.values, color="steelblue")
    axes[0, 0].set_xticks(range(len(counts_plot)))
    axes[0, 0].set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    axes[0, 0].set_title("Class Count")
    for j, v in enumerate(counts_plot.values):
        axes[0, 0].text(j, v + 0.5, str(v), ha="center", fontsize=7)

    axes[0, 1].pie(counts_plot.values, labels=labels, autopct="%1.1f%%", startangle=90)
    ratio_txt = f"Imbalance ratio: {profile.get('class_imbalance_ratio', 'N/A')}"
    axes[0, 1].set_title(f"Class Proportion\n{ratio_txt}")

    axes[1, 0].bar(["H(class)", "H_max"], [h, h_max], color=["steelblue", "lightgray"])
    axes[1, 0].set_title(f"Entropy (ratio={entropy_ratio:.3f})")

    if smote_meta is None:
        axes[1, 1].text(
            0.5, 0.5, "SMOTE 적용 안 됨", ha="center", va="center", transform=axes[1, 1].transAxes, fontsize=12
        )
        axes[1, 1].axis("off")
    elif smote_meta.get("applied") is True:
        try:
            before = smote_meta.get("class_distribution_before", {})
            after = smote_meta.get("class_distribution_after", {})
            all_cls = sorted(set(before) | set(after))[:top_n]
            x = np.arange(len(all_cls))
            w = 0.35
            axes[1, 1].bar(x - w / 2, [before.get(c, 0) for c in all_cls], w, label="before", color="steelblue")
            axes[1, 1].bar(x + w / 2, [after.get(c, 0) for c in all_cls], w, label="after", color="coral")
            axes[1, 1].set_xticks(x)
            axes[1, 1].set_xticklabels([str(c) for c in all_cls], rotation=45, ha="right", fontsize=7)
            axes[1, 1].legend(fontsize=8)
            axes[1, 1].set_title("SMOTE Before/After")
        except Exception:
            axes[1, 1].text(0.5, 0.5, "SMOTE meta corrupt", ha="center", va="center", transform=axes[1, 1].transAxes)
            axes[1, 1].axis("off")
    else:
        axes[1, 1].text(
            0.5, 0.5, "SMOTE skip (gate 미달)", ha="center", va="center", transform=axes[1, 1].transAxes, fontsize=12
        )
        axes[1, 1].axis("off")

    fig.suptitle(f"Class Distribution — {target}", fontsize=12)
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "class_distribution",
        "imbalance",
        _classdist_trigger,
        _classdist_score,
        _classdist_render,
        "class_distribution",
        fallback_on_fail="placeholder",
    )
)


# ── Chart 4: feature_importance_preview ──────────────────────────────────────


def _importance_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    return bool(state.target_column) and len(df) >= 50


def _importance_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.85


def _importance_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import datetime
    import threading

    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    target = state.target_column
    if not target or target not in df.columns:
        return _placeholder_fig("feature_importance_preview", "no_target")
    if len(df) < 50:
        return _placeholder_fig("feature_importance_preview", "data_too_small")

    n_rows, n_total_feats = df.shape

    try:
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.preprocessing import LabelEncoder
    except Exception:
        return _placeholder_fig("feature_importance_preview", "import_failed")

    X = df.select_dtypes(include=[np.number]).drop(columns=[target], errors="ignore").fillna(0)
    if X.shape[1] == 0:
        return _placeholder_fig("feature_importance_preview", "no_numeric")

    y_raw = df[target]
    is_clf = _is_classification(state)

    rs = _rs(state, hints)
    n_est = int(hints.get("rf_n_estimators_override") or min(100, max(30, n_rows // 100)))
    max_depth = int(hints.get("rf_max_depth_override") or min(10, max(2, math.ceil(math.log2(max(n_rows, 2))))))
    timeout = float(hints.get("importance_timeout_override") or max(5.0, n_rows * 0.001 + n_total_feats * 0.1))

    if is_clf:
        le = LabelEncoder()
        try:
            y = le.fit_transform(y_raw.astype(str))
        except Exception:
            y = y_raw.values
        if len(np.unique(y)) < 2:
            return _placeholder_fig("feature_importance_preview", "single_class")
        model = RandomForestClassifier(n_estimators=n_est, max_depth=max_depth, random_state=rs, n_jobs=-1)
        metric_name = "f1_macro"
    else:
        y = pd.to_numeric(y_raw, errors="coerce").fillna(0).values
        model = RandomForestRegressor(n_estimators=n_est, max_depth=max_depth, random_state=rs, n_jobs=-1)
        metric_name = "r2"

    fit_done = threading.Event()
    fit_error: list[Any] = [None]

    def _fit() -> None:
        try:
            model.fit(X.values, y)
        except Exception as e:
            fit_error[0] = e
        finally:
            fit_done.set()

    t = threading.Thread(target=_fit, daemon=True)
    t.start()
    fit_done.wait(timeout=timeout)

    if not fit_done.is_set() or fit_error[0] is not None:
        return _placeholder_fig("feature_importance_preview", "timed_out")

    importances = model.feature_importances_
    if importances.sum() == 0:
        return _placeholder_fig("feature_importance_preview", "no_numeric")

    feat_names = list(X.columns)
    sorted_idx = np.argsort(importances)[::-1]
    sorted_imp = importances[sorted_idx]
    sorted_names = [feat_names[i] for i in sorted_idx]

    top_n_default = int(hints.get("importance_top_n_override", 20))
    cumsum = np.cumsum(sorted_imp) / sorted_imp.sum()
    n95 = int(np.searchsorted(cumsum, 0.95)) + 1
    top_n = max(1, min(top_n_default, n95, len(sorted_imp)))

    top_names = sorted_names[:top_n]
    top_imp = sorted_imp[:top_n]

    cv_score = None
    try:
        from sklearn.model_selection import cross_val_score

        cv_scores = cross_val_score(model, X.values, y, cv=3, scoring=metric_name, error_score="raise")
        cv_score = float(np.mean(cv_scores))
    except Exception:
        pass

    top3_sum = float(sorted_imp[:3].sum())
    total_sum = float(sorted_imp.sum())
    top_feature_concentration = top3_sum / total_sum if total_sum > 0 else None

    nonlinearity_estimate = None
    try:
        top5_names = sorted_names[:5]
        top5_corrs = [abs(float(X[c].corr(pd.Series(y.astype(float), name="y")))) for c in top5_names if c in X.columns]
        mean_linear = float(np.mean(top5_corrs)) if top5_corrs else 0.0
        rf_proxy = cv_score if cv_score is not None else 0.0
        nonlinearity_estimate = float(abs(rf_proxy - mean_linear))
    except Exception:
        pass

    extras_out["eda_baseline"] = {
        "cv_score": cv_score,
        "metric": metric_name,
        "top_feature_concentration": top_feature_concentration,
        "nonlinearity_estimate": nonlinearity_estimate,
        "computed_at": datetime.datetime.utcnow().isoformat(),
    }

    fig, ax = plt.subplots(figsize=(9, max(4.0, top_n * 0.35 + 1)))
    ax.barh(range(top_n), top_imp[::-1], color="steelblue")
    ax.set_yticks(range(top_n))
    ax.set_yticklabels(top_names[::-1], fontsize=8)
    for i, v in enumerate(top_imp[::-1]):
        ax.text(v + 0.001, i, f"{v:.3f}", va="center", fontsize=7)
    ax.set_xlabel("Importance")
    ax.set_title(f"Feature Importance Preview (top {top_n})")
    cv_txt = f"{metric_name}={cv_score:.3f}" if cv_score is not None else f"{metric_name}=N/A"
    ax.text(
        0.99,
        0.01,
        f"Preview only. Final → Day 7 evaluator | {cv_txt}",
        transform=ax.transAxes,
        ha="right",
        va="bottom",
        fontsize=7,
        color="gray",
    )
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "feature_importance_preview",
        "importance",
        _importance_trigger,
        _importance_score,
        _importance_render,
        "feature_importance",
        fallback_on_fail="placeholder",
    )
)


# ── Chart 5: missing_pattern ─────────────────────────────────────────────────


def _missing_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    return int((df.isnull().mean() > 0.05).sum()) >= 2


def _missing_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.8


def _missing_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import numpy as np

    missing_ratio = df.isnull().mean()
    missing_cols = missing_ratio[missing_ratio > 0.05].sort_values(ascending=False)
    if len(missing_cols) < 2:
        return _placeholder_fig("missing_pattern", "no_numeric")

    top20 = missing_cols.head(20)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    axes[0].barh(range(len(top20)), top20.values, color="coral")
    axes[0].set_yticks(range(len(top20)))
    axes[0].set_yticklabels(top20.index.tolist(), fontsize=8)
    axes[0].set_xlabel("Missing Rate")
    axes[0].set_title("Missing Rate by Column (top 20)")
    axes[0].invert_yaxis()

    miss_df = df[missing_cols.index.tolist()]
    n_sample = min(1000, len(df))
    if len(df) > n_sample:
        miss_df = miss_df.sample(n_sample, random_state=42)
    mat = miss_df.isnull().astype(int).values
    axes[1].imshow(mat, aspect="auto", cmap="binary", interpolation="none")
    axes[1].set_xlabel("Column Index")
    axes[1].set_ylabel("Row Sample")
    axes[1].set_title("Missing Pattern Matrix (black=NaN)")

    try:
        isna_corr = miss_df.isnull().corr().abs()
        np.fill_diagonal(isna_corr.values, 0)
        mar_pairs = [
            (isna_corr.columns[i], isna_corr.columns[j])
            for i in range(len(isna_corr))
            for j in range(i + 1, len(isna_corr))
            if isna_corr.iloc[i, j] > 0.7
        ]
        if mar_pairs:
            pair_str = ", ".join(f"({a},{b})" for a, b in mar_pairs[:3])
            fig.text(0.5, -0.02, f"MAR 의심 쌍: {pair_str}", ha="center", fontsize=8, color="red")
    except Exception:
        pass

    fig.suptitle("Missing Pattern", fontsize=12)
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "missing_pattern",
        "missing",
        _missing_trigger,
        _missing_score,
        _missing_render,
        "missing_pattern",
        fallback_on_fail="skip",
    )
)


# ── Chart 6: numeric_distribution_grid ───────────────────────────────────────


def _numdist_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    return len(_num_cols(df)) >= 4


def _numdist_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.75


def _numdist_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import numpy as np

    num_c = [c for c in _num_cols(df) if df[c].var() > 0]
    if not num_c:
        return _placeholder_fig("numeric_distribution_grid", "no_numeric")

    top12 = list(df[num_c].var().nlargest(12).index)
    dist_transforms = arts.get("distribution_transforms", {})

    ncols = 3
    nrows = math.ceil(len(top12) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 4, nrows * 3), squeeze=False)
    axes_flat = axes.flatten()

    for i, c in enumerate(top12):
        ax = axes_flat[i]
        data = df[c].dropna()
        ax.hist(data, bins=30, density=True, alpha=0.6, color="steelblue")
        try:
            from scipy.stats import gaussian_kde

            kde = gaussian_kde(data)
            xs = np.linspace(float(data.min()), float(data.max()), 200)
            ax.plot(xs, kde(xs), color="red", lw=1.5)
        except Exception:
            pass
        ax.axvline(float(data.mean()), color="black", linestyle="--", lw=1)
        try:
            from scipy.stats import skew as _skew

            skewness = float(_skew(data))
        except Exception:
            skewness = 0.0
        title = str(c)
        t_info = dist_transforms.get(c)
        if t_info:
            method = t_info.get("method", "") if isinstance(t_info, dict) else str(t_info)
            lam = t_info.get("lambda") if isinstance(t_info, dict) else None
            title += f" ({method}" + (f", λ={lam:.2f}" if lam is not None else "") + ")"
        ax.set_title(f"{title}\nskew={skewness:.2f}", fontsize=8)

    for j in range(len(top12), len(axes_flat)):
        axes_flat[j].set_visible(False)

    fig.suptitle("Numeric Distribution Grid", fontsize=11)
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "numeric_distribution_grid",
        "distribution",
        _numdist_trigger,
        _numdist_score,
        _numdist_render,
        "numeric_distribution",
        fallback_on_fail="skip",
    )
)


# ── Chart 7: categorical_frequency ───────────────────────────────────────────


def _catfreq_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    return len(_high_card_cat_cols(df)) >= 1


def _catfreq_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.7


def _catfreq_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt

    high_card = _high_card_cat_cols(df)
    if not high_card:
        return _placeholder_fig("categorical_frequency", "not_applicable")

    if len(high_card) > 5:
        warnings.warn("categorical_frequency: showing top-5 high-card columns", stacklevel=2)
        high_card = high_card[:5]

    cardinality_levels = profile.get("cardinality_levels") or {}
    nrows = len(high_card)
    fig, axes = plt.subplots(nrows, 1, figsize=(10, nrows * 3.5), squeeze=False)

    for ax, c in zip(axes.flatten(), high_card):
        vc = df[c].value_counts()
        top15 = vc.head(15)
        other_count = vc.iloc[15:].sum() if len(vc) > 15 else 0
        labels = list(top15.index.astype(str))
        vals = list(top15.values)
        if other_count > 0:
            labels.append("other")
            vals.append(int(other_count))
        ax.barh(range(len(labels)), vals, color="mediumseagreen")
        ax.set_yticks(range(len(labels)))
        ax.set_yticklabels(labels, fontsize=8)
        ax.invert_yaxis()
        card = cardinality_levels.get(c, "")
        total_u = df[c].nunique()
        ax.set_title(f"{c} (cardinality: {card}, total unique: {total_u})", fontsize=9)

    fig.suptitle("Categorical Frequency", fontsize=11)
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "categorical_frequency",
        "categorical",
        _catfreq_trigger,
        _catfreq_score,
        _catfreq_render,
        "categorical_frequency",
        fallback_on_fail="skip",
    )
)


# ── Chart 8: pairplot_top4 ───────────────────────────────────────────────────


def _pairplot_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    return len(_num_cols(df)) >= 4 and len(df) <= 5000


def _pairplot_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.75


def _pairplot_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import pandas as pd

    target = state.target_column
    num_c = _num_cols(df, exclude=target)
    if len(num_c) < 4:
        return _placeholder_fig("pairplot_top4", "no_numeric")

    if target and target in df.columns:
        try:
            t_series = pd.to_numeric(df[target], errors="coerce")
            corrs = df[num_c].corrwith(t_series).abs()
            top4 = corrs.nlargest(4).index.tolist()
        except Exception:
            top4 = num_c[:4]
    else:
        top4 = num_c[:4]

    cols_to_use = top4 + ([target] if target and target in df.columns else [])
    sample_df = df[cols_to_use].copy()
    if len(sample_df) > 1000:
        sample_df = sample_df.sample(1000, random_state=42)

    try:
        import seaborn as sns

        hue = target if target and target in sample_df.columns else None
        g = sns.pairplot(sample_df, vars=top4, hue=hue, diag_kind="kde", plot_kws={"alpha": 0.4})
        g.fig.suptitle("Pairplot Top 4 Features", y=1.02, fontsize=11)
        return g.fig
    except Exception:
        fig, axes = plt.subplots(4, 4, figsize=(12, 12))
        for i, c1 in enumerate(top4):
            for j, c2 in enumerate(top4):
                ax = axes[i][j]
                if i == j:
                    ax.hist(sample_df[c1].dropna(), bins=20, color="steelblue")
                else:
                    ax.scatter(sample_df[c2].dropna(), sample_df[c1].dropna(), alpha=0.3, s=5, color="steelblue")
                if i == 0:
                    ax.set_title(str(c2), fontsize=7)
                if j == 0:
                    ax.set_ylabel(str(c1), fontsize=7)
        fig.suptitle("Pairplot Top 4 Features", fontsize=11)
        fig.tight_layout()
        return fig


_reg(
    ChartSpec(
        "pairplot_top4",
        "bivariate",
        _pairplot_trigger,
        _pairplot_score,
        _pairplot_render,
        "pairplot_top4",
        fallback_on_fail="skip",
    )
)


# ── Chart 9: qq_plot_grid ────────────────────────────────────────────────────


def _qqplot_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    if len(df) < 8:
        return False
    try:
        from scipy.stats import normaltest

        for c in _num_cols(df):
            data = df[c].dropna()
            if len(data) >= 8:
                _, p = normaltest(data)
                if p < 0.05:
                    return True
    except Exception:
        pass
    return False


def _qqplot_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.7


def _qqplot_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt

    try:
        from scipy.stats import normaltest, probplot
    except Exception:
        return _placeholder_fig("qq_plot_grid", "import_failed")

    nonnormal = []
    for c in _num_cols(df):
        data = df[c].dropna()
        if len(data) >= 8:
            try:
                _, p = normaltest(data)
                if p < 0.05:
                    nonnormal.append((c, float(p)))
            except Exception:
                pass

    nonnormal.sort(key=lambda x: x[1])
    top9 = nonnormal[:9]
    if not top9:
        return _placeholder_fig("qq_plot_grid", "not_applicable")

    ncols = 3
    nrows = math.ceil(len(top9) / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(ncols * 4, nrows * 3.5), squeeze=False)
    axes_flat = axes.flatten()

    for i, (c, p) in enumerate(top9):
        ax = axes_flat[i]
        data = df[c].dropna().values
        try:
            (osm, osr), (slope, intercept, _r) = probplot(data, dist="norm")
            ax.scatter(osm, osr, s=8, alpha=0.5, color="steelblue")
            ax.plot([osm[0], osm[-1]], [slope * osm[0] + intercept, slope * osm[-1] + intercept], color="red", lw=1.5)
        except Exception:
            ax.text(0.5, 0.5, "probplot failed", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(f"{c}\n(p={p:.2e})", fontsize=8)

    for j in range(len(top9), len(axes_flat)):
        axes_flat[j].set_visible(False)

    fig.suptitle("QQ Plot Grid (non-normal columns)", fontsize=11)
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "qq_plot_grid",
        "distribution",
        _qqplot_trigger,
        _qqplot_score,
        _qqplot_render,
        "qq_plot_grid",
        fallback_on_fail="skip",
    )
)


# ── Chart 10: target_correlation_bar ─────────────────────────────────────────


def _tcorr_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    if not state.target_column:
        return False
    return len(_num_cols(df, exclude=state.target_column)) >= 2


def _tcorr_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.8


def _tcorr_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import pandas as pd

    target = state.target_column
    if not target or target not in df.columns:
        return _placeholder_fig("target_correlation_bar", "no_target")

    feat_cols = _num_cols(df, exclude=target)
    if len(feat_cols) < 2:
        return _placeholder_fig("target_correlation_bar", "no_numeric")

    try:
        t_series = pd.to_numeric(df[target], errors="coerce")
        if t_series.isnull().all():
            from sklearn.preprocessing import LabelEncoder

            t_series = pd.Series(LabelEncoder().fit_transform(df[target].astype(str)), index=df.index, dtype=float)
    except Exception:
        return _placeholder_fig("target_correlation_bar", "no_target")

    corrs: dict[str, float] = {}
    for c in feat_cols:
        try:
            r = float(df[c].corr(t_series))
            if not math.isnan(r):
                corrs[c] = r
        except Exception:
            pass

    if not corrs:
        return _placeholder_fig("target_correlation_bar", "no_numeric")

    sorted_corrs = sorted(corrs.items(), key=lambda x: abs(x[1]), reverse=True)[:15]
    names = [c for c, _ in sorted_corrs]
    values = [v for _, v in sorted_corrs]
    colors = ["steelblue" if v >= 0 else "coral" for v in values]

    fig, ax = plt.subplots(figsize=(10, max(4.0, len(names) * 0.4 + 1)))
    ax.barh(range(len(names)), values, color=colors)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.axvline(0, color="black", lw=0.8)
    ax.set_xlabel("Pearson Correlation with Target")
    ax.set_title(f"Target Correlation Bar — {target}")
    if all(abs(v) < 0.01 for v in values):
        warnings.warn("target_correlation_bar: all correlations ≈ 0", stacklevel=2)
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "target_correlation_bar",
        "target_relation",
        _tcorr_trigger,
        _tcorr_score,
        _tcorr_render,
        "target_correlation_bar",
        fallback_on_fail="skip",
    )
)


# ── Chart 11: outlier_summary ─────────────────────────────────────────────────


def _outlier_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    import numpy as np

    for c in _num_cols(df):
        data = df[c].dropna().values
        if len(data) == 0:
            continue
        q1, q3 = np.percentile(data, 25), np.percentile(data, 75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        if ((data < q1 - 1.5 * iqr) | (data > q3 + 1.5 * iqr)).mean() > 0.01:
            return True
    return False


def _outlier_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.7


def _outlier_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import numpy as np

    fitted_scalers = arts.get("fitted_scalers") or {}
    robust_cols = {c for c, info in fitted_scalers.items() if isinstance(info, dict) and info.get("method") == "robust"}

    rows = []
    for c in _num_cols(df):
        data = df[c].dropna().values
        if len(data) == 0:
            continue
        q1, q3 = np.percentile(data, 25), np.percentile(data, 75)
        iqr = q3 - q1
        if iqr == 0:
            continue
        mask = (data < q1 - 1.5 * iqr) | (data > q3 + 1.5 * iqr)
        if mask.mean() > 0.01:
            rows.append((c, float(mask.mean()), int(mask.sum()), c in robust_cols))

    if not rows:
        return _placeholder_fig("outlier_summary", "not_applicable")

    rows.sort(key=lambda x: x[1], reverse=True)
    labels = [f"{c} ★" if rob else c for c, _, _, rob in rows]
    ratios = [r for _, r, _, _ in rows]
    counts = [n for _, _, n, _ in rows]

    fig, ax = plt.subplots(figsize=(10, max(4.0, len(rows) * 0.4 + 1)))
    ax.barh(range(len(rows)), ratios, color="coral")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    for i, (ratio, count) in enumerate(zip(ratios, counts)):
        ax.text(ratio + 0.001, i, str(count), va="center", fontsize=7)
    ax.set_xlabel("Outlier Rate (IQR 1.5×)")
    ax.set_title("Outlier Summary (★ = robust scaled)")
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "outlier_summary",
        "outlier",
        _outlier_trigger,
        _outlier_score,
        _outlier_render,
        "outlier_summary",
        fallback_on_fail="skip",
    )
)


# ── Chart 12: smote_before_after_scatter ─────────────────────────────────────


def _smote_scatter_trigger(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> bool:
    smote_meta = arts.get("smote_meta")
    if not smote_meta or not smote_meta.get("applied"):
        return False
    return len(_num_cols(df)) >= 2


def _smote_scatter_score(df: Any, state: Any, hints: dict, profile: dict, arts: dict) -> float:
    return 0.85


def _smote_scatter_render(df: Any, state: Any, hints: dict, profile: dict, arts: dict, extras_out: dict) -> Any:
    import matplotlib.pyplot as plt
    import pandas as pd

    smote_meta = arts.get("smote_meta", {})
    target = state.target_column
    num_c = _num_cols(df, exclude=target)
    if len(num_c) < 2:
        return _placeholder_fig("smote_before_after_scatter", "no_numeric")

    if target and target in df.columns:
        try:
            t_series = pd.to_numeric(df[target], errors="coerce")
            corrs = df[num_c].corrwith(t_series).abs()
            top2 = corrs.nlargest(2).index.tolist()
        except Exception:
            top2 = num_c[:2]
    else:
        top2 = num_c[:2]

    synthetic_idx = smote_meta.get("synthetic_row_idx") or []
    if not synthetic_idx:
        warnings.warn("smote_scatter: synthetic_row_idx empty, showing original only", stacklevel=2)

    valid_syn = [i for i in synthetic_idx if i in df.index]
    orig_df = df[~df.index.isin(valid_syn)]
    syn_df = df[df.index.isin(valid_syn)]

    fig, ax = plt.subplots(figsize=(9, 7))
    classes = list(df[target].unique()) if target and target in df.columns else [None]
    cmap = plt.colormaps.get_cmap("tab10") if hasattr(plt.colormaps, "get_cmap") else plt.cm.get_cmap("tab10")

    for i, cls in enumerate(classes[:10]):
        sub = orig_df[orig_df[target] == cls] if target and target in orig_df.columns else orig_df
        ax.scatter(sub[top2[0]], sub[top2[1]], s=20, alpha=0.5, color=cmap(i / 10), label=f"orig {cls}")

    if len(syn_df) > 0:
        ax.scatter(
            syn_df[top2[0]],
            syn_df[top2[1]],
            s=60,
            marker="X",
            color="black",
            edgecolors="red",
            linewidths=0.5,
            label="synthetic",
            zorder=5,
        )

    ax.set_xlabel(str(top2[0]))
    ax.set_ylabel(str(top2[1]))
    ax.set_title("SMOTE Before/After Scatter")
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    return fig


_reg(
    ChartSpec(
        "smote_before_after_scatter",
        "preprocess_effect",
        _smote_scatter_trigger,
        _smote_scatter_score,
        _smote_scatter_render,
        "smote_scatter",
        fallback_on_fail="skip",
    )
)


# ── main entry point ──────────────────────────────────────────────────────────


def charts(df: Any, state: Any) -> tuple[list[str], dict]:
    """EDA 차트 카탈로그 12종에서 데이터 적응적으로 선택 렌더링.

    Returns (uris, extras): URI 목록 3~12개, 부가 정보 dict.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    profile = _get_profile(state)
    hints = _get_hints(state)
    arts = _get_artifacts(state)
    job_id = state.job_id

    disable: list[str] = hints.get("disable_chart") or []
    force: list[str] = hints.get("force_chart") or []
    max_cap = int(hints.get("max_charts") or 12)

    extras: dict = {}

    # Phase 1: trigger evaluation
    candidates: list[tuple[str, float]] = []
    for name, spec in CHART_REGISTRY.items():
        try:
            triggered = spec.trigger_fn(df, state, hints, profile, arts)
        except Exception:
            triggered = False
        if triggered or name in force:
            try:
                score = spec.score_fn(df, state, hints, profile, arts)
            except Exception:
                score = 0.5
            candidates.append((name, score))

    # Phase 2: hint overrides
    candidates = [(n, s) for n, s in candidates if n not in disable]
    forced_names = {n for n, _ in candidates}
    for fname in force:
        if fname not in forced_names and fname in CHART_REGISTRY:
            candidates.append((fname, 1.0))

    # Phase 3: score filter (≥ 0.5), guarantee ≥ 3
    passing = [(n, s) for n, s in candidates if s >= 0.5]
    if len(passing) < 3:
        sorted_all = sorted(candidates, key=lambda x: x[1], reverse=True)
        passing = sorted_all[: max(3, len(passing))]

    # Phase 4: cap
    passing = sorted(passing, key=lambda x: x[1], reverse=True)[:max_cap]

    # Phase 5: render
    uris: list[str] = []
    for name, _ in passing:
        spec = CHART_REGISTRY[name]
        fig = None
        try:
            fig = spec.render_fn(df, state, hints, profile, arts, extras)
            if fig is None:
                continue
            uri = _save_close(fig, kind=f"eda/tabular/{name}", job_id=job_id)
            uris.append(uri)
        except Exception:
            if fig is not None:
                try:
                    plt.close(fig)
                except Exception:
                    pass
            if spec.fallback_on_fail == "placeholder":
                try:
                    ph = _placeholder_fig(name, "timed_out")
                    uri = _save_close(ph, kind=f"eda/tabular/{name}", job_id=job_id)
                    uris.append(uri)
                except Exception:
                    pass

    # DoD: ensure ≥ 3
    if len(uris) < 3:
        rendered_set = {n for n, _ in passing}
        for name, spec in CHART_REGISTRY.items():
            if len(uris) >= 3:
                break
            if name in rendered_set:
                continue
            try:
                ph = _placeholder_fig(name, "not_applicable")
                uri = _save_close(ph, kind=f"eda/tabular/{name}", job_id=job_id)
                uris.append(uri)
            except Exception:
                pass

    return uris, extras

"""agents.handlers.tabular.preprocessor — 정형 ML/DL 전처리 카탈로그 (jh 담당).

Day 2: transform catalog 15종 (구현 8 + TODO 등록 7).
apply() → (df, state) 튜플 반환 (HJ PR2 contract).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# TransformSpec & Registry
# ---------------------------------------------------------------------------


@dataclass
class TransformSpec:
    name: str
    category: str  # "imputation" | "encoding" | "scaling" | "feature_select" | "feature_gen" | "balancing"
    trigger_fn: Callable[..., bool]  # (profile, hints, category, task_type, target) -> bool
    score_fn: Callable[..., float]  # (profile) -> float
    plan_fn: Optional[Callable[..., dict]] = None  # (state) -> step_dict
    apply_fn: Optional[Callable[..., Any]] = None  # (df, step, state) -> (df, artifacts_dict)
    prerequisite: list = field(default_factory=list)
    mutex: list = field(default_factory=list)
    fit_scope: str = "train_only"
    idempotent: bool = True
    severity_if_fail: str = "warn"
    fallback: Optional[dict] = None
    status: str = "implemented"
    version: str = "1.0"


TRANSFORM_REGISTRY: dict[str, TransformSpec] = {}


def register_transform(spec: TransformSpec) -> None:
    TRANSFORM_REGISTRY[spec.name] = spec


def resolve_threshold(
    key: str,
    hints: dict[str, Any],
    profile: dict[str, Any],
    default: Any,
) -> tuple[Any, str]:
    """임계값 결정 3단 우선순위: hint > adaptive(profiler 추천) > default."""
    if hints.get(key) is not None:
        return hints[key], "hint"
    adaptive = (profile or {}).get("preprocessing_thresholds_suggested", {}).get(key)
    if adaptive is not None:
        return adaptive, "adaptive"
    return default, "default"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ts() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _get_profile(state: Any) -> dict[str, Any]:
    return getattr(state, "data_profile", None) or {}


def _get_hints(state: Any) -> dict[str, Any]:
    return getattr(state, "preprocessing_hints", None) or {}


def _get_category(state: Any) -> str:
    return getattr(state, "category", "tabular_ml")


def _get_task_type(state: Any, profile: dict[str, Any]) -> str:
    task = getattr(state, "task", "auto")
    if task not in ("auto", None):
        return task
    if profile.get("task_type"):
        return str(profile["task_type"])
    target = getattr(state, "target_column", None)
    if not target:
        return "unsupervised"
    return "classification"


def _outlier_ratio(series: Any) -> float:
    """IQR 1.5배 기준 outlier 비율 계산."""
    import numpy as np

    arr = series.dropna().values
    if len(arr) < 4:
        return 0.0
    q1, q3 = float(np.percentile(arr, 25)), float(np.percentile(arr, 75))
    iqr = q3 - q1
    if iqr == 0:
        return 0.0
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return float(np.mean((arr < lower) | (arr > upper)))


def _class_entropy_ratio(y: Any) -> float:
    """H(class) / H_max 계산 (binary/multiclass 통일)."""
    import numpy as np

    counts = y.value_counts(normalize=True)
    k = len(counts)
    if k <= 1:
        return 0.0
    h = float(-np.sum(counts * np.log2(counts + 1e-15)))
    h_max = math.log2(k)
    return h / h_max if h_max > 0 else 0.0


# ---------------------------------------------------------------------------
# 1. Target Encoding (tabular_ml, high-card categorical, KFold OOF)
# ---------------------------------------------------------------------------


def _te_trigger(profile, hints, category, task_type, target):
    if category == "tabular_dl":
        return False
    if not target:
        return False
    card = profile.get("cardinality_levels", {})
    return any(lvl in ("high", "medium") for lvl in card.values())


def _te_plan(state):
    profile = _get_profile(state)
    hints = _get_hints(state)
    min_card, _ = resolve_threshold(
        "target_encoding_min_card", hints, profile, max(20, int(math.sqrt(max(profile.get("n_rows", 100), 1))))
    )
    smoothing = hints.get("target_encoding_smoothing", 10.0)
    card = profile.get("cardinality_levels", {})
    te_cols = [c for c, lvl in card.items() if lvl in ("high", "medium")]
    return {
        "name": "target_encoding",
        "columns": te_cols,
        "params": {"smoothing": smoothing, "n_splits": 5, "min_card": min_card},
        "inputs": [],
        "outputs": ["target_encoder"],
        "prerequisite_steps": [{"name": "impute_categorical", "strength": "soft"}],
        "mutex_steps": ["label_encoding"],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.85,
        "catalog_version": "1.0",
    }


def _te_apply(df, step, state):
    import numpy as np
    from sklearn.model_selection import KFold, StratifiedKFold

    target = state.target_column
    cols = [c for c in step.get("columns", []) if c in df.columns and c != target]
    if not cols or not target or target not in df.columns:
        return df, {}

    smoothing = step.get("params", {}).get("smoothing", 10.0)
    n_splits = step.get("params", {}).get("n_splits", 5)
    y = df[target].copy()
    n_classes = int(y.nunique())
    if n_classes < 2:
        return df, {}

    out = df.copy()
    encoders_by_col: dict = {}

    for col in cols:
        if col not in out.columns:
            continue
        x_col = out[col].astype(str)

        if n_classes == 2:
            global_m = float(y.mean())
            te_vals = np.full(len(out), global_m)
            mapping: dict = {}
            try:
                kf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
                for tr_idx, val_idx in kf.split(out, y):
                    tr_x = x_col.iloc[tr_idx]
                    tr_y = y.iloc[tr_idx]
                    cat_stats = tr_y.groupby(tr_x).agg(["sum", "count"])
                    cat_means = (cat_stats["sum"] + smoothing * global_m) / (cat_stats["count"] + smoothing)
                    val_x = x_col.iloc[val_idx]
                    te_vals[val_idx] = val_x.map(cat_means).fillna(global_m).values
                    for cat, mv in cat_means.items():
                        mapping[str(cat)] = float(mv)
            except Exception:
                te_vals = np.full(len(out), global_m)
            out[f"{col}__te"] = te_vals
            out = out.drop(columns=[col])
            encoders_by_col[col] = {"mapping": mapping, "global_mean": global_m, "unknown_value": global_m}

        else:
            classes = sorted(y.unique())[:-1]
            global_means = {int(c): float((y == c).mean()) for c in classes}
            te_arrays = {int(c): np.full(len(out), global_means[int(c)]) for c in classes}
            mappings: dict = {int(c): {} for c in classes}
            try:
                kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
                for tr_idx, val_idx in kf.split(out):
                    tr_x = x_col.iloc[tr_idx]
                    tr_y = y.iloc[tr_idx]
                    for cls in classes:
                        cls_int = int(cls)
                        gm = global_means[cls_int]
                        binary_y = (tr_y == cls).astype(float)
                        cat_stats = binary_y.groupby(tr_x).agg(["sum", "count"])
                        cat_means = (cat_stats["sum"] + smoothing * gm) / (cat_stats["count"] + smoothing)
                        val_x = x_col.iloc[val_idx]
                        te_arrays[cls_int][val_idx] = val_x.map(cat_means).fillna(gm).values
                        for cat, mv in cat_means.items():
                            mappings[cls_int][str(cat)] = float(mv)
            except Exception:
                pass
            for cls in classes:
                out[f"{col}__te_c{int(cls)}"] = te_arrays[int(cls)]
            out = out.drop(columns=[col])
            encoders_by_col[col] = {
                "global_means": {str(k): v for k, v in global_means.items()},
                "mappings": {str(k): v for k, v in mappings.items()},
                "n_classes": n_classes,
            }

    artifact = {
        "fitted_at": _ts(),
        "method": "kfold_target_encoder",
        "n_splits": n_splits,
        "smoothing": smoothing,
        "encoders_by_col": encoders_by_col,
    }
    return out, {"target_encoder": artifact}


# ---------------------------------------------------------------------------
# 2. Class Weight Compute
# ---------------------------------------------------------------------------


def _cw_trigger(profile, hints, category, task_type, target):
    return task_type == "classification" and bool(target)


def _cw_plan(state):
    return {
        "name": "class_weight_compute",
        "columns": [],
        "params": {"cap_value": 100},
        "inputs": [],
        "outputs": ["class_weight", "dl_imbalance_strategy"],
        "prerequisite_steps": [],
        "mutex_steps": [],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "abort",
        "score": 0.9,
        "catalog_version": "1.0",
    }


def _cw_apply(df, step, state):

    target = state.target_column
    hints = _get_hints(state)
    category = _get_category(state)
    cap = step.get("params", {}).get("cap_value", 100)

    if not target or target not in df.columns:
        return df, {}

    y = df[target].dropna()
    classes = sorted(y.unique())
    if len(classes) < 2:
        raise ValueError(f"class_weight_compute: single class in target '{target}'")

    class_counts = {int(c): int((y == c).sum()) for c in classes}
    n = len(y)
    k = len(classes)

    # Check if SMOTE is in plan (by checking state extras)
    extras = (getattr(state, "category_extras", None) or {}).get("tabular", {})
    smote_active = extras.get("preprocess_artifacts", {}).get("smote_meta", {}).get("applied", False)

    if hints.get("class_weight_force_uniform"):
        weights = {int(c): 1.0 for c in classes}
        strategy = "uniform"
        cap_applied = False
    elif smote_active and category == "tabular_ml":
        weights = None
        strategy = "disabled_due_to_smote"
        cap_applied = False
    else:
        weights = {}
        cap_applied = False
        for c in classes:
            w = n / (k * class_counts[int(c)])
            if w > cap:
                w = float(cap)
                cap_applied = True
            weights[int(c)] = round(w, 6)
        strategy = "balanced"

    artifact = {
        "strategy": strategy,
        "weights": weights,
        "class_counts": class_counts,
        "cap_applied": cap_applied,
        "cap_value": cap,
    }
    extra_artifacts: dict = {"class_weight": artifact}

    if category == "tabular_dl":
        entropy_ratio = _class_entropy_ratio(y)
        n_samples = len(df)
        if weights:
            sampler_weights = [weights.get(int(df[target].iloc[i]), 1.0) for i in range(n_samples)]
        else:
            sampler_weights = [1.0] * n_samples
        method = "both" if entropy_ratio < 0.3 else "weighted_random_sampler"
        dl_strategy = {
            "method": method,
            "sampler_weights": sampler_weights,
            "focal_loss_gamma": 2.0,
            "focal_loss_alpha": weights or {},
            "entropy_ratio": entropy_ratio,
            "recommendation": "weighted_random_sampler",
        }
        extra_artifacts["dl_imbalance_strategy"] = dl_strategy

    return df, extra_artifacts


# ---------------------------------------------------------------------------
# 3. SMOTE Resample (6-gate, tabular_ml only)
# ---------------------------------------------------------------------------


def _smote_trigger(profile, hints, category, task_type, target):
    if task_type != "classification" or category != "tabular_ml":
        return False
    if not hints.get("allow_smote", True):
        return False
    # Use profile info if available
    minority = profile.get("minority_class_count", 10)
    if minority < 6:
        return False
    return True


def _smote_plan(state):
    hints = _get_hints(state)
    strategy_override = hints.get("smote_strategy_override")
    return {
        "name": "smote_resample",
        "columns": [],
        "params": {"strategy_override": strategy_override},
        "inputs": [],
        "outputs": ["smote_meta"],
        "prerequisite_steps": [{"name": "encode_categorical", "strength": "hard"}],
        "mutex_steps": ["class_weight_compute"],
        "fit_scope": "train_only",
        "idempotent": False,
        "needs_review": True,
        "severity_if_fail": "warn",
        "score": 0.7,
        "catalog_version": "1.0",
    }


def _smote_apply(df, step, state):
    import pandas as pd

    target = state.target_column
    hints = _get_hints(state)
    category = _get_category(state)
    seed = getattr(state, "seed", 42) or 42

    if not target or target not in df.columns:
        return df, {}
    if category == "tabular_dl":
        return df, {}

    y = df[target]
    task_type = _get_task_type(state, _get_profile(state))
    if task_type != "classification":
        return df, {}

    # Gate checks
    if not hints.get("allow_smote", True):
        return df, {"smote_meta": {"applied": False, "skip_reason": "gate5_allow_smote_false"}}

    class_counts = y.value_counts()
    minority_count = int(class_counts.min())
    if minority_count < 6:
        return df, {"smote_meta": {"applied": False, "skip_reason": "gate4_minority_too_small"}}

    entropy_ratio = _class_entropy_ratio(y)
    entropy_threshold, _ = resolve_threshold("smote_imbalance_entropy_threshold", hints, _get_profile(state), 0.85)
    if entropy_ratio >= entropy_threshold:
        return df, {"smote_meta": {"applied": False, "skip_reason": "gate3_entropy_balanced"}}

    # Memory gate
    n_majority = int(class_counts.max())
    strategy_override = step.get("params", {}).get("strategy_override")
    if strategy_override:
        sampling_strategy = strategy_override
        if isinstance(sampling_strategy, float):
            s_val = sampling_strategy
        else:
            s_val = 1.0
    elif entropy_ratio >= 0.7:
        sampling_strategy, s_val = 0.5, 0.5
    elif entropy_ratio >= 0.5:
        sampling_strategy, s_val = 0.75, 0.75
    else:
        sampling_strategy, s_val = "auto", 1.0

    n_to_gen = max(0, int(n_majority * s_val) - minority_count)
    n_features = df.shape[1]
    mem_mb = n_to_gen * n_features * 8 / 1024**2 * 1.5
    mem_threshold, _ = resolve_threshold("smote_max_synthetic_mem_mb", hints, _get_profile(state), 512)
    if mem_mb > mem_threshold:
        return df, {"smote_meta": {"applied": False, "skip_reason": "gate6_memory_limit"}}

    k = min(5, minority_count - 1)
    if k < 1:
        return df, {"smote_meta": {"applied": False, "skip_reason": "gate4_k_too_small"}}

    # Choose variant
    cat_cols = df.drop(columns=[target]).select_dtypes(include=["object", "category"]).columns
    try:
        if len(cat_cols) > 0:
            from imblearn.over_sampling import SMOTENC

            feature_cols = [c for c in df.columns if c != target]
            cat_idx = [feature_cols.index(c) for c in cat_cols if c in feature_cols]
            X = df[feature_cols]
            sm = SMOTENC(
                categorical_features=cat_idx, sampling_strategy=sampling_strategy, k_neighbors=k, random_state=seed
            )
            variant = "SMOTENC"
        else:
            from imblearn.over_sampling import SMOTE

            feature_cols = [c for c in df.columns if c != target]
            X = df[feature_cols]
            sm = SMOTE(sampling_strategy=sampling_strategy, k_neighbors=k, random_state=seed)
            variant = "SMOTE"

        before_counts = {int(c): int(cnt) for c, cnt in class_counts.items()}
        X_res, y_res = sm.fit_resample(X, y)
        n_before = len(df)
        synthetic_idx = list(range(n_before, len(X_res)))
        out = pd.concat([pd.DataFrame(X_res, columns=feature_cols), pd.Series(y_res, name=target)], axis=1)
        after_counts = {int(c): int(cnt) for c, cnt in out[target].value_counts().items()}

        balance_ratio = min(after_counts.values()) / max(after_counts.values())
        pass_threshold_val = s_val * 0.9
        balance_ok = balance_ratio >= pass_threshold_val

        meta = {
            "applied": True,
            "variant": variant,
            "k_neighbors": k,
            "sampling_strategy": sampling_strategy,
            "seed_used": seed,
            "before": before_counts,
            "after": after_counts,
            "synthetic_row_idx": synthetic_idx,
            "balance_ok": balance_ok,
            "balance_ratio": round(balance_ratio, 4),
            "pass_threshold": round(pass_threshold_val, 4),
            "entropy_ratio_before": round(entropy_ratio, 4),
        }
        return out, {"smote_meta": meta}

    except Exception as exc:
        warnings.warn(f"SMOTE failed: {exc}")
        return df, {"smote_meta": {"applied": False, "skip_reason": f"error: {exc}"}}


# ---------------------------------------------------------------------------
# 4. VIF Drop (tabular_ml, numpy backend)
# ---------------------------------------------------------------------------


def _vif_trigger(profile, hints, category, task_type, target):
    if category == "tabular_dl":
        return False
    vif_top = profile.get("vif_top")
    if not vif_top:
        return False
    numeric_count = profile.get("numeric_count", 0)
    return numeric_count >= 3


def _vif_plan(state):
    hints = _get_hints(state)
    protect = hints.get("vif_protect_columns", [])
    return {
        "name": "vif_drop",
        "columns": [],
        "params": {"protect": protect},
        "inputs": [],
        "outputs": ["vif_dropped", "vif_final"],
        "prerequisite_steps": [{"name": "scale_numeric", "strength": "soft"}],
        "mutex_steps": ["correlation_drop", "pca_preview"],
        "fit_scope": "full",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.75,
        "catalog_version": "1.0",
    }


def _vif_apply(df, step, state):
    import numpy as np

    target = state.target_column
    hints = _get_hints(state)
    profile = _get_profile(state)
    protect = set(step.get("params", {}).get("protect", []) or hints.get("vif_protect_columns", []))

    # Normalize *_override hint keys to base keys
    norm_hints = dict(hints)
    for _k in ("vif_threshold", "vif_max_drop_ratio"):
        ov = hints.get(f"{_k}_override")
        if ov is not None:
            norm_hints[_k] = ov

    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target and c not in protect]
    if len(num_cols) < 3:
        return df, {"vif_dropped": [], "vif_final": {}}

    threshold, _ = resolve_threshold("vif_threshold", norm_hints, profile, 10.0)
    max_drop_ratio, _ = resolve_threshold(
        "vif_max_drop_ratio", norm_hints, profile, min(0.3, 1 - 1 / max(math.sqrt(len(num_cols)), 1))
    )
    max_drop_count = math.floor(len(num_cols) * max_drop_ratio)
    iteration_cap = max_drop_count + 5

    cols = list(num_cols)
    dropped: list[str] = []
    vif_history: list[tuple] = []
    safety_triggered = False

    for _ in range(iteration_cap):
        sub = df[cols].copy()
        # Drop constant columns first
        sub = sub.loc[:, sub.std() > 0]
        cols = list(sub.columns)
        if len(cols) < 2:
            break
        try:
            corr = np.corrcoef(sub.T)
            inv_corr = np.linalg.inv(corr)
            vifs = np.diag(inv_corr)
        except np.linalg.LinAlgError:
            break

        col_vifs = dict(zip(cols, vifs))
        worst = max(col_vifs, key=lambda c: col_vifs[c])
        worst_vif = col_vifs[worst]

        if worst_vif < threshold:
            break
        if len(dropped) >= max_drop_count:
            safety_triggered = True
            break
        if len(cols) - 1 < 2:
            break

        cols.remove(worst)
        dropped.append(worst)
        vif_history.append((len(dropped), worst, float(worst_vif)))

    final_vifs: dict = {}
    if len(cols) >= 2:
        try:
            sub = df[cols]
            sub = sub.loc[:, sub.std() > 0]
            if sub.shape[1] >= 2:
                corr = np.corrcoef(sub.T)
                inv_corr = np.linalg.inv(corr)
                vifs = np.diag(inv_corr)
                final_vifs = {c: round(float(v), 4) for c, v in zip(sub.columns, vifs)}
        except Exception:
            pass

    out = df.drop(columns=dropped)
    artifacts = {
        "vif_dropped": dropped,
        "vif_final": final_vifs,
        "_vif_history": vif_history,
        "_vif_safety_triggered": safety_triggered,
    }
    return out, artifacts


# ---------------------------------------------------------------------------
# 5. KNN Impute (5~20% missing, n<=5000)
# ---------------------------------------------------------------------------


def _knn_trigger(profile, hints, category, task_type, target):
    missing_by_col = profile.get("missing") or {}
    if not missing_by_col:
        return False
    n_rows = profile.get("n_rows", 0)
    if n_rows > 5000:
        return False
    for pct in missing_by_col.values():
        if 0.05 <= float(pct) <= 0.20:
            return True
    return False


def _knn_plan(state):
    profile = _get_profile(state)
    n_rows = profile.get("n_rows", 100)
    k = min(5, max(1, math.ceil(math.sqrt(n_rows)) - 1))
    missing_by_col = profile.get("missing") or {}
    target = state.target_column
    knn_cols = [c for c, pct in missing_by_col.items() if 0.05 <= float(pct) <= 0.20 and c != target]
    return {
        "name": "knn_impute",
        "columns": knn_cols,
        "params": {"n_neighbors": k},
        "inputs": [],
        "outputs": ["knn_imputer"],
        "prerequisite_steps": [],
        "mutex_steps": ["impute_numeric"],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.7,
        "catalog_version": "1.0",
    }


def _knn_apply(df, step, state):
    import numpy as np
    from sklearn.impute import KNNImputer

    target = state.target_column
    n_rows = len(df)

    if n_rows > 5000:
        return df, {}

    missing_pct = df.isna().mean()
    cols = [c for c in step.get("columns", []) if c in df.columns and c != target]
    if not cols:
        # Auto-detect from df
        cols = [
            c for c in df.select_dtypes(include=[np.number]).columns if c != target and 0.05 <= missing_pct[c] <= 0.20
        ]

    if not cols:
        return df, {}

    k = step.get("params", {}).get("n_neighbors", min(5, max(1, math.ceil(math.sqrt(n_rows)) - 1)))
    max_missing = max(float(missing_pct.get(c, 0)) for c in cols) if cols else 0
    weights = "distance" if max_missing > 0.10 else "uniform"

    imputer = KNNImputer(n_neighbors=k, weights=weights, metric="nan_euclidean")
    out = df.copy()
    try:
        out[cols] = imputer.fit_transform(out[cols])
    except Exception as exc:
        warnings.warn(f"KNN impute failed: {exc}, falling back to median")
        for c in cols:
            out[c] = out[c].fillna(out[c].median())

    artifact = {"n_neighbors": k, "fitted": True, "weights": weights, "columns": cols}
    return out, {"knn_imputer": artifact}


# ---------------------------------------------------------------------------
# 6. Datetime Extraction
# ---------------------------------------------------------------------------


def _dt_trigger(profile, hints, category, task_type, target):
    dt_cols = profile.get("datetime_columns") or []
    return len(dt_cols) > 0


def _dt_plan(state):
    profile = _get_profile(state)
    dt_cols = profile.get("datetime_columns") or []
    return {
        "name": "datetime_extraction",
        "columns": dt_cols,
        "params": {},
        "inputs": [],
        "outputs": ["datetime_extracted"],
        "prerequisite_steps": [],
        "mutex_steps": [],
        "fit_scope": "full",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.8,
        "catalog_version": "1.0",
    }


def _dt_apply(df, step, state):
    import pandas as pd

    cols = step.get("columns") or []
    if not cols:
        cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]

    if not cols:
        return df, {}

    out = df.copy()
    extracted_info: dict = {}

    for col in cols:
        if col not in out.columns:
            continue
        if not pd.api.types.is_datetime64_any_dtype(out[col]):
            try:
                out[col] = pd.to_datetime(out[col], errors="coerce")
            except Exception:
                continue

        series = out[col]
        original_tz = None
        if hasattr(series.dt, "tz") and series.dt.tz is not None:
            original_tz = str(series.dt.tz)
            series = series.dt.tz_convert("UTC").dt.tz_localize(None)

        nat_count = int(series.isna().sum())
        has_time = bool((series.dropna().dt.hour != 0).any() or (series.dropna().dt.minute != 0).any())

        gen_cols: list[str] = []
        prefix = col

        feat_map = {
            "year": series.dt.year,
            "month": series.dt.month,
            "day": series.dt.day,
            "dayofweek": series.dt.dayofweek,
            "quarter": series.dt.quarter,
            "is_weekend": series.dt.dayofweek.isin([5, 6]).astype(int),
            "is_month_end": series.dt.is_month_end.astype(int),
            "is_month_start": series.dt.is_month_start.astype(int),
            "day_of_year": series.dt.day_of_year,
            "week_of_year": series.dt.isocalendar().week.astype(float),
        }
        if has_time:
            feat_map["hour"] = series.dt.hour
            feat_map["minute"] = series.dt.minute

        for feat_name, feat_series in feat_map.items():
            new_col = f"{prefix}__{feat_name}"
            out[new_col] = feat_series.values
            gen_cols.append(new_col)

        out = out.drop(columns=[col])
        extracted_info[col] = {
            "generated_cols": gen_cols,
            "original_tz": original_tz,
            "had_time": has_time,
            "nat_count": nat_count,
        }

    return out, {"datetime_extracted": extracted_info}


# ---------------------------------------------------------------------------
# 7. Distribution Transform (log / log1p / yeo-johnson)
# ---------------------------------------------------------------------------


def _dist_trigger(profile, hints, category, task_type, target):
    skew_by_col = profile.get("skew") or {}
    return any(abs(float(v)) > 1.0 for v in skew_by_col.values())


def _dist_plan(state):
    profile = _get_profile(state)
    target = state.target_column
    skew_by_col = profile.get("skew") or {}
    candidates = {c: float(v) for c, v in skew_by_col.items() if abs(float(v)) > 1.0 and c != target}
    return {
        "name": "distribution_transform",
        "columns": list(candidates.keys()),
        "params": {"skew_candidates": candidates},
        "inputs": ["impute_numeric"],
        "outputs": ["distribution_transforms"],
        "prerequisite_steps": [{"name": "impute_numeric", "strength": "hard"}],
        "mutex_steps": ["quantile_transform"],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.7,
        "catalog_version": "1.0",
    }


def _dist_apply(df, step, state):
    import numpy as np

    target = state.target_column
    cols = [c for c in step.get("columns", []) if c in df.columns and c != target]
    if not cols:
        # Auto-detect
        cols = [
            c
            for c in df.select_dtypes(include=[np.number]).columns
            if c != target and abs(float(df[c].dropna().skew())) > 1.0 and len(df[c].dropna()) >= 30 and df[c].std() > 0
        ]

    if not cols:
        return df, {}

    out = df.copy()
    dist_transforms: dict = {}

    for col in cols:
        if col not in out.columns:
            continue
        s = out[col].dropna()
        if len(s) < 30 or s.std() == 0:
            continue
        skew_before = float(s.skew())
        if abs(skew_before) <= 1.0:
            continue

        col_vals = out[col].copy()
        min_val = float(s.min())

        if min_val > 0:
            method = "log"
            out[col] = np.log(col_vals.clip(lower=1e-9))
            lam = None
        elif min_val >= 0:
            method = "log1p"
            out[col] = np.log1p(col_vals.clip(lower=0))
            lam = None
        else:
            method = "yeo-johnson"
            try:
                from sklearn.preprocessing import PowerTransformer

                pt = PowerTransformer(method="yeo-johnson", standardize=False)
                vals = col_vals.values.reshape(-1, 1)
                transformed = pt.fit_transform(vals).ravel()
                out[col] = transformed
                lam = float(pt.lambdas_[0])
            except Exception:
                method = "log1p"
                shifted = col_vals - min_val
                out[col] = np.log1p(shifted)
                lam = None

        skew_after = float(out[col].dropna().skew())
        dist_transforms[col] = {
            "method": method,
            "lambda": lam,
            "skew_before": round(skew_before, 4),
            "skew_after": round(skew_after, 4),
        }

    return out, {"distribution_transforms": dist_transforms}


# ---------------------------------------------------------------------------
# 8. Scale Robust (outlier > 5% → RobustScaler, else StandardScaler)
# ---------------------------------------------------------------------------


def _robust_trigger(profile, hints, category, task_type, target):
    outlier_by_col = profile.get("outlier_ratio") or {}
    return any(float(v) > 0.05 for v in outlier_by_col.values())


def _robust_plan(state):
    profile = _get_profile(state)
    target = state.target_column
    outlier_by_col = profile.get("outlier_ratio") or {}
    robust_cols = [c for c, v in outlier_by_col.items() if float(v) > 0.05 and c != target]
    standard_cols = [c for c, v in outlier_by_col.items() if float(v) <= 0.05 and c != target]
    return {
        "name": "scale_robust",
        "columns": robust_cols + standard_cols,
        "params": {"robust_cols": robust_cols, "standard_cols": standard_cols},
        "inputs": [],
        "outputs": ["fitted_scalers"],
        "prerequisite_steps": [{"name": "impute_numeric", "strength": "soft"}],
        "mutex_steps": ["scale_numeric"],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.65,
        "catalog_version": "1.0",
    }


def _robust_apply(df, step, state):
    import numpy as np
    from sklearn.preprocessing import RobustScaler, StandardScaler

    target = state.target_column
    params = step.get("params", {})
    robust_cols = [c for c in (params.get("robust_cols") or []) if c in df.columns and c != target]
    standard_cols = [c for c in (params.get("standard_cols") or []) if c in df.columns and c != target]

    if not robust_cols and not standard_cols:
        # Auto-detect
        num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target]
        robust_cols = [c for c in num_cols if _outlier_ratio(df[c]) > 0.05]
        standard_cols = [c for c in num_cols if c not in robust_cols]

    out = df.copy()
    fitted_scalers: dict = {}

    if robust_cols:
        rs = RobustScaler()
        out[robust_cols] = rs.fit_transform(out[robust_cols])
        for i, c in enumerate(robust_cols):
            fitted_scalers[c] = {
                "method": "robust",
                "median": float(rs.center_[i]),
                "iqr": float(rs.scale_[i]),
            }

    if standard_cols:
        ss = StandardScaler()
        out[standard_cols] = ss.fit_transform(out[standard_cols])
        for i, c in enumerate(standard_cols):
            fitted_scalers[c] = {
                "method": "standard",
                "mean": float(ss.mean_[i]),
                "scale": float(ss.scale_[i]),
            }

    return out, {"fitted_scalers": fitted_scalers}


# ---------------------------------------------------------------------------
# Register 8 implemented + 7 planned = 15 transforms
# ---------------------------------------------------------------------------

register_transform(
    TransformSpec(
        name="target_encoding",
        category="encoding",
        trigger_fn=_te_trigger,
        score_fn=lambda p: 0.85,
        plan_fn=_te_plan,
        apply_fn=_te_apply,
        prerequisite=[("impute_categorical", "soft")],
        mutex=["label_encoding"],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="class_weight_compute",
        category="balancing",
        trigger_fn=_cw_trigger,
        score_fn=lambda p: 0.9,
        plan_fn=_cw_plan,
        apply_fn=_cw_apply,
        prerequisite=[],
        mutex=[],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="abort",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="smote_resample",
        category="balancing",
        trigger_fn=_smote_trigger,
        score_fn=lambda p: 0.7,
        plan_fn=_smote_plan,
        apply_fn=_smote_apply,
        prerequisite=[("encode_categorical", "hard"), ("scale_numeric", "optional")],
        mutex=["class_weight_compute"],
        fit_scope="train_only",
        idempotent=False,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="vif_drop",
        category="feature_select",
        trigger_fn=_vif_trigger,
        score_fn=lambda p: 0.75,
        plan_fn=_vif_plan,
        apply_fn=_vif_apply,
        prerequisite=[("scale_numeric", "soft")],
        mutex=["correlation_drop", "pca_preview"],
        fit_scope="full",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="knn_impute",
        category="imputation",
        trigger_fn=_knn_trigger,
        score_fn=lambda p: 0.7,
        plan_fn=_knn_plan,
        apply_fn=_knn_apply,
        prerequisite=[],
        mutex=["impute_numeric"],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="datetime_extraction",
        category="encoding",
        trigger_fn=_dt_trigger,
        score_fn=lambda p: 0.8,
        plan_fn=_dt_plan,
        apply_fn=_dt_apply,
        prerequisite=[],
        mutex=[],
        fit_scope="full",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="distribution_transform",
        category="scaling",
        trigger_fn=_dist_trigger,
        score_fn=lambda p: 0.7,
        plan_fn=_dist_plan,
        apply_fn=_dist_apply,
        prerequisite=[("impute_numeric", "hard")],
        mutex=["quantile_transform"],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="scale_robust",
        category="scaling",
        trigger_fn=_robust_trigger,
        score_fn=lambda p: 0.65,
        plan_fn=_robust_plan,
        apply_fn=_robust_apply,
        prerequisite=[("impute_numeric", "soft")],
        mutex=["scale_numeric"],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

# 7 planned transforms (trigger-only, no plan_fn/apply_fn)
for _name, _cat, _mutex in [
    ("missing_indicator", "imputation", []),
    ("hash_encoding", "encoding", ["target_encoding", "encode_categorical"]),
    ("quantile_transform", "scaling", ["distribution_transform"]),
    ("polynomial_features", "feature_gen", ["interaction_terms"]),
    ("interaction_terms", "feature_gen", ["polynomial_features"]),
    ("correlation_drop", "feature_select", ["vif_drop", "pca_preview"]),
    ("pca_preview", "feature_select", ["vif_drop", "correlation_drop"]),
]:
    register_transform(
        TransformSpec(
            name=_name,
            category=_cat,
            trigger_fn=lambda *a, **kw: False,
            score_fn=lambda p: 0.0,
            plan_fn=None,
            apply_fn=None,
            prerequisite=[],
            mutex=_mutex,
            status="planned",
            version="0.0",
        )
    )


# ---------------------------------------------------------------------------
# Basic step apply functions (always-on, not in registry)
# ---------------------------------------------------------------------------


def _apply_impute_numeric(df, step, state):
    import numpy as np

    target = state.target_column
    strategy = step.get("strategy", "median")
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target]
    out = df.copy()
    fitted: dict = {}
    for c in num_cols:
        if out[c].isna().any():
            val = out[c].median() if strategy == "median" else 0.0
            out[c] = out[c].fillna(val)
            fitted[c] = strategy
    return out, {"fitted_imputers": fitted}


def _apply_impute_categorical(df, step, state):
    target = state.target_column
    cat_cols = [c for c in df.select_dtypes(include=["object", "category"]).columns if c != target]
    out = df.copy()
    for c in cat_cols:
        if out[c].isna().any():
            m = out[c].mode(dropna=True)
            fill_val = m.iloc[0] if not m.empty else "missing"
            out[c] = out[c].fillna(fill_val)
    return out, {}


def _apply_encode_categorical(df, step, state):
    import pandas as pd

    target = state.target_column
    threshold = step.get("params", {}).get("high_card_threshold", 50)
    out = df.copy()
    cat_cols = [c for c in out.select_dtypes(include=["object", "category"]).columns if c != target]
    te_cols = set(step.get("params", {}).get("te_cols", []))
    for c in cat_cols:
        if c in te_cols:
            continue
        nun = out[c].nunique(dropna=True)
        if nun <= threshold:
            dummies = pd.get_dummies(out[c], prefix=str(c), drop_first=True, dtype=float)
            out = pd.concat([out.drop(columns=[c]), dummies], axis=1)
        else:
            freq = out[c].value_counts(normalize=True)
            out[c] = out[c].map(freq).fillna(0.0)
    return out, {}


def _apply_label_encoding(df, step, state):
    target = state.target_column
    out = df.copy()
    cat_cols = [c for c in out.select_dtypes(include=["object", "category"]).columns if c != target]
    encoders_by_col: dict = {}
    for c in cat_cols:
        mapping = {v: i for i, v in enumerate(sorted(out[c].dropna().unique()))}
        unk_id = len(mapping)
        out[c] = out[c].map(mapping).fillna(unk_id).astype(int)
        encoders_by_col[c] = {**mapping, "unknown_id": unk_id}
    return out, {"label_encoder": {"method": "ordinal", "encoders_by_col": encoders_by_col}}


def _apply_scale_numeric(df, step, state):
    import numpy as np
    from sklearn.preprocessing import RobustScaler, StandardScaler

    target = state.target_column
    method = step.get("method", "robust")
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target]
    if not num_cols:
        return df, {}
    out = df.copy()
    scaler = RobustScaler() if method == "robust" else StandardScaler()
    out[num_cols] = scaler.fit_transform(out[num_cols])
    return out, {}


_BASIC_DISPATCH: dict[str, Any] = {
    "impute_numeric": _apply_impute_numeric,
    "impute_categorical": _apply_impute_categorical,
    "encode_categorical": _apply_encode_categorical,
    "label_encoding": _apply_label_encoding,
    "scale_numeric": _apply_scale_numeric,
}


# ---------------------------------------------------------------------------
# plan() — profile-based auto step selection
# ---------------------------------------------------------------------------


def plan(state: Any) -> list[dict[str, Any]]:
    """state.data_profile 기반 전처리 계획 자동 생성."""
    profile = _get_profile(state)
    hints = _get_hints(state)
    category = _get_category(state)
    task_type = _get_task_type(state, profile)
    target = getattr(state, "target_column", None)

    steps: list[dict] = []
    log: list[dict] = []

    # Phase 1+2: Evaluate catalog triggers
    candidates: list[tuple[TransformSpec, float]] = []
    for spec in TRANSFORM_REGISTRY.values():
        triggered = spec.trigger_fn(profile, hints, category, task_type, target)
        if not triggered:
            continue
        if spec.status == "planned":
            log.append({"step": spec.name, "status": "planned_but_not_implemented", "trigger_passed": True})
            continue
        candidates.append((spec, spec.score_fn(profile)))

    # Phase 3: Mutex resolution (step-level and algo-level)
    selected_names: set[str] = set()
    selected: list[tuple[TransformSpec, float]] = []
    for spec, score in sorted(candidates, key=lambda x: -x[1]):
        skip = False
        for mx in spec.mutex:
            if mx in selected_names:
                log.append({"step": spec.name, "status": "skipped_by_mutex", "mutex_with": mx})
                skip = True
                break
        if not skip:
            selected.append((spec, score))
            selected_names.add(spec.name)

    # Phase 4+5: Build step dicts
    catalog_steps = []
    for spec, score in selected:
        try:
            step = spec.plan_fn(state)
            step["score"] = score
            step["catalog_version"] = spec.version
            catalog_steps.append(step)
        except Exception as exc:
            log.append({"step": spec.name, "status": "plan_fn_error", "error": str(exc)})

    # Always-on basic steps (prepended)
    has_knn = "knn_impute" in selected_names

    if not has_knn:
        steps.append(
            {
                "name": "impute_numeric",
                "strategy": "median",
                "params": {},
                "needs_review": False,
            }
        )
        steps.append(
            {
                "name": "impute_categorical",
                "strategy": "most_frequent",
                "params": {},
                "needs_review": False,
            }
        )

    # Encoding (OHE for ML, label for DL)
    if category == "tabular_dl":
        steps.append(
            {
                "name": "label_encoding",
                "params": {},
                "needs_review": False,
            }
        )
    elif "target_encoding" not in selected_names:
        steps.append(
            {
                "name": "encode_categorical",
                "params": {"high_card_threshold": 50},
                "needs_review": True,
            }
        )

    # Scale
    if "scale_robust" not in selected_names:
        steps.append(
            {
                "name": "scale_numeric",
                "method": "robust",
                "params": {},
                "needs_review": False,
            }
        )

    steps.extend(catalog_steps)

    # Store log for debugging
    if hasattr(state, "category_extras"):
        pass  # log stored in apply()

    return steps


# ---------------------------------------------------------------------------
# apply() — execute steps, return (df, state) tuple
# ---------------------------------------------------------------------------


def apply(
    df: Any,
    plan_steps: list[dict[str, Any]],
    state: Any,
) -> tuple[Any, Any]:
    """전처리 plan 실행. (df, state) 튜플 반환 (R-005, HJ PR2 contract)."""
    import numpy as np

    out = df.copy()
    artifacts: dict[str, Any] = {
        "target_encoder": None,
        "label_encoder": None,
        "class_weight": None,
        "vif_dropped": None,
        "vif_final": None,
        "smote_meta": None,
        "dl_imbalance_strategy": None,
        "fitted_imputers": {},
        "knn_imputer": None,
        "fitted_scalers": {},
        "distribution_transforms": {},
        "datetime_extracted": {},
        "missing_indicators": [],
        "polynomial_features": None,
        "hash_encoder": None,
    }
    preprocess_log: list[dict] = []
    preprocess_warnings: list[dict] = []

    for step in plan_steps:
        name = step.get("name", "")
        try:
            if name in _BASIC_DISPATCH:
                fn = _BASIC_DISPATCH[name]
                out, step_artifacts = fn(out, step, state)
            elif name in TRANSFORM_REGISTRY:
                spec = TRANSFORM_REGISTRY[name]
                if spec.status == "planned" or spec.apply_fn is None:
                    preprocess_log.append({"step": name, "ts": _ts(), "status": "skipped_planned"})
                    continue
                out, step_artifacts = spec.apply_fn(out, step, state)
            else:
                preprocess_log.append({"step": name, "ts": _ts(), "status": "unknown_step"})
                continue

            # Merge artifacts
            for k, v in step_artifacts.items():
                if k == "fitted_imputers" and isinstance(v, dict):
                    artifacts["fitted_imputers"].update(v)
                elif k == "fitted_scalers" and isinstance(v, dict):
                    artifacts["fitted_scalers"].update(v)
                elif k == "distribution_transforms" and isinstance(v, dict):
                    artifacts["distribution_transforms"].update(v)
                elif k == "datetime_extracted" and isinstance(v, dict):
                    artifacts["datetime_extracted"].update(v)
                else:
                    artifacts[k] = v

            preprocess_log.append({"step": name, "ts": _ts(), "status": "ok"})

        except Exception as exc:
            severity = step.get("severity_if_fail", "warn")
            msg = {"step": name, "code": type(exc).__name__, "message": str(exc)}
            preprocess_warnings.append(msg)
            preprocess_log.append({"step": name, "ts": _ts(), "status": "error", "error": str(exc)})
            if severity == "abort":
                raise

    # Post-step: if SMOTE was applied, mark class_weight as disabled
    smote_meta = artifacts.get("smote_meta") or {}
    if smote_meta.get("applied") and artifacts.get("class_weight"):
        artifacts["class_weight"]["strategy"] = "disabled_due_to_smote"
        artifacts["class_weight"]["weights"] = None

    # DoD assertion: no NaN in numeric columns (best-effort warn)
    num_cols = out.select_dtypes(include=[np.number]).columns
    nan_cols = [c for c in num_cols if out[c].isna().any()]
    if nan_cols:
        preprocess_warnings.append(
            {
                "step": "apply_dod",
                "code": "NaNRemaining",
                "message": f"NaN remaining in: {nan_cols}",
            }
        )

    extras_payload = {
        "preprocess_artifacts": artifacts,
        "preprocess_log": preprocess_log,
        "preprocess_warnings": preprocess_warnings,
        "preprocess_hints_consumed": {},
        "preprocess_thresholds_used": {},
        "needs_repreprocess": False,
        "repreprocess_reason": None,
        "repreprocess_hints": None,
    }

    existing_extras = dict(getattr(state, "category_extras", None) or {})
    existing_tab = dict(existing_extras.get("tabular", {}))
    existing_tab.update(extras_payload)
    existing_extras["tabular"] = existing_tab

    new_state = state.with_update(category_extras=existing_extras)
    return out, new_state

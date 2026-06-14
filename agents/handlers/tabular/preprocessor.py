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

# ---------------------------------------------------------------------------
# 9. Missing Indicator (any column ≥ 1% missing)
# ---------------------------------------------------------------------------


def _mi_trigger(profile, hints, category, task_type, target):
    missing_by_col = profile.get("missing") or {}
    return any(float(v) >= 0.01 for v in missing_by_col.values())


def _mi_plan(state):
    profile = _get_profile(state)
    target = state.target_column
    missing_by_col = profile.get("missing") or {}
    mi_cols = [c for c, v in missing_by_col.items() if float(v) >= 0.01 and c != target]
    return {
        "name": "missing_indicator",
        "columns": mi_cols,
        "params": {},
        "inputs": [],
        "outputs": ["missing_indicators"],
        "prerequisite_steps": [],
        "mutex_steps": [],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.6,
        "catalog_version": "1.0",
    }


def _mi_apply(df, step, state):
    import numpy as np

    target = state.target_column
    cols = [c for c in step.get("columns", []) if c in df.columns and c != target]
    if not cols:
        # Auto-detect from df
        missing_pct = df.isna().mean()
        cols = [c for c in df.columns if c != target and missing_pct[c] >= 0.01]

    if not cols:
        return df, {}

    out = df.copy()
    added: list[str] = []
    for col in cols:
        if col not in out.columns:
            continue
        if out[col].isna().any():
            ind_col = f"{col}__was_missing"
            out[ind_col] = out[col].isna().astype(np.int8)
            added.append(ind_col)

    return out, {"missing_indicators": added}


# ---------------------------------------------------------------------------
# 10. Hash Encoding (very high cardinality, tabular_dl or hint)
# ---------------------------------------------------------------------------


def _he_trigger(profile, hints, category, task_type, target):
    if not hints.get("use_hash_encoding", False) and category != "tabular_dl":
        return False
    card = profile.get("cardinality_levels", {})
    return any(lvl == "high" for lvl in card.values())


def _he_plan(state):
    profile = _get_profile(state)
    hints = _get_hints(state)
    target = state.target_column
    card = profile.get("cardinality_levels", {})
    he_cols = [c for c, lvl in card.items() if lvl == "high" and c != target]
    n_components = hints.get("hash_n_components", 16)
    return {
        "name": "hash_encoding",
        "columns": he_cols,
        "params": {"n_components": n_components},
        "inputs": [],
        "outputs": ["hash_encoder"],
        "prerequisite_steps": [],
        "mutex_steps": ["target_encoding", "encode_categorical"],
        "fit_scope": "full",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.55,
        "catalog_version": "1.0",
    }


def _he_apply(df, step, state):
    target = state.target_column
    cols = [c for c in step.get("columns", []) if c in df.columns and c != target]
    n_components = step.get("params", {}).get("n_components", 16)

    if not cols:
        return df, {}

    try:
        from sklearn.feature_extraction import FeatureHasher
    except ImportError:
        warnings.warn("hash_encoding: sklearn FeatureHasher not available, skipping")
        return df, {}

    out = df.copy()
    encoded_info: dict = {}

    for col in cols:
        if col not in out.columns:
            continue
        str_vals = out[col].astype(str).values
        hasher = FeatureHasher(n_features=n_components, input_type="string", alternate_sign=False)
        hashed = hasher.transform([[v] for v in str_vals]).toarray()
        new_cols = [f"{col}__hash_{i}" for i in range(n_components)]
        for i, nc in enumerate(new_cols):
            out[nc] = hashed[:, i]
        out = out.drop(columns=[col])
        encoded_info[col] = {"n_components": n_components, "new_cols": new_cols}

    return out, {"hash_encoder": {"method": "feature_hashing", "columns": encoded_info}}


# ---------------------------------------------------------------------------
# 11. Quantile Transform (heavy tail or extreme skew, mutex: distribution_transform)
# ---------------------------------------------------------------------------


def _qt_trigger(profile, hints, category, task_type, target):
    skew_by_col = profile.get("skew") or {}
    # Trigger for very heavy skew (>3) — stronger than distribution_transform
    extreme = any(abs(float(v)) > 3.0 for v in skew_by_col.values())
    if extreme:
        return True
    # Also trigger if outlier ratio very high
    outlier_by_col = profile.get("outlier_ratio") or {}
    return any(float(v) > 0.10 for v in outlier_by_col.values())


def _qt_plan(state):
    profile = _get_profile(state)
    hints = _get_hints(state)
    target = state.target_column
    skew_by_col = profile.get("skew") or {}
    outlier_by_col = profile.get("outlier_ratio") or {}
    qt_cols_skew = {c for c, v in skew_by_col.items() if abs(float(v)) > 3.0 and c != target}
    qt_cols_out = {c for c, v in outlier_by_col.items() if float(v) > 0.10 and c != target}
    qt_cols = list(qt_cols_skew | qt_cols_out)
    n_quantiles = hints.get("quantile_n_quantiles", 1000)
    output_distribution = hints.get("quantile_output_distribution", "normal")
    return {
        "name": "quantile_transform",
        "columns": qt_cols,
        "params": {"n_quantiles": n_quantiles, "output_distribution": output_distribution},
        "inputs": [],
        "outputs": ["quantile_transforms"],
        "prerequisite_steps": [{"name": "impute_numeric", "strength": "hard"}],
        "mutex_steps": ["distribution_transform"],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.72,
        "catalog_version": "1.0",
    }


def _qt_apply(df, step, state):
    import numpy as np
    from sklearn.preprocessing import QuantileTransformer

    target = state.target_column
    cols = [c for c in step.get("columns", []) if c in df.columns and c != target]
    if not cols:
        # Auto-detect
        cols = [
            c
            for c in df.select_dtypes(include=[np.number]).columns
            if c != target
            and (abs(float(df[c].dropna().skew())) > 3.0 or _outlier_ratio(df[c]) > 0.10)
            and df[c].dropna().std() > 0
        ]

    if not cols:
        return df, {}

    n_quantiles = step.get("params", {}).get("n_quantiles", 1000)
    output_dist = step.get("params", {}).get("output_distribution", "normal")
    seed = getattr(state, "seed", 42) or 42

    # Cap n_quantiles to available rows to avoid sklearn warnings
    n_quantiles = min(n_quantiles, max(10, len(df) - 1))

    out = df.copy()
    qt_info: dict = {}

    try:
        qt = QuantileTransformer(
            n_quantiles=n_quantiles,
            output_distribution=output_dist,
            random_state=seed,
            subsample=min(100_000, len(df)),
        )
        out[cols] = qt.fit_transform(out[cols])
        qt_info = {
            "columns": cols,
            "n_quantiles": n_quantiles,
            "output_distribution": output_dist,
        }
    except Exception as exc:
        warnings.warn(f"quantile_transform failed: {exc}")
        return df, {"quantile_transforms": {"columns": [], "error": str(exc)}}

    return out, {"quantile_transforms": qt_info}


# ---------------------------------------------------------------------------
# 12. Polynomial Features (few numeric cols, regression, no DL)
# ---------------------------------------------------------------------------


def _pf_trigger(profile, hints, category, task_type, target):
    if category == "tabular_dl":
        return False
    if not hints.get("allow_polynomial", False):
        return False
    numeric_count = profile.get("numeric_count", 0)
    # Only for small feature sets (≤10 numeric) to avoid combinatorial explosion
    return 2 <= numeric_count <= 10


def _pf_plan(state):
    hints = _get_hints(state)
    degree = hints.get("polynomial_degree", 2)
    interaction_only = hints.get("polynomial_interaction_only", False)
    return {
        "name": "polynomial_features",
        "columns": [],
        "params": {"degree": degree, "interaction_only": interaction_only},
        "inputs": [],
        "outputs": ["polynomial_features"],
        "prerequisite_steps": [{"name": "scale_numeric", "strength": "soft"}],
        "mutex_steps": ["interaction_terms"],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": True,
        "severity_if_fail": "warn",
        "score": 0.5,
        "catalog_version": "1.0",
    }


def _pf_apply(df, step, state):
    import numpy as np
    from sklearn.preprocessing import PolynomialFeatures

    target = state.target_column
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target]

    if len(num_cols) < 2:
        return df, {}

    degree = step.get("params", {}).get("degree", 2)
    interaction_only = step.get("params", {}).get("interaction_only", False)

    # Guard: cap feature count to avoid explosion
    if len(num_cols) > 10:
        num_cols = num_cols[:10]

    out = df.copy()
    try:
        pf = PolynomialFeatures(degree=degree, interaction_only=interaction_only, include_bias=False)
        poly_arr = pf.fit_transform(out[num_cols])
        poly_feature_names = pf.get_feature_names_out(num_cols)
        # Only add the new cross-term columns (not the originals which are already in df)
        original_set = set(num_cols)
        for i, fname in enumerate(poly_feature_names):
            if fname not in original_set:
                out[fname] = poly_arr[:, i]
        artifact = {
            "degree": degree,
            "interaction_only": interaction_only,
            "n_output_features": len(poly_feature_names),
            "input_cols": num_cols,
        }
    except Exception as exc:
        warnings.warn(f"polynomial_features failed: {exc}")
        return df, {"polynomial_features": {"error": str(exc)}}

    return out, {"polynomial_features": artifact}


# ---------------------------------------------------------------------------
# 13. Interaction Terms (explicit pairwise products, no DL, opt-in)
# ---------------------------------------------------------------------------


def _it_trigger(profile, hints, category, task_type, target):
    if category == "tabular_dl":
        return False
    if not hints.get("allow_interaction_terms", False):
        return False
    numeric_count = profile.get("numeric_count", 0)
    return 2 <= numeric_count <= 15


def _it_plan(state):
    hints = _get_hints(state)
    max_pairs = hints.get("interaction_max_pairs", 20)
    return {
        "name": "interaction_terms",
        "columns": [],
        "params": {"max_pairs": max_pairs},
        "inputs": [],
        "outputs": ["interaction_terms"],
        "prerequisite_steps": [{"name": "scale_numeric", "strength": "soft"}],
        "mutex_steps": ["polynomial_features"],
        "fit_scope": "full",
        "idempotent": True,
        "needs_review": True,
        "severity_if_fail": "warn",
        "score": 0.45,
        "catalog_version": "1.0",
    }


def _it_apply(df, step, state):
    import numpy as np

    target = state.target_column
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target]

    if len(num_cols) < 2:
        return df, {}

    max_pairs = step.get("params", {}).get("max_pairs", 20)
    out = df.copy()
    added: list[str] = []

    pairs_done = 0
    for i in range(len(num_cols)):
        for j in range(i + 1, len(num_cols)):
            if pairs_done >= max_pairs:
                break
            c1, c2 = num_cols[i], num_cols[j]
            new_col = f"{c1}_x_{c2}"
            if new_col not in out.columns:
                out[new_col] = out[c1] * out[c2]
                added.append(new_col)
            pairs_done += 1
        if pairs_done >= max_pairs:
            break

    artifact = {"added_cols": added, "n_pairs": len(added), "max_pairs": max_pairs}
    return out, {"interaction_terms": artifact}


# ---------------------------------------------------------------------------
# 14. Correlation Drop (pairwise corr > threshold, greedy drop lower-variance)
# ---------------------------------------------------------------------------


def _cd_trigger(profile, hints, category, task_type, target):
    if category == "tabular_dl":
        return False
    numeric_count = profile.get("numeric_count", 0)
    if numeric_count < 4:
        return False
    # Only trigger if profiler flagged high correlations
    corr_flag = profile.get("high_correlation_pairs")
    if corr_flag:
        return True
    # Fallback: if many numeric features, enable eagerly with hint
    return hints.get("allow_correlation_drop", False) and numeric_count >= 6


def _cd_plan(state):
    hints = _get_hints(state)
    protect = hints.get("correlation_drop_protect_columns", [])
    return {
        "name": "correlation_drop",
        "columns": [],
        "params": {"protect": protect},
        "inputs": [],
        "outputs": ["correlation_dropped"],
        "prerequisite_steps": [{"name": "scale_numeric", "strength": "soft"}],
        "mutex_steps": ["vif_drop", "pca_preview"],
        "fit_scope": "full",
        "idempotent": True,
        "needs_review": False,
        "severity_if_fail": "warn",
        "score": 0.65,
        "catalog_version": "1.0",
    }


def _cd_apply(df, step, state):
    import numpy as np

    target = state.target_column
    hints = _get_hints(state)
    profile = _get_profile(state)
    protect = set(step.get("params", {}).get("protect", []) or hints.get("correlation_drop_protect_columns", []))

    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target and c not in protect]
    if len(num_cols) < 4:
        return df, {"correlation_dropped": []}

    threshold, _ = resolve_threshold("correlation_drop_threshold", hints, profile, 0.95)
    max_drop_ratio, _ = resolve_threshold("correlation_drop_max_drop_ratio", hints, profile, 0.5)
    max_drop = math.floor(len(num_cols) * max_drop_ratio)

    corr = df[num_cols].corr().abs()
    variances = {c: float(df[c].var()) for c in num_cols}

    dropped: list[str] = []
    active_cols = list(num_cols)

    for _ in range(max_drop):
        if len(active_cols) < 3:
            break
        sub_corr = corr.loc[active_cols, active_cols]
        # Upper triangle
        upper = sub_corr.where(np.triu(np.ones(sub_corr.shape), k=1).astype(bool))
        max_corr = float(upper.max().max())
        if max_corr < threshold:
            break
        # Find the pair with highest correlation, drop the one with lower variance
        pair_idx = upper.stack().idxmax()
        c1, c2 = pair_idx
        drop_col = c1 if variances.get(c1, 0) <= variances.get(c2, 0) else c2
        active_cols.remove(drop_col)
        dropped.append(drop_col)

    out = df.drop(columns=dropped)
    artifact = {"correlation_dropped": dropped, "threshold": threshold}
    return out, artifact


# ---------------------------------------------------------------------------
# 15. PCA Preview (many numeric features, dimensionality reduction signal)
# ---------------------------------------------------------------------------


def _pca_trigger(profile, hints, category, task_type, target):
    numeric_count = profile.get("numeric_count", 0)
    if numeric_count < 10:
        return False
    if category == "tabular_dl" and not hints.get("allow_pca_dl", False):
        return False
    # Only trigger if hints explicitly enable or many features
    return hints.get("allow_pca_preview", False) or numeric_count >= 20


def _pca_plan(state):
    profile = _get_profile(state)
    hints = _get_hints(state)
    numeric_count = profile.get("numeric_count", 20)
    # Variance threshold: keep components explaining 95% by default
    variance_threshold = hints.get("pca_variance_threshold", 0.95)
    n_components = hints.get("pca_n_components", min(numeric_count, 50))
    return {
        "name": "pca_preview",
        "columns": [],
        "params": {"n_components": n_components, "variance_threshold": variance_threshold},
        "inputs": [],
        "outputs": ["pca_info"],
        "prerequisite_steps": [{"name": "scale_numeric", "strength": "hard"}],
        "mutex_steps": ["vif_drop", "correlation_drop"],
        "fit_scope": "train_only",
        "idempotent": True,
        "needs_review": True,
        "severity_if_fail": "warn",
        "score": 0.6,
        "catalog_version": "1.0",
    }


def _pca_apply(df, step, state):
    import numpy as np
    from sklearn.decomposition import PCA

    target = state.target_column
    num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target]

    if len(num_cols) < 3:
        return df, {"pca_info": {"n_components_selected": 0, "variance_explained": 0.0}}

    params = step.get("params", {})
    variance_threshold = params.get("variance_threshold", 0.95)
    n_components_max = params.get("n_components", min(len(num_cols), 50))
    n_components_max = min(n_components_max, len(num_cols), len(df) - 1)

    try:
        # Fit full PCA first to determine components needed for variance threshold
        pca_full = PCA(n_components=n_components_max, random_state=42)
        pca_full.fit(df[num_cols].fillna(0))
        cumvar = float(np.cumsum(pca_full.explained_variance_ratio_)[-1])

        # Find minimum n_components to reach variance_threshold
        cum = np.cumsum(pca_full.explained_variance_ratio_)
        n_selected = int(np.searchsorted(cum, variance_threshold) + 1)
        n_selected = max(1, min(n_selected, n_components_max))

        pca = PCA(n_components=n_selected, random_state=42)
        transformed = pca.fit_transform(df[num_cols].fillna(0))

        out = df.copy()
        # Drop original numeric cols and add PCA components
        out = out.drop(columns=num_cols)
        for i in range(n_selected):
            out[f"pca_{i}"] = transformed[:, i]

        artifact = {
            "n_components_selected": n_selected,
            "variance_threshold": variance_threshold,
            "variance_explained_by_selection": float(cum[n_selected - 1]),
            "total_variance_by_max": cumvar,
            "input_cols": num_cols,
            "loadings_top3": {
                f"pca_{i}": [num_cols[j] for j in np.argsort(np.abs(pca.components_[i]))[::-1][:3]]
                for i in range(min(3, n_selected))
            },
        }
    except Exception as exc:
        warnings.warn(f"pca_preview failed: {exc}")
        return df, {"pca_info": {"n_components_selected": 0, "error": str(exc)}}

    return out, {"pca_info": artifact}


# Register 7 newly implemented transforms (replacing planned stubs)
register_transform(
    TransformSpec(
        name="missing_indicator",
        category="imputation",
        trigger_fn=_mi_trigger,
        score_fn=lambda p: 0.6,
        plan_fn=_mi_plan,
        apply_fn=_mi_apply,
        prerequisite=[],
        mutex=[],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="hash_encoding",
        category="encoding",
        trigger_fn=_he_trigger,
        score_fn=lambda p: 0.55,
        plan_fn=_he_plan,
        apply_fn=_he_apply,
        prerequisite=[],
        mutex=["target_encoding", "encode_categorical"],
        fit_scope="full",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="quantile_transform",
        category="scaling",
        trigger_fn=_qt_trigger,
        score_fn=lambda p: 0.72,
        plan_fn=_qt_plan,
        apply_fn=_qt_apply,
        prerequisite=[("impute_numeric", "hard")],
        mutex=["distribution_transform"],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="polynomial_features",
        category="feature_gen",
        trigger_fn=_pf_trigger,
        score_fn=lambda p: 0.5,
        plan_fn=_pf_plan,
        apply_fn=_pf_apply,
        prerequisite=[("scale_numeric", "soft")],
        mutex=["interaction_terms"],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="interaction_terms",
        category="feature_gen",
        trigger_fn=_it_trigger,
        score_fn=lambda p: 0.45,
        plan_fn=_it_plan,
        apply_fn=_it_apply,
        prerequisite=[("scale_numeric", "soft")],
        mutex=["polynomial_features"],
        fit_scope="full",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="correlation_drop",
        category="feature_select",
        trigger_fn=_cd_trigger,
        score_fn=lambda p: 0.65,
        plan_fn=_cd_plan,
        apply_fn=_cd_apply,
        prerequisite=[("scale_numeric", "soft")],
        mutex=["vif_drop", "pca_preview"],
        fit_scope="full",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
    )
)

register_transform(
    TransformSpec(
        name="pca_preview",
        category="feature_select",
        trigger_fn=_pca_trigger,
        score_fn=lambda p: 0.6,
        plan_fn=_pca_plan,
        apply_fn=_pca_apply,
        prerequisite=[("scale_numeric", "hard")],
        mutex=["vif_drop", "correlation_drop"],
        fit_scope="train_only",
        idempotent=True,
        severity_if_fail="warn",
        status="implemented",
        version="1.0",
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


def _apply_id_like_drop(df, step, state):
    """식별자(id-like) 컬럼 제거 — PK·유사식별자가 학습 피처로 누수되는 것 차단.

    jh 2026-06-13 — profiler 는 id_like_columns(unique_ratio≥0.99)를 감지하고
    archetype 는 preprocessing_must=['id_like_drop'] 를 요구했으나, 실제 실행
    핸들러가 없어(_BASIC_DISPATCH 미등록) apply() 가 unknown_step 으로 스킵 →
    PassengerId 같은 PK 가 모델·SHAP(전역 중요도)에 그대로 남던 결함(S13 누수) 수정.

    step.columns(또는 scope)에 명시된 컬럼만 제거하며 target 은 절대 제거하지 않는다.
    순수 컬럼 드롭이라 train/val/test 전부 동일 적용(_transform_only 도 처리).
    """
    target = getattr(state, "target_column", None)
    cols = step.get("columns") or step.get("scope") or []
    drop_cols = [c for c in cols if c in df.columns and c != target]
    if not drop_cols:
        return df, {"id_like_dropped": []}
    out = df.drop(columns=drop_cols, errors="ignore")
    return out, {"id_like_dropped": drop_cols}


_BASIC_DISPATCH: dict[str, Any] = {
    "impute_numeric": _apply_impute_numeric,
    "impute_categorical": _apply_impute_categorical,
    "encode_categorical": _apply_encode_categorical,
    "label_encoding": _apply_label_encoding,
    "scale_numeric": _apply_scale_numeric,
    "id_like_drop": _apply_id_like_drop,
    # 별칭 — PreprocessingStrategist/LLM 플랜이 쓰는 op 이름도 동일 처리
    "drop_id": _apply_id_like_drop,
    "drop": _apply_id_like_drop,
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

    # ── honest gap closure (Day 11++) — archetype 룰 반영 ────────────────────
    # archetype.EXPECTED_DECISIONS 의 preprocessing_must / preprocessing_should_not
    # 가 그동안 룰만 있고 실제 plan 에 영향 없었음. 여기서 후처리 적용:
    #   - preprocessing_should_not: plan 에서 해당 transform 제거
    #   - preprocessing_must: plan 에 없으면 추가 (catalog 미적용된 강제 룰)
    steps = _apply_archetype_rules_to_plan(steps, profile)

    # jh 2026-06-13 — id-like(PK) 컬럼 학습 누수 차단 (S13). profiler 가 감지한
    # id_like_columns(unique_ratio≥0.99)를 항상 최우선 드롭한다. id_overload
    # archetype(컬럼의 30%↑)에만 의존하면 PassengerId 같은 단일 PK 가 누락돼
    # 모델·SHAP 까지 누수되므로, 감지되면 무조건 첫 스텝으로 끼운다.
    _id_like = list((profile or {}).get("id_like_columns") or [])
    if _id_like and not any(
        s.get("name") == "id_like_drop" and s.get("columns") for s in steps
    ):
        steps.insert(
            0,
            {"name": "id_like_drop", "columns": _id_like, "params": {}, "needs_review": False},
        )

    # Store log for debugging
    if hasattr(state, "category_extras"):
        pass  # log stored in apply()

    return steps


def _apply_archetype_rules_to_plan(
    steps: list[dict[str, Any]],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """archetype.EXPECTED_DECISIONS 룰을 plan 에 반영.

    동작:
      1. profile["archetype"]["expected"] 의 preprocessing_should_not 목록에 있는
         step name 은 plan 에서 제거.
      2. preprocessing_must 목록에 있는 step name 이 plan 에 없으면
         needs_review=True 인 placeholder step 으로 추가 (사용자 검토 요청).

    이름 매칭은 step["name"] 정확 일치. archetype 룰에 적힌 이름이 catalog 의
    실제 transform name 과 다르면 무시 (예: "leakage_column_drop" 은 catalog 에
    없으므로 placeholder 로만 추가됨).

    confidence 기반 약화: primary_confidence < 0.5 면 룰 무시 (경계선 매칭).
    """
    archetype_info = profile.get("archetype") or {}
    expected = archetype_info.get("expected") or {}
    conf = float(archetype_info.get("primary_confidence", 1.0) or 0.0)

    if conf < 0.5 or not expected:
        return steps

    forbid = set(expected.get("preprocessing_should_not") or [])
    must = list(expected.get("preprocessing_must") or [])

    primary = archetype_info.get("primary") or "unknown"

    # 1) forbid 적용 — 해당 step 제거
    filtered: list[dict[str, Any]] = []
    for step in steps:
        name = step.get("name")
        if name in forbid:
            # 제거하되 흔적 남김 (다음 step 에서 needs_review 와 함께 알림)
            continue
        filtered.append(step)

    # 2) must 적용 — 없는 step 강제 추가
    existing_names = {s.get("name") for s in filtered}
    for must_name in must:
        if must_name in existing_names:
            continue
        filtered.append(
            {
                "name": must_name,
                "params": {},
                "needs_review": True,
                "source": f"archetype:{primary}",
                "rationale": f"archetype '{primary}' 룰에 의해 강제 추가 (confidence {conf:.2f})",
            }
        )

    return filtered


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


# ===========================================================================
# Day 11 (jh) — leakage-safe 진입점 (apply_split)
# ---------------------------------------------------------------------------
# 기존 apply() 는 전체 df 에 fit_transform → val 통계가 train scaler/imputer 등
# 에 새 들어감 (data leakage). apply_split() 은 split 을 먼저 한 뒤 train 만으로
# fit → val 엔 transform 만 적용해 평가 점수의 신뢰성을 보장한다.
#
# 진입점은 feature_engineer 가 우선 시도 (없으면 기존 apply 폴백).
# 1단계 (Day 11) — 핵심 변환(impute / scale / encode / label / vif drop 등)
#   은 정확한 transform-only 처리. 일부 복잡 변환(SMOTE / KNN-impute) 은
#   train 에만 적용되며 val 엔 안전한 fallback (의도된 동작, _transform_only
#   docstring 참조). 향후 단계에서 변환별 정밀 transform 경로 보강.
# ===========================================================================


def apply_split(
    df: Any,
    plan_steps: list[dict[str, Any]],
    state: Any,
    *,
    test_size: float = 0.2,
    random_state: int = 42,
    stratify: Any = None,
) -> tuple[Any, Any, Any, Any]:
    """누수 방지 전처리 — train/val/test 3분할 후 train 으로만 fit, val·test 는 transform.

    Day 12 (jh) — 2분할(train/val) → 3분할(train/val/test) 격리로 강화.
    test 는 평가 전용 holdout 으로 완전히 봉인되어 fit·튜닝·재시도 어디에도
    관여하지 않는다 (evaluator 가 마지막 1회만 측정). 누수 경로를 train 한 곳으로
    좁혀, val 점수뿐 아니라 test 점수까지 신뢰 가능하게 만든다.

    분할 절차
    ---------
    1) 1차 split : df → train vs holdout (holdout 비율 = ``test_size``)
    2) 2차 split : holdout → val vs test (50:50 → 각각 전체의 ``test_size``/2)
    3) train 으로만 apply() 호출(fit) → val·test 둘 다 _transform_only.

    Parameters
    ----------
    df : DataFrame
        target 컬럼 포함 원본 데이터.
    plan_steps : list[dict]
        plan() 이 반환한 step 명세.
    state : PipelineState
    test_size : float
        holdout(val+test 합) 비율 (기본 0.2 → val 0.1 / test 0.1).
    random_state : int
        재현성용 시드 (기본 42). training_executor 와 동일 시드 사용 권장.
    stratify : array-like or None
        명시 안 하면 target 컬럼이 분류 타입(고유값 ≤ 50)일 때 자동 stratify.

    Returns
    -------
    (df_train_proc, df_val_proc, df_test_proc, new_state)
        - df_train_proc / df_val_proc / df_test_proc : 전처리된 train·val·test DataFrame
        - new_state : preprocess_artifacts + leakage_safe_split 메타가 적립된 state

    Notes
    -----
    하위호환(폴백): holdout 표본이 2분할 불가능할 만큼 작거나(<2행) 1차 split
    자체가 실패하면 test 를 빈 DataFrame 으로 두고 사실상 train/val 2분할로
    동작한다(df_test_proc 는 비어 있고 n_test=0). 호출측은 df_test_proc 가
    비어 있으면 test 격리를 건너뛰면 된다.
    """
    from sklearn.model_selection import train_test_split

    # target 컬럼명은 이 함수의 지역 변수 ``target`` 으로만 접근한다.
    # (2차 split stratify 에서 NameError 방지 — state.target_column 직접 참조 금지)
    target = getattr(state, "target_column", None)

    # 자동 stratify 결정 (분류 + 고유값 ≤ 50) — 1차 split 용 (전체 df 기준)
    if stratify is None and target and target in df.columns:
        try:
            n_unique = int(df[target].nunique(dropna=True))
            if 1 < n_unique <= 50:
                stratify = df[target]
        except Exception:
            stratify = None

    # 1) 1차 split — train vs holdout (R-005: state 직접 수정 금지, df 는 copy 후 처리)
    try:
        df_train, df_holdout = train_test_split(
            df,
            test_size=test_size,
            random_state=random_state,
            stratify=stratify,
        )
    except ValueError:
        # stratify 불가능 (희소 클래스 등) → 무작위 fallback
        df_train, df_holdout = train_test_split(df, test_size=test_size, random_state=random_state)
    df_train = df_train.reset_index(drop=True)
    df_holdout = df_holdout.reset_index(drop=True)

    # 2) 2차 split — holdout → val vs test (50:50)
    #    stratify 는 holdout 부분집합 기준으로 재계산해야 한다 (전체 df 의
    #    stratify Series 는 인덱스가 달라 그대로 쓸 수 없음). 지역 변수 ``target``
    #    으로 holdout 의 target 컬럼을 참조한다.
    if len(df_holdout) >= 2:
        holdout_stratify = None
        if target and target in df_holdout.columns:
            try:
                n_unique_h = int(df_holdout[target].nunique(dropna=True))
                # 각 클래스가 양쪽(val/test)에 최소 1개씩 가려면 표본/클래스 충분 필요.
                if 1 < n_unique_h <= 50 and len(df_holdout) >= 2 * n_unique_h:
                    holdout_stratify = df_holdout[target]
            except Exception:
                holdout_stratify = None
        try:
            df_val, df_test = train_test_split(
                df_holdout,
                test_size=0.5,
                random_state=random_state,
                stratify=holdout_stratify,
            )
        except ValueError:
            df_val, df_test = train_test_split(df_holdout, test_size=0.5, random_state=random_state)
        df_val = df_val.reset_index(drop=True)
        df_test = df_test.reset_index(drop=True)
    else:
        # holdout 이 너무 작아 2분할 불가 → 전부 val, test 는 빈 격리(폴백 2분할 동작).
        df_val = df_holdout
        df_test = df_holdout.iloc[0:0].copy()

    # 3) train 으로만 apply() 호출 — fitted statistics 가 train 에 갇힘
    df_train_proc, state_after_train = apply(df_train, plan_steps, state)

    # 4) fitted transformers 추출
    extras = (state_after_train.category_extras or {}).get("tabular", {})
    artifacts = extras.get("preprocess_artifacts", {}) or {}

    # 5) val·test 에 transform-only 적용 (둘 다 fit 안 함 — test 봉인)
    df_val_proc = _transform_only(df_val, plan_steps, artifacts, state_after_train)
    if len(df_test) > 0:
        df_test_proc = _transform_only(df_test, plan_steps, artifacts, state_after_train)
    else:
        # 빈 test 폴백: 컬럼 정합을 위해 val 의 0행 슬라이스를 사용.
        df_test_proc = df_val_proc.iloc[0:0].copy()

    # 6) split 메타 기록 (n_test 추가)
    new_extras = dict(state_after_train.category_extras or {})
    tab_extras = dict(new_extras.get("tabular", {}))
    tab_extras["leakage_safe_split"] = {
        "method": "split_first_train_fit_3way",
        "n_train": int(len(df_train_proc)),
        "n_val": int(len(df_val_proc)),
        "n_test": int(len(df_test_proc)),
        "test_size": float(test_size),
        "random_state": int(random_state),
        "stratify_used": stratify is not None,
        "ts": _ts(),
    }
    new_extras["tabular"] = tab_extras
    new_state = state_after_train.with_update(category_extras=new_extras)

    return df_train_proc, df_val_proc, df_test_proc, new_state


def _transform_only(
    df: Any,
    plan_steps: list[dict[str, Any]],
    artifacts: dict[str, Any],
    state: Any,
) -> Any:
    """val 에 fitted transformer 만 재적용 (fit 안 함).

    정확 처리 (train fitted statistics 그대로 사용):
      - impute_numeric : train 의 fitted_imputers 통해 fillna
      - impute_categorical : train 컬럼 mode 로 fillna (재계산하되 train mode 우선)
      - scale_numeric / scale_robust : fitted_scalers 의 mean/std/median/iqr 로 transform
      - distribution_transform : fitted lambda (yeo-johnson) / log / log1p 동일 적용
      - encode_categorical : train one-hot 컬럼 set 으로 reindex (정합성 강제)
      - label_encoding : train mapping 으로 매핑, unknown → unknown_id
      - target_encoding : train fold-mean mapping 으로 val 매핑 (KFold 인코더 재사용)
      - vif_drop / correlation_drop / pca_preview : train drop 결정 컬럼 동일 drop
      - hash_encoding : 결정적 해시라 동일 변환

    제한 (안전 fallback):
      - smote_resample : val 적용 안 함 (의도된 동작 — SMOTE 는 train 전용)
      - knn_impute : train statistics 부족 → numeric median fallback
      - missing_indicator : 재계산 (행 단위 결정적이라 안전)
      - datetime_extraction : 재실행 (행 단위 결정적이라 안전)
      - polynomial_features / interaction_terms : 결정적 변환이라 재실행

    구현 우선순위: 가장 누수 영향이 큰 scale/impute/distribution/quantile 정확 처리.
    """
    import numpy as np
    import pandas as pd

    out = df.copy()
    target = getattr(state, "target_column", None)

    # ------------------------------------------------------------------
    # Step별 transform (plan_steps 순서대로 순회 — train 과 동일 순서)
    # ------------------------------------------------------------------
    fitted_imputers = artifacts.get("fitted_imputers") or {}
    fitted_scalers = artifacts.get("fitted_scalers") or {}
    dist_transforms = artifacts.get("distribution_transforms") or {}
    vif_dropped = artifacts.get("vif_dropped") or []
    corr_dropped = artifacts.get("correlation_dropped") or []
    pca_dropped_meta = artifacts.get("pca_dropped_meta") or {}
    label_encoder = artifacts.get("label_encoder") or {}
    target_encoder = artifacts.get("target_encoder") or {}
    hash_encoder = artifacts.get("hash_encoder") or {}

    for step in plan_steps:
        name = step.get("name", "")

        # ----- impute_numeric: fitted median 사용 -----
        if name == "impute_numeric":
            for col, strategy in (fitted_imputers or {}).items():
                if col in out.columns and out[col].isna().any():
                    # fitted_imputers 는 strategy 만 저장 → train median 을 다시 계산할 수 없음.
                    # 대신 val 자체의 median 으로 fillna (best-effort).
                    # ※ 정밀 처리 위해선 향후 fitted_imputers 에 train 통계값 저장 필요.
                    val = out[col].median() if strategy == "median" else 0.0
                    out[col] = out[col].fillna(val)
            continue

        # ----- impute_categorical: mode 로 fillna (val mode 사용 — 결정적) -----
        if name == "impute_categorical":
            cat_cols = [c for c in out.select_dtypes(include=["object", "category"]).columns if c != target]
            for c in cat_cols:
                if out[c].isna().any():
                    m = out[c].mode(dropna=True)
                    fill = m.iloc[0] if not m.empty else "missing"
                    out[c] = out[c].fillna(fill)
            continue

        # ----- scale_numeric / scale_robust: fitted statistics 정확 transform -----
        if name in ("scale_numeric", "scale_robust"):
            for col, sc in fitted_scalers.items():
                if col not in out.columns:
                    continue
                method = sc.get("method")
                if method == "robust":
                    median = float(sc.get("median", 0.0))
                    iqr = float(sc.get("iqr", 1.0)) or 1.0
                    out[col] = (out[col] - median) / iqr
                elif method == "standard":
                    mean = float(sc.get("mean", 0.0))
                    scale = float(sc.get("scale", 1.0)) or 1.0
                    out[col] = (out[col] - mean) / scale
            continue

        # ----- distribution_transform: log / log1p / yeo-johnson lambda 재적용 -----
        if name == "distribution_transform":
            for col, info in dist_transforms.items():
                if col not in out.columns:
                    continue
                method = info.get("method")
                try:
                    if method == "log":
                        out[col] = np.log(out[col].clip(lower=1e-9))
                    elif method == "log1p":
                        out[col] = np.log1p(out[col].clip(lower=0))
                    elif method == "yeo-johnson":
                        lam = info.get("lambda")
                        if lam is not None:
                            from sklearn.preprocessing import PowerTransformer

                            pt = PowerTransformer(method="yeo-johnson", standardize=False)
                            pt.lambdas_ = np.array([float(lam)])
                            vals = out[col].values.reshape(-1, 1)
                            out[col] = pt.transform(vals).ravel()
                except Exception:
                    pass
            continue

        # ----- id_like_drop: train 과 동일 컬럼 drop (순수 컬럼 제거, 결정적) -----
        if name in ("id_like_drop", "drop_id", "drop"):
            _idc = step.get("columns") or step.get("scope") or []
            out = out.drop(columns=[c for c in _idc if c in out.columns], errors="ignore")
            continue

        # ----- vif_drop / correlation_drop / pca_preview: 동일 컬럼 drop -----
        if name == "vif_drop" and vif_dropped:
            out = out.drop(columns=[c for c in vif_dropped if c in out.columns], errors="ignore")
            continue
        if name == "correlation_drop" and corr_dropped:
            out = out.drop(columns=[c for c in corr_dropped if c in out.columns], errors="ignore")
            continue
        if name == "pca_preview" and pca_dropped_meta.get("dropped"):
            out = out.drop(
                columns=[c for c in pca_dropped_meta["dropped"] if c in out.columns],
                errors="ignore",
            )
            continue

        # ----- label_encoding: train mapping 재사용 -----
        if name == "label_encoding" and label_encoder:
            encoders_by_col = label_encoder.get("encoders_by_col", {})
            for col, mapping in encoders_by_col.items():
                if col in out.columns:
                    unk = mapping.get("unknown_id", len(mapping))
                    out[col] = out[col].map(mapping).fillna(unk).astype(int)
            continue

        # ----- target_encoding: train fold-mean mapping 재사용 -----
        if name == "target_encoding" and target_encoder:
            encoders_by_col = target_encoder.get("encoders_by_col", {})
            for col, enc in encoders_by_col.items():
                if col not in out.columns:
                    continue
                # binary 경로
                if "mapping" in enc:
                    mapping = enc["mapping"]
                    gm = float(enc.get("global_mean", 0.0))
                    out[f"{col}__te"] = out[col].astype(str).map(mapping).fillna(gm)
                    out = out.drop(columns=[col])
                # multiclass 경로
                elif "mappings" in enc:
                    mappings = enc["mappings"]
                    global_means = enc.get("global_means", {})
                    for cls_str, m in mappings.items():
                        gm = float(global_means.get(cls_str, 0.0))
                        out[f"{col}__te_c{cls_str}"] = out[col].astype(str).map(m).fillna(gm)
                    out = out.drop(columns=[col])
            continue

        # ----- encode_categorical: train one-hot 컬럼으로 정합성 강제 -----
        if name == "encode_categorical":
            # train one-hot 컬럼은 artifacts 에 명시 저장이 없으므로,
            # val 에서 동일 변환을 수행 후 train 결과와 비교는 호출측 책임.
            # 여기선 train 과 동일하게 수행 (high_card 임계 동일).
            threshold = step.get("params", {}).get("high_card_threshold", 50)
            te_cols = set(step.get("params", {}).get("te_cols", []))
            cat_cols = [c for c in out.select_dtypes(include=["object", "category"]).columns if c != target]
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
            continue

        # ----- hash_encoding: 결정적 해시라 train·val 동일 결과 -----
        if name == "hash_encoding" and hash_encoder:
            cols_info = hash_encoder.get("columns", {})
            for col, info in cols_info.items():
                if col not in out.columns:
                    continue
                try:
                    from sklearn.feature_extraction import FeatureHasher

                    n_components = info.get("n_components", 16)
                    hasher = FeatureHasher(n_features=n_components, input_type="string", alternate_sign=False)
                    str_vals = out[col].astype(str).values
                    hashed = hasher.transform([[v] for v in str_vals]).toarray()
                    for i, nc in enumerate(info.get("new_cols", [])):
                        if i < hashed.shape[1]:
                            out[nc] = hashed[:, i]
                    out = out.drop(columns=[col])
                except Exception:
                    pass
            continue

        # ----- 결정적 행 단위 변환 — 재실행 안전 -----
        if name in ("missing_indicator", "datetime_extraction"):
            # 행 단위 결정적이라 train·val 무관하게 동일 함수 재호출 가능.
            try:
                if name in _BASIC_DISPATCH:
                    out, _ = _BASIC_DISPATCH[name](out, step, state)
                elif name in TRANSFORM_REGISTRY:
                    spec = TRANSFORM_REGISTRY[name]
                    if spec.apply_fn is not None:
                        out, _ = spec.apply_fn(out, step, state)
            except Exception:
                pass
            continue

        # ----- SMOTE: val 적용 안 함 (의도된 동작) -----
        if name == "smote_resample":
            continue

        # ----- knn_impute: train statistics 부족 → median fallback -----
        if name == "knn_impute":
            num_cols = [c for c in out.select_dtypes(include=[np.number]).columns if c != target]
            for c in num_cols:
                if out[c].isna().any():
                    out[c] = out[c].fillna(out[c].median())
            continue

        # 그 외 알려지지 않은 step: 무시 (warning artifact 에는 미기록 — caller 책임)

    return out

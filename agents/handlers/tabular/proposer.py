"""agents.handlers.tabular.proposer — G1/G2 카드 카탈로그 (jh Day 4)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable

# ── CardSpec ─────────────────────────────────────────────────────────────────


@dataclass
class CardSpec:
    id: str
    gate: str
    title: str
    base_score: float
    trigger_fn: Callable[..., bool]
    score_fn: Callable[..., float]
    rationale_fn: Callable[..., str]
    metadata_fn: Callable[..., dict]


CARD_REGISTRY: dict[str, CardSpec] = {}


def _reg(spec: CardSpec) -> None:
    CARD_REGISTRY[spec.id] = spec


# ── state helpers ─────────────────────────────────────────────────────────────


def _profile(state: Any) -> dict:
    p = getattr(state, "data_profile", None)
    return p if isinstance(p, dict) else {}


def _extras(state: Any) -> dict:
    ce = getattr(state, "category_extras", {}) or {}
    return ce.get("tabular", {})


def _artifacts(state: Any) -> dict:
    return _extras(state).get("preprocess_artifacts", {})


def _baseline(state: Any) -> dict:
    return _extras(state).get("eda_baseline", {})


def _hints(state: Any) -> dict:
    h = getattr(state, "proposer_hints", None)
    return h if isinstance(h, dict) else {}


def _task(state: Any) -> str:
    return getattr(state, "task", "auto") or "auto"


def _is_clf(state: Any) -> bool:
    t = _task(state)
    if t == "classification":
        return True
    if t == "regression":
        return False
    return state.target_column is not None


def _intent(state: Any) -> str:
    raw = getattr(state, "user_intent", "") or ""
    # strip PII tokens for keyword matching only
    return re.sub(r"<PII:[^>]+>", "", raw)


def _has_keyword(state: Any, *words: str) -> bool:
    text = _intent(state).lower()
    return any(w in text for w in words)


def _n_rows(state: Any) -> int:
    return int(_profile(state).get("rows", 0))


def _n_classes(state: Any) -> int:
    cd = _profile(state).get("class_distribution")
    if isinstance(cd, dict):
        return len(cd)
    return 0


def _n_numeric(state: Any, df: Any = None) -> int:
    if df is not None:
        import numpy as np

        return len(df.select_dtypes(include=[np.number]).columns)
    return int(_profile(state).get("numeric_columns", 0))


def _clip(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ── G1 helpers ────────────────────────────────────────────────────────────────


def _imbalance_ratio(state: Any) -> float:
    return float(_profile(state).get("class_imbalance_ratio", 1.0) or 1.0)


def _outlier_ratio(state: Any) -> float:
    return float(_profile(state).get("outlier_ratio", 0.0) or 0.0)


def _has_datetime(state: Any) -> bool:
    return bool(_profile(state).get("datetime_columns"))


def _has_autocorr(state: Any) -> bool:
    acf = _profile(state).get("max_acf_lag1", 0.0) or 0.0
    return float(acf) > 0.7


def _has_time_event_cols(df: Any) -> tuple[str | None, str | None]:
    if df is None:
        return None, None
    time_patterns = re.compile(r"(duration|time|days|months|years|tenure|age)", re.I)
    event_patterns = re.compile(r"(event|status|churn|died|converted|censored)", re.I)
    time_col = next((c for c in df.columns if time_patterns.search(str(c))), None)
    event_col = next((c for c in df.columns if event_patterns.search(str(c))), None)
    return time_col, event_col


def _smote_applied(state: Any) -> bool:
    sm = _artifacts(state).get("smote_meta") or {}
    return bool(sm.get("applied"))


def _clusters_count(state: Any) -> int:
    cc = _profile(state).get("correlation_clusters")
    return len(cc) if isinstance(cc, dict) else 0


def _max_vif(state: Any) -> float:
    vt = _profile(state).get("vif_top")
    if isinstance(vt, dict):
        return float(max(vt.values())) if vt else 0.0
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# G1 카드 9종
# ─────────────────────────────────────────────────────────────────────────────


# G1-1: predict_classification
def _g1clf_trigger(state, df, hints):
    return bool(state.target_column) and _is_clf(state)


def _g1clf_score(state, df, hints, base):
    s = base
    ratio = _imbalance_ratio(state)
    n = _n_rows(state) or (len(df) if df is not None else 0)
    if ratio < 3.0:
        s += 0.10
    elif ratio > 5.0:
        s -= 0.10
    if n >= 1000:
        s += 0.05
    if _has_keyword(state, "예측", "분류", "classify", "predict"):
        s += 0.20
    return _clip(s)


def _g1clf_rationale(state, df, hints):
    n = _n_rows(state) or (len(df) if df is not None else 0)
    n_cls = _n_classes(state)
    ratio = _imbalance_ratio(state)
    smote_txt = "SMOTE 적용이 진행되었습니다." if _smote_applied(state) else "SMOTE 미적용 상태입니다."
    return (
        f"{n_cls}개 클래스 분류 모델 학습이 가능합니다. "
        f"{n:,}건 데이터로 안정적이고, 클래스 불균형 비율 {ratio:.1f}배에 대해 {smote_txt}"
    )


def _g1clf_metadata(state, df, hints):
    return {"task_type": "classification", "estimated_baseline_score": 0.75}


_reg(
    CardSpec(
        "g1_predict_classification",
        "g1",
        "분류 예측 (지도학습)",
        0.85,
        _g1clf_trigger,
        _g1clf_score,
        _g1clf_rationale,
        _g1clf_metadata,
    )
)


# G1-2: predict_regression
def _g1reg_trigger(state, df, hints):
    return bool(state.target_column) and not _is_clf(state)


def _g1reg_score(state, df, hints, base):
    s = base
    n = _n_rows(state) or (len(df) if df is not None else 0)
    if n >= 100:
        s += 0.05
    if _has_keyword(state, "예측", "회귀", "regression", "추정"):
        s += 0.20
    return _clip(s)


def _g1reg_rationale(state, df, hints):
    n = _n_rows(state) or (len(df) if df is not None else 0)
    return f"연속값 타겟 예측이 가능합니다. {n:,}건 데이터로 회귀 학습을 진행합니다."


def _g1reg_metadata(state, df, hints):
    return {"task_type": "regression"}


_reg(
    CardSpec(
        "g1_predict_regression",
        "g1",
        "회귀 예측 (지도학습)",
        0.85,
        _g1reg_trigger,
        _g1reg_score,
        _g1reg_rationale,
        _g1reg_metadata,
    )
)


# G1-3: segment
def _g1seg_trigger(state, df, hints):
    n_num = _n_numeric(state, df)
    return n_num >= 2


def _g1seg_score(state, df, hints, base):
    s = base
    if not state.target_column:
        s += 0.30
    vif = _max_vif(state)
    if vif > 10:
        s += 0.15
    nc = _clusters_count(state)
    if nc >= 3:
        s += 0.10
    if _has_keyword(state, "군집", "세그먼트", "cluster", "segment"):
        s += 0.20
    return _clip(s)


def _g1seg_rationale(state, df, hints):
    nc = _clusters_count(state)
    vif = _max_vif(state)
    if state.target_column:
        prefix = "타겟과 함께"
    else:
        prefix = "타겟 없이 비지도"
    return (
        f"{prefix} 군집 알고리즘으로 데이터 구조를 탐색합니다. "
        f"상관 클러스터 {nc}개가 발견되었으며, 최대 VIF {vif:.1f}입니다."
    )


def _g1seg_metadata(state, df, hints):
    return {"task_type": "unsupervised", "candidate_n_clusters": [2, 3, 4, 5]}


_reg(
    CardSpec(
        "g1_segment",
        "g1",
        "세그먼트 분석 (군집)",
        0.55,
        _g1seg_trigger,
        _g1seg_score,
        _g1seg_rationale,
        _g1seg_metadata,
    )
)


# G1-4: importance
def _g1imp_trigger(state, df, hints):
    n = _n_rows(state) or (len(df) if df is not None else 0)
    return bool(state.target_column) and n >= 50


def _g1imp_score(state, df, hints, base):
    s = base
    n_num = _n_numeric(state, df)
    if n_num >= 3:
        s += 0.05
    if _has_keyword(state, "해석", "이유", "원인", "중요", "importance", "interpret"):
        s += 0.20
    return _clip(s)


def _g1imp_rationale(state, df, hints):
    return (
        "타겟에 영향이 큰 feature를 식별합니다. "
        "SHAP 또는 permutation importance로 정밀 분석이 진행됩니다. "
        "Day 3 EDA의 미리보기는 RandomForest 기반 빠른 추정이고, 본 분석은 더 정밀합니다."
    )


def _g1imp_metadata(state, df, hints):
    t = "classification" if _is_clf(state) else "regression"
    return {"task_type": t, "interpretation_method": "SHAP+permutation"}


_reg(
    CardSpec(
        "g1_importance", "g1", "피처 중요도 해석", 0.65, _g1imp_trigger, _g1imp_score, _g1imp_rationale, _g1imp_metadata
    )
)


# G1-5: hybrid
def _g1hyb_trigger(state, df, hints):
    n = _n_rows(state) or (len(df) if df is not None else 0)
    if not state.target_column or n < 1000:
        return False
    return _has_keyword(state, "해석") and _has_keyword(state, "예측")


def _g1hyb_score(state, df, hints, base):
    s = base
    if _has_keyword(state, "해석") and _has_keyword(state, "예측"):
        s += 0.25
    n = _n_rows(state) or (len(df) if df is not None else 0)
    if n >= 5000:
        s += 0.10
    return _clip(s)


def _g1hyb_rationale(state, df, hints):
    return "예측 정확도와 해석 가능성을 동시에 만족합니다. LightGBM 기반 학습 + SHAP 해석이 진행됩니다."


def _g1hyb_metadata(state, df, hints):
    t = "classification" if _is_clf(state) else "regression"
    return {"task_type": t, "interpretation_method": "SHAP", "prefer_model": "LightGBM"}


_reg(
    CardSpec(
        "g1_hybrid",
        "g1",
        "예측 + 해석 동시 분석",
        0.60,
        _g1hyb_trigger,
        _g1hyb_score,
        _g1hyb_rationale,
        _g1hyb_metadata,
    )
)


# G1-6: anomaly_handoff
def _g1ano_trigger(state, df, hints):
    return _outlier_ratio(state) > 0.10


def _g1ano_score(state, df, hints, base):
    s = base
    ratio = _outlier_ratio(state)
    if ratio > 0.20:
        s += 0.40
    if _has_keyword(state, "이상", "특이", "비정상", "anomaly"):
        s += 0.30
    return _clip(s)


def _g1ano_rationale(state, df, hints):
    pct = _outlier_ratio(state)
    return (
        f"이상치 비율이 {pct:.1%}로 높습니다. anomaly 카테고리로 전환하시면 IForest, LOF 같은 전용 모델이 사용됩니다."
    )


def _g1ano_metadata(state, df, hints):
    return {"task_type": "handoff", "target_category": "anomaly_detection"}


_reg(
    CardSpec(
        "g1_anomaly_handoff",
        "g1",
        "이상치 탐지 (anomaly 위임)",
        0.30,
        _g1ano_trigger,
        _g1ano_score,
        _g1ano_rationale,
        _g1ano_metadata,
    )
)


# G1-7: timeseries_handoff
def _g1ts_trigger(state, df, hints):
    return _has_datetime(state) and _has_autocorr(state)


def _g1ts_score(state, df, hints, base):
    s = base
    acf = float(_profile(state).get("max_acf_lag1", 0.0) or 0.0)
    if acf > 0.7:
        s += 0.45
    if _has_keyword(state, "시간", "추세", "시계열", "timeseries", "forecast"):
        s += 0.30
    return _clip(s)


def _g1ts_rationale(state, df, hints):
    return (
        "datetime 컬럼과 강한 자기상관이 발견되어 시계열 분석이 적합합니다. "
        "timeseries 카테고리에서 SARIMA, Prophet, TFT 같은 시계열 모델이 사용됩니다."
    )


def _g1ts_metadata(state, df, hints):
    return {"task_type": "handoff", "target_category": "timeseries"}


_reg(
    CardSpec(
        "g1_timeseries_handoff",
        "g1",
        "시계열 분석 (timeseries 위임)",
        0.30,
        _g1ts_trigger,
        _g1ts_score,
        _g1ts_rationale,
        _g1ts_metadata,
    )
)


# G1-8: survival_analysis
def _g1surv_trigger(state, df, hints):
    time_col, event_col = _has_time_event_cols(df)
    if time_col and event_col:
        return True
    if _has_keyword(state, "생존", "이탈", "유지", "duration", "churn"):
        return True
    return False


def _g1surv_score(state, df, hints, base):
    s = base
    time_col, event_col = _has_time_event_cols(df)
    if time_col and event_col:
        s += 0.30
    if _has_keyword(state, "생존", "이탈", "유지", "churn"):
        s += 0.20
    return _clip(s)


def _g1surv_rationale(state, df, hints):
    time_col, event_col = _has_time_event_cols(df)
    tc = time_col or "time"
    ec = event_col or "event"
    return (
        f"시간 컬럼 ({tc})과 이벤트 컬럼 ({ec})으로 생존 분석이 가능합니다. Kaplan-Meier 곡선과 Cox 회귀가 사용됩니다."
    )


def _g1surv_metadata(state, df, hints):
    time_col, event_col = _has_time_event_cols(df)
    return {"task_type": "survival", "time_column": time_col, "event_column": event_col}


_reg(
    CardSpec(
        "g1_survival_analysis",
        "g1",
        "생존 분석 (Kaplan-Meier/Cox)",
        0.40,
        _g1surv_trigger,
        _g1surv_score,
        _g1surv_rationale,
        _g1surv_metadata,
    )
)


# G1-9: multi_target
def _g1mt_trigger(state, df, hints):
    tc = getattr(state, "target_columns", None)
    if isinstance(tc, list) and len(tc) >= 2:
        return True
    tc2 = getattr(state, "target_column", None)
    return isinstance(tc2, list) and len(tc2) >= 2


def _g1mt_score(state, df, hints, base):
    s = base
    tc = getattr(state, "target_columns", None) or getattr(state, "target_column", None)
    if isinstance(tc, list):
        if df is not None:
            n_num = sum(1 for c in tc if c in df.columns and df[c].dtype.kind in "iuf")
            if n_num == len(tc):
                s += 0.15
    if _has_keyword(state, "멀티", "다중", "multi"):
        s += 0.10
    return _clip(s)


def _g1mt_rationale(state, df, hints):
    tc = getattr(state, "target_columns", None) or []
    n = len(tc) if isinstance(tc, list) else 2
    return f"{n}개 타겟을 동시에 예측합니다. multi-output 회귀 또는 분류 모델이 사용됩니다."


def _g1mt_metadata(state, df, hints):
    tc = getattr(state, "target_columns", None) or []
    return {"task_type": "multi_target", "n_targets": len(tc) if isinstance(tc, list) else 0}


_reg(
    CardSpec(
        "g1_multi_target", "g1", "멀티 타겟 분석", 0.50, _g1mt_trigger, _g1mt_score, _g1mt_rationale, _g1mt_metadata
    )
)


# ─────────────────────────────────────────────────────────────────────────────
# G2 카드 5종
# ─────────────────────────────────────────────────────────────────────────────

_G2_ORDER = ["g2_ml_light", "g2_ml_standard", "g2_ml_heavy", "g2_dl_light", "g2_dl_heavy"]

_G2_THRESHOLDS = [0.30, 0.55, 0.75, 0.90]  # boundaries between 5 tiers


def _g2_tier(weight_score: float) -> int:
    for i, thr in enumerate(_G2_THRESHOLDS):
        if weight_score < thr:
            return i
    return 4


# G2 trigger helpers (all use weight_score context passed at call time)
def _dummy_trigger(*_):
    return True  # G2 cards are selected algorithmically, not by individual triggers


def _dummy_score(*_):
    return 0.5


def _g2light_rationale(state, df, hints):
    n = _n_rows(state)
    bl = _baseline(state)
    cv = bl.get("cv_score")
    cv_txt = f"baseline 점수 {cv:.2f}로 이미 안정적이라 무거운 모델로 개선 여지가 적습니다." if cv else ""
    return f"{n:,}건 데이터에 가벼운 모델이 적합합니다. 학습 5초 이내. {cv_txt}"


def _g2light_meta(state, df, hints):
    return {
        "candidate_models": ["LogisticRegression", "DecisionTree", "NaiveBayes", "kNN", "RF(50)"],
        "estimated_train_time_sec": 5,
        "interpretability": "high",
    }


_reg(
    CardSpec(
        "g2_ml_light",
        "g2",
        "ML 가벼움 (학습 ~5초, LogReg/DT/NB/k-NN)",
        0.5,
        _dummy_trigger,
        _dummy_score,
        _g2light_rationale,
        _g2light_meta,
    )
)


def _g2standard_rationale(state, df, hints):
    n = _n_rows(state)
    bl = _baseline(state)
    cv = bl.get("cv_score")
    cv_txt = f"baseline {cv:.2f}에서 추가 5~10% 개선이 기대됩니다." if cv else ""
    return f"정형 데이터 표준 모델 (XGBoost/LightGBM)입니다. {n:,}건에 안정적이고, {cv_txt} 학습 ~30초 예상됩니다."


def _g2standard_meta(state, df, hints):
    return {
        "candidate_models": ["XGBoost", "LightGBM", "CatBoost"],
        "estimated_train_time_sec": 30,
        "interpretability": "high (SHAP)",
    }


_reg(
    CardSpec(
        "g2_ml_standard",
        "g2",
        "ML 표준 (학습 ~30초, XGBoost/LightGBM/CatBoost)",
        0.5,
        _dummy_trigger,
        _dummy_score,
        _g2standard_rationale,
        _g2standard_meta,
    )
)


def _g2heavy_rationale(state, df, hints):
    bl = _baseline(state)
    cv = bl.get("cv_score")
    cv_txt = f"baseline {cv:.2f}" if cv else "baseline 미측정"
    return (
        f"복잡한 패턴 ({cv_txt})에 대해 full HPO로 개선합니다. FLAML warm-start로 효율 학습되며, 시간 ~5분 예상됩니다."
    )


def _g2heavy_meta(state, df, hints):
    return {
        "candidate_models": ["XGBoost+HPO", "LightGBM+HPO"],
        "estimated_train_time_sec": 300,
        "hpo_trials": 200,
    }


_reg(
    CardSpec(
        "g2_ml_heavy",
        "g2",
        "ML 정밀 (학습 ~5분, FLAML HPO 200 trial)",
        0.5,
        _dummy_trigger,
        _dummy_score,
        _g2heavy_rationale,
        _g2heavy_meta,
    )
)


def _g2dlight_rationale(state, df, hints):
    n = _n_rows(state)
    n_cls = _n_classes(state)
    return (
        f"{n:,}건 + {n_cls}클래스에 가벼운 DL이 적합합니다. "
        "categorical 임베딩이 자동 학습되며, TabPFN은 사전학습 모델이라 학습 시간이 짧습니다 (~1분)."
    )


def _g2dlight_meta(state, df, hints):
    return {
        "candidate_models": ["TabPFN", "MLP"],
        "estimated_train_time_sec": 60,
        "gpu_recommended": False,
        "interpretability": "medium",
    }


_reg(
    CardSpec(
        "g2_dl_light",
        "g2",
        "DL 가벼움 (학습 ~1분, TabPFN/MLP, GPU 불필요)",
        0.5,
        _dummy_trigger,
        _dummy_score,
        _g2dlight_rationale,
        _g2dlight_meta,
    )
)


def _g2dheavy_rationale(state, df, hints):
    n = _n_rows(state)
    bl = _baseline(state)
    cv = bl.get("cv_score")
    cv_txt = f"baseline {cv:.2f}" if cv else "baseline 미측정"
    return (
        f"복잡한 패턴 ({cv_txt}) + 대용량 데이터 ({n:,}건) 조합으로 트랜스포머가 적합합니다. "
        "GPU 권장이며, 학습 시간 ~5분 예상됩니다."
    )


def _g2dheavy_meta(state, df, hints):
    return {
        "candidate_models": ["FTTransformer", "TabTransformer"],
        "estimated_train_time_sec": 300,
        "gpu_recommended": True,
        "interpretability": "medium (attention)",
    }


_reg(
    CardSpec(
        "g2_dl_heavy",
        "g2",
        "DL 정밀 (학습 ~5분, FTTransformer/TabTransformer, GPU 권장)",
        0.5,
        _dummy_trigger,
        _dummy_score,
        _g2dheavy_rationale,
        _g2dheavy_meta,
    )
)


# ── G2 weight_score computation ───────────────────────────────────────────────


def _size_signal(n_rows: int) -> float:
    if n_rows < 500:
        return 0.1
    if n_rows < 5000:
        return 0.3
    if n_rows < 50000:
        return 0.6
    if n_rows < 500000:
        return 0.85
    return 1.0


def _complexity_signal(cv_score: float | None, top_feat_conc: float | None, nonlinearity: float | None) -> float:
    if cv_score is None:
        base = 0.5
    elif cv_score >= 0.90:
        base = 0.1
    elif cv_score >= 0.80:
        base = 0.3
    elif cv_score >= 0.70:
        base = 0.5
    elif cv_score >= 0.60:
        base = 0.7
    else:
        base = 0.9

    bonus = 0.0
    if top_feat_conc is not None and top_feat_conc < 0.40:
        bonus += 0.1
    if nonlinearity is not None and nonlinearity > 0.15:
        bonus += 0.1
    return _clip(base + bonus)


def _quality_signal(state: Any) -> float:
    profile = _profile(state)
    s = 0.1

    entropy = float(profile.get("class_entropy_ratio", 1.0) or 1.0)
    if entropy < 0.3:
        s += 0.3

    n_rows = int(profile.get("rows", 0))
    if n_rows > 0:
        missing = float(profile.get("missing_ratio", 0.0) or 0.0)
        if missing > 0.20:
            s += 0.2

    outlier = float(profile.get("outlier_ratio", 0.0) or 0.0)
    if outlier > 0.10:
        s += 0.2

    n_cols = int(profile.get("columns", 0))
    if n_cols > 0:
        card_levels = profile.get("cardinality_levels") or {}
        high_card = sum(1 for v in card_levels.values() if v in ("high", "very_high"))
        if high_card / n_cols > 0.30:
            s += 0.2

    return _clip(s)


def _resource_signal(state: Any, hints: dict) -> float:
    if hints.get("time_constraint") is not None:
        return 0.3
    return 0.7


def _compute_weight_score(state: Any, hints: dict) -> float:
    n_rows = _n_rows(state)
    bl = _baseline(state)
    cv = bl.get("cv_score") if isinstance(bl, dict) else None
    bl_cv_override = hints.get("baseline_cv_override")
    if bl_cv_override is not None:
        cv = float(bl_cv_override)

    top_feat = bl.get("top_feature_concentration") if isinstance(bl, dict) else None
    nonlin = bl.get("nonlinearity_estimate") if isinstance(bl, dict) else None

    size = _size_signal(n_rows)
    complexity = _complexity_signal(cv, top_feat, nonlin)
    quality = _quality_signal(state)
    resource = _resource_signal(state, hints)

    ws = size * 0.20 + complexity * 0.45 + quality * 0.20 + resource * 0.15
    return _clip(ws)


# ── G1 public function ────────────────────────────────────────────────────────

_DISABLED_REASONS = {
    "g1_predict_classification": "타겟이 없거나 분류 task가 아닙니다.",
    "g1_predict_regression": "타겟이 없거나 회귀 task가 아닙니다.",
    "g1_segment": "수치형 컬럼이 2개 이상 필요합니다.",
    "g1_importance": "타겟이 없거나 데이터가 부족합니다 (50건 이상 필요).",
    "g1_hybrid": "n_rows < 1000이거나 '해석'+'예측' 의도가 없습니다.",
    "g1_anomaly_handoff": "이상치 비율이 10% 미만입니다.",
    "g1_timeseries_handoff": "datetime 컬럼 또는 자기상관이 없습니다.",
    "g1_survival_analysis": "시간·이벤트 컬럼이 확인되지 않습니다.",
    "g1_multi_target": "target_columns 리스트(≥2)가 없습니다.",
}


def g1(state: Any, df: Any = None) -> list[dict[str, Any]]:
    """G1 카탈로그 9종 중 데이터 적응적 top-3 반환.

    Returns:
        list[dict] 정확히 3개, score 내림차순.
    """
    hints = _hints(state)
    disable: list[str] = hints.get("disable_card") or []
    force: list[str] = hints.get("force_card") or []

    candidates = []
    for spec in CARD_REGISTRY.values():
        if spec.gate != "g1":
            continue

        # hint: disable
        if spec.id in disable:
            candidates.append(
                {
                    "id": spec.id,
                    "gate": "g1",
                    "title": spec.title,
                    "rationale": "사용자 요청에 의해 비활성화되었습니다.",
                    "score": 0.0,
                    "triggered": False,
                    "disabled_reason": "사용자 요청에 의해 비활성화.",
                    "is_recommendation": False,
                    "metadata": {},
                }
            )
            continue

        # hint: force
        if spec.id in force:
            card = {
                "id": spec.id,
                "gate": "g1",
                "title": spec.title,
                "rationale": spec.rationale_fn(state, df, hints),
                "score": 1.0,
                "triggered": True,
                "disabled_reason": None,
                "is_recommendation": False,
                "metadata": spec.metadata_fn(state, df, hints),
            }
            candidates.append(card)
            continue

        try:
            triggered = spec.trigger_fn(state, df, hints)
        except Exception:
            triggered = False

        base = spec.base_score if triggered else 0.0
        try:
            score = spec.score_fn(state, df, hints, base) if triggered else 0.0
        except Exception:
            score = base

        disabled_reason = None if triggered else _DISABLED_REASONS.get(spec.id)
        try:
            rationale = spec.rationale_fn(state, df, hints) if triggered else disabled_reason or ""
        except Exception:
            rationale = disabled_reason or ""
        try:
            metadata = spec.metadata_fn(state, df, hints)
        except Exception:
            metadata = {}

        candidates.append(
            {
                "id": spec.id,
                "gate": "g1",
                "title": spec.title,
                "rationale": rationale,
                "score": score,
                "triggered": triggered,
                "disabled_reason": disabled_reason,
                "is_recommendation": False,
                "metadata": metadata,
            }
        )

    # sort by score desc
    candidates.sort(key=lambda c: c["score"], reverse=True)
    top3 = candidates[:3]

    # pad if fewer than 3
    if len(top3) < 3:
        top3 = candidates  # use what we have

    assert len(top3) == 3, f"g1 should return 3 cards, got {len(top3)}"
    return top3


# ── G2 public function ────────────────────────────────────────────────────────


def g2(state: Any, df: Any = None) -> list[dict[str, Any]]:
    """G2 모델 무게 카드 (추천 1 + 대안 1~2) 반환.

    Returns:
        list[dict] 1~3개, is_recommendation 1개 보장.
    """
    hints = _hints(state)
    disable: list[str] = hints.get("disable_card") or []
    force: list[str] = hints.get("force_card") or []
    disable_dl: bool = bool(hints.get("disable_dl", False))
    prefer_speed: bool = bool(hints.get("prefer_speed", False))
    prefer_accuracy: bool = bool(hints.get("prefer_accuracy", False))

    n_rows = _n_rows(state)
    n_cls = _n_classes(state)
    g1_choice = (state.gate_responses or {}).get("g1") if hasattr(state, "gate_responses") else None

    # compute weight score
    ws = _compute_weight_score(state, hints)

    # handle hint overrides
    if prefer_speed:
        rec_id = "g2_ml_light"
    elif prefer_accuracy:
        rec_id = "g2_dl_heavy" if ws >= 0.75 else "g2_ml_heavy"
    else:
        tier = _g2_tier(ws)
        rec_id = _G2_ORDER[tier]

    # DL eligibility check
    dl_min_rows = int(hints.get("dl_min_rows_override") or max(5000, int(_profile(state).get("columns", 0)) * 100))
    dl_min_rows = max(dl_min_rows, 5000)
    dl_max_cls = int(hints.get("dl_max_classes_override") or min(10, math.ceil(math.log2(max(n_rows, 2))) + 3))
    dl_eligible = n_rows >= dl_min_rows and (n_cls == 0 or n_cls <= dl_max_cls)

    if not dl_eligible and rec_id.startswith("g2_dl"):
        rec_id = "g2_ml_heavy"

    # alternatives: adjacent tiers
    rec_idx = _G2_ORDER.index(rec_id)
    alt_ids = []
    if rec_idx > 0:
        alt_ids.append(_G2_ORDER[rec_idx - 1])
    if rec_idx < len(_G2_ORDER) - 1:
        alt_ids.append(_G2_ORDER[rec_idx + 1])

    # remove non-dl-eligible dl cards from alternatives
    if not dl_eligible:
        alt_ids = [a for a in alt_ids if not a.startswith("g2_dl")]

    all_ids = [rec_id] + alt_ids

    # DoD: ensure dl card if eligible
    if dl_eligible:
        has_dl = any(i.startswith("g2_dl") for i in all_ids)
        if not has_dl:
            all_ids.append("g2_dl_light")

    # apply disable_dl
    if disable_dl:
        all_ids = [i for i in all_ids if not i.startswith("g2_dl")]
        if rec_id.startswith("g2_dl"):
            rec_id = "g2_ml_heavy"
            if rec_id not in all_ids:
                all_ids = [rec_id] + [i for i in all_ids if i != rec_id]

    # apply force_card
    for fid in force:
        if fid in CARD_REGISTRY and CARD_REGISTRY[fid].gate == "g2":
            if fid not in all_ids:
                all_ids.append(fid)
            rec_id = fid  # force takes is_recommendation

    # apply disable_card
    all_ids = [i for i in all_ids if i not in disable]
    if rec_id in disable:
        # pick next best
        rec_id = next((i for i in all_ids if i not in disable), all_ids[0] if all_ids else "g2_ml_standard")

    # G1 fine-tuning scores
    g1_score_delta: dict[str, float] = {}
    if g1_choice == "g1_segment":
        for gid in _G2_ORDER:
            if gid.startswith("g2_dl"):
                g1_score_delta[gid] = -0.20
            elif gid == "g2_ml_light":
                g1_score_delta[gid] = 0.15
    elif g1_choice == "g1_importance":
        for gid in _G2_ORDER:
            if gid.startswith("g2_ml"):
                g1_score_delta[gid] = 0.10
            else:
                g1_score_delta[gid] = -0.10
    elif g1_choice == "g1_hybrid":
        g1_score_delta["g2_ml_heavy"] = 0.15
    elif g1_choice == "g1_multi_target":
        for gid in _G2_ORDER:
            if gid.startswith("g2_dl"):
                g1_score_delta[gid] = 0.10

    # build card dicts
    cards = []
    for cid in all_ids:
        if cid not in CARD_REGISTRY:
            continue
        spec = CARD_REGISTRY[cid]
        is_rec = cid == rec_id
        base_score = 0.85 if is_rec else 0.60
        adj = g1_score_delta.get(cid, 0.0)
        score = _clip(base_score + adj)

        try:
            rationale = spec.rationale_fn(state, df, hints)
            if not is_rec:
                rationale = "대안 " + rationale
        except Exception:
            rationale = spec.title

        try:
            metadata = spec.metadata_fn(state, df, hints)
        except Exception:
            metadata = {}

        metadata["weight_score"] = round(ws, 4)

        cards.append(
            {
                "id": cid,
                "gate": "g2",
                "title": spec.title,
                "rationale": rationale,
                "score": score,
                "triggered": True,
                "disabled_reason": None,
                "is_recommendation": is_rec,
                "metadata": metadata,
            }
        )

    # guarantee exactly one is_recommendation
    recs = [c for c in cards if c["is_recommendation"]]
    if len(recs) == 0 and cards:
        cards[0]["is_recommendation"] = True
    elif len(recs) > 1:
        for c in recs[1:]:
            c["is_recommendation"] = False

    # ensure at least 1
    if not cards:
        spec = CARD_REGISTRY["g2_ml_standard"]
        cards = [
            {
                "id": "g2_ml_standard",
                "gate": "g2",
                "title": spec.title,
                "rationale": spec.rationale_fn(state, df, hints),
                "score": 0.85,
                "triggered": True,
                "disabled_reason": None,
                "is_recommendation": True,
                "metadata": {**spec.metadata_fn(state, df, hints), "weight_score": round(ws, 4)},
            }
        ]

    # sort: recommendation first, then by score
    cards.sort(key=lambda c: (not c["is_recommendation"], -c["score"]))

    return cards

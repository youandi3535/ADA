"""agents.handlers.tabular.archetype — 정형 데이터 archetype 분류 + 적합 결정 규칙 (jh 담당).

설계 의도
=========
지금까지 profiler 는 신호(imbalance / VIF / cardinality / leakage / id_like / p>>n)를
개별 키로 추출만 했고, selector·insight·output_extras 는 신호별로 알아서 해석해야 했다.
그러다 보니 다음이 깨졌다:

  - extreme imbalance (1:1000+) 인데도 selector 는 그냥 LightGBM 추천하고 끝.
  - target leakage suspect 가 있어도 selector·proposer 는 그대로 진행.
  - p≫n (피처 >> 행) 데이터에 RandomForest/XGBoost 강하게 추천하는 어색함.
  - id_like 컬럼이 학습 피처에 그대로 남아 있어도 별도 가드 없음.

본 모듈은 **데이터의 archetype** 을 1개(또는 우선순위 정렬된 다수) 로 분류하고,
각 archetype 별로 **적합한 결정 (expected_decisions)** 을 명세한다. selector·insight·
output_extras 는 archetype 결과 1개만 읽으면 데이터 맞춤 결정을 할 수 있다.

10 archetype
============
priority 0 (긴급 — 다른 결정 우선) :
  - target_leakage_suspected : profile.target_leakage_suspects 존재. 모델 학습보다
    누수 컬럼 제거 권고가 우선.
  - extreme_imbalance         : class_imbalance_ratio ≥ 1000. tabular_ml 부적합 →
    anomaly_detection 카테고리 권고. 일반 SMOTE 도 메모리 폭주.

priority 1 (데이터 형태에 따른 모델 가이드) :
  - p_gg_n                   : n_features ≥ n_rows / 2. RF/XGB 과적합 위험,
    Lasso/Ridge 우선. DL 비추.
  - high_cardinality_heavy   : cardinality_levels 의 "high" 가 3 개 이상. CatBoost
    또는 target encoding+smoothing 강조.
  - multicollinear_heavy     : correlation_clusters 가 2 개 이상 또는 corr_condition_number > 100.
    VIF drop 필수, 선형 모델은 정규화 강제.

priority 2 (균형/세부 라우팅) :
  - imbalanced_moderate      : 10 ≤ class_imbalance_ratio < 1000. SMOTE 또는
    class_weight, LightGBM/CatBoost 우선.
  - clean_balanced           : 결측 < 10%, 균형, 카디 정상. 모든 모델 OK,
    RandomForest 안정적.
  - low_signal               : mutual_info_top 의 최댓값이 < 0.05. 추가 피처 엔지니어링
    또는 비지도 접근 권고.
  - regression_heteroscedastic : 회귀 + 잔차 패턴(추정). log/yeo-johnson 변환 권고.
  - id_overload              : id_like_columns 가 전체 컬럼의 30% 이상. 학습 피처
    구성 자체를 재검토 권고.

expected_decisions
==================
각 archetype 에는 다음 키가 매핑된다:

  selector_top1_in / selector_top1_not_in : top-1 모델이 포함/배제돼야 할 집합
  preprocessing_must : preprocessing_plan 에 반드시 포함돼야 할 transform 명
  preprocessing_should_not : 포함되면 안 되는 transform 명
  insight_must_mention : insight 텍스트가 반드시 인용해야 할 키워드
  proposer_recommends_category : G1/G2 에서 권고해야 할 카테고리 (anomaly_detection 등)
  threshold_strategy : "f1_max" / "cost_min" / "recall_min" 등 분류 임계치 전략
  warnings : 사용자에게 노출해야 할 경고 텍스트

decision audit (test_decision_quality.py) 가 이 매핑을 ground truth 로 사용해
시스템의 결정 정확도를 측정한다.
"""

from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────────────────────────────────────
# Archetype 정의 — 우선순위 순서 (앞쪽이 더 강한 신호)
# ──────────────────────────────────────────────────────────────────────────────

ARCHETYPE_PRIORITY: list[str] = [
    # priority 0 — 긴급
    "target_leakage_suspected",
    "extreme_imbalance",
    # priority 1 — 형태 기반
    "p_gg_n",
    "id_overload",              # high_cardinality_heavy 보다 앞 (수치 unique 오탐 방지)
    "multicollinear_heavy",     # high_cardinality_heavy 보다 앞
    "high_cardinality_heavy",
    # priority 2 — 세부 라우팅
    "imbalanced_moderate",
    "low_signal",
    "regression_heteroscedastic",
    "clean_balanced",
]


# ──────────────────────────────────────────────────────────────────────────────
# Archetype 별 기대 결정 (decision audit ground truth)
# ──────────────────────────────────────────────────────────────────────────────

EXPECTED_DECISIONS: dict[str, dict[str, Any]] = {
    "target_leakage_suspected": {
        "preprocessing_must": ["leakage_column_drop"],
        "insight_must_mention": ["누수", "leakage", "target과 상관"],
        "warnings": ["target leakage 의심 컬럼 학습 제외 권고"],
        "threshold_strategy": "f1_max",
        "selector_top1_in": {"RandomForest", "LogisticRegression", "Ridge", "Dummy"},
        # 누수 의심 시엔 보수적 모델 권고 (강력한 GBDT 가 누수 그대로 학습할 위험)
    },
    "extreme_imbalance": {
        "proposer_recommends_category": "anomaly_detection",
        "insight_must_mention": ["극단 불균형", "이상탐지"],
        "warnings": ["클래스 비율 1:1000 이상 — 정형 분류보다 이상탐지 카테고리 권고"],
        "preprocessing_should_not": ["smote_resample"],  # 메모리 폭주
        "threshold_strategy": "cost_min",
    },
    "p_gg_n": {
        "selector_top1_in": {"LogisticRegression", "Ridge", "Lasso"},
        "selector_top1_not_in": {"RandomForest", "XGBoost", "LightGBM", "CatBoost"},
        "insight_must_mention": ["피처가 행보다 많", "정규화"],
        "warnings": ["피처 수가 행 수에 가깝거나 더 큼 — 정규화 모델 권고, DL 비추"],
        "preprocessing_must": ["correlation_drop", "vif_drop"],
        "threshold_strategy": "f1_max",
    },
    "high_cardinality_heavy": {
        "selector_top1_in": {"CatBoost", "LightGBM"},
        "preprocessing_must": ["target_encoding", "smote_resample"]  # high-card + 보통 imbalance 와 동반
        if False else ["target_encoding"],
        "insight_must_mention": ["고차원 범주", "범주형"],
        "threshold_strategy": "f1_max",
    },
    "multicollinear_heavy": {
        "preprocessing_must": ["vif_drop"],
        "insight_must_mention": ["다중공선성", "상관"],
        "warnings": ["수치형 피처 간 강한 상관 — VIF 기반 컬럼 제거 적용"],
        "selector_top1_in": {"RandomForest", "Ridge", "LightGBM"},
        "selector_top1_not_in": {"LogisticRegression"},  # 정규화 없으면 불안정
        "threshold_strategy": "f1_max",
    },
    "id_overload": {
        "preprocessing_must": ["id_like_drop"],
        "insight_must_mention": ["식별자", "id"],
        "warnings": ["식별자 추정 컬럼이 다수 — 학습 피처 구성 재검토 권고"],
        "threshold_strategy": "f1_max",
    },
    "imbalanced_moderate": {
        "selector_top1_in": {"LightGBM", "CatBoost", "RandomForest"},
        "preprocessing_must": ["class_weight_compute"],
        "insight_must_mention": ["클래스 불균형"],
        "threshold_strategy": "cost_min",
    },
    "low_signal": {
        "insight_must_mention": ["신호 약함", "피처 엔지니어링"],
        "warnings": ["mutual information 최댓값 < 0.05 — 추가 피처 또는 비지도 접근 권고"],
        "threshold_strategy": "f1_max",
    },
    "regression_heteroscedastic": {
        "preprocessing_must": ["distribution_transform"],
        "insight_must_mention": ["이분산", "변환"],
        "threshold_strategy": None,  # 회귀
    },
    "clean_balanced": {
        # 모든 모델 OK — 가장 강한 강제 조건 없음. 점수표대로 진행.
        "threshold_strategy": "f1_max",
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# Archetype 분류기
# ──────────────────────────────────────────────────────────────────────────────

# 임계 상수 (튜닝 가능)
_EXTREME_IMBALANCE_RATIO = 1000.0
_MODERATE_IMBALANCE_RATIO = 10.0
_P_GG_N_FEATURE_RATIO = 0.5  # n_features / n_rows ≥ 0.5
_HIGH_CARD_COUNT_THRESHOLD = 3
_MULTICOLLINEAR_CLUSTER_THRESHOLD = 2
_MULTICOLLINEAR_COND_NUMBER = 100.0
_ID_OVERLOAD_RATIO = 0.30  # id_like_columns / total_columns ≥ 0.30
_LOW_SIGNAL_MI_THRESHOLD = 0.05
_CLEAN_MISSING_RATE = 0.10


def _is_numeric_dtype(dtype_str: str) -> bool:
    """dtype 문자열이 numeric 인지 판단."""
    s = str(dtype_str).lower()
    return any(t in s for t in ("int", "float", "number"))


def classify_archetypes(profile: dict[str, Any], state: Any) -> dict[str, Any]:
    """data_profile + state 를 기반으로 archetype 1 개 이상 분류 → 우선순위 정렬 반환.

    Args:
        profile : profiler.profile() 결과를 포함한 data_profile (rows / cols /
                  class_imbalance_ratio / cardinality_levels / target_leakage_suspects /
                  id_like_columns / mutual_info_top / correlation_clusters / dtypes /
                  preprocessing_thresholds_suggested 등)
        state   : PipelineState — task 추정 + category 확인용

    Returns:
        {
            "primary"   : str — 가장 우선순위 높은 archetype 1 개 (또는 "clean_balanced" 폴백)
            "matched"   : list[str] — 매칭된 모든 archetype, 우선순위 순서
            "signals"   : dict[str, Any] — 어떤 신호로 매칭됐는지 근거 (decision audit 용)
            "expected"  : dict[str, Any] — primary archetype 의 expected_decisions
        }
    """
    n_rows = int(profile.get("rows", 0) or 0)
    n_cols = int(profile.get("cols", len(profile.get("dtypes", {})) or 0))
    target = getattr(state, "target_column", None)
    n_features = max(n_cols - (1 if target else 0), 0)

    imbalance = float(profile.get("class_imbalance_ratio", 1.0) or 1.0)
    leakage = profile.get("target_leakage_suspects") or []
    id_like = profile.get("id_like_columns") or []
    card_levels = profile.get("cardinality_levels") or {}
    mutual_info = profile.get("mutual_info_top") or {}
    corr_clusters = profile.get("correlation_clusters") or {}
    cond_number = float(
        (profile.get("preprocessing_thresholds_suggested") or {})
        .get("_computed_with", {})
        .get("corr_condition_number", 1.0) or 1.0
    )

    # missing 평균
    missing = profile.get("missing") or {}
    missing_rate = float(sum(missing.values()) / max(len(missing), 1)) if missing else 0.0

    dtypes_map = profile.get("dtypes") or {}
    high_card_count = sum(
        1 for col, lvl in card_levels.items()
        if lvl == "high" and not _is_numeric_dtype(dtypes_map.get(col, ""))
    )

    # task 추정 — selector 와 동일 룰
    task = getattr(state, "task", "auto")
    if task == "auto":
        cd = profile.get("class_distribution") or {}
        if cd and len(cd) <= 50:
            task = "classification"
        elif profile.get("class_imbalance_ratio") is not None:
            # imbalance_ratio 가 잡혔다는 건 target 이 이산형이라는 신호
            task = "classification"
        else:
            task = "regression"

    matched: list[str] = []
    signals: dict[str, Any] = {}

    # priority 0
    if leakage:
        matched.append("target_leakage_suspected")
        signals["leakage_columns"] = [item.get("column") for item in leakage]

    if task == "classification" and imbalance >= _EXTREME_IMBALANCE_RATIO:
        matched.append("extreme_imbalance")
        signals["imbalance_ratio"] = imbalance

    # priority 1
    if n_rows > 0 and n_features > 0 and (n_features / n_rows) >= _P_GG_N_FEATURE_RATIO:
        matched.append("p_gg_n")
        signals["feature_to_row_ratio"] = round(n_features / n_rows, 3)

    if high_card_count >= _HIGH_CARD_COUNT_THRESHOLD:
        matched.append("high_cardinality_heavy")
        signals["high_cardinality_count"] = high_card_count

    if (
        len(corr_clusters) >= _MULTICOLLINEAR_CLUSTER_THRESHOLD
        or cond_number >= _MULTICOLLINEAR_COND_NUMBER
    ):
        matched.append("multicollinear_heavy")
        signals["corr_clusters"] = len(corr_clusters)
        signals["corr_condition_number"] = cond_number

    if n_cols > 0 and (len(id_like) / n_cols) >= _ID_OVERLOAD_RATIO:
        matched.append("id_overload")
        signals["id_like_ratio"] = round(len(id_like) / n_cols, 3)

    # priority 2
    if (
        task == "classification"
        and _MODERATE_IMBALANCE_RATIO <= imbalance < _EXTREME_IMBALANCE_RATIO
        and "extreme_imbalance" not in matched
    ):
        matched.append("imbalanced_moderate")
        signals["imbalance_ratio"] = imbalance

    if mutual_info:
        max_mi = float(max(mutual_info.values()))
        if max_mi < _LOW_SIGNAL_MI_THRESHOLD:
            matched.append("low_signal")
            signals["max_mutual_info"] = max_mi

    # regression_heteroscedastic : 정확한 판단은 학습 후 잔차로만 가능하므로
    # profile 단계에선 회귀 + 결측 또는 분포 skew 강함 정도로 약하게 추정.
    if task == "regression":
        numeric_stats = profile.get("numeric_stats") or {}
        # std/mean 이 매우 크면 분산 폭주 가능 → 약한 heteroscedasticity 신호
        ratios = []
        for col, st in numeric_stats.items() if isinstance(numeric_stats, dict) else []:
            if not isinstance(st, dict):
                continue
            mean = abs(float(st.get("mean", 0.0) or 0.0))
            std = float(st.get("std", 0.0) or 0.0)
            if mean > 1e-9:
                ratios.append(std / mean)
        if ratios and max(ratios) > 3.0:
            matched.append("regression_heteroscedastic")
            signals["max_coefficient_of_variation"] = round(max(ratios), 3)

    # 모든 priority 후보 매칭 후 — 깨끗하면 clean_balanced 폴백
    if not matched and missing_rate < _CLEAN_MISSING_RATE:
        matched.append("clean_balanced")

    # 우선순위 정렬
    matched = sorted(matched, key=lambda a: ARCHETYPE_PRIORITY.index(a))
    primary = matched[0] if matched else "clean_balanced"

    return {
        "primary": primary,
        "matched": matched,
        "signals": signals,
        "expected": dict(EXPECTED_DECISIONS.get(primary, {})),
    }


def get_expected_decisions(archetype: str) -> dict[str, Any]:
    """archetype 이름 → expected_decisions dict (decision audit 헬퍼)."""
    return dict(EXPECTED_DECISIONS.get(archetype, {}))

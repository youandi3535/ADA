"""agents.handlers.timeseries.selector — 시계열 모델 추천 (CS 담당, cs-day5 v3 디벨롭).

진입함수 (dispatcher 자동 등록):
  - score(state, recipes=None) -> dict
      반환: {"top3": list[str], "rationale": str, "citations": list[str], "meta": dict}

DoD (불변):
  - top3 길이 ≥ 3
  - citations ≥ 1 (R-501) — recipes 비어 있을 땐 빈 list 허용 + warning
  - n_rows < 100 → 보수적 통계 모델만 유지
  - exog 0 → SARIMAX 제외 (top3 진입 X)

방법론 헌장 매핑 (0~7단계 + 누수 1-1~1-7 + 모델선택 7축)
─────────────────────────────────────────────────────────────────
- 0단계 (문제정의·horizon·variate·point/interval) → meta 키 + 점수 조정 (7축 가·라·마·사)
- 1단계 (시간축 무결성·target_kind) → profiler carry 키(timeaxis_integrity·target_kind) 인식 → 점수 조정 (7축 라)
- 2단계 EDA (계절·정상성·이분산·changepoint·CCF) → eda carry 키(seasonal_period·stationary·heteroscedastic·changepoints·acf_peaks) 인식 → 점수 조정 (7축 다·바·사)
- 3단계 (피처·도메인) → preprocessor `category_extras["timeseries"]["exog_columns"]` 권위 소스 통일 (A안 핵심 수정)
- 4단계 (검증·walk-forward) → meta `multistep_strategy` 로 다운스트림 pipeline·HPO 에 신호
- 5단계 (임계·HPO) → meta `recommended_threshold` 보너스 큰 모델 우선
- 6단계 (모델선택 7축) → 7축 전부 점수 룰로 코드화 (가 계열길이 · 나 horizon · 다 계절성 · 라 target_kind · 마 multivariate · 바 heteroscedastic · 사 changepoints)
- 7단계 (롤백) → 기준선(seasonal_naive·ETS) 메타 강제 추천 (방법론 4-2·6-5 "못 이기면 채택 금지")
- 누수 1-1 (타겟 누수) → leakage_suspect_cols 가 있을 때 exog 정책 강화 (해당 컬럼 제외 권고 메타)
- 누수 1-2 (시간정렬) → horizon-aware → meta `multistep_strategy`("direct"/"recursive"/"hybrid")
- 누수 1-3~1-7 → preprocessor·evaluator 영역, selector 는 영역 외

A안 디벨롭 핵심 (어제 인수인계 표 셋째 줄):
─────────────────────────────────────────────────────────────────
1. exog 소스 통일 — `category_extras["timeseries"]["exog_columns"]` 우선, eda 보조.
2. baseline_recommend 메타 — seasonal_naive(s≥2 + n≥2s) / ETS(n≥30) 를 메타로만 추천.
3. 7축 반영 — 헌장 2-1 7개 축 전부 점수 룰로 코드화 (가~사).
4. meta(multistep_strategy / hybrid_hint / baseline_recommend / leakage_excluded) — 다운스트림에 신호.
5. rationale R-501 강화 — 모든 조정값 수치 인용 (검증 가능).

핵심 설계 원칙 (cs-day5 §O 계승):
- recipe 기반 base candidates — 3 분기 (단기/이상/계절) · default = "단기 예측"
- DoD 강제 (n<100 → DL · exog=0 → SARIMAX EXCLUDED)
- score clip(0, 1) + top3 길이 3 보장 (ARIMA → Prophet → SARIMA fallback)
- 인라인 안전 우선 — 어떤 상태에서도 default 진행
- 회귀 0 — 기존 3 키 (top3 / rationale / citations) 불변, `meta` 키만 신규 추가
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
SUPPORTED_MODELS = ("ARIMA", "SARIMA", "SARIMAX", "Prophet", "ETS", "seasonal_naive")
STAT_MODELS = ("ARIMA", "SARIMA", "SARIMAX", "ETS")

BASE_SCORE = 0.70

# Day5 기존 가중 (불변 — 회귀 0)
DL_PENALTY_SMALL = -0.20
SARIMA_SEASONAL_BONUS = 0.15
SARIMAX_SEASONAL_BONUS = 0.10
SARIMAX_EXOG_BONUS = 0.20
ARIMA_STAT_BONUS = 0.10
ARIMA_NONSTAT_PENALTY = -0.05

# A안 7축 디벨롭 가중 (신규, ML 전용)
PROPHET_LONG_HORIZON_BONUS = 0.05
SARIMA_STRONG_SEASONAL_BONUS = 0.05
MULTIVARIATE_SARIMAX_BONUS = 0.05
HETERO_PROPHET_BONUS = 0.03
HETERO_SARIMA_BONUS = 0.03
CHANGEPOINTS_PROPHET_BONUS = 0.05

SEASONAL_PERIODS = (7, 12, 30, 365)
ACF_STRONG_THRESHOLD = 2


# ════════════════════════════════════════════════════════════════
# 주제 적합도 매트릭스 (2026-06-05, 사용자 요청 — 주제 맞춤 최적 모델)
# ════════════════════════════════════════════════════════════════
# 키워드 → 토픽 신호 매핑 (한·영 혼용, 도메인 키워드 포함)
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "short_term": ("단기", "내일", "이번 주", "다음 주", "short", "next day", "near-term"),
    "mid_term": ("중기", "한 달", "월간", "mid", "monthly", "monthly forecast"),
    "long_term": ("장기", "분기", "연간", "long", "long-term", "long horizon", "annual"),
    "multivariate": ("다변량", "외생", "exog", "multivariate", "다중", "공휴일", "프로모션", "holiday", "promo"),
    "interval": ("구간", "신뢰구간", "신뢰", "interval", "confidence", "ci", "prediction interval", "pi", "분위"),
    "anomaly": ("이상", "이상치", "이상 시점", "anomaly", "outlier", "감지", "탐지", "detection"),
    "baseline": ("기준선", "베이스라인", "naive", "baseline", "단순", "비교"),
    "seasonal_decomp": ("계절성", "계절 분해", "분해", "seasonality", "decomposition", "stl"),
    "interpretable": ("해석", "설명", "interpret", "explain", "투명"),
}

# 모델 × 토픽 적합도 보너스 (작은 가중 — 기존 7축 매트릭스 균형 유지)
# 양수 = 토픽에 적합, 음수 = 비적합. 토픽 미감지 시 적용 안 함.
TOPIC_BONUS: dict[str, dict[str, float]] = {
    "short_term": {"ARIMA": 0.05, "SARIMA": 0.05, "ETS": 0.05, "Prophet": 0.03},
    "mid_term": {"SARIMA": 0.05, "Prophet": 0.05, "ETS": 0.03},
    "long_term": {"Prophet": 0.08, "ARIMA": -0.03, "SARIMA": -0.03, "ETS": -0.03},
    "multivariate": {"SARIMAX": 0.08, "ARIMA": -0.03, "ETS": -0.03},
    "interval": {"SARIMA": 0.05, "SARIMAX": 0.05, "ETS": 0.05, "Prophet": 0.05, "ARIMA": 0.03},
    "anomaly": {"Prophet": 0.05, "SARIMA": 0.05},
    "baseline": {"seasonal_naive": 0.10, "ETS": 0.08, "ARIMA": 0.05},
    "seasonal_decomp": {"Prophet": 0.05, "SARIMA": 0.05, "ETS": 0.03},
    "interpretable": {"ARIMA": 0.05, "SARIMA": 0.05, "ETS": 0.05, "Prophet": 0.03},
}


# ════════════════════════════════════════════════════════════════
# 전문가 4 차원 점수표 (2026-06-08, Phase 1-A)
# ════════════════════════════════════════════════════════════════
# 인간 전문가가 모델을 평가하는 4 차원 정량 점수.
# 점수 범위 0.0~1.0. 학술적 근거 + CS 운영 경험 기반 기본값.
EXPERT_DIMENSIONS: dict[str, dict[str, float]] = {
    "interpretability": {
        "ARIMA": 0.95,
        "SARIMA": 0.85,
        "SARIMAX": 0.80,
        "ETS": 0.75,
        "Prophet": 0.70,
        "seasonal_naive": 1.00,
    },
    "robustness": {
        "ARIMA": 0.30,
        "SARIMA": 0.30,
        "SARIMAX": 0.30,
        "ETS": 0.40,
        "Prophet": 0.90,
        "seasonal_naive": 1.00,
    },
    "uncertainty_quality": {
        "ARIMA": 0.80,
        "SARIMA": 0.85,
        "SARIMAX": 0.85,
        "ETS": 0.70,
        "Prophet": 0.90,
        "seasonal_naive": 0.20,
    },
    "retraining_cost": {
        "ARIMA": 0.95,
        "SARIMA": 0.85,
        "SARIMAX": 0.80,
        "ETS": 0.90,
        "Prophet": 0.70,
        "seasonal_naive": 1.00,
    },
}

EXPERT_PRIORITY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "interpretability": ("해석", "설명", "투명", "interpret", "explain", "transparent", "explainable"),
    "robustness": ("안정", "강건", "충격", "robust", "stable", "변동", "shock", "resilient"),
    "uncertainty_quality": (
        "불확실",
        "신뢰구간",
        "구간",
        "uncertainty",
        "interval",
        "pi",
        "prediction interval",
        "quantile",
    ),
    "retraining_cost": ("빠른", "실시간", "재학습", "효율", "fast", "real-time", "efficient", "retrain"),
}

EXPERT_WEIGHT_SCALE = 0.15


def _resolve_expert_priorities(state, signals, n_rows):
    """user_intent + 데이터 신호 → 4 차원 우선순위 가중치 (합=1.0).

    결정 우선순위:
      1순위 — user_intent 명시 키워드 (최우선 차원 0.40 가중)
      2순위 — 데이터 신호 (changepoints·heteroscedastic·짧은 계열)
      3순위 — 기본 균형 (0.25 × 4)
    """
    _ = signals  # 미래 확장 보존
    priorities = {
        "interpretability": 0.25,
        "robustness": 0.25,
        "uncertainty_quality": 0.25,
        "retraining_cost": 0.25,
    }

    intent = (getattr(state, "user_intent", None) or "").lower()
    eda = _eda_dict(state)

    matched_dim = None
    for dim, kws in EXPERT_PRIORITY_KEYWORDS.items():
        if any(kw.lower() in intent for kw in kws):
            matched_dim = dim
            break

    if matched_dim:
        priorities[matched_dim] = 0.40
        remaining = (1.0 - 0.40) / 3
        for k in priorities:
            if k != matched_dim:
                priorities[k] = remaining
    else:
        try:
            cp = int(eda.get("changepoints") or 0)
        except (TypeError, ValueError):
            cp = 0
        hetero = bool(eda.get("heteroscedastic"))

        if cp >= 3:
            priorities["robustness"] = 0.35
            priorities["interpretability"] = 0.25
            priorities["uncertainty_quality"] = 0.25
            priorities["retraining_cost"] = 0.15
        elif hetero:
            priorities["uncertainty_quality"] = 0.35
            priorities["interpretability"] = 0.25
            priorities["robustness"] = 0.25
            priorities["retraining_cost"] = 0.15
        elif 0 < n_rows < 100:
            priorities["interpretability"] = 0.35
            priorities["robustness"] = 0.30
            priorities["uncertainty_quality"] = 0.20
            priorities["retraining_cost"] = 0.15

    total = sum(priorities.values())
    if total <= 0:
        return {k: 0.25 for k in priorities}
    return {k: round(v / total, 4) for k, v in priorities.items()}


def _compute_expert_scores(candidates, priorities):
    """모델별 weighted expert score 계산 (0.0~1.0)."""
    scores = {}
    for model in candidates:
        score = 0.0
        for dim, weight in priorities.items():
            dim_table = EXPERT_DIMENSIONS.get(dim) or {}
            model_score = dim_table.get(model, 0.5)
            score += weight * model_score
        scores[model] = round(score, 4)
    return scores


def _apply_expert_bonus(adj, expert_scores):
    """expert_score 를 adj 에 가산 (EXPERT_WEIGHT_SCALE 곱). in-place."""
    for model, score in expert_scores.items():
        if model in adj:
            adj[model] += EXPERT_WEIGHT_SCALE * score


# ════════════════════════════════════════════════════════════════
# §0. 헬퍼
# ════════════════════════════════════════════════════════════════
def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


# ════════════════════════════════════════════════════════════════
# 주제 신호 추출 + 적합도 보너스 적용 (2026-06-05)
# ════════════════════════════════════════════════════════════════
def _topic_signals(state: Any, chosen_meta: dict, horizon: int, n_rows: int) -> dict[str, bool]:
    """user_intent 키워드 + chosen_recipe.meta 종합해 토픽 신호 dict 반환.

    토픽이 명확하면 selector 가 적합 모델에 가중치 부여 → "주제 맞춤 최적 모델".

    user_intent 미상 + meta 빈 경우 → 모두 False (영향 0, 회귀 안전).
    """
    intent = (getattr(state, "user_intent", None) or "").lower()
    signals = {k: False for k in TOPIC_KEYWORDS}

    # 1) user_intent 키워드 매칭
    if intent:
        for topic, kws in TOPIC_KEYWORDS.items():
            if any(kw.lower() in intent for kw in kws):
                signals[topic] = True

    # 2) chosen_recipe.meta 보강
    meta = chosen_meta or {}
    forecast_kind = meta.get("forecast_kind")
    variate = meta.get("variate")
    task_kind = meta.get("task_kind")

    if forecast_kind in ("interval", "quantile"):
        signals["interval"] = True
    if variate == "multivariate":
        signals["multivariate"] = True
    if task_kind == "classification":
        signals["anomaly"] = True

    # 3) horizon 기반 시계열 길이 (intent 미명시 시 fallback)
    if not (signals["short_term"] or signals["mid_term"] or signals["long_term"]):
        if horizon > 0:
            if horizon <= 7:
                signals["short_term"] = True
            elif horizon <= 30:
                signals["mid_term"] = True
            else:
                signals["long_term"] = True

    # 4) 짧은 계열 (n<100) → 베이스라인 토픽 자동 활성 (해석성 + 안정)
    if n_rows > 0 and n_rows < 100:
        signals["baseline"] = True
        signals["interpretable"] = True

    return signals


def _apply_topic_bonus(adj: dict[str, float], signals: dict[str, bool]) -> dict[str, list[str]]:
    """signals True 인 토픽의 TOPIC_BONUS 를 adj 에 더함.

    반환: 각 모델별로 적용된 토픽 이름 list (rationale·meta 노출용).
    candidates 풀에 없는 모델 보너스는 무시 (KeyError 안전).
    """
    applied: dict[str, list[str]] = {m: [] for m in adj}
    for topic, active in signals.items():
        if not active:
            continue
        bonus_map = TOPIC_BONUS.get(topic) or {}
        for model, bonus in bonus_map.items():
            if model in adj:
                adj[model] += bonus
                applied[model].append(f"{topic}:{bonus:+.2f}")
    return applied


def _chosen_recipe(state: Any) -> dict:
    """state.chosen_recipe → dict 안전 변환.

    HJ-5 (2026-06-05) 이후 PipelineState 정식 필드 (Optional[dict[str, Any]]).
    getattr 패턴 유지 — None 또는 미세팅 시 빈 dict 반환.
    """
    raw = getattr(state, "chosen_recipe", None)
    return raw if isinstance(raw, dict) else {}


def _eda_dict(state: Any) -> dict:
    """state.eda_summary 는 Optional[dict | str] union (HJ-2). dict 만 허용."""
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _category_extras(state: Any) -> dict:
    raw = getattr(state, "category_extras", None) or {}
    if not isinstance(raw, dict):
        return {}
    cat = raw.get("timeseries", {})
    return cat if isinstance(cat, dict) else {}


def _exog_columns(state: Any, eda: dict) -> list[str]:
    """exog 통일 — A안 핵심 수정.

    우선순위:
      1. state.category_extras["timeseries"]["exog_columns"]
      2. eda.get("exog") or eda.get("exog_columns")
    """
    extras = _category_extras(state)
    cols = extras.get("exog_columns")
    if isinstance(cols, list) and cols:
        return [str(c) for c in cols]
    fallback = eda.get("exog") or eda.get("exog_columns") or []
    if isinstance(fallback, list):
        return [str(c) for c in fallback]
    return []


def _horizon(state: Any, eda: dict) -> int:
    """horizon 추출 — category_extras 우선, chosen_recipe.meta.horizon_hint 보조."""
    extras = _category_extras(state)
    h = extras.get("horizon")
    if isinstance(h, int) and h >= 1:
        return h
    chosen = _chosen_recipe(state)
    meta = chosen.get("meta") if isinstance(chosen, dict) else None
    if isinstance(meta, dict):
        h2 = meta.get("horizon_hint")
        if isinstance(h2, int) and h2 >= 1:
            return h2
    h3 = eda.get("horizon") or eda.get("horizon_hint")
    if isinstance(h3, int) and h3 >= 1:
        return h3
    return 0


def _normalize_recipe_key(recipe_title: Any) -> str:
    if not isinstance(recipe_title, str):
        return "단기 예측"
    if "이상" in recipe_title or "탐지" in recipe_title:
        return "이상 시점"
    if "계절" in recipe_title or "분해" in recipe_title:
        return "계절 분해"
    if "단기" in recipe_title or "예측" in recipe_title:
        return "단기 예측"
    return "단기 예측"


def _is_seasonal_strong(s: Any, acf_peaks: Any) -> bool:
    if s not in SEASONAL_PERIODS:
        return False
    if not isinstance(acf_peaks, list):
        return False
    return len(acf_peaks) >= ACF_STRONG_THRESHOLD


def _baseline_recommend(s: Any, n_rows: int) -> list[str]:
    """방법론 4-2·6-5 — "기준선 못 이기면 채택 금지" 메타."""
    rec: list[str] = []
    if isinstance(s, int) and s >= 2 and n_rows >= 2 * s:
        rec.append("seasonal_naive")
    if n_rows >= 30:
        rec.append("ETS")
    return rec


def _multistep_strategy(horizon: int, recipe_key: str, n_rows: int) -> str:
    if horizon <= 1:
        return "recursive"
    if horizon >= 12 and n_rows >= 200 and recipe_key in ("계절 분해", "이상 시점"):
        return "direct"
    return "hybrid"


def _hybrid_hint(top3: list[str], horizon: int, n_rows: int) -> str | None:
    """DL 비활성. 통계 모델만으로 하이브리드 힌트 없음 (시계열 ML 전용)."""
    return None


# ════════════════════════════════════════════════════════════════
# §A~§H. score (진입점)
# ════════════════════════════════════════════════════════════════
def score(state: Any, recipes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """top3 + rationale + citations + meta 반환.

    설계도 cs-day5 §A~§H + A안 디벨롭 7축 적용. 회귀 0 — 기존 3 키 그대로,
    `meta` 키만 신규 추가.
    """
    recipes = recipes or []

    # ── §A-1 : chosen_recipe 가드 + 정규화 ──
    chosen = _chosen_recipe(state)
    recipe_title_raw = chosen.get("title") or "단기 예측"
    recipe_key = _normalize_recipe_key(recipe_title_raw)

    # ── §A-2 : 입력 추출 ──
    profile = getattr(state, "data_profile", None) or {}
    if not isinstance(profile, dict):
        profile = {}
    eda = _eda_dict(state)
    n_rows = int(profile.get("rows") or profile.get("n_rows", 0) or 0)
    s = eda.get("seasonal_period")
    stationary = eda.get("stationary")
    acf_peaks = eda.get("acf_peaks") or []
    target_kind = eda.get("target_kind")
    is_multivariate = bool(eda.get("is_multivariate"))
    heteroscedastic = bool(eda.get("heteroscedastic"))
    changepoints = int(eda.get("changepoints") or 0)
    leakage_suspect = eda.get("leakage_suspect_cols") or []
    if not isinstance(leakage_suspect, list):
        leakage_suspect = []
    exog_all = _exog_columns(state, eda)
    exog = [c for c in exog_all if c not in leakage_suspect]
    leakage_excluded = [c for c in exog_all if c in leakage_suspect]
    horizon = _horizon(state, eda)

    # ── §B : recipe_key 별 base candidates ──
    if recipe_key == "단기 예측":
        candidates = ["ARIMA", "SARIMA", "Prophet", "SARIMAX", "ETS"]
    elif recipe_key == "이상 시점":
        candidates = ["Prophet", "SARIMA", "ETS"]
    elif recipe_key == "계절 분해":
        candidates = ["Prophet", "SARIMA", "SARIMAX", "ETS"]
    else:
        candidates = ["ARIMA", "SARIMA", "Prophet", "ETS"]

    base = {m: BASE_SCORE for m in candidates}
    adj: dict[str, float] = {m: 0.0 for m in candidates}

    # ── §C : 계열 길이 (7축 가) — DL 비활성, 통계 모델만 ──
    # 짧은 데이터는 ARIMA/ETS/seasonal_naive 가 자동 적합 (selector 가 별도 페널티 불요)

    # ── §D : seasonal_period (7축 다) ──
    if s in SEASONAL_PERIODS:
        if "SARIMA" in adj:
            adj["SARIMA"] += SARIMA_SEASONAL_BONUS
        if "SARIMAX" in adj:
            adj["SARIMAX"] += SARIMAX_SEASONAL_BONUS
    if _is_seasonal_strong(s, acf_peaks) and "SARIMA" in adj:
        adj["SARIMA"] += SARIMA_STRONG_SEASONAL_BONUS

    # ── §E : exog 정책 (A안 핵심) ──
    n_exog = len(exog)
    if "SARIMAX" in candidates:
        if n_exog >= 1 and n_rows >= 100:
            adj["SARIMAX"] += SARIMAX_EXOG_BONUS
        else:
            candidates.remove("SARIMAX")
            adj.pop("SARIMAX", None)
            base.pop("SARIMAX", None)

    # ── §F : stationary → ARIMA 조정 ──
    if stationary is True and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_STAT_BONUS
    elif stationary is False and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_NONSTAT_PENALTY

    # ── §F+ : 7축 디벨롭 추가 ──
    if horizon >= 30:
        if "Prophet" in adj:
            adj["Prophet"] += PROPHET_LONG_HORIZON_BONUS

    if is_multivariate:
        if "SARIMAX" in adj:
            adj["SARIMAX"] += MULTIVARIATE_SARIMAX_BONUS

    if heteroscedastic:
        if "Prophet" in adj:
            adj["Prophet"] += HETERO_PROPHET_BONUS
        if "SARIMA" in adj:
            adj["SARIMA"] += HETERO_SARIMA_BONUS

    if changepoints >= 3 and "Prophet" in adj:
        adj["Prophet"] += CHANGEPOINTS_PROPHET_BONUS

    # ── §F++ (2026-06-05) : 주제 적합도 보너스 (user_intent + chosen_recipe.meta) ──
    chosen_meta = chosen.get("meta") if isinstance(chosen, dict) else {}
    topic_signals = _topic_signals(state, chosen_meta or {}, horizon, n_rows)
    intent_match = _apply_topic_bonus(adj, topic_signals)

    # ── §F+++ (2026-06-08, Phase 1-A) : 전문가 4 차원 점수 적용 ──
    # 인간 전문가의 추가 고려 사항 (해석성·강건성·불확실성·재학습 효율) 정량화.
    # 7축·9토픽 위에 추가 신호로 가산. user_intent 또는 데이터 신호로 우선순위 자동 결정.
    expert_priorities = _resolve_expert_priorities(state, topic_signals, n_rows)
    expert_scores = _compute_expert_scores(list(candidates), expert_priorities)
    _apply_expert_bonus(adj, expert_scores)

    # ── §G : 점수 매트릭스 + top3 정렬 ──
    scores = {m: _clip(base[m] + adj[m]) for m in candidates}
    sorted_models = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    top3 = [name for name, _ in sorted_models[:3]]

    for fb in ("ARIMA", "Prophet", "SARIMA"):
        if len(top3) >= 3:
            break
        if fb not in top3:
            top3.append(fb)

    # ── §H : citations + rationale + meta ──
    citations = [r["hash"] for r in recipes[:3] if isinstance(r, dict) and r.get("hash")]

    baseline_rec = _baseline_recommend(s, n_rows)
    multistep = _multistep_strategy(horizon, recipe_key, n_rows)
    hybrid = _hybrid_hint(top3, horizon, n_rows)

    meta = {
        "recipe_key": recipe_key,
        "n_rows": n_rows,
        "seasonal_period": s,
        "exog_columns": exog,
        "horizon": horizon,
        "stationary": stationary,
        "target_kind": target_kind,
        "is_multivariate": is_multivariate,
        "heteroscedastic": heteroscedastic,
        "changepoints": changepoints,
        "scores": {m: round(v, 3) for m, v in scores.items()},
        "baseline_recommend": baseline_rec,
        "multistep_strategy": multistep,
        "hybrid_hint": hybrid,
        "leakage_excluded": leakage_excluded,
        # 주제 적합도 신호 (2026-06-05) — insight·output_extras 에서 활용
        "topic_signals": {k: v for k, v in topic_signals.items() if v},
        "intent_match": {m: lst for m, lst in intent_match.items() if lst},
        # 전문가 4 차원 (2026-06-08, Phase 1-A) — insight·output_extras 에서 trace·인용
        "expert_priorities": expert_priorities,
        "expert_scores": expert_scores,
        "expert_top_dimension": (
            max(expert_priorities, key=lambda k: expert_priorities[k]) if expert_priorities else None
        ),
        "expert_dimensions_used": list(EXPERT_DIMENSIONS.keys()),
    }

    rationale_parts = [
        f"recipe={recipe_key}",
        f"n={n_rows}",
        f"s={s}",
        f"exog={n_exog}",
        f"stationary={stationary}",
        f"horizon={horizon}",
        f"multivariate={is_multivariate}",
        f"hetero={heteroscedastic}",
        f"changepoints={changepoints}",
        f"→ top3={top3}",
        f"baseline={baseline_rec}",
        f"multistep={multistep}",
    ]
    if hybrid:
        rationale_parts.append(f"hybrid={hybrid}")
    if leakage_excluded:
        rationale_parts.append(f"leakage_excluded={leakage_excluded}")
    active_topics = [t for t, v in topic_signals.items() if v]
    if active_topics:
        rationale_parts.append(f"topics={active_topics}")
    top_dim = meta.get("expert_top_dimension")
    if top_dim and top3:
        top_model = top3[0]
        top_score = expert_scores.get(top_model)
        if top_score is not None:
            rationale_parts.append(f"expert={top_dim}({top_score:.2f}@{top_model})")
    rationale = ", ".join(rationale_parts)

    return {"top3": top3, "rationale": rationale, "citations": citations, "meta": meta}

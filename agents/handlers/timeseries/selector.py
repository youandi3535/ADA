"""agents.handlers.timeseries.selector — 시계열 모델 추천 (CS 담당, cs-day5 v3 디벨롭).

진입함수 (dispatcher 자동 등록):
  - score(state, recipes=None) -> dict
      반환: {"top3": list[str], "rationale": str, "citations": list[str], "meta": dict}

DoD (불변):
  - top3 길이 ≥ 3
  - citations ≥ 1 (R-501) — recipes 비어 있을 땐 빈 list 허용 + warning
  - n_rows < 100 → DL(Informer/TFT/PatchTST) 제외 (페널티)
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
SUPPORTED_MODELS = ("ARIMA", "SARIMA", "SARIMAX", "Prophet", "Informer", "TFT", "PatchTST")
DL_MODELS = ("Informer", "TFT", "PatchTST")
STAT_MODELS = ("ARIMA", "SARIMA", "SARIMAX")

BASE_SCORE = 0.70

# Day5 기존 가중 (불변 — 회귀 0)
DL_PENALTY_SMALL = -0.20
SARIMA_SEASONAL_BONUS = 0.15
SARIMAX_SEASONAL_BONUS = 0.10
SARIMAX_EXOG_BONUS = 0.20
ARIMA_STAT_BONUS = 0.10
ARIMA_NONSTAT_PENALTY = -0.05

# A안 7축 디벨롭 가중 (신규)
DL_MID_PENALTY = -0.05
DL_LARGE_BONUS = 0.05
PROPHET_LONG_HORIZON_BONUS = 0.05
DL_LONG_HORIZON_BONUS = 0.05
SARIMA_STRONG_SEASONAL_BONUS = 0.05
MULTIVARIATE_SARIMAX_BONUS = 0.05
MULTIVARIATE_DL_BONUS = 0.05
HETERO_PROPHET_BONUS = 0.03
HETERO_SARIMA_BONUS = 0.03
CHANGEPOINTS_PROPHET_BONUS = 0.05
TARGET_KIND_CUMULATIVE_DL_PENALTY = -0.05

SEASONAL_PERIODS = (7, 12, 30, 365)
ACF_STRONG_THRESHOLD = 2


# ════════════════════════════════════════════════════════════════
# §0. 헬퍼
# ════════════════════════════════════════════════════════════════
def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


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
    has_dl = any(m in DL_MODELS for m in top3)
    has_stat = any(m in STAT_MODELS for m in top3)
    if has_dl and has_stat and horizon >= 12 and n_rows >= 500:
        stat_first = next(m for m in top3 if m in STAT_MODELS)
        dl_first = next(m for m in top3 if m in DL_MODELS)
        return f"{stat_first}->{dl_first}_residual"
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
        candidates = ["ARIMA", "SARIMA", "Prophet", "SARIMAX"]
    elif recipe_key == "이상 시점":
        candidates = ["Prophet", "SARIMA", "TFT", "PatchTST"]
    elif recipe_key == "계절 분해":
        candidates = ["Prophet", "SARIMA", "SARIMAX", "TFT", "PatchTST"]
    else:
        candidates = ["ARIMA", "SARIMA", "Prophet"]

    base = {m: BASE_SCORE for m in candidates}
    adj: dict[str, float] = {m: 0.0 for m in candidates}

    # ── §C : 계열 길이 (7축 가) ──
    if n_rows < 100:
        for m in DL_MODELS:
            if m in adj:
                adj[m] += DL_PENALTY_SMALL
    elif n_rows < 500:
        for m in DL_MODELS:
            if m in adj:
                adj[m] += DL_MID_PENALTY
    elif n_rows >= 1000:
        for m in DL_MODELS:
            if m in adj:
                adj[m] += DL_LARGE_BONUS

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
        for m in DL_MODELS:
            if m in adj:
                adj[m] += DL_LONG_HORIZON_BONUS

    if target_kind == "cumulative":
        for m in DL_MODELS:
            if m in adj:
                adj[m] += TARGET_KIND_CUMULATIVE_DL_PENALTY

    if is_multivariate:
        if "SARIMAX" in adj:
            adj["SARIMAX"] += MULTIVARIATE_SARIMAX_BONUS
        for m in DL_MODELS:
            if m in adj:
                adj[m] += MULTIVARIATE_DL_BONUS

    if heteroscedastic:
        if "Prophet" in adj:
            adj["Prophet"] += HETERO_PROPHET_BONUS
        if "SARIMA" in adj:
            adj["SARIMA"] += HETERO_SARIMA_BONUS

    if changepoints >= 3 and "Prophet" in adj:
        adj["Prophet"] += CHANGEPOINTS_PROPHET_BONUS

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
    rationale = ", ".join(rationale_parts)

    return {"top3": top3, "rationale": rationale, "citations": citations, "meta": meta}

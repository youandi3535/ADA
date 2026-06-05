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
   기존 코드의 `eda.get("exog") or []` 는 eda_summary 에 `exog` 키가 채워지지
   않아 **항상 빈 list** → SARIMAX 무조건 제외 버그. 수정으로 SARIMAX 가 정상 진입.
2. baseline_recommend 메타 — seasonal_naive(s≥2 + n≥2s) / ETS(n≥30) 를 메타로만 추천.
   **top3 에는 절대 안 넣음** (pipeline SUPPORTED_MODELS 미지원).
3. 7축 반영 — 헌장 2-1 7개 축 전부 점수 룰로 코드화 (가~사).
4. meta(multistep_strategy / hybrid_hint / baseline_recommend / leakage_excluded) — 다운스트림 pipeline·HPO·evaluator·insight 에 신호.
5. rationale R-501 강화 — 모든 조정값 수치 인용 (검증 가능).

핵심 설계 원칙 (cs-day5 §O 계승)
─────────────────────────────────────────────────────────────────
- recipe 기반 base candidates — 3 분기 (단기/이상/계절) · default = "단기 예측"
- DoD 강제 (n<100 → DL · exog=0 → SARIMAX EXCLUDED)
- score clip(0, 1) + top3 길이 3 보장 (ARIMA → Prophet → SARIMA fallback)
- 인라인 안전 우선 — 어떤 상태에서도 default 진행
- 회귀 0 — 기존 3 키 (top3 / rationale / citations) 불변, `meta` 키만 신규 추가
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
# 시계열 카테고리 전용. anomaly 카테고리의 COPOD/IsolationForest/LOF/OneClassSVM/
# AutoEncoder/TranAD/AnomalyTransformer 는 여기 포함하지 않는다 (카테고리 격리).
SUPPORTED_MODELS = ("ARIMA", "SARIMA", "SARIMAX", "Prophet", "Informer", "TFT", "PatchTST")
DL_MODELS = ("Informer", "TFT", "PatchTST")
STAT_MODELS = ("ARIMA", "SARIMA", "SARIMAX")

BASE_SCORE = 0.70

# Day5 기존 가중 (불변 — 회귀 0)
DL_PENALTY_SMALL = -0.20  # n<100 → DL (DoD)
SARIMA_SEASONAL_BONUS = 0.15  # s ∈ {7,12,30,365}
SARIMAX_SEASONAL_BONUS = 0.10
SARIMAX_EXOG_BONUS = 0.20
ARIMA_STAT_BONUS = 0.10
ARIMA_NONSTAT_PENALTY = -0.05

# A안 7축 디벨롭 가중 (신규 — 모두 작은 보너스라 기존 매트릭스 균형 유지)
DL_MID_PENALTY = -0.05  # 100 ≤ n < 500 약페널티 (DL 학습 안정성 부족) — 7축 가
DL_LARGE_BONUS = 0.05  # n ≥ 1000 DL 약보너스 — 7축 가
PROPHET_LONG_HORIZON_BONUS = 0.05  # horizon ≥ 30 → Prophet (장기 추세+계절) — 7축 나
DL_LONG_HORIZON_BONUS = 0.05  # horizon ≥ 30 → Transformer 장기예측 적합 — 7축 나
SARIMA_STRONG_SEASONAL_BONUS = 0.05  # acf_peaks 다수 + s 명시 → SARIMA 추가 — 7축 다
MULTIVARIATE_SARIMAX_BONUS = 0.05  # is_multivariate True → SARIMAX 추가 — 7축 마
MULTIVARIATE_DL_BONUS = 0.05  # is_multivariate True → DL 추가 — 7축 마
HETERO_PROPHET_BONUS = 0.03  # heteroscedastic → Prophet 약(잔차 변동성) — 7축 바
HETERO_SARIMA_BONUS = 0.03  # heteroscedastic → SARIMA 약 — 7축 바
CHANGEPOINTS_PROPHET_BONUS = 0.05  # changepoints ≥ 3 → Prophet (내장 검출) — 7축 사
TARGET_KIND_CUMULATIVE_DL_PENALTY = -0.05  # cumulative 타겟 + DL → 누적성 학습 어려움 — 7축 라

SEASONAL_PERIODS = (7, 12, 30, 365)
ACF_STRONG_THRESHOLD = 2  # acf_peaks ≥ 2 + s 명시 → 계절성 명확


# ════════════════════════════════════════════════════════════════
# §0. 헬퍼
# ════════════════════════════════════════════════════════════════
def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _chosen_recipe(state: Any) -> dict:
    """state.chosen_recipe 는 PipelineState 에 없을 수 있어 getattr 안전."""
    raw = getattr(state, "chosen_recipe", None)
    return raw if isinstance(raw, dict) else {}


def _eda_dict(state: Any) -> dict:
    """state.eda_summary 는 Optional[str] 이지만 핸들러는 dict 도 직접 주입 가능.

    HJ 단절 B 가 연결되면 dict 가 전달됨. dict 만 허용 (str 은 빈 dict 처리).
    """
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _category_extras(state: Any) -> dict:
    """state.category_extras["timeseries"] — preprocessor 권위 소스."""
    raw = getattr(state, "category_extras", None) or {}
    if not isinstance(raw, dict):
        return {}
    cat = raw.get("timeseries", {})
    return cat if isinstance(cat, dict) else {}


def _exog_columns(state: Any, eda: dict) -> list[str]:
    """exog 통일 — A안 핵심 수정.

    우선순위:
      1. state.category_extras["timeseries"]["exog_columns"]  (preprocessor 권위 소스)
      2. eda.get("exog") or eda.get("exog_columns")            (보조 — 미래 호환)

    기존 `eda.get("exog") or []` 는 eda_summary 에 exog 키가 채워지지 않아
    항상 빈 list → SARIMAX 무조건 EXCLUDED 버그였다. 수정으로 SARIMAX 가
    정상 후보로 진입한다.
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
    """horizon 추출 — category_extras 우선, chosen_recipe.meta.horizon_hint 보조, 없으면 0.

    proposer §F 의 horizon_hint 와 정합. 0 = 미지정 → 다운스트림이 freq 로 추정.
    """
    extras = _category_extras(state)
    h = extras.get("horizon")
    if isinstance(h, int) and h >= 1:
        return h
    # proposer recipe meta 의 horizon_hint 가 chosen_recipe 에 복사돼 있을 수 있음
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
    """proposer 의 긴 표제("단기 예측 (1~30일)" 등)를 분기 키로 통일."""
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
    """계절성 명확도 — s 명시 + acf_peaks ≥ 2 → 명확 (7축 다)."""
    if s not in SEASONAL_PERIODS:
        return False
    if not isinstance(acf_peaks, list):
        return False
    return len(acf_peaks) >= ACF_STRONG_THRESHOLD


def _baseline_recommend(s: Any, n_rows: int) -> list[str]:
    """방법론 4-2·6-5 — "기준선 못 이기면 채택 금지" 메타.

    seasonal_naive(s≥2 + n≥2s) / ETS(n≥30) 를 메타로만 추천.
    top3 에는 **절대 추가 X** (pipeline SUPPORTED_MODELS 미지원 → 학습 깨짐).
    pipeline 차례에서 ETS/seasonal_naive 학습 추가되면 다운스트림에서 자연 활용.
    """
    rec: list[str] = []
    if isinstance(s, int) and s >= 2 and n_rows >= 2 * s:
        rec.append("seasonal_naive")
    if n_rows >= 30:
        rec.append("ETS")
    return rec


def _multistep_strategy(horizon: int, recipe_key: str, n_rows: int) -> str:
    """다운스트림 학습 루프 힌트 — direct/recursive/hybrid (헌장 2-2 horizon 축).

    - horizon ≤ 1 → "recursive" (one-step + roll)
    - horizon ≥ 12 + n 충분 + 계절/이상 recipe → "direct" (multi-output)
    - 그 외 → "hybrid" (단기 recursive, 장기 direct)
    """
    if horizon <= 1:
        return "recursive"
    if horizon >= 12 and n_rows >= 200 and recipe_key in ("계절 분해", "이상 시점"):
        return "direct"
    return "hybrid"


def _hybrid_hint(top3: list[str], horizon: int, n_rows: int) -> str | None:
    """장기 horizon + DL + STAT 공존 시 결합 신호 (헌장 2-3 하이브리드)."""
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
    `meta` 키만 신규 추가 (Optional 소비 — 기존 다운스트림 영향 0).
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
    # 누수 1-1: leakage_suspect_cols 는 exog 풀에서 제외 (타겟 누수 차단)
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
    else:  # default fallback
        candidates = ["ARIMA", "SARIMA", "Prophet"]

    base = {m: BASE_SCORE for m in candidates}
    adj: dict[str, float] = {m: 0.0 for m in candidates}

    # ── §C : 계열 길이 (7축 가) — DL 페널티/보너스 ──
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

    # ── §D : seasonal_period (7축 다) — SARIMA/SARIMAX 보너스 + 강한 계절성 추가 ──
    if s in SEASONAL_PERIODS:
        if "SARIMA" in adj:
            adj["SARIMA"] += SARIMA_SEASONAL_BONUS
        if "SARIMAX" in adj:
            adj["SARIMAX"] += SARIMAX_SEASONAL_BONUS
    if _is_seasonal_strong(s, acf_peaks) and "SARIMA" in adj:
        adj["SARIMA"] += SARIMA_STRONG_SEASONAL_BONUS

    # ── §E : exog 정책 (A안 핵심) — category_extras 권위 소스 ──
    n_exog = len(exog)
    if "SARIMAX" in candidates:
        if n_exog >= 1 and n_rows >= 100:
            adj["SARIMAX"] += SARIMAX_EXOG_BONUS
        else:
            # DoD : exog 없거나 n 부족 → SARIMAX top3 진입 X
            candidates.remove("SARIMAX")
            adj.pop("SARIMAX", None)
            base.pop("SARIMAX", None)

    # ── §F : stationary → ARIMA 조정 ──
    if stationary is True and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_STAT_BONUS
    elif stationary is False and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_NONSTAT_PENALTY

    # ── §F+ : 7축 디벨롭 추가 ──
    # (나) horizon ≥ 30 → Prophet/DL 약보너스
    if horizon >= 30:
        if "Prophet" in adj:
            adj["Prophet"] += PROPHET_LONG_HORIZON_BONUS
        for m in DL_MODELS:
            if m in adj:
                adj[m] += DL_LONG_HORIZON_BONUS

    # (라) target_kind cumulative + DL → 누적성 학습 어려움
    if target_kind == "cumulative":
        for m in DL_MODELS:
            if m in adj:
                adj[m] += TARGET_KIND_CUMULATIVE_DL_PENALTY

    # (마) is_multivariate → SARIMAX/DL 보너스
    if is_multivariate:
        if "SARIMAX" in adj:
            adj["SARIMAX"] += MULTIVARIATE_SARIMAX_BONUS
        for m in DL_MODELS:
            if m in adj:
                adj[m] += MULTIVARIATE_DL_BONUS

    # (바) heteroscedastic → Prophet/SARIMA 약(잔차 변동성 대응)
    if heteroscedastic:
        if "Prophet" in adj:
            adj["Prophet"] += HETERO_PROPHET_BONUS
        if "SARIMA" in adj:
            adj["SARIMA"] += HETERO_SARIMA_BONUS

    # (사) changepoints ≥ 3 → Prophet (내장 changepoint 검출)
    if changepoints >= 3 and "Prophet" in adj:
        adj["Prophet"] += CHANGEPOINTS_PROPHET_BONUS

    # ── §G : 점수 매트릭스 + top3 정렬 ──
    scores = {m: _clip(base[m] + adj[m]) for m in candidates}
    sorted_models = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    top3 = [name for name, _ in sorted_models[:3]]

    # 길이 < 3 보장 — ARIMA → Prophet → SARIMA fallback
    for fb in ("ARIMA", "Prophet", "SARIMA"):
        if len(top3) >= 3:
            break
        if fb not in top3:
            top3.append(fb)

    # ── §H : citations + rationale + meta ──
    citations = [r["hash"] for r in recipes[:3] if isinstance(r, dict) and r.get("hash")]

    # 신규 메타
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

    # R-501 수치 인용 강화 — 모든 조정 값 노출 (검증 가능)
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

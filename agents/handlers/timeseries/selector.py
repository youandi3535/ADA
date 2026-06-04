"""agents.handlers.timeseries.selector — 시계열 모델 추천 (CS 담당, cs-day5 v2).

진입함수 (dispatcher 자동 등록):
  - score(state, recipes=None) -> dict
      반환: {"top3": list[str], "rationale": str, "citations": list[str]}

DoD: top3 길이 = 3 + citations ≥ 1 (R-501) + n<100 → DL 제외 + exog=0 → SARIMAX 제외.

점수 매트릭스 (recipe_title 별 base candidates + 5 조정):
  base + DL 페널티 (n<100) + SARIMA 보너스 (s∈{7,12,30,365})
       + SARIMAX exog 정책 (exog≥1 & n≥100 보너스 / 아니면 EXCLUDED)
       + ARIMA stationary 조정

핵심 설계 원칙:
  - recipe 기반 base candidates — 3 분기 (단기/이상/계절) · default = "단기 예측"
  - DoD 강제 2 개 : n<100 → DL -0.20 · exog=0 → SARIMAX EXCLUDED
  - score clip(0, 1) + top3 길이 3 보장 (ARIMA fallback)
  - R-501 인용 강제
  - 인라인 안전 우선 (chosen_recipe / eda 없어도 default 진행)
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
# 시계열 카테고리 전용. anomaly 카테고리의 COPOD/IsolationForest/LOF/OneClassSVM/
# AutoEncoder/TranAD/AnomalyTransformer 는 여기 포함하지 않는다 (카테고리 격리).
SUPPORTED_MODELS = ("ARIMA", "SARIMA", "SARIMAX", "Prophet", "Informer", "TFT", "PatchTST")
DL_MODELS = ("Informer", "TFT", "PatchTST")
BASE_SCORE = 0.70
DL_PENALTY_SMALL = -0.20
SARIMA_SEASONAL_BONUS = 0.15
SARIMAX_SEASONAL_BONUS = 0.10
SARIMAX_EXOG_BONUS = 0.20
ARIMA_STAT_BONUS = 0.10
ARIMA_NONSTAT_PENALTY = -0.05
SEASONAL_PERIODS = (7, 12, 30, 365)


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _chosen_recipe(state: Any) -> dict:
    """state.chosen_recipe 는 PipelineState 에 없을 수 있어 getattr 안전."""
    raw = getattr(state, "chosen_recipe", None)
    return raw if isinstance(raw, dict) else {}


def _eda_dict(state: Any) -> dict:
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


# ════════════════════════════════════════════════════════════════
# §A~§H. score
# ════════════════════════════════════════════════════════════════
def score(state: Any, recipes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """top3 + rationale + citations 반환. 설계도 cs-day5 §A~§H 그대로."""
    recipes = recipes or []

    # ── §A-1 : chosen_recipe 가드 ──
    chosen = _chosen_recipe(state)
    recipe_title = chosen.get("title") or "단기 예측"  # default (인라인 안전)

    # ── §A-2 : 입력 추출 ──
    profile = getattr(state, "data_profile", None) or {}
    eda = _eda_dict(state)
    n_rows = int(profile.get("rows") or profile.get("n_rows", 0) or 0)
    s = eda.get("seasonal_period")
    stationary = eda.get("stationary")
    exog = eda.get("exog") or []

    # ── §B : recipe_title 별 base candidates ──
    if recipe_title == "단기 예측":
        candidates = ["ARIMA", "SARIMA", "Prophet", "SARIMAX"]
    elif recipe_title in ("이상 시점 탐지", "이상 시점"):
        candidates = ["Prophet", "SARIMA", "TFT", "PatchTST"]
    elif recipe_title in ("계절성 분해", "계절 분해"):
        candidates = ["Prophet", "SARIMA", "SARIMAX", "TFT", "PatchTST"]
    else:
        candidates = ["ARIMA", "SARIMA", "Prophet"]  # default fallback

    base = {m: BASE_SCORE for m in candidates}
    adj = {m: 0.0 for m in candidates}

    # ── §C : n_rows < 100 → DL 페널티 ──
    if n_rows < 100:
        for m in DL_MODELS:
            if m in adj:
                adj[m] += DL_PENALTY_SMALL

    # ── §D : seasonal_period ∈ {7,12,30,365} → SARIMA 보너스 ──
    if s in SEASONAL_PERIODS:
        if "SARIMA" in adj:
            adj["SARIMA"] += SARIMA_SEASONAL_BONUS
        if "SARIMAX" in adj:
            adj["SARIMAX"] += SARIMAX_SEASONAL_BONUS

    # ── §E : exog 존재 + n≥100 → SARIMAX 보너스 / 그 외 EXCLUDED ──
    if "SARIMAX" in candidates:
        if len(exog) >= 1 and n_rows >= 100:
            adj["SARIMAX"] += SARIMAX_EXOG_BONUS
        else:
            candidates.remove("SARIMAX")  # DoD : exog 없으면 top3 진입 X
            adj.pop("SARIMAX", None)
            base.pop("SARIMAX", None)

    # ── §F : stationary → ARIMA 조정 ──
    if stationary is True and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_STAT_BONUS
    elif stationary is False and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_NONSTAT_PENALTY

    # ── §G : 점수 매트릭스 + top3 정렬 ──
    scores = {m: _clip(base[m] + adj[m]) for m in candidates}
    sorted_models = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    top3 = [name for name, _ in sorted_models[:3]]

    # 길이 < 3 보장 — ARIMA fallback
    while len(top3) < 3:
        if "ARIMA" not in top3:
            top3.append("ARIMA")
        elif "Prophet" not in top3:
            top3.append("Prophet")
        else:
            top3.append("SARIMA")

    # ── §H : citations + rationale ──
    citations = [r["hash"] for r in (recipes or [])[:3] if r.get("hash")]

    rationale = f"recipe={recipe_title}, n={n_rows}, s={s}, exog={len(exog)}, stationary={stationary} → top3 = {top3}"
    return {"top3": top3, "rationale": rationale, "citations": citations}

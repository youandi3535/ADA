"""agents.handlers.timeseries.proposer — 시계열 G2/G3 fallback 제안 (CS 담당, cs-day4 v2).

LLM 실패 시 dispatcher (gates/) 가 본 함수를 호출하여 fallback.

진입함수 (dispatcher 자동 등록):
  - g1(state) -> list[dict]   G2 3 안 (단기 예측 / 이상 시점 / 계절 분해) — eda 기반 점수 조정
  - g2(state) -> list[dict]   G3 카테고리 (timeseries 유지)

DoD: g1 list 길이 ≥ 3 + g2 list 길이 ≥ 1 + 모든 score ∈ [0.0, 1.0].

핵심 설계 원칙:
  - proposer = LLM fallback — 어떤 입력에도 결과 반환 (인라인 안전 우선)
  - 점수 조정 룰 — eda 활용 가능 시만 적용, 없으면 default (강제 X)
  - user_intent 최우선 (+0.30)
  - rationale 동적 생성 (R-501 — eda 값 직접 인용)
  - score clip(0, 1)
"""

from __future__ import annotations

from typing import Any

# ── base scores ───────────────────────────────────────────────────
BASE_SCORES = {"단기 예측": 0.85, "이상 시점": 0.65, "계절 분해": 0.55}
USER_INTENT_BONUS = 0.30


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _get_profile(state: Any) -> dict:
    return getattr(state, "data_profile", None) or {}


def _eda_dict(state: Any) -> dict:
    """state.eda_summary 가 str/None 일 수 있으므로 dict 로 안전 변환."""
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _n_rows(state: Any) -> int:
    profile = _get_profile(state)
    return int(profile.get("rows") or profile.get("n_rows", 0) or 0)


def _default_recipes() -> list[dict[str, Any]]:
    """eda_summary None 시 base scores 그대로 (A-1b 인라인 안전)."""
    return [
        {"id": 1, "title": "단기 예측 (1~30일)", "rationale": "최근 추세 기반 forecasting", "score": 0.85},
        {"id": 2, "title": "이상 시점 탐지", "rationale": "변동성 큰 구간 식별", "score": 0.65},
        {"id": 3, "title": "계절성 분해", "rationale": "추세/계절/잔차 분리", "score": 0.55},
    ]


def _build_rationale(title: str, eda: dict, n: int) -> str:
    s = eda.get("seasonal_period")
    stat = eda.get("stationary")
    if title == "단기 예측":
        return f"비정상 시계열 (stationary={stat}, n={n}) — 차분 후 forecasting 효과적"
    if title == "이상 시점":
        return "변동성 큰 데이터 — 이상 탐지 적합"
    if title == "계절 분해":
        return f"계절성 명확 (s={s}, n={n}) — STL/seasonal_decompose 유의미"
    return ""


# ════════════════════════════════════════════════════════════════
# §A~§E. g1 — 3 recipe 점수 조정
# ════════════════════════════════════════════════════════════════
def g1(state: Any) -> list[dict[str, Any]]:
    """G2 3 안 fallback — eda 기반 점수 조정 (단기/이상/계절)."""
    # ── A-1 : eda_summary 존재 가드 ──
    eda = _eda_dict(state)
    if not eda:
        return _default_recipes()  # A-1b 인라인 안전

    # ── A-2 : base scores 초기화 ──
    adj = {"단기": 0.0, "이상": 0.0, "계절": 0.0}
    n_rows = _n_rows(state)
    intent = (getattr(state, "user_intent", None) or "").lower()

    # ── §B : recipe ① "단기 예측" ──
    if eda.get("stationary") is False:  # B-1
        adj["단기"] += 0.10
    if any(kw in intent for kw in ["예측", "forecast", "forecasting", "예보"]):  # B-2 ★
        adj["단기"] += USER_INTENT_BONUS
    if n_rows >= 100:  # B-3
        adj["단기"] += 0.05
    else:
        adj["단기"] -= 0.05

    # ── §C : recipe ② "이상 시점 탐지" ──
    residual_std = eda.get("residual_std", 0.0)
    total_std = eda.get("total_std", 1.0)
    if total_std and total_std > 0 and (residual_std / total_std) > 0.30:  # C-1
        adj["이상"] += 0.20
    if any(kw in intent for kw in ["이상", "anomaly", "탐지", "detection"]):  # C-2 ★
        adj["이상"] += USER_INTENT_BONUS
    if (eda.get("changepoints") or 0) >= 1:  # C-3
        adj["이상"] += 0.10

    # ── §D : recipe ③ "계절 분해" ──
    s = eda.get("seasonal_period")
    if s in (7, 12, 30, 365):  # D-1
        adj["계절"] += 0.20
    else:
        adj["계절"] -= 0.10
    if s and isinstance(s, int) and n_rows >= 2 * s:  # D-2
        adj["계절"] += 0.05
    else:
        adj["계절"] -= 0.15
    if any(kw in intent for kw in ["계절", "season", "분해", "decomposition", "stl"]):  # D-3 ★
        adj["계절"] += USER_INTENT_BONUS

    # ── §E-1 : g1 최종 조립 ──
    recipes = [
        {
            "id": 1,
            "title": "단기 예측 (1~30일)",
            "rationale": _build_rationale("단기 예측", eda, n_rows),
            "score": round(_clip(BASE_SCORES["단기 예측"] + adj["단기"]), 2),
        },
        {
            "id": 2,
            "title": "이상 시점 탐지",
            "rationale": _build_rationale("이상 시점", eda, n_rows),
            "score": round(_clip(BASE_SCORES["이상 시점"] + adj["이상"]), 2),
        },
        {
            "id": 3,
            "title": "계절성 분해",
            "rationale": _build_rationale("계절 분해", eda, n_rows),
            "score": round(_clip(BASE_SCORES["계절 분해"] + adj["계절"]), 2),
        },
    ]
    recipes.sort(key=lambda r: r["score"], reverse=True)
    return recipes


# ════════════════════════════════════════════════════════════════
# §E-2. g2 — 카테고리 유지
# ════════════════════════════════════════════════════════════════
def g2(state: Any) -> list[dict[str, Any]]:
    """G3 방법론 — 시계열 카테고리 유지 우선."""
    return [
        {
            "id": 1,
            "title": "timeseries",
            "rationale": "현재 카테고리 유지 — 시계열 데이터는 시계열 처리",
            "score": 0.95,
        },
    ]

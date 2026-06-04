"""agents.handlers.timeseries.proposer — 시계열 G1/G2 fallback 제안 (CS 담당, cs-day4 v3 디벨롭).

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

cs-day4 v3 디벨롭 (방법론 0·2·6단계 + 디벨롭보고서 §2-4):
  - §C 이상: changepoints 단계 가중(1~2건 +0.10, 3건+ +0.15) + 이분산(heteroscedastic) +0.10
  - §B 단기: target_kind=="cumulative" → 차분 후 forecasting 신호 (rationale 보강)
  - §D 계절: is_multiplicative → 계절 분해 시 로그 변환 힌트 (rationale)
  - 신규 §F: 0단계 성격 meta (point/interval · uni/multivariate · horizon 힌트) — 기존 4키 불변, meta 추가
  - rationale R-501 강화 — changepoints·residual_ratio 실제값 인용
"""

from __future__ import annotations

from typing import Any

# ── base scores ───────────────────────────────────────────────────
BASE_SCORES = {"단기 예측": 0.85, "이상 시점": 0.65, "계절 분해": 0.55}
USER_INTENT_BONUS = 0.30
SEASONAL_PERIODS = (7, 12, 30, 365)
# horizon 힌트 fallback (freq → 기본 예측 시점 수)
_FREQ_HORIZON = {"D": 7, "W": 4, "M": 12, "MS": 12, "H": 24, "Q": 4}


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
    """R-501 — eda 실제값을 직접 인용한 동적 rationale."""
    s = eda.get("seasonal_period")
    stat = eda.get("stationary")
    cp = eda.get("changepoints") or 0
    target_kind = eda.get("target_kind")
    is_mult = eda.get("is_multiplicative")

    if title == "단기 예측":
        kind_hint = " · 누적형 타겟 → 차분 권장" if target_kind == "cumulative" else ""
        return f"비정상 시계열 (stationary={stat}, n={n}){kind_hint} — 차분 후 forecasting 효과적"
    if title == "이상 시점":
        # 수치 인용: changepoint 수 + 잔차 비율
        rr = None
        try:
            rs = eda.get("residual_std")
            ts = eda.get("total_std")
            if rs is not None and ts:
                rr = round(float(rs) / float(ts), 2)
        except Exception:
            rr = None
        rr_txt = f", 잔차비율={rr}" if rr is not None else ""
        return f"변동성 큰 데이터 (changepoints={cp}{rr_txt}) — 이상 탐지 적합"
    if title == "계절 분해":
        mult_hint = " · 승법성 → 로그 변환 검토" if is_mult else ""
        return f"계절성 명확 (s={s}, n={n}){mult_hint} — STL/seasonal_decompose 유의미"
    return ""


# ════════════════════════════════════════════════════════════════
# §F. 0단계 성격 meta (point/interval · uni/multivariate · horizon)
# ════════════════════════════════════════════════════════════════
def _build_meta(title: str, eda: dict, profile: dict) -> dict[str, Any]:
    """방법론 0단계 — 예측 목표 성격 제안. 기존 4키 외 추가 키(소비처 회귀 0).

    - variate     : "multivariate" if exog 있음 else "univariate"
    - forecast_kind: "interval" (불확실성 큰 경우) / "point"
    - task_kind   : recipe 별 — 이상 시점은 "classification"(레짐/이벤트), 그 외 "regression"
    - horizon_hint: seasonal_period 또는 freq 기반 기본 예측 시점 수
    """
    is_multivariate = bool(eda.get("is_multivariate"))
    s = eda.get("seasonal_period")
    freq = profile.get("freq") or eda.get("freq") or "D"
    horizon_hint = s if (isinstance(s, int) and s >= 2) else _FREQ_HORIZON.get(freq, 7)

    # 변동성 크거나 changepoint 있으면 구간 예측 권장 (방법론 0단계 point vs interval)
    cp = eda.get("changepoints") or 0
    hetero = bool(eda.get("heteroscedastic"))
    forecast_kind = "interval" if (cp >= 1 or hetero) else "point"

    task_kind = "classification" if title == "이상 시점" else "regression"

    return {
        "variate": "multivariate" if is_multivariate else "univariate",
        "forecast_kind": forecast_kind,
        "task_kind": task_kind,
        "horizon_hint": int(horizon_hint),
    }


# ════════════════════════════════════════════════════════════════
# §A~§F. g1 — 3 recipe 점수 조정 + meta
# ════════════════════════════════════════════════════════════════
def g1(state: Any) -> list[dict[str, Any]]:
    """G1 3 안 fallback — eda 기반 점수 조정 (단기/이상/계절) + 0단계 meta."""
    # ── A-1 : eda_summary 존재 가드 ──
    eda = _eda_dict(state)
    if not eda:
        return _default_recipes()  # A-1b 인라인 안전

    # ── A-2 : base scores 초기화 ──
    adj = {"단기": 0.0, "이상": 0.0, "계절": 0.0}
    n_rows = _n_rows(state)
    profile = _get_profile(state)
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
    # B-4 (신규): 누적형 타겟 → 차분 후 forecasting 적합 (방법론 롤백4)
    if eda.get("target_kind") == "cumulative":
        adj["단기"] += 0.05

    # ── §C : recipe ② "이상 시점 탐지" ──
    residual_std = eda.get("residual_std", 0.0)
    total_std = eda.get("total_std", 1.0)
    if total_std and total_std > 0 and (residual_std / total_std) > 0.30:  # C-1
        adj["이상"] += 0.20
    if any(kw in intent for kw in ["이상", "anomaly", "탐지", "detection"]):  # C-2 ★
        adj["이상"] += USER_INTENT_BONUS
    # C-3 (디벨롭): changepoints 단계 가중 (방법론 2-1·증상D — 레짐 다수일수록 강함)
    cp = eda.get("changepoints") or 0
    if cp >= 3:
        adj["이상"] += 0.15
    elif cp >= 1:
        adj["이상"] += 0.10
    # C-4 (신규): 이분산 → 변동성 신호 (방법론 2-1)
    if eda.get("heteroscedastic") is True:
        adj["이상"] += 0.10

    # ── §D : recipe ③ "계절 분해" ──
    s = eda.get("seasonal_period")
    if s in SEASONAL_PERIODS:  # D-1
        adj["계절"] += 0.20
    else:
        adj["계절"] -= 0.10
    if s and isinstance(s, int) and n_rows >= 2 * s:  # D-2
        adj["계절"] += 0.05
    else:
        adj["계절"] -= 0.15
    if any(kw in intent for kw in ["계절", "season", "분해", "decomposition", "stl"]):  # D-3 ★
        adj["계절"] += USER_INTENT_BONUS

    # ── §E-1 : g1 최종 조립 (+ §F meta) ──
    titles = [
        (1, "단기 예측 (1~30일)", "단기 예측", "단기"),
        (2, "이상 시점 탐지", "이상 시점", "이상"),
        (3, "계절성 분해", "계절 분해", "계절"),
    ]
    recipes = [
        {
            "id": rid,
            "title": title,
            "rationale": _build_rationale(rkey, eda, n_rows),
            "score": round(_clip(BASE_SCORES[rkey] + adj[akey]), 2),
            "meta": _build_meta(rkey, eda, profile),
        }
        for (rid, title, rkey, akey) in titles
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

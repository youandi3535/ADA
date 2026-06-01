"""agents.handlers.timeseries.insight — 시계열 인사이트 (CS 담당, cs-day8 v2).

SYSTEM_PROMPT 수치 2+ 강제 + prompt_payload (horizon 추론) + fallback 5 단 한국어 조립.

진입함수 (dispatcher 자동 등록):
  - generate(state) -> str          한국어 3~5 문장 (fallback 반환; LLM 은 dispatcher)
  - prompt_payload(state) -> dict   LLM 입력 (HJ BaseAgent._call_llm)
  - fallback(state) -> str          LLM 실패 시 한국어 템플릿

DoD: 한국어 3~5문장 + 정확한 수치 2개 이상 + top features 1개 이상
     (예: "다음 7일 매출이 평균 +12.3% 증가, naïve 대비 +40% 우수").

핵심 설계 원칙:
  - 수치 2+ DoD 강제 — SYSTEM_PROMPT 규칙 3 + fallback F-5 수치 보장 매트릭스
  - direction 한국어 매핑 — None / "none" 구분 (혼합 vs 횡보)
  - freq 폴백 3 단 — 정확 매칭 → prefix → "주기"
  - 수치 우선순위 — improvement > MASE > skip
  - 응급 안전망 — fallback 자체 실패 시 응급 텍스트
"""

from __future__ import annotations

from typing import Any

# ── 한국어 표현 매핑 ──────────────────────────────────────────────
DIRECTION_KO: dict[str, str] = {
    "increasing": "상승",
    "decreasing": "하락",
    "none": "횡보",
}

# pd.infer_freq 코드 → 한국어 단위 (정확 매칭 우선, prefix 폴백)
FREQ_UNIT_KO: dict[str, str] = {
    "D": "일",
    "B": "영업일",
    "W": "주",
    "M": "개월",
    "MS": "개월",
    "Q": "분기",
    "QS": "분기",
    "Y": "년",
    "YS": "년",
    "A": "년",
    "H": "시간",
    "T": "분",
    "S": "초",
}

FREQ_HORIZON_FALLBACK = {"D": 7, "W": 4, "M": 12, "MS": 12, "H": 24}

SYSTEM_PROMPT = """당신은 시계열 분석 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~5문장으로 인사이트를 작성하세요.

규칙:
1. 추세 방향 (상승/하락/횡보) 을 1번째 문장에 명시
2. 계절성/주기 가 있다면 2번째 문장에 언급 (주기 숫자 포함)
3. 정확한 수치 2개 이상 인용 (★ 강화)
   - 예: 변화율 % (slope), naïve 대비 개선율, MASE, 주기 숫자
   - 도메인 예시 : "다음 7일 매출이 평균 12% 증가"
4. 마지막 1문장은 행동 권고 (예: "주간 재고는 X 수준으로 조정 권장")
5. 마크다운/리스트/이모지 금지, 순수 한국어 문단만 작성
"""


# ════════════════════════════════════════════════════════════════
# 헬퍼
# ════════════════════════════════════════════════════════════════
def _eda_dict(state: Any) -> dict:
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _unit_ko(freq: Any) -> str:
    """freq 단위 한국어 — 정확 매칭 → prefix 폴백 → "주기"."""
    if not freq:
        return "주기"
    return FREQ_UNIT_KO.get(freq) or FREQ_UNIT_KO.get(freq[:1] if freq else "") or "주기"


# ════════════════════════════════════════════════════════════════
# §B. prompt_payload — horizon 추론 포함 (7 키)
# ════════════════════════════════════════════════════════════════
def prompt_payload(state: Any) -> dict[str, Any]:
    """LLM 호출용 payload — dispatcher 가 사용 (HJ BaseAgent._call_llm)."""
    bm = getattr(state, "best_model", None) or {}
    data_profile = getattr(state, "data_profile", None) or {}
    eda = _eda_dict(state)

    trend = data_profile.get("trend") or {}
    s = data_profile.get("seasonality") or {}
    period = s.get("period") or eda.get("seasonal_period") or 7

    freq = data_profile.get("freq") or eda.get("freq") or "D"
    horizon_n = period if (period and isinstance(period, int)) else FREQ_HORIZON_FALLBACK.get(freq, 7)
    unit_ko = _unit_ko(freq)
    horizon_text = f"다음 {horizon_n}{unit_ko}"

    return {
        "category": "timeseries",
        "user_intent": getattr(state, "user_intent", None),
        "best_model": bm,
        "stationarity": data_profile.get("stationarity"),
        "trend": trend,
        "seasonality": s,
        "eval_result": getattr(state, "eval_result", None),
        "horizon_text": horizon_text,
        "horizon_n": horizon_n,
        "unit_ko": unit_ko,
        "system_prompt": SYSTEM_PROMPT,
    }


# ════════════════════════════════════════════════════════════════
# §F. fallback — 5 단 한국어 조립 (수치 2+ 보장)
# ════════════════════════════════════════════════════════════════
def fallback(state: Any) -> str:
    """LLM 실패 시 한국어 3~5문장 fallback (수치 2+ 보장 매트릭스)."""
    try:
        return _build_fallback(state)
    except Exception:
        # 응급 안전망 (fallback 자체 예외)
        return "이번 분석 결과는 추가 검토가 필요합니다."


def _build_fallback(state: Any) -> str:
    bm = getattr(state, "best_model", None) or {}
    data_profile = getattr(state, "data_profile", None) or {}
    eda = _eda_dict(state)
    metrics = bm.get("metrics") or {}
    # ★ X-3/X-6: per-row + metrics 는 state.eval_result (top-level) — best_model.metrics 우선, eval_result 보강
    eval_result = getattr(state, "eval_result", None) or {}
    if not metrics:
        metrics = eval_result.get("metrics") or {}

    # ── F-1 : direction 한국어 매핑 ──
    trend = data_profile.get("trend") or {}
    direction_en = trend.get("direction")
    direction_ko = DIRECTION_KO.get(direction_en, "혼합")

    # ── F-2 : freq 단위 한국어 ──
    freq = data_profile.get("freq") or eda.get("freq") or "D"
    unit_ko = _unit_ko(freq)

    # ── seasonality + period ──
    s = data_profile.get("seasonality") or {}
    has_seas = s.get("has_seasonality")
    period = s.get("period") or eda.get("seasonal_period") or 7

    # ── F-3 : 수치 ① slope 변화율 ──
    slope_pct = trend.get("slope")
    if slope_pct is not None and abs(slope_pct) > 0.001:
        slope_text = f" (평균 {slope_pct:+.1%})"
    else:
        slope_text = ""  # skip — 수치 ② + ③ 으로 보장

    # ── F-4 : 수치 ② improvement / MASE 대체 ──
    improvement = metrics.get("rmse_improvement_vs_naive")
    mase = metrics.get("MASE")
    if improvement is not None:
        perf_text = f"naïve 대비 {improvement:+.1%} 우수한 성능"
    elif mase is not None:
        if mase < 1.0:
            perf_text = f"MASE {mase:.2f} 의 양호한 성능"
        else:
            perf_text = f"MASE {mase:.2f} 의 추가 검토가 필요한 성능"
    else:
        perf_text = "추가 검토가 필요한 성능"

    model_name = bm.get("model_name", "미정")

    # horizon
    horizon_n = period if (period and isinstance(period, int)) else FREQ_HORIZON_FALLBACK.get(freq, 7)
    horizon_text = f"다음 {horizon_n}{unit_ko}"

    # ── F-5 : 4~5 문장 동적 조립 ──
    sentences: list[str] = []
    # 문장 1 : 추세 + slope 수치 ①
    sentences.append(f"본 시계열은 {direction_ko} 추세{slope_text} 를 보입니다.")
    # 문장 2 : 계절성 + period 수치 ② (has_seas True 일 때만)
    if has_seas and period:
        sentences.append(f"{period}{unit_ko} 주기 계절성이 관측됩니다.")
    # 문장 3 : 모델 성능 + improvement 수치 ③
    sentences.append(f"{model_name} 모델이 {perf_text} 을 보입니다.")
    # 문장 4 : horizon (예측 활용)
    sentences.append(f"{horizon_text} 동안 단기 예측에 활용 가능합니다.")
    # 문장 5 : 행동 권고 (마지막)
    sentences.append("운영팀은 주간 단위로 모델 결과를 모니터링할 것을 권장합니다.")

    # 최악 케이스 (수치 0) 보강 — has_seas=False + improvement=None + slope=None + MASE=None
    if not has_seas and improvement is None and slope_pct is None and mase is None:
        sentences.insert(
            -1, f"{horizon_n}{unit_ko} 후 예측을 위해 추가 모니터링이 필요합니다."
        )  # period 대신 horizon_n 수치 인용

    return " ".join(sentences)


# ════════════════════════════════════════════════════════════════
# 진입점 (dispatcher 자동 등록, "generate" capability)
# ════════════════════════════════════════════════════════════════
def generate(state: Any) -> str:
    """HANDLER_REGISTRY 등록 진입점 — InsightAgent dispatcher 가 호출.

    LLM 기반 생성은 dispatcher 가 담당하고, 여기서는 규칙 기반 fallback 을 반환한다.
    dispatcher 가 LLM 응답을 받으면 이 결과 대신 LLM 결과를 사용한다.
    """
    return fallback(state)

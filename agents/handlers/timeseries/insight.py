"""agents.handlers.timeseries.insight — 시계열 인사이트 프롬프트 (CS 담당)."""

from __future__ import annotations

from typing import Any

# ── 한국어 표현 매핑 ──────────────────────────────────────────────────────────
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

SYSTEM_PROMPT = """당신은 시계열 분석 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~5문장으로 인사이트를 작성하세요.

규칙:
1. 추세 방향(상승/하락/횡보) 을 1번에 명시
2. 계절성/주기 가 있다면 2번에 언급
3. 예측치 또는 RMSE 같은 정확한 수치 1개 이상 인용
4. 마지막 1문장은 행동 권고 (예: "주간 재고는 X 수준으로 조정 권장")
5. 마크다운/리스트/이모지 금지, 순수 한국어 문단만
"""


def prompt_payload(state: Any) -> dict[str, Any]:
    """LLM 호출용 payload — dispatcher 가 사용."""
    return {
        "category": "timeseries",
        "user_intent": state.user_intent,
        "best_model": state.best_model,
        "stationarity": (state.data_profile or {}).get("stationarity"),
        "trend": (state.data_profile or {}).get("trend"),
        "seasonality": (state.data_profile or {}).get("seasonality"),
        "eval_result": state.eval_result,
    }


def fallback(state: Any) -> str:
    """LLM 실패시 fallback 텍스트.

    한국어 자연성:
      - direction="none" → "횡보" (영어 "none" 노출 방지)
      - period 단위는 freq 기반 동적 ("D"→일, "MS"→개월, "H"→시간 등)

    호출 조건: InsightAgent dispatcher 가 LLM 1차 + retry 모두 가드 실패 시 발동.
    """
    bm = state.best_model or {}
    profile = state.data_profile or {}
    trend = profile.get("trend") or {}
    seasonality = profile.get("seasonality") or {}

    # 방향 한국어 매핑 — direction=None(키 없음)→"혼합", "none"(명시)→"횡보"
    direction_en = trend.get("direction")
    direction_ko = DIRECTION_KO.get(direction_en, "혼합")

    # 계절성 표현 — 단위 동적 결정
    season_note = ""
    if seasonality.get("has_seasonality"):
        period = seasonality.get("period") or 7
        freq = profile.get("freq") or "D"
        unit_ko = FREQ_UNIT_KO.get(freq) or FREQ_UNIT_KO.get(freq[:1] if freq else "") or "주기"
        season_note = f" {period}{unit_ko} 주기 계절성이 관측되었습니다."

    return (
        f"본 시계열 데이터는 전반적으로 {direction_ko} 추세를 보입니다.{season_note} "
        f"최적 모델은 {bm.get('model_name', '미정')} 으로 선택되었으며, "
        f"향후 단기 예측에 활용 가능합니다. "
        f"운영팀은 주간 단위로 모델 결과를 모니터링할 것을 권장합니다."
    )


def generate(state: Any) -> str:
    """HANDLER_REGISTRY 등록 진입점 — InsightAgent dispatcher 가 호출.

    LLM 기반 생성은 dispatcher 가 담당하고, 여기서는 규칙 기반 fallback 을 반환한다.
    dispatcher 가 LLM 응답을 받으면 이 결과 대신 LLM 결과를 사용한다.
    """
    return fallback(state)

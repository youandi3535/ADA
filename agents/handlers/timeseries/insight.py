"""agents.handlers.timeseries.insight — 시계열 인사이트 프롬프트 (A 담당)."""
from __future__ import annotations

from typing import Any

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
    """LLM 실패시 fallback 텍스트."""
    bm = state.best_model or {}
    trend = (state.data_profile or {}).get("trend", {})
    direction = trend.get("direction", "혼합")
    return (
        f"본 시계열 데이터는 전반적으로 {direction} 추세를 보입니다. "
        f"최적 모델은 {bm.get('model_name', '미정')} 으로 선택되었으며, "
        f"향후 단기 예측에 활용 가능합니다. "
        f"운영팀은 주간 단위로 모델 결과를 모니터링할 것을 권장합니다."
    )

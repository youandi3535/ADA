"""agents.handlers.anomaly.insight — 이상탐지 인사이트 (B 담당)."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """당신은 이상탐지 결과 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~5문장으로 인사이트를 작성하세요.

규칙:
1. 학습된 이상치 비율(contamination)과 AUC 같은 정확한 수치 1개 이상 인용
2. 가장 영향력 큰 피처(이상치 기여도) 1개 이상 언급
3. Top-N 이상치 사례가 있다면 1건 인용 (예: "거래 #12345 가 평균 대비 8σ 벗어남")
4. 마지막 1문장은 운영 권고 (예: "고위험 거래는 즉시 fraud 팀 알림")
5. 마크다운/리스트/이모지 금지
"""


def prompt_payload(state: Any) -> dict[str, Any]:
    return {
        "category": "anomaly_detection",
        "user_intent": state.user_intent,
        "best_model": state.best_model,
        "contamination_estimate": (state.data_profile or {}).get("contamination_estimate"),
        "eval_result": state.eval_result,
    }


def fallback(state: Any) -> str:
    bm = state.best_model or {}
    contam = (state.data_profile or {}).get("contamination_estimate", 0.05)
    return (
        f"본 데이터에서 약 {contam:.1%} 비율의 이상치가 탐지되었습니다. "
        f"{bm.get('model_name', '미정')} 모델이 가장 안정적인 성능을 보였습니다. "
        f"운영팀은 상위 이상치 사례를 우선 점검 권장합니다."
    )

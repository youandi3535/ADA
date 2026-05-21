"""agents.insight — InsightAgent (Day11).

비즈니스 인사이트 한국어 생성. 정량 → 한국어 스토리텔링.
"""
from __future__ import annotations

import json

from ada.core.state import PipelineState
from agents.base import BaseAgent

SYSTEM_PROMPT = """당신은 분석 메트릭을 비즈니스 의사결정자가 이해할 수 있도록
3~5문장 한국어 인사이트로 옮기는 분석 스토리텔러입니다.

규칙:
1. 정확한 수치를 본문에 인용한다 (예: "정확도 87%").
2. 영향력 큰 피처 상위 3개를 자연스럽게 언급한다 (SHAP 결과 활용).
3. 마지막 한 문장은 행동 권고(예: "마케팅 우선순위는 X")로 끝낸다.
4. 마크다운/리스트/이모지 사용 금지. 순수 한국어 문단만.
"""


class InsightAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-opus-4-7"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            payload = {
                "category": state.category,
                "user_intent": state.user_intent,
                "best_model": state.best_model,
                "eval_result": state.eval_result,
                "explanations": state.explanations,
            }
            text = "이번 분석은 학습 결과 요약이 부족하여 인사이트 생성을 보류합니다."
            try:
                text = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(payload, ensure_ascii=False)[:4500],
                    max_tokens=600,
                    temperature=0.4,
                )
            except Exception as e:
                self.logger.warning("insight_llm_failed", error=str(e))
            return state.with_update(insights=text.strip(), next_agent="gate_outputs")

"""agents.intent_elicitor — IntentElicitorAgent (Day05 v2 / G0 게이트).

자유 의도 텍스트 → 구조화된 intent_spec.
"""

from __future__ import annotations

from ada.core.state import PipelineState
from agents.base import BaseAgent

SYSTEM_PROMPT = """당신은 사용자의 한 줄 의도 텍스트를 다음 JSON 스키마로 구조화합니다.

{
  "task_keyword": "예측|분류|이상탐지|시계열|클러스터링|기타",
  "target_kind": "수치|범주|시계열|이상|미정",
  "audience": "임원|실무|분석가|미정",
  "deadline": "주|월|즉시|미정",
  "free_form": "<원본 의도 그대로>"
}

오직 JSON 만 출력하세요. 마크다운 fence 금지."""


class IntentElicitorAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            user_text = (state.user_intent or state.user_question or "").strip()
            if not user_text:
                spec = {
                    "task_keyword": "미정",
                    "target_kind": "미정",
                    "audience": "미정",
                    "deadline": "미정",
                    "free_form": "",
                }
            else:
                try:
                    raw = await self._call_llm(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=user_text,
                        max_tokens=600,
                        temperature=0.0,
                        json_mode=True,
                    )
                    spec = self._parse_json(raw)
                except Exception as e:
                    self.logger.warning("intent_parse_fallback", error=str(e))
                    spec = {
                        "task_keyword": "미정",
                        "target_kind": "미정",
                        "audience": "미정",
                        "deadline": "미정",
                        "free_form": user_text,
                    }

            gate_responses = dict(state.gate_responses)
            gate_responses["G0"] = {"intent_spec": spec}
            return state.with_update(
                gate_responses=gate_responses,
                current_gate="G0",
                next_agent="data_profiler",
            )

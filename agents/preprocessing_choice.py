"""agents.preprocessing_choice — PreprocessingChoiceAgent (Day10 미니 게이트).

자동 결정 신뢰도 낮을 때만 활성. needs_review 단계가 1개 이상이면 게이트로.
"""

from __future__ import annotations

from ada.core.state import PipelineState
from agents.base import BaseAgent


class PreprocessingChoiceAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            choice_required = any(s.get("needs_review") for s in (state.preprocessing_plan or []))
            gate_responses = dict(state.gate_responses)
            if choice_required:
                gate_responses["preprocess_mini"] = {
                    "options": state.preprocessing_plan,
                    "awaiting_decision": True,
                }
            return state.with_update(gate_responses=gate_responses, next_agent="gate_model_strategy")

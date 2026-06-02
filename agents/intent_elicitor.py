"""agents.intent_elicitor -- IntentElicitorAgent (Day05 v2 / G0 gate).

free-form intent text -> structured intent_spec.
"""

from __future__ import annotations

from ada.core.state import PipelineState
from agents.base import BaseAgent

SYSTEM_PROMPT = """You are an assistant that structures a user's analysis intent into the following JSON schema.
If user text is provided, use it directly. If not, infer from the given data context.

{
  "task_keyword": "prediction|classification|anomaly_detection|timeseries|clustering|other",
  "target_kind": "numeric|categorical|timeseries|anomaly|unknown",
  "audience": "executive|practitioner|analyst|unknown",
  "deadline": "week|month|immediate|unknown",
  "free_form": "<original intent or inference rationale>"
}

Output only JSON. No markdown fences."""


class IntentElicitorAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            user_text = (state.user_intent or state.user_question or "").strip()

            if user_text:
                llm_prompt = user_text
            else:
                # No user input -> LLM infers from state context
                self.logger.info(
                    "intent_inferred_from_state",
                    category=state.category,
                    task=state.task,
                    target_column=state.target_column,
                )
                llm_prompt = (
                    "No user intent was provided. "
                    "Infer the analysis intent from the data context below and fill in the JSON.\n"
                    f"category: {state.category}\n"
                    f"task: {state.task or 'auto'}\n"
                    f"target_column: {state.target_column or 'none'}"
                )

            try:
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=llm_prompt,
                    max_tokens=600,
                    temperature=0.0,
                    json_mode=True,
                )
                spec = self._parse_json(raw)
                if not user_text:
                    spec["free_form"] = ""
            except Exception as e:
                self.logger.warning("intent_parse_fallback", error=str(e))
                spec = {
                    "task_keyword": "unknown",
                    "target_kind": "unknown",
                    "audience": "unknown",
                    "deadline": "unknown",
                    "free_form": user_text,
                }

            gate_responses = dict(state.gate_responses)
            gate_responses["G0"] = {"intent_spec": spec}
            return state.with_update(
                gate_responses=gate_responses,
                current_gate="G0",
                next_agent="data_profiler",
            )

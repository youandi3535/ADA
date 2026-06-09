"""agents.intent_elicitor -- IntentElicitorAgent (Day05 v2 / G1 gate)."""

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


# HJ 2026-06-09 -- G1 short: category -> task_keyword direct mapping (no LLM).
_CATEGORY_TO_TASK_KEYWORD: dict[str, str] = {
    "tabular_ml": "prediction",
    "tabular_dl": "prediction",
    "timeseries": "timeseries",
    "anomaly_detection": "anomaly_detection",
}

_TASK_TO_KEYWORD: dict[str, str] = {
    "classification": "classification",
    "regression": "prediction",
    "forecasting": "timeseries",
    "anomaly_detection": "anomaly_detection",
}


def _default_spec_from_state(state: PipelineState) -> dict:
    """Empty-input default — derive from category/task without LLM call.

    빈 입력 시 LLM 도 데이터 컨텍스트만 보고 답함. 룰과 동일 → LLM 1회(~40s) 절감.
    """
    keyword = _TASK_TO_KEYWORD.get(state.task or "") or _CATEGORY_TO_TASK_KEYWORD.get(state.category, "other")
    if state.category == "timeseries":
        target_kind = "timeseries"
    elif state.category == "anomaly_detection":
        target_kind = "anomaly"
    elif state.task == "classification":
        target_kind = "categorical"
    elif state.task == "regression":
        target_kind = "numeric"
    else:
        target_kind = "unknown"
    return {
        "task_keyword": keyword,
        "target_kind": target_kind,
        "audience": "unknown",
        "deadline": "unknown",
        "free_form": "",
    }


class IntentElicitorAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            user_text = (state.user_intent or state.user_question or "").strip()

            if not user_text:
                # HJ 2026-06-09 G1 short: empty input -> skip LLM, use rule default.
                self.logger.info(
                    "intent_default_no_llm",
                    category=state.category,
                    task=state.task,
                    target_column=state.target_column,
                )
                spec = _default_spec_from_state(state)
            else:
                try:
                    raw = await self._call_llm(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=user_text,
                        max_tokens=400,  # 600->400 (measured ~250t, margin 1.6x)
                        temperature=0.0,
                        json_mode=True,
                    )
                    spec = self._parse_json(raw)
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
            gate_responses["G1"] = {"intent_spec": spec}
            return state.with_update(
                gate_responses=gate_responses,
                current_gate="G1",
                next_agent="data_profiler",
            )

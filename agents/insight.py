"""agents.insight — Day 0 dispatcher 패턴.

카테고리별 프롬프트는 ``handlers/{cat}/insight.{prompt_payload,fallback}`` 사용.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import importlib
import json

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent

CATEGORY_TO_MODULE = {
    "timeseries": "agents.handlers.timeseries.insight",
    "anomaly_detection": "agents.handlers.anomaly.insight",
    "tabular_ml": "agents.handlers.tabular.insight",
    "tabular_dl": "agents.handlers.tabular.insight",
}


class InsightAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-opus-4-7"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            mod_name = CATEGORY_TO_MODULE.get(state.category)
            text: str = ""
            try:
                mod = importlib.import_module(mod_name) if mod_name else None
                system_prompt = getattr(mod, "SYSTEM_PROMPT", "한국어 3~5문장으로 인사이트.")
                payload_fn = getattr(mod, "prompt_payload", None)
                fallback_fn = getattr(mod, "fallback", None)

                payload = payload_fn(state) if callable(payload_fn) else {"category": state.category}

                try:
                    text = await self._call_llm(
                        system_prompt=system_prompt,
                        user_prompt=json.dumps(payload, ensure_ascii=False)[:4500],
                        max_tokens=600,
                        temperature=0.4,
                    )
                except Exception as e:
                    self.logger.warning("insight_llm_failed", error=str(e))
                    if callable(fallback_fn):
                        text = fallback_fn(state)
            except Exception as e:
                self.logger.warning("insight_handler_missing", error=str(e))

            if not text:
                text = "이번 분석 결과는 추가 검토가 필요합니다."

            return state.with_update(insights=text.strip(), next_agent="gate_outputs")

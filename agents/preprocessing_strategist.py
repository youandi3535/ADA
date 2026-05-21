"""agents.preprocessing_strategist — Day 0 dispatcher 패턴.

LLM 으로 plan 시도 → 실패 시 ``handlers/{cat}/preprocessor.plan()`` fallback.
수정 권한: **HJ 단독** (dispatcher).
"""
from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
import agents.handlers.timeseries  # noqa: F401
import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401

SYSTEM_PROMPT = """당신은 시니어 데이터 엔지니어로서 데이터 프로파일을 보고
전처리 단계를 JSON 으로 설계합니다.

응답:
{
  "steps": [
    {"name": "impute_numeric", "strategy": "median", "needs_review": false},
    ...
  ],
  "rationale": "한국어 1문장",
  "leakage_risks": []
}
"""


class PreprocessingStrategistAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            plan: list[dict[str, Any]] = []

            try:
                payload = {
                    "category": state.category,
                    "data_profile": state.data_profile,
                    "target_column": state.target_column,
                }
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(payload, ensure_ascii=False)[:4000],
                    max_tokens=800,
                    temperature=0.1,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                plan = parsed.get("steps") or []
            except Exception as e:
                self.logger.warning("preprocess_llm_fallback", error=str(e))

            if not plan:
                handler = get_handler(state.category, "plan")
                if handler is not None:
                    try:
                        plan = handler(state) or []
                    except Exception as e:
                        self.logger.warning("preprocess_handler_failed",
                                            category=state.category, error=str(e))

            return state.with_update(preprocessing_plan=plan,
                                     next_agent="feature_engineer")

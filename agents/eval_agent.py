"""agents.eval_agent — Day 0 dispatcher 패턴.

카테고리별 임계치는 ``handlers/{cat}/evaluator.evaluate(state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import json
from typing import Any

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler

SYSTEM_PROMPT = """당신은 QA 평가관입니다. best_model.metrics + eval_result 를 보고
모델 출시 가능성을 JSON 으로 종합 판단합니다.

{"passed": true, "rationale": "한국어 1~2문장", "threshold_violations": [...]}
"""


class EvalAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-opus-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # 1) 카테고리 핸들러로 임계치 판정
            eval_result: dict[str, Any] = {
                "passed": True,
                "rationale": "기본 통과",
                "threshold_violations": [],
                "metrics": {},
            }
            handler = get_handler(state.category, "evaluate")
            if handler is not None:
                try:
                    eval_result = handler(state) or eval_result
                except Exception as e:
                    self.logger.warning("evaluator_handler_failed", category=state.category, error=str(e))

            # 2) LLM 종합 판정 (선택)
            try:
                payload = {
                    "best_model": state.best_model,
                    "eda_summary": state.eda_summary,
                    "training_warnings": state.training_warnings,
                    "category": state.category,
                    "rule_eval": eval_result,
                }
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(payload, ensure_ascii=False)[:2500],
                    max_tokens=400,
                    temperature=0.0,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                if "passed" in parsed:
                    eval_result["passed"] = bool(parsed["passed"])
                    eval_result["rationale"] = parsed.get("rationale", eval_result["rationale"])
                    eval_result["threshold_violations"] = parsed.get(
                        "threshold_violations",
                        eval_result["threshold_violations"],
                    )
            except Exception as e:
                self.logger.warning("eval_llm_skip", error=str(e))

            # 3) 분기
            if eval_result["passed"]:
                return state.with_update(eval_result=eval_result, next_agent="explainability")
            new_re_loop = state.re_loop_count + 1
            if new_re_loop <= state.max_re_loop:
                return state.with_update(
                    eval_result=eval_result, re_loop_count=new_re_loop, next_agent="training_executor"
                )
            return state.with_update(
                eval_result=eval_result, error="평가 임계치 미달 + 재루프 한도 도달", next_agent="error_recovery"
            )

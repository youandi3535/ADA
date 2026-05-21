"""agents.eval_agent — EvalAgent (Day11).

임계치 룰 + LLM 판단 결합. passed=False 면 재루프 가능 (R-505 cap=2).
"""
from __future__ import annotations

import json

from ada.core.state import PipelineState
from agents.base import BaseAgent

THRESHOLDS = {
    "tabular_ml":         {"val_f1": 0.65, "val_accuracy": 0.70},
    "tabular_dl":         {"val_f1": 0.70},
    "timeseries":         {},  # rmse 는 도메인 의존이라 LLM 만 사용
    "anomaly_detection":  {"val_auc": 0.70},
}

SYSTEM_PROMPT = """당신은 모델 출시 가능성을 판정하는 QA 평가관입니다.
입력: best_model.metrics, eda_summary, training_warnings
응답 JSON:
{
  "passed": true,
  "rationale": "한국어 1~2문장",
  "threshold_violations": ["val_f1<0.7" ...]
}
"""


class EvalAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-opus-4-7"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            best = state.best_model or {}
            metrics = best.get("metrics") or {}

            # 1) 임계치 룰
            violations: list[str] = []
            for k, thr in THRESHOLDS.get(state.category, {}).items():
                v = metrics.get(k)
                if v is not None and float(v) < thr:
                    violations.append(f"{k}<{thr} (got {v:.3f})")

            passed = len(violations) == 0
            rationale = "임계치 통과" if passed else "; ".join(violations)

            # 2) LLM 종합 판정 (선택)
            try:
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps({
                        "best_model": best,
                        "eda_summary": state.eda_summary,
                        "training_warnings": state.training_warnings,
                        "category": state.category,
                    }, ensure_ascii=False)[:2500],
                    max_tokens=400,
                    temperature=0.0,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                if "passed" in parsed:
                    passed = bool(parsed["passed"])
                    rationale = parsed.get("rationale", rationale)
                    violations = parsed.get("threshold_violations", violations)
            except Exception as e:
                self.logger.warning("eval_llm_skip", error=str(e))

            eval_result = {
                "passed": passed,
                "rationale": rationale,
                "threshold_violations": violations,
                "metrics": metrics,
            }
            if passed:
                return state.with_update(eval_result=eval_result, next_agent="explainability")
            new_re_loop = state.re_loop_count + 1
            if new_re_loop <= state.max_re_loop:
                return state.with_update(eval_result=eval_result,
                                         re_loop_count=new_re_loop,
                                         next_agent="training_executor")
            return state.with_update(eval_result=eval_result,
                                     error="평가 임계치 미달 + 재루프 한도 도달",
                                     next_agent="error_recovery")

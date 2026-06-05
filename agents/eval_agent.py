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
                new_state = state.with_update(eval_result=eval_result, next_agent="explainability")
            else:
                new_re_loop = state.re_loop_count + 1
                if new_re_loop <= state.max_re_loop:
                    new_state = state.with_update(
                        eval_result=eval_result,
                        re_loop_count=new_re_loop,
                        next_agent="training_executor",
                    )
                else:
                    new_state = state.with_update(
                        eval_result=eval_result,
                        error="평가 임계치 미달 + 재루프 한도 도달",
                        next_agent="error_recovery",
                    )

            # Phase 1.4 — ReportContext ⑧ evaluation + ⑩ limitations 적립.
            try:
                new_state = _contribute_evaluation_and_limitations(self, new_state, eval_result)
            except Exception as e:  # noqa: BLE001
                self.logger.warning("contribute_eval_failed", error=str(e))
            return new_state


# ==============================================================
# Phase 1.4 — ReportContext 적립 헬퍼 (module-level)
# ==============================================================


def _contribute_evaluation_and_limitations(agent: Any, state: Any, eval_result: dict[str, Any]) -> Any:
    """eval_result + best_model.metrics → evaluation + limitations 적립.

    primary_metric 은 best_model.metrics 의 첫 항목 또는 카테고리 기본 후보로 추정.
    BusinessImpactQuantifier (Phase 2) 가 business_kpi 를 나중에 보강.
    """
    bm = getattr(state, "best_model", None) or {}
    metrics_raw = bm.get("metrics") or {}

    metrics_normalized: dict[str, dict[str, Any]] = {}
    for name, value in metrics_raw.items():
        if isinstance(value, (int, float)):
            metrics_normalized[str(name)] = {"value": float(value)}
        elif isinstance(value, dict):
            metrics_normalized[str(name)] = {**value}
        else:
            metrics_normalized[str(name)] = {"value": value}

    # primary_metric — 카테고리 친화 후보 우선
    category = getattr(state, "category", "") or ""
    preferred = {
        "tabular_ml": ["auc", "roc_auc", "f1", "accuracy", "rmse", "mae"],
        "tabular_dl": ["auc", "f1", "accuracy", "rmse"],
        "timeseries": ["smape", "mape", "rmse", "mae"],
        "anomaly_detection": ["pr_auc", "f1", "precision", "recall"],
    }.get(category, [])
    primary_name = next((p for p in preferred if p in metrics_normalized), None)
    if not primary_name and metrics_normalized:
        primary_name = next(iter(metrics_normalized))

    primary_payload: dict[str, Any] = {}
    if primary_name:
        primary_payload = {
            "name": primary_name,
            "value": metrics_normalized[primary_name].get("value"),
            "direction": "lower_better"
            if any(t in primary_name.lower() for t in ("rmse", "mae", "mape", "smape", "loss"))
            else "higher_better",
        }

    evaluation_payload: dict[str, Any] = {
        "primary_metric": primary_payload,
        "metrics": metrics_normalized,
        "gate_passed": bool(eval_result.get("passed", False)),
        "gate_rationale": str(eval_result.get("rationale", "")),
    }
    new_state = agent.contribute_to_context(state, "evaluation", evaluation_payload)

    # ⑩ limitations — threshold_violations 를 model_caveats 로 매핑.
    violations = eval_result.get("threshold_violations") or []
    if violations:
        caveats = [str(v) for v in violations if v]
        new_state = agent.contribute_to_context(
            new_state,
            "limitations",
            {"model_caveats": caveats},
        )
    return new_state

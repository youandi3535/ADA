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


# HJ 2026-06-11 — G5 모달 라이브 피드용. eda_agent.py 패턴 동일.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


SYSTEM_PROMPT = """당신은 QA 평가관입니다. best_model.metrics + eval_result 를 보고
모델 출시 가능성을 JSON 으로 종합 판단합니다.

{"passed": true, "rationale": "한국어 1~2문장", "threshold_violations": [...]}
"""


class EvalAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-opus-4-6"
    use_anthropic_api = True

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # HJ 2026-06-11 — G5 모달 라이브 피드: eval 시작 즉시 status publish.
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g5_phase": "eval_start",
                    "g5_status": f"모델 '{(state.best_model or {}).get('model_name', '미정')}' 평가 중…",
                },
            )

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

            # HJ 2026-06-11 — G5 모달 라이브 피드: 평가 결과 자연어 인사이트 publish.
            # G2 의 eda_insights 패턴 — passed/메트릭/rationale/violations 자연어로.
            try:
                _g5_eval_insights: list[str] = []
                bm_name = (state.best_model or {}).get("model_name", "?")
                passed_txt = "✓ 통과" if eval_result.get("passed") else "✗ 미달"
                _g5_eval_insights.append(f"평가 결과: {bm_name} → {passed_txt}")
                metrics = eval_result.get("metrics") or {}
                if metrics:
                    _m_pairs = []
                    for k in list(metrics.keys())[:5]:
                        v = metrics[k]
                        try:
                            _m_pairs.append(f"{k}={float(v):.3f}")
                        except (TypeError, ValueError):
                            _m_pairs.append(f"{k}={v}")
                    _g5_eval_insights.append(f"평가 메트릭: {', '.join(_m_pairs)}")
                rt = str(eval_result.get("rationale") or "").strip()
                if rt:
                    _g5_eval_insights.append(f"평가 요약: {rt[:200]}")
                violations = eval_result.get("threshold_violations") or []
                if violations:
                    _vs = [str(v)[:100] for v in violations[:3]]
                    _g5_eval_insights.append(f"임계치 미달: {' / '.join(_vs)}")
                _g5_eval_insights = await self._dynamic_insights(
                    _g5_eval_insights,
                    backend="claude",
                    context="G5 평가",
                    job_id=state.job_id,
                    key="g5_eval_insights",
                )
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g5_phase": "eval_done",
                        "g5_status": f"평가 완료 — {bm_name} {passed_txt}",
                        "g5_eval_insights": _g5_eval_insights,
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("g5_eval_insights_publish_failed", error=str(e))

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

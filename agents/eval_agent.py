"""agents.eval_agent — Day 0 dispatcher 패턴.

카테고리별 임계치는 ``handlers/{cat}/evaluator.evaluate(state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import asyncio
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


async def _consume_explain_task(task: Any) -> dict[str, Any] | None:
    """③ eval 병렬 선계산 explainability task 회수.

    실패·예외 시 None 반환 → explainability 노드가 정상적으로 재계산하므로 무손실.
    """
    if task is None:
        return None
    try:
        result = await task
        return result if isinstance(result, dict) and result else None
    except Exception:  # noqa: BLE001
        return None


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

            # HJ 2026-06-14 — ③ explainability(SHAP, CPU)를 eval LLM(I/O)과 병렬 선계산.
            #   to_thread 기반이라 eval 의 LLM 대기시간에 SHAP 가 겹쳐 ~30s 절감(결과 비트 동일).
            #   passed/한도도달 → explainability 노드가 결과 재사용(재계산 스킵, publish 는 유지).
            #   재시도(미달) → task.cancel() 로 폐기(다음 best_model 로 재계산).
            explain_task = None
            try:
                if state.best_model:
                    from agents.explainability import ExplainabilityAgent  # noqa: WPS433

                    explain_task = asyncio.create_task(ExplainabilityAgent()._compute_artifacts(state))
            except Exception:  # noqa: BLE001
                explain_task = None

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
                # HJ 2026-06-14 — 사용자 지시: LLM 은 '설명(rationale)'만. passed/violations(재시도를
                #   유발하는 판정)은 규칙 기반(handler)으로 고정한다. 비결정적 LLM 이 규칙 통과를
                #   미통과로 뒤집어 4·5단계가 끝없이 재시도(롤백)되던 문제를 제거한다.
                _llm_comment = str(parsed.get("rationale") or "").strip()
                if _llm_comment:
                    eval_result["llm_comment"] = _llm_comment
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
                # HJ 2026-06-14 — 사용자 지시: 임계치는 고정값이 아니라 데이터·카테고리 적응형.
                #   적응형 임계값과 지표 충족 여부(✓/✗)·산출 근거를 모달에 함께 표시해 비교 가능하게 한다.
                _thr = eval_result.get("thresholds") or {}
                if _thr:
                    _t_pairs = []
                    for _tk, _tv in list(_thr.items())[:5]:
                        try:
                            _mv = metrics.get(_tk)
                            _ok = "✓" if (_mv is not None and float(_mv) >= float(_tv)) else "✗"
                            _t_pairs.append(f"{_tk}≥{float(_tv):.3f} {_ok}")
                        except (TypeError, ValueError):
                            _t_pairs.append(f"{_tk}≥{_tv}")
                    _g5_eval_insights.append(f"적응형 임계: {', '.join(_t_pairs)}")
                _thr_basis = str(eval_result.get("threshold_basis") or "").strip()
                if _thr_basis:
                    _g5_eval_insights.append(f"임계 기준: {_thr_basis[:160]}")
                rt = str(eval_result.get("rationale") or "").strip()
                if rt:
                    _g5_eval_insights.append(f"평가 요약: {rt[:200]}")
                violations = eval_result.get("threshold_violations") or []
                if violations:
                    _vs = [str(v)[:100] for v in violations[:3]]
                    _g5_eval_insights.append(f"임계치 미달: {' / '.join(_vs)}")
                # HJ 2026-06-13 — 윤색(규칙 기반 사실에 해석 한 문장)은 단순 작업이라 Ollama 로 전환
                #   (Claude 토큰 절약) + 백그라운드로(critical path 제거). 핵심 평가 판정·rationale 은
                #   EvalAgent 본 LLM(Claude)이 이미 생성했고, 윤색은 publish 전용(state 무관)이라 품질 무영향.
                self._spawn_insight_polish(
                    list(_g5_eval_insights),
                    backend="ollama",
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

            # 3) 분기 — HJ 2026-06-12 계층적 3단계 무인 자동 재시도.
            #   1차 HP재튜닝 / 2차 피처재구성 / 3차 전처리재검토. 경로상 게이트는
            #   BaseGate 가 re_loop_count>0 동안 current_gate=None 으로 자동통과.
            _RELOOP_ENTRY = {
                1: "hyperparameter_tuner",
                2: "feature_engineer",
                3: "preprocessing_strategist",
            }
            # HJ 2026-06-13 — baseline 이김 판정은 4단계(metrics_aggregator)로 이전. 5단계는 임계점(passed)만 본다.
            # HJ 2026-06-13 — 롤백(무인 자동 재시도) 진행 상태를 모달에 발행. 사용자가 "왜 오래
            #   걸리는지" 인지하도록 1·2·3차 롤백 단계·사유를 알린다. 통과/종료 시 active=False.
            _TIER_DESC = {
                1: "1차 롤백 · 하이퍼파라미터 재튜닝",
                2: "2차 롤백 · 피처 재구성",
                3: "3차 롤백 · 전처리 재검토",
            }

            def _publish_rollback(active: bool, tier: int = 0, desc: str = "", entry: str = "") -> None:
                # HJ 2026-06-13 — 통합 롤백 배너 스키마(4·5단계 공용). 우하단 빨강 박스에 단계·차수·사유·예상시간.
                _viol = eval_result.get("threshold_violations") or []
                _eta = {"hyperparameter_tuner": 240, "feature_engineer": 300, "preprocessing_strategist": 360}.get(
                    entry, 240
                )
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "rollback_active": bool(active),
                        "rollback_stage": 5,
                        "rollback_tier": int(tier),
                        "rollback_max": int(state.max_re_loop),
                        "rollback_desc": desc,
                        "rollback_reason": (str(_viol[0])[:120] if _viol else "평가 임계 성능 미달"),
                        "rollback_eta_sec": int(_eta) if active else 0,
                    },
                )

            if eval_result["passed"]:
                # HJ 2026-06-13 — 통과 시 re_loop_count 리셋(중요). 안 하면 이후 gate_outputs(G6)가
                #   _base_gate 의 re_loop_count>0 자동통과 분기에 걸려 산출물 선택을 안 띄우고 G7 로
                #   점프(G6 건너뜀)한다. 통과=정상 전진이므로 0 으로 되돌려 G6 가 정상 인터럽트되게 한다.
                # HJ 2026-06-14 — ③ 병렬 선계산한 SHAP 회수해 explainability 노드가 재사용하게 전달.
                _exp = await _consume_explain_task(explain_task)
                _u: dict[str, Any] = {"eval_result": eval_result, "re_loop_count": 0, "next_agent": "explainability"}
                if _exp:
                    _u["explanations"] = _exp
                new_state = state.with_update(**_u)
                _publish_rollback(False)
            else:
                new_re_loop = state.re_loop_count + 1
                entry = _RELOOP_ENTRY.get(new_re_loop)
                if new_re_loop <= state.max_re_loop and entry is not None:
                    # 재시도: passed 미달 또는 baseline 미달 → 1차 HP재튜닝 / 2차 피처재구성 / 3차 전처리재검토.
                    #   누수 안전: feature_engineer 재실행도 leakage_safe_split(train fit→val transform) 경로 유지.
                    # HJ 2026-06-14 — ③ 재시도 경로는 선계산 SHAP 폐기(다음 best_model 로 재계산).
                    if explain_task is not None:
                        explain_task.cancel()
                    new_state = state.with_update(
                        eval_result=eval_result,
                        re_loop_count=new_re_loop,
                        next_agent=entry,
                    )
                    _publish_rollback(True, new_re_loop, _TIER_DESC.get(new_re_loop, f"{new_re_loop}차 롤백"), entry)
                else:
                    # 한도 도달 — 마지막 best 로 진행 (re_loop_count 리셋 → G6 정상 인터럽트, 자동통과 방지).
                    # HJ 2026-06-14 — ③ explainability 진행 → 선계산 결과 재사용.
                    _exp2 = await _consume_explain_task(explain_task)
                    _u2: dict[str, Any] = {
                        "eval_result": eval_result,
                        "re_loop_count": 0,
                        "next_agent": "explainability",
                    }
                    if _exp2:
                        _u2["explanations"] = _exp2
                    new_state = state.with_update(**_u2)
                    _publish_rollback(False)

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

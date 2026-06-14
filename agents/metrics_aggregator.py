"""agents.metrics_aggregator — MetricsAggregatorAgent (Day08).

후보별 메트릭 정규화 후 best_model 선정.
classification : val_f1 최대
regression     : val_r2 최대
forecasting    : val_rmse 최소
anomaly        : val_auc 최대
"""

from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

CATEGORY_OBJECTIVE = {
    "tabular_ml": ("val_f1", "max"),
    "tabular_dl": ("val_f1", "max"),
    "timeseries": ("val_rmse", "min"),
    "anomaly_detection": ("val_auc", "max"),
}


# HJ 2026-06-13 — 4단계 baseline 리루프 진행 상태 발행(우하단 빨강 배너). eval_agent(5단계)와 동일
#   통합 스키마(rollback_*). frontend updateRollbackBanner 가 단계·차수·사유·예상시간을 표시.
def _safe_publish_stage_partial(job_id, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


class MetricsAggregatorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            metric_key, direction = CATEGORY_OBJECTIVE.get(state.category, ("val_f1", "max"))
            # HJ 2026-06-13 — best_model 선정에서 baseline(Dummy/LR/Ridge 등) 제외.
            #   baseline 은 비교용(improvement_over_baseline)이지 추천 대상이 아니다. baseline 이
            #   metric 1등이어도 추천되면 (1) 무의미하고 (2) "모델이 기준선조차 못 이김"이라는
            #   경고 신호를 가린다 → 진짜 모델 중에서만 best 를 고른다.
            _cat_key = "tabular" if state.category.startswith("tabular") else state.category
            _extras = (getattr(state, "category_extras", None) or {}).get(_cat_key, {})
            _baseline_names = {str(n) for n in (_extras.get("baseline_model_names") or [])}
            scored: list[tuple[float, dict[str, Any]]] = []
            for m in state.trained_models:
                if m.get("model_name") in _baseline_names:
                    continue  # baseline 은 best 후보에서 제외 (비교용으로만 trained 에 존재)
                v = (m.get("metrics") or {}).get(metric_key)
                if v is None:
                    continue
                scored.append((float(v), m))
            if not scored:
                return state.with_update(
                    error=f"no non-baseline model scored {metric_key}",
                    next_agent="error_recovery",
                )
            scored.sort(key=lambda x: x[0], reverse=(direction == "max"))
            best = dict(scored[0][1])
            best["is_best"] = True
            best["objective_metric"] = metric_key
            best["objective_value"] = scored[0][0]
            _best_val = scored[0][0]

            # HJ 2026-06-13 — 4단계 baseline 리루프(5단계 임계점 re_loop 와 별개, 별도 카운터).
            #   진짜 best 가 기준선(Dummy 등)조차 못 이기면 → 전처리부터 자동 재시도(매 회차 preprocessing_strategist).
            #   화면 유지: 재시도 중 BaseGate 가 baseline_re_loop_count>0 로 게이트 자동통과(current_gate=None)
            #     → frontend frontier=maxReached 유지 → cur 고정(이전 단계·팝업으로 안 돌아감).
            #   누수 안전: preprocessing→feature 재실행도 leakage_safe_split(train fit→val transform) 유지.
            # HJ 2026-06-14 — 사용자 지시: 4단계 재시도 판정은 '가장 센 베이스라인(LR/Ridge)'이 아니라
            #   Dummy(naive 바닥) 기준. 모델이 Dummy 만 이기면 재시도하지 않는다 — LR/Ridge 가 더 좋은
            #   데이터는 재학습해도 영영 못 넘어 무한 롤백되던 문제(베이스라인보다 높은데도 재시도) 해결.
            #   LR/Ridge 대비 격차·통계적 유의성은 evaluator/insight 가 별도 '참고'로 보고(재학습 유발 X).
            _bl_vals = [
                float((m.get("metrics") or {}).get(metric_key))
                for m in state.trained_models
                if str(m.get("model_name", "")).lower().startswith("dummy")
                and (m.get("metrics") or {}).get(metric_key) is not None
            ]
            #   이미 사용자가 "계속 진행"을 수락한 상태(baseline_not_beaten=True)면 재판정하지 않는다
            #   — 5단계 re_loop 로 metrics 가 다시 와도 baseline 리루프를 또 돌리지 않도록(수락 존중).
            _clear_rollback = {"rollback_active": False, "rollback_eta_sec": 0}
            if _bl_vals and not state.baseline_not_beaten:
                _bl_best = max(_bl_vals) if direction == "max" else min(_bl_vals)
                _beat = (_best_val > _bl_best) if direction == "max" else (_best_val < _bl_best)
                if not _beat:
                    _nb = state.baseline_re_loop_count + 1
                    if _nb <= state.max_baseline_re_loop:
                        # HJ 2026-06-13 — 4단계 자동 리루프 진행 상태 발행(우하단 빨강 배너, 통합 스키마).
                        #   사용자에게 "왜·몇 차·예상 추가시간"을 알린다(선택 아님, 자동 재시도).
                        _safe_publish_stage_partial(
                            state.job_id,
                            {
                                "rollback_active": True,
                                "rollback_stage": 4,
                                "rollback_tier": _nb,
                                "rollback_max": int(state.max_baseline_re_loop),
                                "rollback_desc": "전처리부터 전체 재구성 (모델 학습 재시도)",
                                "rollback_reason": (
                                    f"최고 모델이 기준선(Dummy)을 못 이김 "
                                    f"({metric_key}: 모델 {_best_val:.3f} vs 기준 {_bl_best:.3f})"
                                ),
                                "rollback_eta_sec": 360,
                            },
                        )
                        return state.with_update(
                            best_model=best,
                            baseline_re_loop_count=_nb,
                            next_agent="preprocessing_strategist",
                        )
                    # HJ 2026-06-13 — 3회 소진 후에도 기준선 미달 → error 가 아니라 사용자 선택 팝업(G5).
                    #   baseline_not_beaten=True 로 표시하고 brl=0 리셋 후 gate_best_model 로 진행:
                    #   프론트가 G5 에서 "계속 진행(더미 제외 상위2 중 선택) / 처음으로" 팝업을 띄운다.
                    #   (error_recovery 전체 재시작이 아니라 사용자에게 결정권을 넘긴다.) 자동 리루프 종료 → 배너 끔.
                    _safe_publish_stage_partial(state.job_id, _clear_rollback)
                    return state.with_update(
                        best_model=best,
                        baseline_re_loop_count=0,
                        baseline_not_beaten=True,
                        next_agent="gate_best_model",
                    )
                # 진짜 모델이 baseline 이김 → 정상 진행 (플래그/카운터/배너 리셋).
                _safe_publish_stage_partial(state.job_id, _clear_rollback)
                return state.with_update(
                    best_model=best,
                    baseline_re_loop_count=0,
                    baseline_not_beaten=False,
                    next_agent="gate_best_model",
                )
            # baseline 정보 없음(DL/시계열 등) 또는 이미 "계속" 수락 — baseline_re_loop_count/배너 리셋 후 진행.
            #   (리셋 안 하면 직전 baseline 리루프 잔여 카운터로 gate_best_model 이 자동통과돼 5단계 스킵.)
            _safe_publish_stage_partial(state.job_id, _clear_rollback)
            return state.with_update(best_model=best, baseline_re_loop_count=0, next_agent="gate_best_model")

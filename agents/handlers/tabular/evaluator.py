"""agents.handlers.tabular.evaluator — 정형 평가 (jh 담당).

기본 임계: tabular_ml val_f1>=0.65, val_accuracy>=0.70. tabular_dl val_f1>=0.70.

Day 11 (jh) — 다음 3가지 보강:
  1. 베이스라인 격차 (improvement_over_baseline) — "강모델이 더미보다 얼마나 나은가"
  2. CV 통계 (cv_stats) — best_model 의 fold 평균·표준편차 노출 (신뢰구간)
  3. 격차의 통계적 유의성 (lift_significant) — lift > 2 * baseline_cv_std 면 의미있음

CV 평가는 비용을 고려해 다음 가드:
  - n_rows > 50000 → skip (대용량은 hold-out 으로 충분)
  - tabular_dl → skip (GPU 비용 큼)
  - pipeline.evaluate_with_cv 미존재 (다른 카테고리) → skip
"""

from __future__ import annotations

from typing import Any

# Day 11 (jh) — val_r2 임계 추가 (C4 해소). 회귀 task 에서 evaluator 게이트가
# 공허 통과하던 문제를 해결. Day10 test_e2e.py 가 직접 assert 하던 보호 장치를
# evaluator 본체로 흡수.
THRESHOLDS_BY_CAT = {
    "tabular_ml": {"val_f1": 0.55, "val_r2": 0.30},
    "tabular_dl": {"val_f1": 0.60},
}

# Day 11 (jh) — improvement_over_baseline 계산에 사용할 metric 우선순위.
# 분류는 val_f1 우선, 회귀는 val_r2 우선.
_BASELINE_COMPARE_METRICS = ("val_f1", "val_accuracy", "val_r2")

# Day 11 (jh) — CV 평가 가드. 큰 데이터는 hold-out 으로 충분, CV 비용 폭주 방지.
_CV_MAX_ROWS = 50_000
_CV_N_SPLITS = 5
# 격차가 baseline_std 의 몇 배 이상이면 통계적으로 유의로 표시 (rule-of-thumb)
_SIGNIFICANCE_THRESHOLD_K = 2.0


def _baseline_names(state: Any) -> list[str]:
    """state.category_extras 에서 baseline 모델 이름 조회.

    ModelSelectionAgent 가 selector.score 의 baselines 키를 받아 적립.
    """
    cat_key = "tabular" if state.category.startswith("tabular") else state.category
    extras = (getattr(state, "category_extras", None) or {}).get(cat_key, {})
    names = extras.get("baseline_model_names") or []
    return [str(n) for n in names]


def _find_baseline_metrics(state: Any) -> dict[str, Any]:
    """trained_models 에서 baseline 모델 중 가장 좋은 점수 1개 선택.

    baseline 후보가 여럿이면(Dummy + LogisticRegression 등), val_f1/val_r2 기준
    더 강한 baseline 선택 → "강 baseline 대비 격차" 라는 보수적 표현이 됨.
    """
    baselines = _baseline_names(state)
    if not baselines:
        return {}
    trained = getattr(state, "trained_models", None) or []
    candidates = [
        (m.get("model_name"), (m.get("metrics") or {}))
        for m in trained
        if m.get("model_name") in baselines
    ]
    if not candidates:
        return {}
    # 가장 좋은 baseline 선택 (val_f1 → val_accuracy → val_r2 순)
    def _key(item: tuple[str, dict]) -> float:
        _, mtr = item
        for k in _BASELINE_COMPARE_METRICS:
            v = mtr.get(k)
            if v is not None:
                return float(v)
        return float("-inf")

    name, metrics = max(candidates, key=_key)
    return {"name": name, "metrics": dict(metrics)}


def _compute_improvement(best_metrics: dict, baseline_metrics: dict) -> dict[str, Any]:
    """best vs baseline 격차 — metric 별 lift 와 대표 lift_primary 반환."""
    if not best_metrics or not baseline_metrics:
        return {}
    lift: dict[str, float] = {}
    for k in _BASELINE_COMPARE_METRICS:
        bv = best_metrics.get(k)
        bb = baseline_metrics.get(k)
        if bv is not None and bb is not None:
            try:
                lift[k] = round(float(bv) - float(bb), 4)
            except Exception:
                pass
    # 대표 lift: 분류는 val_f1, 회귀는 val_r2
    primary_metric = None
    primary_lift = None
    for k in ("val_f1", "val_r2", "val_accuracy"):
        if k in lift:
            primary_metric = k
            primary_lift = lift[k]
            break
    return {
        "lift_by_metric": lift,
        "primary_metric": primary_metric,
        "primary_lift": primary_lift,
    }


def _resolve_task_for_cv(state: Any) -> str:
    """state 기반 task 추정 — pipeline.evaluate 시그니처와 동일."""
    task = getattr(state, "task", "auto")
    if task in ("classification", "regression"):
        return task
    profile = state.data_profile or {}
    cd = profile.get("class_distribution") or {}
    if cd and len(cd) <= 50:
        return "classification"
    return "regression"


def _should_run_cv(state: Any) -> bool:
    """CV 가드 — 데이터 크면/DL/지원 안되면 skip.

    Day 11 (jh) 추가: state.trained_models 비어있으면 운영 흐름이 아닌
    단위/단발 테스트 시나리오로 간주 → skip (CV 비용 0). 운영에선
    training_executor 가 항상 trained_models 채우므로 영향 없음.
    """
    if state.category != "tabular_ml":
        return False
    n_rows = int((state.data_profile or {}).get("rows", 0))
    if n_rows > _CV_MAX_ROWS:
        return False
    # 운영 흐름이 아니면 (trained_models 비어있으면) CV skip
    trained = getattr(state, "trained_models", None) or []
    if not trained:
        return False
    return True


def _compute_cv_stats(state: Any, model_name: str, params: dict) -> dict[str, Any]:
    """주어진 모델을 CV 로 재평가 → fold 통계 반환.

    실패/예외 시 빈 dict (graceful). 운영 회귀 방지를 위해 모든 오류 catch.
    """
    if not _should_run_cv(state):
        return {}
    try:
        from agents.handlers.common.shared import load_dataframe_from_state
        from agents.training_executor import _split_xy
        from pipelines.factory import PipelineFactory

        df = load_dataframe_from_state(state)
        X, y = _split_xy(df, state.target_column)
        if X is None or y is None or len(X) == 0:
            return {}

        pipeline = PipelineFactory.create(state.category)
        if not hasattr(pipeline, "evaluate_with_cv"):
            return {}

        task = _resolve_task_for_cv(state)
        return pipeline.evaluate_with_cv(
            X, y, model_name=model_name, params=params or {},
            n_splits=_CV_N_SPLITS, task=task,
        ) or {}
    except Exception:
        return {}


def _add_significance(improvement: dict, baseline_cv_std: float | None) -> dict:
    """lift 가 baseline_cv_std 의 K 배 이상이면 significant 마킹.

    baseline_cv_std 가 0 이거나 None 이면 'unknown' (판단 불가).
    """
    if not improvement:
        return improvement
    out = dict(improvement)
    lift = out.get("primary_lift")
    if lift is None:
        return out
    if baseline_cv_std is None or baseline_cv_std == 0:
        out["lift_significant"] = None  # 판단 불가
        out["baseline_cv_std"] = baseline_cv_std
        out["significance_threshold_k"] = _SIGNIFICANCE_THRESHOLD_K
        return out
    threshold = _SIGNIFICANCE_THRESHOLD_K * float(baseline_cv_std)
    out["lift_significant"] = bool(abs(float(lift)) >= threshold)
    out["baseline_cv_std"] = float(baseline_cv_std)
    out["significance_threshold_k"] = _SIGNIFICANCE_THRESHOLD_K
    return out


def evaluate(state: Any) -> dict[str, Any]:
    best = state.best_model or {}
    metrics = best.get("metrics") or {}
    thr = THRESHOLDS_BY_CAT.get(state.category, {})
    violations: list[str] = []
    for k, t in thr.items():
        v = metrics.get(k)
        if v is not None and float(v) < t:
            violations.append(f"{k}<{t} (got {v:.3f})")
    passed = len(violations) == 0

    # Day 11 (jh) — baseline 대비 격차 계산. baseline 미학습/누락 시 빈 dict.
    baseline = _find_baseline_metrics(state)
    improvement = _compute_improvement(metrics, baseline.get("metrics") or {})

    # Day 11 (jh) — CV 통계 + 통계적 유의성.
    # best_model 과 baseline 둘 다 CV 재평가 (가드 통과 시).
    cv_stats: dict[str, Any] = {}
    baseline_cv_stats: dict[str, Any] = {}
    best_name = best.get("model_name")
    best_params = best.get("params_used") or {}
    if best_name:
        cv_stats = _compute_cv_stats(state, best_name, best_params)
    baseline_name = baseline.get("name")
    if baseline_name:
        # baseline 은 기본값으로 학습 (params_used 가 없거나 빈 dict)
        baseline_cv_stats = _compute_cv_stats(state, baseline_name, {})

    # 통계적 유의성: baseline_cv_std 를 기준으로 lift 가 노이즈인지 판단.
    baseline_primary_std = baseline_cv_stats.get("primary_std") if baseline_cv_stats else None
    improvement = _add_significance(improvement, baseline_primary_std)

    result = {
        "passed": passed,
        "rationale": "임계치 통과" if passed else "; ".join(violations),
        "threshold_violations": violations,
        "metrics": metrics,
        "improvement_over_baseline": improvement,
        "baseline_used": baseline,
        "cv_stats": cv_stats,
        "baseline_cv_stats": baseline_cv_stats,
    }
    return result

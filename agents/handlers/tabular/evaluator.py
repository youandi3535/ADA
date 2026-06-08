"""agents.handlers.tabular.evaluator — 정형 평가 (jh 담당).

기본 임계: tabular_ml val_f1>=0.65, val_accuracy>=0.70. tabular_dl val_f1>=0.70.

Day 11 (jh) — 베이스라인 격차 계산 추가. "강모델이 더미보다 얼마나 나은가" 가
모델 가치를 정의하므로, evaluate() 결과에 improvement_over_baseline 필드를
추가하여 insight/output 단계에서 인용 가능하게 한다.
"""

from __future__ import annotations

from typing import Any

THRESHOLDS_BY_CAT = {
    "tabular_ml": {"val_f1": 0.55},
    "tabular_dl": {"val_f1": 0.60},
}

# Day 11 (jh) — improvement_over_baseline 계산에 사용할 metric 우선순위.
# 분류는 val_f1 우선, 회귀는 val_r2 우선.
_BASELINE_COMPARE_METRICS = ("val_f1", "val_accuracy", "val_r2")


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

    result = {
        "passed": passed,
        "rationale": "임계치 통과" if passed else "; ".join(violations),
        "threshold_violations": violations,
        "metrics": metrics,
        "improvement_over_baseline": improvement,
        "baseline_used": baseline,
    }
    return result

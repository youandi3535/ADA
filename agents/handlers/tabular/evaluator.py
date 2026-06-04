"""agents.handlers.tabular.evaluator — 정형 평가 (jh 담당).

기본 임계: tabular_ml val_f1>=0.65, val_accuracy>=0.70. tabular_dl val_f1>=0.70.
"""

from __future__ import annotations

from typing import Any

THRESHOLDS_BY_CAT = {
    "tabular_ml": {"val_f1": 0.55},
    "tabular_dl": {"val_f1": 0.60},
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
    return {
        "passed": passed,
        "rationale": "임계치 통과" if passed else "; ".join(violations),
        "threshold_violations": violations,
        "metrics": metrics,
    }

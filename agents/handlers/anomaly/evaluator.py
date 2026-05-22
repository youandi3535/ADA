"""agents.handlers.anomaly.evaluator — 이상탐지 평가 (NY 담당).

기본: val_auc 0.70 임계. Day 7 (NY): precision@k, F1, threshold sweep.
"""

from __future__ import annotations

from typing import Any

THRESHOLD = {"val_auc": 0.70}


def evaluate(state: Any) -> dict[str, Any]:
    best = state.best_model or {}
    metrics = best.get("metrics") or {}
    violations: list[str] = []
    for k, thr in THRESHOLD.items():
        v = metrics.get(k)
        if v is not None and float(v) < thr:
            violations.append(f"{k}<{thr} (got {v:.3f})")
    passed = len(violations) == 0
    return {
        "passed": passed,
        "rationale": "임계치 통과" if passed else "; ".join(violations),
        "threshold_violations": violations,
        "metrics": metrics,
    }

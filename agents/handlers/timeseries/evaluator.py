"""agents.handlers.timeseries.evaluator — 시계열 평가 (A 담당).

기본: val_rmse 임계치 없이 통과. Day 7 (A): naive baseline 대비 개선율, MASE/sMAPE.
"""
from __future__ import annotations

from typing import Any


def evaluate(state: Any) -> dict[str, Any]:
    best = state.best_model or {}
    metrics = best.get("metrics") or {}
    rmse = metrics.get("val_rmse")
    # 임시 — Day 7 에서 naive baseline 대비 개선율 추가 예정
    passed = rmse is not None
    rationale = ("RMSE 측정 완료" if passed
                 else "RMSE 메트릭 부재 — 학습 실패 가능성")
    return {
        "passed": passed,
        "rationale": rationale,
        "threshold_violations": [] if passed else ["val_rmse missing"],
        "metrics": metrics,
    }

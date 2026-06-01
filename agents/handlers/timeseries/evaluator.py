"""agents.handlers.timeseries.evaluator — 시계열 평가 (CS 담당, cs-day7 v2).

cs-day6 의 pipeline.evaluate 가 MASE/sMAPE/naïve/PI coverage 까지 모두 계산하여
metrics dict 에 포함. 본 evaluator 는 자매 카테고리 (anomaly · tabular) 와 동일 패턴
— 단순 임계치 판정만.

진입함수 (dispatcher 자동 등록):
  - evaluate(state) -> dict   반환: passed / rationale / threshold_violations / metrics

DoD: eval_result["metrics"]["rmse_improvement_vs_naive"] 필드
     (cs-day6 가 채움 → cs-day7 가 그대로 전달).

핵심 설계 원칙:
  - 자매 카테고리와 동일 시그니처/구조
  - 데이터 재로드 X — cs-day6 가 모든 메트릭 계산
  - 상대 임계치 — 절대 RMSE X · improvement + MASE 핵심
  - violations 누적 — 단일 violation 으로도 passed=False
  - None 안전 — MASE/sMAPE/cov 가 None 이면 임계치 skip
"""

from __future__ import annotations

from typing import Any

# ── 임계치 (시계열 특수성 — 상대값 위주) ──────────────────────────
THRESHOLDS = {
    "rmse_improvement_vs_naive_min": 0.0,  # > 0 통과 (naïve 보다 우수)
    "MASE_max": 1.0,  # < 1.0 통과 (in-sample naïve 보다 우수)
    "sMAPE_max": 30.0,  # < 30% 통과 (있을 때만)
    "pi_coverage_min": 0.90,  # ≥ 0.90 통과 (있을 때만)
}


def evaluate(state: Any) -> dict[str, Any]:
    """시계열 평가 — metrics 키 임계치 판정 (자매 카테고리 동일 패턴)."""
    # ── A-1 : best_model 존재 ──
    best = getattr(state, "best_model", None) or {}
    if not best or not isinstance(best, dict):
        return {
            "passed": False,
            "rationale": "no_best_model — cs-day6 모든 후보 실패",
            "threshold_violations": ["no_best_model"],
            "metrics": {},
        }

    # ── A-2 : metrics 추출 (빈 dict 여도 통과 — 임계치 판정 시 None 처리) ──
    metrics = best.get("metrics") or {}

    # ── B-1 : 메트릭 추출 ──
    violations: list[str] = []
    improvement = metrics.get("rmse_improvement_vs_naive")
    mase = metrics.get("MASE")
    smape = metrics.get("sMAPE")
    cov = metrics.get("pi_coverage")

    # ── B-2 : violations 누적 ──
    # improvement : None 도 violation (cs-day6 가 계산 실패)
    if improvement is None:
        violations.append("rmse_improvement_vs_naive missing")
    elif improvement <= THRESHOLDS["rmse_improvement_vs_naive_min"]:
        violations.append(
            f"rmse_improvement_vs_naive<={THRESHOLDS['rmse_improvement_vs_naive_min']} (got {improvement:.3f})"
        )

    # MASE : 있을 때만
    if mase is not None and mase >= THRESHOLDS["MASE_max"]:
        violations.append(f"MASE>={THRESHOLDS['MASE_max']} (got {mase:.3f})")

    # sMAPE : 있을 때만
    if smape is not None and smape > THRESHOLDS["sMAPE_max"]:
        violations.append(f"sMAPE>{THRESHOLDS['sMAPE_max']} (got {smape:.1f})")

    # pi_coverage : 있을 때만
    if cov is not None and cov < THRESHOLDS["pi_coverage_min"]:
        violations.append(f"pi_coverage<{THRESHOLDS['pi_coverage_min']} (got {cov:.3f})")

    # ── C-1 : 최종 반환 ──
    passed = len(violations) == 0
    rationale = "임계치 통과 (improvement > 0 · MASE < 1.0 · PI cov ≥ 0.90)" if passed else "; ".join(violations)
    return {
        "passed": passed,
        "rationale": rationale,
        "threshold_violations": violations,
        "metrics": metrics,  # cs-day6 의 모든 키 그대로 전달
    }

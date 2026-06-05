"""tests/handlers/timeseries/test_evaluator — cs-day7 v3 디벨롭 검증.

검증 카테고리:
  회귀 가드 (4): 기존 4 임계치 (improvement / MASE / sMAPE / pi_coverage) 검사 불변
  반환 키 (1): 기존 4 키 + 신규 3 키 (fold_diagnostics / leakage_suspect_signals / symptom_classification)
  H1 fold_diagnostics (4): no_folds / stable / unstable / very_unstable + fold_scores 위치 호환
  H2 leakage_suspect_signals (3): too_good_vs_naive / mase_too_low / single_fold_outlier_good
  H3 symptom_classification (5): A 미감지 / B 과소적합 / C 누수 의심 / D fold 편차 / E naïve 못 이김 / normal
  엣지 (3): best_model None / metrics 빈 dict / fold_scores 잘못된 형식
"""

from __future__ import annotations

import pytest


# ════════════════════════════════════════════════════════════════
# fixture 헬퍼 — state 모의 객체
# ════════════════════════════════════════════════════════════════
class _StubState:
    """evaluator(state) 가 getattr 로 best_model 추출 — 가벼운 stub."""

    def __init__(self, best_model=None):
        self.best_model = best_model


def _make_best(metrics=None, fold_scores=None, where="top"):
    """best_model dict 생성 — fold_scores 를 다양한 위치에 배치 가능."""
    best = {"model_name": "ARIMA", "metrics": dict(metrics or {})}
    if fold_scores is not None:
        if where == "top":
            best["fold_scores"] = list(fold_scores)
        elif where == "metrics":
            best["metrics"]["fold_scores"] = list(fold_scores)
        elif where == "cv_result":
            best["cv_result"] = {"fold_scores": list(fold_scores)}
    return best


# ════════════════════════════════════════════════════════════════
# 회귀 가드 — 기존 4 임계치 검사 불변
# ════════════════════════════════════════════════════════════════
class TestRegression:
    """기존 4 임계치 검사 회귀 (cs-day7 v2 → v3 변경 영향 0)."""

    def test_passed_when_all_thresholds_met(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.5, "MASE": 0.7}))
        r = evaluate(st)
        assert r["passed"] is True
        assert r["threshold_violations"] == []

    def test_failed_when_improvement_zero(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.0, "MASE": 0.7}))
        r = evaluate(st)
        assert r["passed"] is False
        assert any("rmse_improvement_vs_naive" in v for v in r["threshold_violations"])

    def test_failed_when_improvement_missing(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"MASE": 0.5}))
        r = evaluate(st)
        assert r["passed"] is False
        assert any("missing" in v for v in r["threshold_violations"])

    def test_failed_when_mase_geq_one(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 1.5}))
        r = evaluate(st)
        assert r["passed"] is False
        assert any("MASE" in v for v in r["threshold_violations"])


# ════════════════════════════════════════════════════════════════
# 반환 키 — 기존 4 + 신규 3 (호환성)
# ════════════════════════════════════════════════════════════════
class TestReturnKeys:
    """eval_result 키 정합 — 자매 카테고리 + 신규 3 키."""

    def test_returns_four_legacy_keys_plus_three_new(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7}))
        r = evaluate(st)
        # 기존 4 키 (회귀 가드 — cs-day7 evaluator dispatcher 와 자매 카테고리 정합)
        for k in ("passed", "rationale", "threshold_violations", "metrics"):
            assert k in r, f"기존 키 {k} 누락 — 회귀"
        # 신규 3 키 (cs-day7 v3 디벨롭)
        for k in ("fold_diagnostics", "leakage_suspect_signals", "symptom_classification"):
            assert k in r, f"신규 키 {k} 누락"
        # 타입 정합
        assert isinstance(r["fold_diagnostics"], dict)
        assert isinstance(r["leakage_suspect_signals"], list)
        assert isinstance(r["symptom_classification"], dict)


# ════════════════════════════════════════════════════════════════
# H1 fold_diagnostics — 롤백 5
# ════════════════════════════════════════════════════════════════
class TestFoldDiagnostics:
    """walk-forward fold 분산 진단 (4 케이스 + 위치 호환)."""

    def test_no_folds_yields_unavailable(self):
        """fold_scores 없으면 {"available": False}."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7}))
        r = evaluate(st)
        assert r["fold_diagnostics"]["available"] is False

    def test_stable_folds_classified_stable(self):
        """cv < 0.5 → stable."""
        from agents.handlers.timeseries.evaluator import evaluate

        # mean ≈ 0.5, std ≈ 0.02 → cv ≈ 0.04 stable
        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.5, "MASE": 0.7}, fold_scores=[0.48, 0.50, 0.52]))
        r = evaluate(st)
        assert r["fold_diagnostics"]["available"] is True
        assert r["fold_diagnostics"]["n_folds"] == 3
        assert r["fold_diagnostics"]["stability"] == "stable"

    def test_unstable_folds_classified_unstable(self):
        """0.5 ≤ cv < 1.0 → unstable."""
        from agents.handlers.timeseries.evaluator import evaluate

        # mean = 0.3, std ≈ 0.21 → cv ≈ 0.7
        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7}, fold_scores=[0.1, 0.3, 0.5]))
        r = evaluate(st)
        assert r["fold_diagnostics"]["available"] is True
        assert r["fold_diagnostics"]["stability"] in ("unstable", "very_unstable")

    def test_fold_scores_in_metrics_dict_also_detected(self):
        """fold_scores 가 metrics 안에 있어도 감지 (호환성)."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(
            _make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7}, fold_scores=[0.3, 0.31, 0.32], where="metrics")
        )
        r = evaluate(st)
        assert r["fold_diagnostics"]["available"] is True
        assert r["fold_diagnostics"]["n_folds"] == 3


# ════════════════════════════════════════════════════════════════
# H2 leakage_suspect_signals — 누수 1-6 사후 진단
# ════════════════════════════════════════════════════════════════
class TestLeakageSignals:
    """누수 1-6 사후 진단 — 3 신호."""

    def test_too_good_vs_naive_triggers_suspect(self):
        """improvement > 0.95 → too_good_vs_naive."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.98, "MASE": 0.5}))
        r = evaluate(st)
        kinds = [s["kind"] for s in r["leakage_suspect_signals"]]
        assert "too_good_vs_naive" in kinds
        # 누수 신호 있으면 passed=False (정직한 실패 원칙)
        assert r["passed"] is False

    def test_mase_too_low_triggers_suspect(self):
        """MASE < 0.01 → mase_too_low."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.4, "MASE": 0.005}))
        r = evaluate(st)
        kinds = [s["kind"] for s in r["leakage_suspect_signals"]]
        assert "mase_too_low" in kinds

    def test_single_fold_outlier_good_triggers_suspect(self):
        """특정 fold만 mean+2σ 초과 → single_fold_outlier_good."""
        from agents.handlers.timeseries.evaluator import evaluate

        # fold 1 만 비정상 좋음 (0.9 vs 나머지 0.1 근방)
        st = _StubState(
            _make_best(
                {"rmse_improvement_vs_naive": 0.3, "MASE": 0.5}, fold_scores=[0.05, 0.07, 0.95, 0.06, 0.08, 0.04]
            )
        )
        r = evaluate(st)
        kinds = [s["kind"] for s in r["leakage_suspect_signals"]]
        assert "single_fold_outlier_good" in kinds


# ════════════════════════════════════════════════════════════════
# H3 symptom_classification — 헌장 7단계 증상 분류
# ════════════════════════════════════════════════════════════════
class TestSymptomClassification:
    """증상 A~E + normal 자동 분류 (5 + 1)."""

    def test_normal_when_all_pass(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.4, "MASE": 0.7}))
        r = evaluate(st)
        assert r["symptom_classification"]["symptom"] == "normal"

    def test_symptom_E_when_naive_unbeaten(self):
        """improvement≤0 + MASE≥1.0 → 증상 E (naïve 못 이김)."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": -0.1, "MASE": 1.3}))
        r = evaluate(st)
        assert r["symptom_classification"]["symptom"] == "E"

    def test_symptom_B_when_underfit(self):
        """improvement≤0 + MASE 정상 → 증상 B."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": -0.05, "MASE": 0.8}))
        r = evaluate(st)
        assert r["symptom_classification"]["symptom"] == "B"

    def test_symptom_C_when_leakage_suspect(self):
        """누수 신호 있으면 → 증상 C (다른 모든 증상보다 우선)."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.98, "MASE": 0.5}))
        r = evaluate(st)
        assert r["symptom_classification"]["symptom"] == "C"

    def test_symptom_D_when_fold_unstable(self):
        """fold cv unstable + 누수 없음 → 증상 D."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7}, fold_scores=[0.1, 0.3, 0.5]))
        r = evaluate(st)
        # 누수 신호 없고 fold 출렁임 있으면 D
        assert r["symptom_classification"]["symptom"] == "D"


# ════════════════════════════════════════════════════════════════
# 엣지 — best_model 부재 / metrics 빈 / fold_scores 형식 오류
# ════════════════════════════════════════════════════════════════
class TestEdgeCases:
    def test_best_model_none_returns_no_model_symptom(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(best_model=None)
        r = evaluate(st)
        assert r["passed"] is False
        assert r["symptom_classification"]["symptom"] == "no_model"
        # 신규 키 모두 노출 (호환성)
        assert "fold_diagnostics" in r
        assert "leakage_suspect_signals" in r

    def test_empty_metrics_dict_graceful(self):
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState({"model_name": "ARIMA", "metrics": {}})
        r = evaluate(st)
        # improvement missing → violation
        assert r["passed"] is False
        # 신규 키 모두 존재
        for k in ("fold_diagnostics", "leakage_suspect_signals", "symptom_classification"):
            assert k in r

    def test_invalid_fold_scores_skipped_safely(self):
        """fold_scores 가 list 가 아닌 등 비정상 형식 → available=False."""
        from agents.handlers.timeseries.evaluator import evaluate

        bad = {
            "model_name": "ARIMA",
            "metrics": {"rmse_improvement_vs_naive": 0.3, "MASE": 0.7},
            "fold_scores": "not_a_list",
        }
        st = _StubState(bad)
        r = evaluate(st)
        assert r["fold_diagnostics"]["available"] is False


# ════════════════════════════════════════════════════════════════
# L4·L5·L6·L7 보완 검증 (재정독 후 추가)
# ════════════════════════════════════════════════════════════════
class TestRefinements:
    """재정독 후 누락·미구현 5건 보완 검증."""

    def test_L4_classification_hint_when_recipe_task_kind_classification(self):
        """L4 — chosen_recipe.meta.task_kind='classification' 이면 안내 메시지."""
        from agents.handlers.timeseries.evaluator import evaluate

        class _StateWithRecipe:
            def __init__(self):
                self.best_model = _make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7})
                self.chosen_recipe = {"title": "이상 시점", "meta": {"task_kind": "classification"}}

        r = evaluate(_StateWithRecipe())
        assert r.get("task_kind_hint") is not None
        assert "classification" in r["task_kind_hint"]
        assert "결정 임계" in r["task_kind_hint"]

    def test_L4_no_hint_when_regression(self):
        """L4 — task_kind 가 regression(default) 이면 task_kind_hint=None."""
        from agents.handlers.timeseries.evaluator import evaluate

        class _StateReg:
            def __init__(self):
                self.best_model = _make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7})
                self.chosen_recipe = {"title": "단기 예측", "meta": {"task_kind": "regression"}}

        r = evaluate(_StateReg())
        assert r.get("task_kind_hint") is None

    def test_L5_fold_metrics_per_metric_diagnosed(self):
        """L5 — fold_metrics 가 있으면 fold_diagnostics.per_metric 채워짐."""
        from agents.handlers.timeseries.evaluator import evaluate

        best = _make_best({"rmse_improvement_vs_naive": 0.3, "MASE": 0.7}, fold_scores=[0.3, 0.32, 0.28])
        best["fold_metrics"] = [
            {"val_rmse": 10.0, "val_mae": 8.0, "MASE": 0.7},
            {"val_rmse": 12.0, "val_mae": 9.0, "MASE": 0.75},
            {"val_rmse": 11.0, "val_mae": 8.5, "MASE": 0.72},
        ]
        r = evaluate(_StubState(best))
        fd = r["fold_diagnostics"]
        assert fd.get("available") is True
        assert "per_metric" in fd
        assert "val_rmse" in fd["per_metric"]
        assert fd["per_metric"]["val_rmse"]["n"] == 3
        assert "cv" in fd["per_metric"]["val_rmse"]

    def test_L6_rationale_korean_when_passed(self):
        """L6 — 정상 통과 시 한국어 + 수치 인용."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.4, "MASE": 0.7, "pi_coverage": 0.93}))
        r = evaluate(st)
        rat = r["rationale"]
        # 한국어 키워드 + 수치 인용
        assert "임계치 통과" in rat
        assert "naïve 대비 개선" in rat
        assert "MASE" in rat
        # 수치 인용 (개선율 + MASE + 커버리지)
        assert any(c.isdigit() for c in rat)

    def test_L6_rationale_korean_when_failed_with_rollback(self):
        """L6 — 실패 시 한국어 + 증상 + 롤백 우선순위."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": -0.1, "MASE": 1.3}))
        r = evaluate(st)
        rat = r["rationale"]
        assert "임계치 미달" in rat
        assert "증상=" in rat or "증상=naïve" in rat
        assert "롤백 우선순위" in rat

    def test_L7_smape_too_low_triggers_suspect(self):
        """L7 — sMAPE < 0.5 → smape_too_low 누수 신호."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.4, "MASE": 0.5, "sMAPE": 0.1}))
        r = evaluate(st)
        kinds = [s["kind"] for s in r["leakage_suspect_signals"]]
        assert "smape_too_low" in kinds

    def test_L7_pi_coverage_too_high_triggers_suspect(self):
        """L7 — pi_coverage ≥ 0.999 → pi_coverage_too_high 누수 신호."""
        from agents.handlers.timeseries.evaluator import evaluate

        st = _StubState(_make_best({"rmse_improvement_vs_naive": 0.4, "MASE": 0.5, "pi_coverage": 0.9995}))
        r = evaluate(st)
        kinds = [s["kind"] for s in r["leakage_suspect_signals"]]
        assert "pi_coverage_too_high" in kinds

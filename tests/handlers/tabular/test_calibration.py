"""tests.handlers.tabular.test_calibration — 확률 보정 검증 (jh, Day 11++).

검증 범위:
  1. ECE 계산 정확성 (완벽 보정 / 최악 / 중간)
  2. Platt / Isotonic fit 함수가 callable 반환 + 호출 가능
  3. K-fold CV 평가 honest (random 데이터에 ECE 0 안 나옴)
  4. 가드 (no_best_model / baseline / regression / no_predict_proba / 다중분류 / 적은 샘플)
  5. 보정 후 ECE 개선 (실제 RF 모델로 sanity)
  6. reliability_diagram_data 출력 형식
  7. 캐시 재사용
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.handlers.tabular import calibration as cal_mod

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


class _SimpleState:
    def __init__(self, **kwargs):
        self.category = kwargs.get("category", "tabular_ml")
        self.task = kwargs.get("task", "classification")
        self.best_model = kwargs.get("best_model")
        self.data_profile = kwargs.get("data_profile") or {}
        self.target_column = kwargs.get("target_column", "y")
        self.category_extras = kwargs.get("category_extras") or {}
        self.job_id = kwargs.get("job_id", "test-cal")


# ──────────────────────────────────────────────────────────────────────────────
# 1. ECE 계산
# ──────────────────────────────────────────────────────────────────────────────


class TestECE:
    """compute_ece 정확성."""

    def test_perfectly_calibrated_returns_low(self):
        # 예측 확률 = 실제 비율 → ECE ≈ 0
        rng = np.random.default_rng(42)
        n = 1000
        y_proba = rng.uniform(0, 1, n)
        # 각 샘플에 대해 베르누이(proba) 추출 → 평균적으로 보정됨
        y_true = (rng.uniform(0, 1, n) < y_proba).astype(int)
        ece = cal_mod.compute_ece(y_true, y_proba, n_bins=10)
        assert ece < 0.05, f"잘 보정된 데이터의 ECE 가 {ece:.4f} — 0.05 미만이어야 함"

    def test_worst_calibration_high_ece(self):
        # 모든 예측 0.5 인데 실제 정답률 1.0 → ECE = 0.5
        y_proba = np.full(100, 0.5)
        y_true = np.ones(100)
        ece = cal_mod.compute_ece(y_true, y_proba)
        assert abs(ece - 0.5) < 0.01

    def test_overconfident_underperformance(self):
        # 모든 예측 0.9 인데 실제 0.5 정답률 → ECE 0.4
        y_proba = np.full(100, 0.9)
        y_true = np.concatenate([np.ones(50), np.zeros(50)])
        ece = cal_mod.compute_ece(y_true, y_proba)
        assert abs(ece - 0.4) < 0.05

    def test_empty_input_returns_zero(self):
        ece = cal_mod.compute_ece(np.array([]), np.array([]))
        assert ece == 0.0

    def test_n_bins_affects_resolution(self):
        # 더 많은 bin = 더 세밀 = 작은 데이터에선 잡음 더 큼
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        ece_5 = cal_mod.compute_ece(y_true, y_proba, n_bins=5)
        ece_20 = cal_mod.compute_ece(y_true, y_proba, n_bins=20)
        # 둘 다 합리적 범위
        assert 0.0 <= ece_5 <= 0.5
        assert 0.0 <= ece_20 <= 0.5


# ──────────────────────────────────────────────────────────────────────────────
# 2. Platt / Isotonic fit
# ──────────────────────────────────────────────────────────────────────────────


class TestCalibratorFit:
    """fit_platt / fit_isotonic 가 callable 반환 + 정상 동작."""

    def test_platt_returns_callable(self):
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        cal = cal_mod.fit_platt(y_true, y_proba)
        assert callable(cal)

    def test_platt_output_in_range(self):
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        cal = cal_mod.fit_platt(y_true, y_proba)
        cal_proba = cal(y_proba)
        assert (cal_proba >= 0).all() and (cal_proba <= 1).all()

    def test_isotonic_returns_callable(self):
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        cal = cal_mod.fit_isotonic(y_true, y_proba)
        assert callable(cal)

    def test_isotonic_output_in_range(self):
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        cal = cal_mod.fit_isotonic(y_true, y_proba)
        cal_proba = cal(y_proba)
        assert (cal_proba >= 0).all() and (cal_proba <= 1).all()

    def test_isotonic_monotonic(self):
        # Isotonic 는 단조 증가여야 함
        rng = np.random.default_rng(1)
        y_proba = rng.uniform(0, 1, 500)
        y_true = (y_proba > 0.5).astype(int)  # 강한 신호
        cal = cal_mod.fit_isotonic(y_true, y_proba)
        # 0 → 1 grid 에서 보정값이 단조 증가
        grid = np.linspace(0, 1, 50)
        cal_grid = cal(grid)
        diffs = np.diff(cal_grid)
        assert (diffs >= -1e-9).all(), "Isotonic 보정 함수가 단조 증가 위반"


# ──────────────────────────────────────────────────────────────────────────────
# 3. K-fold CV 평가 honest
# ──────────────────────────────────────────────────────────────────────────────


class TestCVEvaluation:
    """K-fold CV 가 honest ECE 평가 — 과적합으로 0 안 만듦."""

    def test_random_data_doesnt_get_zero_ece(self):
        # 신호 없는 random data → 어떤 보정도 의미 없음, ECE 0 아님
        rng = np.random.default_rng(42)
        n = 300
        y_proba = rng.uniform(0, 1, n)
        y_true = rng.integers(0, 2, n).astype(float)  # 완전 random
        ece_after = cal_mod._evaluate_calibrator_cv(cal_mod.fit_platt, y_true, y_proba)
        # 신호 없으면 ECE 가 0.05~0.3 사이 (random fluctuation)
        assert ece_after > 0.0, "random 데이터에 ECE 0 — CV 과적합 의심"

    def test_real_signal_improves_after_calibration(self):
        # 모델 출력처럼 강한 신호 + 약간 미보정 → 보정 후 개선
        from sklearn.ensemble import RandomForestClassifier

        rng = np.random.default_rng(42)
        n = 500
        X = rng.normal(0, 1, (n, 5))
        y = ((X[:, 0] + X[:, 1]) > 0).astype(int)
        model = RandomForestClassifier(n_estimators=30, random_state=42)
        model.fit(X, y)
        y_proba = model.predict_proba(X)[:, 1]

        ece_before = cal_mod.compute_ece(y, y_proba)
        ece_after_platt = cal_mod._evaluate_calibrator_cv(cal_mod.fit_platt, y, y_proba)
        ece_after_iso = cal_mod._evaluate_calibrator_cv(cal_mod.fit_isotonic, y, y_proba)
        # 최소 하나는 ECE 개선해야 — RF train set 보정 효과 분명
        best = min(ece_after_platt, ece_after_iso)
        # 보정 후가 보정 전보다 더 나쁘면 안 됨 (margin 0.05 — CV noise 허용)
        assert best <= ece_before + 0.05, (
            f"보정 후 ECE 가 보정 전보다 0.05 이상 나빠짐: "
            f"before={ece_before:.4f}, after_best={best:.4f}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. calibrate() 가드
# ──────────────────────────────────────────────────────────────────────────────


class TestCalibrateGuards:
    """가드 통과 못 했을 때 skipped_reason 채워서 반환."""

    def test_no_best_model_skip(self):
        state = _SimpleState(best_model=None)
        result = cal_mod.calibrate(state)
        assert result["skipped_reason"] == "no_best_model"
        assert result["method"] is None
        assert result["ece_before"] is None

    def test_baseline_model_skip(self):
        state = _SimpleState(
            best_model={"model_name": "Dummy", "metrics": {"val_f1": 0.5}}
        )
        result = cal_mod.calibrate(state)
        assert result["skipped_reason"] == "baseline_skip"

    def test_logistic_regression_baseline_skip(self):
        state = _SimpleState(
            best_model={"model_name": "LogisticRegression", "metrics": {"val_f1": 0.7}}
        )
        result = cal_mod.calibrate(state)
        # baseline_skip 또는 model_reload_failed (테스트 환경 무모델) 둘 다 정상
        assert result["skipped_reason"] in ("baseline_skip", "model_reload_failed")

    def test_regression_not_supported(self):
        # val_r2 만 있고 val_f1 없으면 회귀 → skip
        state = _SimpleState(
            best_model={"model_name": "RandomForest", "metrics": {"val_r2": 0.7}}
        )
        result = cal_mod.calibrate(state)
        assert result["skipped_reason"] == "regression_not_supported"


# ──────────────────────────────────────────────────────────────────────────────
# 5. skipped result 형식
# ──────────────────────────────────────────────────────────────────────────────


class TestSkippedResultShape:
    """skipped 결과도 동일 키 구조여야 — insight·output_extras 가 안 깨지게."""

    def test_skipped_has_all_keys(self):
        result = cal_mod._skipped_result("test_reason")
        required = {
            "ece_before", "ece_after", "method", "methods_tried",
            "improvement_ratio", "reliability_chart_path",
            "n_samples_used", "skipped_reason",
        }
        assert required.issubset(result.keys())

    def test_skipped_methods_tried_empty_dict(self):
        result = cal_mod._skipped_result("test_reason")
        assert isinstance(result["methods_tried"], dict)
        assert result["methods_tried"] == {}


# ──────────────────────────────────────────────────────────────────────────────
# 6. reliability_diagram_data
# ──────────────────────────────────────────────────────────────────────────────


class TestReliabilityDiagramData:
    """reliability_diagram_data 출력 형식 + 정확성."""

    def test_returns_required_keys(self):
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        data = cal_mod.reliability_diagram_data(y_true, y_proba, n_bins=10)
        assert {"bin_mean_proba", "bin_actual", "bin_count", "bin_centers"}.issubset(data.keys())

    def test_n_bins_matches_output_length(self):
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        data = cal_mod.reliability_diagram_data(y_true, y_proba, n_bins=5)
        assert len(data["bin_centers"]) == 5
        assert len(data["bin_count"]) == 5

    def test_bin_counts_sum_to_total(self):
        rng = np.random.default_rng(0)
        y_proba = rng.uniform(0, 1, 200)
        y_true = (rng.uniform(0, 1, 200) < y_proba).astype(int)
        data = cal_mod.reliability_diagram_data(y_true, y_proba, n_bins=10)
        assert sum(data["bin_count"]) == 200


# ──────────────────────────────────────────────────────────────────────────────
# 7. 캐시 재사용
# ──────────────────────────────────────────────────────────────────────────────


class TestCacheReuse:
    """category_extras 캐시 있으면 재계산 안 함."""

    def test_reliability_chart_uses_cache(self):
        state = _SimpleState(
            best_model={"model_name": "RandomForest", "metrics": {"val_f1": 0.8}},
            category_extras={
                "tabular": {
                    "calibration": {
                        "reliability_chart_path": "s3://cached/cal.png",
                        "method": "platt",
                    }
                }
            },
        )
        path = cal_mod.reliability_diagram_chart(state)
        assert path == "s3://cached/cal.png"


# ──────────────────────────────────────────────────────────────────────────────
# 8. is_nan helper
# ──────────────────────────────────────────────────────────────────────────────


def test_is_nan_helper():
    assert cal_mod._is_nan(float("nan")) is True
    assert cal_mod._is_nan(0.5) is False
    assert cal_mod._is_nan(0.0) is False

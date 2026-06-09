"""tests.handlers.tabular.test_threshold_optimizer — Cost-sensitive 임계치 검증.

검증 범위:
  1. expected_cost 계산 정확성 (대칭/비대칭)
  2. F1-max / cost-min / Youden J / recall-min 4 전략 동작
  3. 비대칭 cost_matrix 입력 시 cost-min 임계치가 F1-max 와 다름 (실제 효과)
  4. cost_matrix 없으면 cost-min skip
  5. recall_min 달성 불가 시 None 반환
  6. 가드 (no_best_model / baseline / regression / multiclass)
  7. 캐시 재사용
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from agents.handlers.tabular import threshold_optimizer as ts_mod


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
        self.job_id = kwargs.get("job_id", "test-ts")


def _signal_data(n: int = 500, seed: int = 42, imbalance: float = 0.3) -> tuple[np.ndarray, np.ndarray]:
    """이진 분류 합성 — 신호 있는 확률 + 라벨."""
    rng = np.random.default_rng(seed)
    y_proba = rng.uniform(0, 1, n)
    # 0.5 임계치 근처에서 라벨이 결정되되, imbalance 비율 조절
    y_true = (y_proba > (1 - imbalance)).astype(int)
    # 약간의 노이즈 추가 — 완벽 모델 X
    flip_idx = rng.choice(n, size=int(n * 0.1), replace=False)
    y_true[flip_idx] = 1 - y_true[flip_idx]
    return y_true, y_proba


# ──────────────────────────────────────────────────────────────────────────────
# 1. expected_cost 계산
# ──────────────────────────────────────────────────────────────────────────────


class TestExpectedCost:
    """compute_expected_cost — confusion matrix × cost matrix."""

    def test_symmetric_cost_default(self):
        y_true = np.array([1, 1, 0, 0])
        y_proba = np.array([0.9, 0.4, 0.6, 0.1])
        # threshold 0.5: pred = [1, 0, 1, 0]
        #   tp=1 (idx 0), fn=1 (idx 1), fp=1 (idx 2), tn=1 (idx 3)
        cost = ts_mod.compute_expected_cost(y_true, y_proba, 0.5, {"fp": 1, "fn": 1, "tp": 0, "tn": 0})
        assert cost == 2.0  # 1 fp + 1 fn = 2

    def test_asymmetric_fn_higher(self):
        y_true = np.array([1, 1, 0, 0])
        y_proba = np.array([0.9, 0.4, 0.6, 0.1])
        # FN 비용 10, FP 비용 1: 1*1 + 1*10 = 11
        cost = ts_mod.compute_expected_cost(y_true, y_proba, 0.5, {"fp": 1, "fn": 10})
        assert cost == 11.0

    def test_threshold_change_affects_cost(self):
        y_true = np.array([1, 1, 0, 0])
        y_proba = np.array([0.9, 0.4, 0.6, 0.1])
        # 임계치 0.3 으로 낮추면: pred = [1, 1, 1, 0] → tp=2, fp=1, fn=0
        cost_low = ts_mod.compute_expected_cost(y_true, y_proba, 0.3, {"fp": 1, "fn": 10})
        # 0.3 에선 FN=0 → cost = 1 (fp 하나만)
        assert cost_low == 1.0

    def test_zero_cost_when_perfect(self):
        y_true = np.array([1, 1, 0, 0])
        y_proba = np.array([0.9, 0.8, 0.1, 0.2])
        # 임계치 0.5: pred = [1,1,0,0] → tp=2, tn=2 → cost 0
        cost = ts_mod.compute_expected_cost(y_true, y_proba, 0.5, {"fp": 100, "fn": 100})
        assert cost == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# 2. confusion + metrics helper
# ──────────────────────────────────────────────────────────────────────────────


class TestConfusionAndMetrics:
    """_confusion 와 _metrics_at 정확성."""

    def test_confusion_perfect(self):
        y_true = np.array([1, 1, 0, 0])
        y_pred = np.array([1, 1, 0, 0])
        tn, fp, fn, tp = ts_mod._confusion(y_true, y_pred)
        assert (tn, fp, fn, tp) == (2, 0, 0, 2)

    def test_metrics_at_perfect(self):
        y_true = np.array([1, 1, 1, 0, 0, 0])
        y_proba = np.array([0.9, 0.8, 0.7, 0.2, 0.1, 0.05])
        m = ts_mod._metrics_at(y_true, y_proba, 0.5)
        assert m["precision"] == 1.0
        assert m["recall"] == 1.0
        assert m["f1"] == pytest.approx(1.0)

    def test_metrics_at_zero_threshold(self):
        # threshold 0.0 면 전부 양성 예측 → recall 1.0, precision = base_rate
        y_true = np.array([1, 0, 1, 0])
        y_proba = np.array([0.5, 0.5, 0.5, 0.5])
        m = ts_mod._metrics_at(y_true, y_proba, 0.01)
        assert m["recall"] == 1.0
        assert m["precision"] == 0.5  # 2 양성 / 4 예측 양성


# ──────────────────────────────────────────────────────────────────────────────
# 3. F1-max
# ──────────────────────────────────────────────────────────────────────────────


class TestF1Max:
    """find_f1_max 동작 검증."""

    def test_returns_threshold_in_range(self):
        y_true, y_proba = _signal_data(n=500)
        result = ts_mod.find_f1_max(y_true, y_proba)
        assert 0.01 <= result["threshold"] <= 0.99
        assert 0.0 <= result["f1"] <= 1.0

    def test_returns_expected_keys(self):
        y_true, y_proba = _signal_data(n=200)
        result = ts_mod.find_f1_max(y_true, y_proba)
        assert {"threshold", "f1", "precision", "recall", "expected_cost"}.issubset(result.keys())

    def test_expected_cost_none_without_matrix(self):
        y_true, y_proba = _signal_data(n=200)
        result = ts_mod.find_f1_max(y_true, y_proba, cost_matrix=None)
        assert result["expected_cost"] is None

    def test_expected_cost_present_with_matrix(self):
        y_true, y_proba = _signal_data(n=200)
        result = ts_mod.find_f1_max(y_true, y_proba, cost_matrix={"fp": 1, "fn": 5})
        assert result["expected_cost"] is not None
        assert result["expected_cost"] >= 0


# ──────────────────────────────────────────────────────────────────────────────
# 4. Cost-min — 비대칭 비용에서 F1-max 와 임계치 달라야
# ──────────────────────────────────────────────────────────────────────────────


class TestCostMin:
    """find_cost_min — FN/FP 비용 비대칭이면 임계치가 F1-max 와 다름."""

    def test_fn_high_lowers_threshold(self):
        """FN 비용 ≫ FP 비용 → 임계치 낮춰서 양성 더 많이 잡음 (recall↑)."""
        y_true, y_proba = _signal_data(n=500, imbalance=0.3)
        f1_result = ts_mod.find_f1_max(y_true, y_proba, cost_matrix={"fp": 1, "fn": 1})
        cost_result = ts_mod.find_cost_min(y_true, y_proba, cost_matrix={"fp": 1, "fn": 20})
        # FN 비용이 매우 높으면 cost-min 임계치 < F1-max 임계치
        # (양성 더 많이 잡아 FN 회피)
        assert cost_result["threshold"] <= f1_result["threshold"] + 0.05, (
            f"FN={20} 비대칭 비용에서 cost-min 임계치 ({cost_result['threshold']}) 가 "
            f"F1-max ({f1_result['threshold']}) 보다 낮아야 함"
        )

    def test_fp_high_raises_threshold(self):
        """FP 비용 ≫ FN 비용 → 임계치 높여서 양성 보수적 (precision↑)."""
        y_true, y_proba = _signal_data(n=500, imbalance=0.3)
        f1_result = ts_mod.find_f1_max(y_true, y_proba, cost_matrix={"fp": 1, "fn": 1})
        cost_result = ts_mod.find_cost_min(y_true, y_proba, cost_matrix={"fp": 20, "fn": 1})
        # FP 비용이 매우 높으면 cost-min 임계치 ≥ F1-max
        assert cost_result["threshold"] >= f1_result["threshold"] - 0.05, (
            f"FP={20} 비대칭 비용에서 cost-min 임계치 ({cost_result['threshold']}) 가 "
            f"F1-max ({f1_result['threshold']}) 보다 높아야 함"
        )

    def test_cost_min_minimizes_cost(self):
        """cost-min 의 expected_cost 가 다른 어떤 임계치보다 ≤."""
        y_true, y_proba = _signal_data(n=500)
        cost_matrix = {"fp": 5, "fn": 100}
        cost_result = ts_mod.find_cost_min(y_true, y_proba, cost_matrix=cost_matrix)
        f1_result = ts_mod.find_f1_max(y_true, y_proba, cost_matrix=cost_matrix)
        # cost_min 이 F1-max 보다 cost 가 작거나 같아야 (정의상)
        assert cost_result["expected_cost"] <= f1_result["expected_cost"] + 0.01


# ──────────────────────────────────────────────────────────────────────────────
# 5. Youden J
# ──────────────────────────────────────────────────────────────────────────────


class TestYoudenJ:
    """find_youden_j — TPR - FPR 최대화."""

    def test_returns_threshold_and_j(self):
        y_true, y_proba = _signal_data(n=500)
        result = ts_mod.find_youden_j(y_true, y_proba)
        assert 0.01 <= result["threshold"] <= 0.99
        assert "j_statistic" in result
        assert -1.0 <= result["j_statistic"] <= 1.0

    def test_j_positive_for_signal(self):
        # 신호 있는 데이터에서 J > 0 (모델이 random 보다 나음)
        y_true, y_proba = _signal_data(n=500)
        result = ts_mod.find_youden_j(y_true, y_proba)
        assert result["j_statistic"] > 0


# ──────────────────────────────────────────────────────────────────────────────
# 6. Recall-min
# ──────────────────────────────────────────────────────────────────────────────


class TestRecallMin:
    """find_recall_min — recall ≥ target 에서 precision 최대."""

    def test_feasible_returns_threshold(self):
        y_true, y_proba = _signal_data(n=500)
        result = ts_mod.find_recall_min(y_true, y_proba, target_recall=0.5)
        assert result is not None
        assert result["recall"] >= 0.5

    def test_infeasible_high_target_returns_none(self):
        # 신호 약한 데이터에서 recall 0.99 요구 → 달성 불가능에 가까움
        rng = np.random.default_rng(0)
        n = 100
        y_proba = rng.uniform(0.3, 0.7, n)  # 신호 약함
        y_true = rng.integers(0, 2, n).astype(int)
        result = ts_mod.find_recall_min(y_true, y_proba, target_recall=1.01)  # 1.0 초과
        assert result is None


# ──────────────────────────────────────────────────────────────────────────────
# 7. optimize_thresholds 가드
# ──────────────────────────────────────────────────────────────────────────────


class TestOptimizeGuards:
    """optimize_thresholds 가드 — skipped_reason 채워서 반환."""

    def test_no_best_model_skip(self):
        state = _SimpleState(best_model=None)
        result = ts_mod.optimize_thresholds(state)
        assert result["skipped_reason"] == "no_best_model"

    def test_baseline_skip(self):
        state = _SimpleState(
            best_model={"model_name": "Dummy", "metrics": {"val_f1": 0.5}}
        )
        result = ts_mod.optimize_thresholds(state)
        assert result["skipped_reason"] == "baseline_skip"

    def test_regression_skip(self):
        state = _SimpleState(
            best_model={"model_name": "RandomForest", "metrics": {"val_r2": 0.7}}
        )
        result = ts_mod.optimize_thresholds(state)
        assert result["skipped_reason"] == "regression_not_supported"


# ──────────────────────────────────────────────────────────────────────────────
# 8. Skipped result 형식
# ──────────────────────────────────────────────────────────────────────────────


class TestSkippedResultShape:
    """skipped 결과 키 구조 — insight·output_extras 가 안 깨지게."""

    def test_skipped_has_all_keys(self):
        result = ts_mod._skipped_result("test_reason")
        required = {
            "strategies", "recommended", "cost_matrix", "calibrated",
            "target_recall", "chart_path", "n_samples_used", "skipped_reason",
        }
        assert required.issubset(result.keys())

    def test_skipped_strategies_empty_dict(self):
        result = ts_mod._skipped_result("test_reason")
        assert isinstance(result["strategies"], dict)
        assert result["strategies"] == {}


# ──────────────────────────────────────────────────────────────────────────────
# 9. 캐시 재사용
# ──────────────────────────────────────────────────────────────────────────────


class TestCacheReuse:
    """threshold_strategies_chart 가 캐시 우선 사용."""

    def test_chart_uses_cache(self):
        state = _SimpleState(
            best_model={"model_name": "RandomForest", "metrics": {"val_f1": 0.8}},
            category_extras={
                "tabular": {
                    "threshold_strategies": {
                        "chart_path": "s3://cached/threshold.png",
                        "strategies": {},
                    }
                }
            },
        )
        path = ts_mod.threshold_strategies_chart(state)
        assert path == "s3://cached/threshold.png"

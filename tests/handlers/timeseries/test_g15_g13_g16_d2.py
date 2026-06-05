"""테스트 — G15 잔차 진단 + G13 DM 검정 + G16 미래 exog 자동 생성 + D2 누적 권고."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ════════════════════════════════════════════════════════
# G15 — 잔차 진단
# ════════════════════════════════════════════════════════
class TestResidualDiagnostics:
    def test_helper_exists(self):
        from agents.handlers.timeseries.evaluator import _diagnose_residuals

        assert callable(_diagnose_residuals)

    def test_white_noise_when_random_residuals(self):
        from agents.handlers.timeseries.evaluator import _diagnose_residuals

        rng = np.random.default_rng(42)
        y_true = list(rng.normal(100, 10, 50))
        y_pred = list(np.array(y_true) + rng.normal(0, 0.5, 50))
        result = _diagnose_residuals({"y_pred_val": y_pred, "y_val_actual": y_true})
        assert result["kind"] in ("white_noise", "unknown")

    def test_autocorrelated_when_strong_pattern(self):
        from agents.handlers.timeseries.evaluator import _diagnose_residuals

        n = 100
        y_true = list(np.arange(n, dtype=float))
        y_pred = list(np.arange(n, dtype=float) - 0.5 * np.arange(n))
        result = _diagnose_residuals({"y_pred_val": y_pred, "y_val_actual": y_true})
        assert result["kind"] in ("autocorrelated", "biased", "unknown")

    def test_unknown_when_few_residuals(self):
        from agents.handlers.timeseries.evaluator import _diagnose_residuals

        result = _diagnose_residuals({"y_pred_val": [1.0], "y_val_actual": [1.5]})
        assert result["kind"] == "unknown"

    def test_evaluate_returns_residual_diagnostics_key(self, ts_state):
        from agents.handlers.timeseries.evaluator import evaluate

        s = ts_state.with_update(
            best_model={
                "model_name": "ARIMA",
                "metrics": {
                    "val_rmse": 10.0,
                    "MASE": 0.6,
                    "rmse_improvement_vs_naive": 0.2,
                    "y_pred_val": list(range(50)),
                    "y_val_actual": list(np.array(range(50)) + 0.1),
                },
            }
        )
        result = evaluate(s)
        assert "residual_diagnostics" in result


# ════════════════════════════════════════════════════════
# G13 — Diebold-Mariano 검정
# ════════════════════════════════════════════════════════
class TestDMTest:
    def test_helper_exists(self):
        from agents.handlers.timeseries.evaluator import _dm_test

        assert callable(_dm_test)

    def test_unavailable_when_no_pred(self):
        from agents.handlers.timeseries.evaluator import _dm_test

        assert _dm_test({}).get("available") is False

    def test_model_wins_when_better(self):
        from agents.handlers.timeseries.evaluator import _dm_test

        n = 50
        y_true = list(np.linspace(10, 20, n))
        y_pred = list(np.linspace(10.1, 19.9, n))  # 거의 완벽 예측
        y_train_tail = [10.0]  # naïve 가 멀리 떨어짐
        result = _dm_test({"y_pred_val": y_pred, "y_val_actual": y_true, "y_train_tail": y_train_tail})
        assert result["available"] is True
        assert result["verdict"] in ("model_wins", "tie")

    def test_evaluate_returns_dm_test_key(self, ts_state):
        from agents.handlers.timeseries.evaluator import evaluate

        s = ts_state.with_update(
            best_model={
                "model_name": "ARIMA",
                "metrics": {
                    "val_rmse": 10.0,
                    "MASE": 0.6,
                    "rmse_improvement_vs_naive": 0.2,
                    "y_pred_val": list(range(50)),
                    "y_val_actual": list(np.array(range(50)) + 0.5),
                    "y_train_tail": [-1.0],
                },
            }
        )
        result = evaluate(s)
        assert "dm_test" in result


# ════════════════════════════════════════════════════════
# G16 — 미래 exog 자동 생성
# ════════════════════════════════════════════════════════
class TestGenerateFutureExog:
    def test_method_exists(self):
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        assert hasattr(TimeSeriesPipeline, "generate_future_exog")

    def test_calendar_columns(self):
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        df = TimeSeriesPipeline.generate_future_exog(last_date="2024-01-31", n_steps=7, freq="D", kinds=("calendar",))
        assert len(df) == 7
        for col in ("cal_dayofweek", "cal_month", "cal_is_month_end", "cal_is_quarter_end"):
            assert col in df.columns

    def test_fourier_columns(self):
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        df = TimeSeriesPipeline.generate_future_exog(
            last_date="2024-01-01",
            n_steps=10,
            freq="D",
            kinds=("fourier",),
            fourier_period=7,
            fourier_n=2,
        )
        assert "fourier_sin_1" in df.columns
        assert "fourier_cos_1" in df.columns
        assert "fourier_sin_2" in df.columns

    def test_default_combo(self):
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        df = TimeSeriesPipeline.generate_future_exog(last_date="2024-06-01", n_steps=5)
        assert "ds" in df.columns
        assert len(df) == 5
        # 기본은 calendar + fourier
        assert "cal_dayofweek" in df.columns
        assert "fourier_sin_1" in df.columns


# ════════════════════════════════════════════════════════
# D2 — 누적 타깃 자동 권고 메타
# ════════════════════════════════════════════════════════
class TestTargetDiffRecommend:
    def test_meta_step_active_when_cumulative(self, ts_state):
        from agents.handlers.timeseries.preprocessor import plan

        s = ts_state.with_update(data_profile={"rows": 200, "target_kind": "cumulative"})
        steps = plan(s)
        names = [step.get("name") for step in steps]
        assert "_meta_target_diff_recommend" in names

    def test_no_meta_when_level_target(self, ts_state):
        from agents.handlers.timeseries.preprocessor import plan

        s = ts_state.with_update(data_profile={"rows": 200, "target_kind": "level"})
        steps = plan(s)
        names = [step.get("name") for step in steps]
        assert "_meta_target_diff_recommend" not in names

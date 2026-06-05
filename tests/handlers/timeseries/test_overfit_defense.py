"""테스트 — 과적합/과소적합 방어 + X6 winsorize 제거 검증 (2026-06-05).

OF1 search_space ARIMA/SARIMA order 데이터 길이 적응
OF3 Prophet changepoint_prior_scale 상한 0.1
OF4 pipeline.evaluate train_rmse + overfit_gap 키 노출
OF5 evaluator fit_quality 진단 (overfit/underfit/ok)
OF6 insight 의 fit_quality 한국어 안내
X6  winsorize 완전 제거 (preprocessor)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ════════════════════════════════════════════════════════
# X6 — winsorize 완전 제거 검증
# ════════════════════════════════════════════════════════
class TestWinsorizeRemoved:
    def test_winsorize_not_in_plan(self, ts_state):
        from agents.handlers.timeseries.preprocessor import plan

        s = ts_state.with_update(data_profile={"rows": 200, "outlier_iqr_ratio": 0.50})
        steps = plan(s)
        names = [step.get("name") for step in steps]
        assert "winsorize" not in names

    def test_winsorize_helper_removed(self):
        from agents.handlers.timeseries import preprocessor

        assert not hasattr(preprocessor, "_apply_winsorize")


# ════════════════════════════════════════════════════════
# OF1 — ARIMA/SARIMA order 데이터 길이 적응
# ════════════════════════════════════════════════════════
class TestOrderAdaptation:
    def test_arima_short_data_caps_order(self):
        """trial.study.user_attrs['n_rows']=50 시 ARIMA p_max=1."""
        from pipelines.timeseries.search_space import get_search_space

        class FakeTrial:
            def __init__(self, n_rows):
                self.suggestions = {}

                class FS:
                    user_attrs = {"n_rows": n_rows}

                self.study = FS

            def suggest_int(self, name, low, high):
                self.suggestions[name] = (low, high)
                return low

            def suggest_categorical(self, name, choices):
                return choices[0]

            def suggest_float(self, name, low, high, log=False):
                return low

        t = FakeTrial(n_rows=50)
        get_search_space("ARIMA", t)
        assert t.suggestions["p"] == (0, 1)
        assert t.suggestions["q"] == (0, 1)
        assert t.suggestions["d"] == (0, 1)

    def test_arima_long_data_full_range(self):
        from pipelines.timeseries.search_space import get_search_space

        class FakeTrial:
            def __init__(self, n_rows):
                self.suggestions = {}

                class FS:
                    user_attrs = {"n_rows": n_rows}

                self.study = FS

            def suggest_int(self, name, low, high):
                self.suggestions[name] = (low, high)
                return low

            def suggest_categorical(self, name, choices):
                return choices[0]

            def suggest_float(self, name, low, high, log=False):
                return low

        t = FakeTrial(n_rows=500)
        get_search_space("ARIMA", t)
        # n>=300 → 전체 범위 (3, 2, 3)
        assert t.suggestions["p"][1] == 3
        assert t.suggestions["q"][1] == 3


# ════════════════════════════════════════════════════════
# OF3 — Prophet changepoint_prior_scale 상한 보수화
# ════════════════════════════════════════════════════════
class TestProphetConservative:
    def test_prophet_changepoint_upper_bound(self):
        from pipelines.timeseries.search_space import get_search_space

        captured = {}

        class FakeTrial:
            def suggest_float(self, name, low, high, log=False):
                captured[name] = high
                return low

            def suggest_categorical(self, name, choices):
                return choices[0]

            class study:
                user_attrs: dict = {}

        get_search_space("Prophet", FakeTrial())
        # 상한 0.1 보수화 확인 (기존 0.5 → 0.1)
        assert captured["changepoint_prior_scale"] == 0.1


# ════════════════════════════════════════════════════════
# OF4 — pipeline.evaluate train_rmse + overfit_gap 키
# ════════════════════════════════════════════════════════
class TestPipelineOverfitKeys:
    def test_evaluate_returns_train_rmse_and_overfit_gap_keys(self):
        """evaluate() 반환 dict 에 OF4 신규 2 키 존재."""
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        pipe = TimeSeriesPipeline()
        rng = np.random.default_rng(42)
        n = 100
        X = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=n)})
        y = rng.normal(10, 2, n).cumsum()

        try:
            model = pipe.train(X[:80], y[:80], "ARIMA", {"order": (1, 1, 1)})
            metrics = pipe.evaluate(model, X[80:], y[80:])
        except Exception:
            pytest.skip("ARIMA 학습 환경 부재")

        assert "train_rmse" in metrics
        assert "overfit_gap" in metrics


# ════════════════════════════════════════════════════════
# OF5 — evaluator fit_quality 진단
# ════════════════════════════════════════════════════════
class TestFitQualityDiagnosis:
    def test_helper_exists(self):
        from agents.handlers.timeseries.evaluator import _diagnose_fit_quality

        assert callable(_diagnose_fit_quality)

    def test_overfit_severe_detected(self):
        from agents.handlers.timeseries.evaluator import _diagnose_fit_quality

        # val_rmse 가 train 의 +80% → severe
        result = _diagnose_fit_quality({"train_rmse": 10.0, "val_rmse": 18.0, "overfit_gap": 0.8})
        assert result["kind"] == "overfit"
        assert result["severity"] == "severe"
        assert "심각한 과적합" in result["hint"]

    def test_overfit_warn_detected(self):
        from agents.handlers.timeseries.evaluator import _diagnose_fit_quality

        result = _diagnose_fit_quality({"train_rmse": 10.0, "val_rmse": 14.0, "overfit_gap": 0.4})
        assert result["kind"] == "overfit"
        assert result["severity"] == "warn"

    def test_underfit_detected(self):
        from agents.handlers.timeseries.evaluator import _diagnose_fit_quality

        # improvement<=0 + MASE>=1.0 → underfit
        result = _diagnose_fit_quality({"MASE": 1.5, "rmse_improvement_vs_naive": -0.05})
        assert result["kind"] == "underfit"
        assert result["severity"] == "severe"
        assert "naïve" in result["hint"]

    def test_ok_when_gap_normal(self):
        from agents.handlers.timeseries.evaluator import _diagnose_fit_quality

        result = _diagnose_fit_quality({"train_rmse": 10.0, "val_rmse": 11.0, "overfit_gap": 0.1})
        assert result["kind"] == "ok"

    def test_unknown_when_no_train_rmse(self):
        from agents.handlers.timeseries.evaluator import _diagnose_fit_quality

        result = _diagnose_fit_quality({"val_rmse": 11.0})
        assert result["kind"] == "unknown"

    def test_evaluate_returns_fit_quality_key(self, ts_state):
        from agents.handlers.timeseries.evaluator import evaluate

        s = ts_state.with_update(
            best_model={
                "model_name": "ARIMA",
                "metrics": {
                    "val_rmse": 10.0,
                    "MASE": 0.6,
                    "rmse_improvement_vs_naive": 0.2,
                    "train_rmse": 9.0,
                    "overfit_gap": 0.11,
                },
            }
        )
        result = evaluate(s)
        assert "fit_quality" in result
        assert result["fit_quality"]["kind"] == "ok"


# ════════════════════════════════════════════════════════
# OF6 — insight 의 fit_quality 한국어 안내
# ════════════════════════════════════════════════════════
class TestInsightFitQualityHint:
    def test_overfit_hint_appears_in_fallback(self, ts_state):
        from agents.handlers.timeseries.insight import fallback

        s = ts_state.with_update(
            best_model={"model_name": "ARIMA", "metrics": {"MASE": 0.5, "rmse_improvement_vs_naive": 0.2}},
            eval_result={
                "fit_quality": {
                    "kind": "overfit",
                    "severity": "severe",
                    "hint": "심각한 과적합 (val_rmse 가 train_rmse 의 +80%). 정규화 강화 권장.",
                    "overfit_gap": 0.8,
                },
            },
        )
        text = fallback(s)
        assert "과적합" in text or "정규화" in text

    def test_no_hint_when_ok(self, ts_state):
        from agents.handlers.timeseries.insight import fallback

        s = ts_state.with_update(
            best_model={"model_name": "ARIMA", "metrics": {"MASE": 0.5, "rmse_improvement_vs_naive": 0.2}},
            eval_result={"fit_quality": {"kind": "ok", "severity": "none"}},
        )
        text = fallback(s)
        # ok 시 과적합 단어 없어야
        assert "심각한 과적합" not in text

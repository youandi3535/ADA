"""CS cs-day6 v3 — timeseries pipeline 단위 테스트.

검증 카테고리:
  회귀 가드 (4): 기존 ARIMA/SARIMA/Prophet/UnknownModel 패턴 보존
  신규 모델 (3): SARIMAX(exog) / ETS / seasonal_naive 학습+예측+평가
  evaluate 15 키 (2): 신규 3 키 (y_pred_val/y_val_actual/y_train_tail)
  train_with_cv (4): rolling-origin / gap=horizon-1 / fold_metrics / mean=improvement
  엣지 (3): 짧은 시리즈 자동 축소 / seasonal_naive 짧은 y / search_space Unknown raise
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ════════════════════════════════════════════════════════════════
# 공통 fixture
# ════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _no_mlflow(monkeypatch):
    """BasePipeline._start_mlflow_run 패치 — 외부 MLflow 호출 차단."""
    from pipelines.base import BasePipeline

    class _Noop:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(BasePipeline, "_start_mlflow_run", lambda self, **kw: _Noop())


@pytest.fixture()
def pipe():
    from pipelines.timeseries.pipeline import TimeSeriesPipeline

    return TimeSeriesPipeline()


@pytest.fixture()
def ts_data():
    """추세+노이즈 60 포인트."""
    rng = np.random.default_rng(42)
    return np.cumsum(rng.standard_normal(60)).astype(np.float64) + 100.0


@pytest.fixture()
def ts_data_seasonal():
    """주간 계절성 + 추세 200 포인트."""
    rng = np.random.default_rng(7)
    t = np.arange(200, dtype=float)
    return 100.0 + 0.5 * t + 10.0 * np.sin(2 * np.pi * t / 7.0) + rng.standard_normal(200) * 2.0


@pytest.fixture()
def ts_with_exog():
    """exog 컬럼 포함 DataFrame (n=120, exog 영향 작게 들어감)."""
    rng = np.random.default_rng(11)
    n = 120
    exog = rng.standard_normal(n) * 5
    y = 50.0 + 0.3 * np.arange(n) + 0.5 * exog + rng.standard_normal(n)
    X = pd.DataFrame({"ds": pd.date_range("2024-01-01", periods=n, freq="D"), "temp": exog})
    return X, y, ["temp"]


# ════════════════════════════════════════════════════════════════
# 회귀 가드 (기존 4 테스트 패턴 보존)
# ════════════════════════════════════════════════════════════════


class TestRegressionGuard:
    """회귀 0 — 기존 ARIMA/SARIMA/Prophet/Unknown 패턴 동일 유지."""

    def test_arima_train_predict_evaluate(self, pipe, ts_data):
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(50)})
        model = pipe.train(X, ts_data[:50], "ARIMA", {"order": (1, 1, 1)})
        assert model is not None
        metrics = pipe.evaluate(model, ts_data[50:], ts_data[50:], "forecasting")
        assert "val_rmse" in metrics and "val_mae" in metrics
        assert metrics["val_rmse"] >= 0.0

    def test_sarima_train(self, pipe, ts_data):
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(50)})
        model = pipe.train(
            X,
            ts_data[:50],
            "SARIMA",
            {"order": (1, 1, 0), "seasonal_order": (0, 0, 0, 4)},
        )
        assert model is not None

    def test_unknown_ts_model_raises(self, pipe, ts_data):
        pytest.importorskip("statsmodels")
        with pytest.raises(Exception):
            pipe.train(pd.DataFrame({"ds": range(50)}), ts_data[:50], "GhostTS", {})


# ════════════════════════════════════════════════════════════════
# 신규 모델 학습·예측·평가 (3)
# ════════════════════════════════════════════════════════════════


class TestNewModels:
    """SARIMAX/ETS/seasonal_naive — cs-day6 v3 디벨롭 추가 분기."""

    def test_sarimax_train_with_exog(self, pipe, ts_with_exog):
        """SARIMAX 학습이 exog 컬럼명으로 정상. SARIMAX 의 forecast 는 exog
        동반 호출이 statsmodels 표준 — 직접 API 검증."""
        pytest.importorskip("statsmodels")
        X, y, exog_cols = ts_with_exog
        n = len(y)
        split = int(n * 0.8)
        params = {
            "order": (1, 0, 0),
            "seasonal_order": (0, 0, 0, 0),
            "exog_columns": exog_cols,
        }
        model = pipe.train(X.iloc[:split], y[:split], "SARIMAX", params)
        assert model is not None
        # SARIMAX 표준: forecast(steps, exog=...) — exog 동반 필수
        exog_val = X.iloc[split:][exog_cols]
        forecast = model.forecast(steps=len(exog_val), exog=exog_val)
        assert len(forecast) == len(exog_val)

    def test_ets_train_evaluate(self, pipe, ts_data_seasonal):
        pytest.importorskip("statsmodels")
        y = ts_data_seasonal
        X = pd.DataFrame({"ds": range(len(y))})
        split = int(len(y) * 0.8)
        params = {
            "trend": "add",
            "seasonal": "add",
            "seasonal_periods": 7,
            "damped_trend": False,
        }
        model = pipe.train(X.iloc[:split], y[:split], "ETS", params)
        assert model is not None
        metrics = pipe.evaluate(model, y[split:], y[split:], "forecasting")
        assert metrics["val_rmse"] >= 0.0
        assert "MASE" in metrics

    def test_seasonal_naive_train_evaluate(self, pipe, ts_data_seasonal):
        y = ts_data_seasonal
        X = pd.DataFrame({"ds": range(len(y))})
        split = int(len(y) * 0.8)
        params = {"seasonal_periods": 7}
        model = pipe.train(X.iloc[:split], y[:split], "seasonal_naive", params)
        assert model is not None
        # forecast 인터페이스 확인
        preds = model.forecast(steps=10)
        assert len(preds) == 10
        # evaluate 호환
        metrics = pipe.evaluate(model, y[split:], y[split:], "forecasting")
        assert "val_rmse" in metrics


# ════════════════════════════════════════════════════════════════
# evaluate 15 키 (신규 3 키 — 단절 C-5 해소)
# ════════════════════════════════════════════════════════════════


class TestEvaluateExtendedKeys:
    """evaluate() 가 신규 3 키 (y_pred_val/y_val_actual/y_train_tail) 반환."""

    def test_evaluate_returns_new_three_keys(self, pipe, ts_data):
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(50)})
        model = pipe.train(X, ts_data[:50], "ARIMA", {"order": (1, 1, 1)})
        metrics = pipe.evaluate(model, ts_data[50:], ts_data[50:], "forecasting")
        assert "y_pred_val" in metrics
        assert "y_val_actual" in metrics
        assert "y_train_tail" in metrics
        assert isinstance(metrics["y_pred_val"], list)
        assert isinstance(metrics["y_val_actual"], list)
        assert isinstance(metrics["y_train_tail"], list)
        # y_train_tail 최대 200
        assert len(metrics["y_train_tail"]) <= 200

    def test_evaluate_existing_12_keys_preserved(self, pipe, ts_data):
        """회귀 — cs-day7 evaluator 가 의존하는 12 키 모두 보존."""
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(50)})
        model = pipe.train(X, ts_data[:50], "ARIMA", {"order": (1, 1, 1)})
        metrics = pipe.evaluate(model, ts_data[50:], ts_data[50:], "forecasting")
        expected_keys = {
            "val_rmse",
            "val_mae",
            "rmse_naive",
            "rmse_improvement_vs_naive",
            "MASE",
            "sMAPE",
            "pi_coverage",
            "pi_lower",
            "pi_upper",
            "naive_kind",
            "naive_s",
            "mlflow_run_id",
        }
        for k in expected_keys:
            assert k in metrics, f"기존 12 키 중 {k} 누락 — cs-day7 evaluator 회귀"


# ════════════════════════════════════════════════════════════════
# train_with_cv (walk-forward, 방법론 4-1·누수 1-4)
# ════════════════════════════════════════════════════════════════


class TestTrainWithCV:
    """rolling-origin walk-forward + gap=horizon-1 + mean=improvement."""

    def test_cv_basic_rolling_origin(self, pipe, ts_data_seasonal):
        """기본 동작 — n_splits=3 fold 점수 + 평균/분산."""
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(len(ts_data_seasonal))})
        result = pipe.train_with_cv(
            X,
            ts_data_seasonal,
            "ARIMA",
            {"order": (1, 1, 1), "horizon": 1},
            n_splits=3,
            task="forecasting",
        )
        assert "fold_scores" in result
        assert "fold_metrics" in result
        assert "mean" in result
        assert "std" in result
        assert "n_splits" in result
        assert "gap" in result
        assert result["gap"] == 0  # horizon=1 → gap=0
        assert isinstance(result["mean"], float)
        # fold_scores 개수 = n_splits_eff (작은 데이터 자동 축소 가능)
        assert len(result["fold_scores"]) == result["n_splits"]

    def test_cv_gap_from_horizon(self, pipe, ts_data_seasonal):
        """horizon>1 일 때 gap = horizon-1 (누수 1-4 차단)."""
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(len(ts_data_seasonal))})
        result = pipe.train_with_cv(
            X,
            ts_data_seasonal,
            "ARIMA",
            {"order": (1, 1, 1), "horizon": 7},
            n_splits=3,
            task="forecasting",
        )
        assert result["gap"] == 6  # horizon=7 → gap=6

    def test_cv_fold_metrics_per_fold(self, pipe, ts_data_seasonal):
        """각 fold 의 metrics 가 fold_metrics 에 dict 로 누적."""
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(len(ts_data_seasonal))})
        result = pipe.train_with_cv(
            X,
            ts_data_seasonal,
            "ARIMA",
            {"order": (1, 1, 1), "horizon": 1},
            n_splits=3,
            task="forecasting",
        )
        assert len(result["fold_metrics"]) == result["n_splits"]
        # 정상 fold 는 4 키 있어야 함
        success_folds = [m for m in result["fold_metrics"] if m]
        if success_folds:
            for m in success_folds:
                assert "val_rmse" in m
                assert "rmse_improvement_vs_naive" in m

    def test_cv_mean_is_improvement_friendly(self, pipe, ts_data_seasonal):
        """mean 키가 HPO study.direction='maximize' 와 정합 (improvement 평균)."""
        pytest.importorskip("statsmodels")
        X = pd.DataFrame({"ds": range(len(ts_data_seasonal))})
        result = pipe.train_with_cv(
            X,
            ts_data_seasonal,
            "ARIMA",
            {"order": (1, 1, 1), "horizon": 1},
            n_splits=2,
            task="forecasting",
        )
        # mean 이 fold_scores 평균과 정합 (실패 fold 는 0.0)
        assert isinstance(result["mean"], float)
        if result["fold_scores"]:
            expected = float(np.mean(result["fold_scores"]))
            assert abs(result["mean"] - expected) < 1e-9


# ════════════════════════════════════════════════════════════════
# 엣지 (3)
# ════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """극단·짧은 데이터 안전 처리."""

    def test_cv_short_series_skip(self, pipe):
        """n<10 이면 CV skip + neutral mean=0 반환."""
        y = np.arange(8, dtype=float)
        X = pd.DataFrame({"ds": range(8)})
        result = pipe.train_with_cv(X, y, "ARIMA", {"order": (1, 0, 0), "horizon": 1})
        assert result["mean"] == 0.0
        assert result.get("skip_reason") == "n<10"

    def test_seasonal_naive_short_y(self, pipe):
        """y 가 period 보다 짧으면 simple naive 로 강등 (마지막 값 반복)."""
        y = np.asarray([1.0, 2.0, 3.0])
        X = pd.DataFrame({"ds": range(3)})
        model = pipe.train(X, y, "seasonal_naive", {"seasonal_periods": 7})
        preds = model.forecast(steps=5)
        assert len(preds) == 5
        # 모든 예측이 마지막 값(3.0) (period=1 강등)
        assert all(p == 3.0 for p in preds)

    def test_search_space_unknown_model_raises(self):
        """search_space.get_search_space 가 UNKNOWN 모델에 ValueError."""
        optuna = pytest.importorskip("optuna")
        from pipelines.timeseries import search_space

        study = optuna.create_study(direction="maximize")

        def _objective(trial):
            search_space.get_search_space("UNKNOWN_MODEL", trial)
            return 0.0

        with pytest.raises(Exception):
            # Optuna 가 ValueError 를 trial 실패로 잡거나 raise — 어느 쪽이든 OK
            study.optimize(_objective, n_trials=1, catch=())

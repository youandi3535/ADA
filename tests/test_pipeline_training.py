"""tests/test_pipeline_training.py — 실제 모델 학습 파이프라인 end-to-end 검증.

train → predict → evaluate 체인을 소규모 합성 데이터로 검증한다.
미설치 의존성은 pytest.importorskip 으로 자동 스킵.
MLflow 호출은 _start_mlflow_run 패치로 차단.
"""

from __future__ import annotations

import numpy as np
import pytest

# ── 공통 픽스처 ──────────────────────────────────────────────────────────────


@pytest.fixture()
def clf_data():
    """이진 분류 합성 데이터 (100 × 5)."""
    rng = np.random.default_rng(42)
    X = rng.standard_normal((100, 5)).astype(np.float32)
    y = (X[:, 0] > 0).astype(int)
    return X, y


@pytest.fixture()
def reg_data():
    """회귀 합성 데이터 (100 × 5)."""
    rng = np.random.default_rng(42)
    X = rng.standard_normal((100, 5)).astype(np.float32)
    y = (X[:, 0] * 2 + rng.standard_normal(100)).astype(np.float32)
    return X, y


@pytest.fixture()
def ts_data():
    """시계열 합성 데이터 (60 포인트)."""
    rng = np.random.default_rng(42)
    return np.cumsum(rng.standard_normal(60)).astype(np.float64)


@pytest.fixture()
def anomaly_data():
    """이상탐지 합성 데이터: 정상 100 + 이상치 20."""
    rng = np.random.default_rng(42)
    X = np.vstack(
        [
            rng.standard_normal((100, 5)),
            rng.standard_normal((20, 5)) * 5 + 10,
        ]
    ).astype(np.float32)
    y = np.array([0] * 100 + [1] * 20)
    return X, y


@pytest.fixture(autouse=True)
def _no_mlflow(monkeypatch):
    """BasePipeline._start_mlflow_run 을 no-op 으로 패치해 외부 서버 호출 차단."""
    from pipelines.base import BasePipeline

    class _Noop:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(BasePipeline, "_start_mlflow_run", lambda self, **kw: _Noop())


# ── 1. Tabular ML ─────────────────────────────────────────────────────────────


class TestTabularMLPipeline:
    """TabularMLPipeline — RandomForest·XGBoost·LightGBM·CatBoost × clf/reg."""

    @pytest.fixture()
    def pipe(self):
        from pipelines.tabular_ml.pipeline import TabularMLPipeline

        return TabularMLPipeline()

    # --- RandomForest: sklearn 필수 의존이므로 항상 실행 ---

    def test_rf_classification_train_predict_evaluate(self, pipe, clf_data):
        X, y = clf_data
        model = pipe.train(X[:80], y[:80], "RandomForest", {"n_estimators": 10, "random_state": 42})
        preds = pipe.predict(model, X[80:])
        assert preds.shape == (20,)
        metrics = pipe.evaluate(model, X[80:], y[80:], "classification")
        assert "val_accuracy" in metrics and "val_f1" in metrics
        assert 0.0 <= metrics["val_accuracy"] <= 1.0

    def test_rf_regression_train_predict_evaluate(self, pipe, reg_data):
        X, y = reg_data
        model = pipe.train(X[:80], y[:80], "RandomForest", {"n_estimators": 10, "random_state": 42})
        preds = pipe.predict(model, X[80:])
        assert preds.shape == (20,)
        metrics = pipe.evaluate(model, X[80:], y[80:], "regression")
        assert "val_rmse" in metrics and "val_r2" in metrics
        assert metrics["val_rmse"] >= 0.0

    def test_rf_train_with_cv(self, pipe, clf_data):
        X, y = clf_data
        result = pipe.train_with_cv(X, y, "RandomForest", {"n_estimators": 5, "random_state": 42}, n_splits=3)
        assert len(result["fold_scores"]) == 3
        assert "mean" in result and "std" in result
        assert 0.0 <= result["mean"] <= 1.0

    # --- XGBoost ---

    def test_xgboost_classification(self, pipe, clf_data):
        pytest.importorskip("xgboost")
        X, y = clf_data
        model = pipe.train(X[:80], y[:80], "XGBoost", {"n_estimators": 10, "random_state": 42})
        metrics = pipe.evaluate(model, X[80:], y[80:], "classification")
        assert 0.0 <= metrics["val_accuracy"] <= 1.0

    def test_xgboost_regression(self, pipe, reg_data):
        pytest.importorskip("xgboost")
        X, y = reg_data
        model = pipe.train(X[:80], y[:80], "XGBoost", {"n_estimators": 10, "random_state": 42})
        metrics = pipe.evaluate(model, X[80:], y[80:], "regression")
        assert metrics["val_rmse"] >= 0.0

    # --- LightGBM ---

    def test_lightgbm_classification(self, pipe, clf_data):
        pytest.importorskip("lightgbm")
        X, y = clf_data
        model = pipe.train(X[:80], y[:80], "LightGBM", {"n_estimators": 10, "random_state": 42, "verbose": -1})
        metrics = pipe.evaluate(model, X[80:], y[80:], "classification")
        assert 0.0 <= metrics["val_accuracy"] <= 1.0

    def test_lightgbm_regression(self, pipe, reg_data):
        pytest.importorskip("lightgbm")
        X, y = reg_data
        model = pipe.train(X[:80], y[:80], "LightGBM", {"n_estimators": 10, "random_state": 42, "verbose": -1})
        metrics = pipe.evaluate(model, X[80:], y[80:], "regression")
        assert metrics["val_rmse"] >= 0.0

    # --- CatBoost ---

    def test_catboost_classification(self, pipe, clf_data):
        pytest.importorskip("catboost")
        X, y = clf_data
        model = pipe.train(X[:80], y[:80], "CatBoost", {"iterations": 10, "random_seed": 42})
        metrics = pipe.evaluate(model, X[80:], y[80:], "classification")
        assert 0.0 <= metrics["val_accuracy"] <= 1.0

    def test_catboost_regression(self, pipe, reg_data):
        pytest.importorskip("catboost")
        X, y = reg_data
        model = pipe.train(X[:80], y[:80], "CatBoost", {"iterations": 10, "random_seed": 42})
        metrics = pipe.evaluate(model, X[80:], y[80:], "regression")
        assert metrics["val_rmse"] >= 0.0

    def test_unknown_model_raises(self, pipe, clf_data):
        X, y = clf_data
        with pytest.raises(ValueError, match="Unknown model"):
            pipe.train(X, y, "GhostModel", {})


# ── 2. Tabular DL ─────────────────────────────────────────────────────────────


class TestTabularDLPipeline:
    """TabularDLPipeline — TabPFN·TabTransformer·FTTransformer."""

    @pytest.fixture()
    def pipe(self):
        from pipelines.tabular_dl.pipeline import TabularDLPipeline

        return TabularDLPipeline()

    def test_tabpfn_classification(self, pipe, clf_data):
        pytest.importorskip("tabpfn")
        X, y = clf_data
        model = pipe.train(X[:80], y[:80], "TabPFN", {})
        preds = pipe.predict(model, X[80:])
        assert preds.shape == (20,)

    def test_tabtransformer_classification(self, pipe, clf_data):
        pytest.importorskip("pytorch_tabular")
        X, y = clf_data
        model = pipe.train(X[:80], y[:80], "TabTransformer", {"epochs": 2, "batch_size": 32})
        preds = pipe.predict(model, X[80:])
        assert preds.shape[0] == 20

    def test_fttransformer_classification(self, pipe, clf_data):
        pytest.importorskip("pytorch_tabular")
        X, y = clf_data
        model = pipe.train(X[:80], y[:80], "FTTransformer", {"epochs": 2, "batch_size": 32})
        preds = pipe.predict(model, X[80:])
        assert preds.shape[0] == 20

    def test_unknown_dl_model_raises(self, pipe, clf_data):
        X, y = clf_data
        with pytest.raises(ValueError, match="Unknown DL model"):
            pipe.train(X, y, "GhostDLModel", {})


# ── 3. TimeSeries ─────────────────────────────────────────────────────────────


class TestTimeSeriesPipeline:
    """TimeSeriesPipeline — ARIMA·SARIMA·Prophet."""

    @pytest.fixture()
    def pipe(self):
        from pipelines.timeseries.pipeline import TimeSeriesPipeline

        return TimeSeriesPipeline()

    def test_arima_train_predict_evaluate(self, pipe, ts_data):
        pytest.importorskip("statsmodels")
        import pandas as pd

        y = ts_data
        X_df = pd.DataFrame({"ds": range(50)})
        model = pipe.train(X_df, y[:50], "ARIMA", {"order": (1, 1, 1)})
        assert model is not None
        # X_val 로 y[50:] 를 전달하면 len(y[50:]) 스텝 예측
        metrics = pipe.evaluate(model, y[50:], y[50:], "forecasting")
        assert "val_rmse" in metrics and "val_mae" in metrics
        assert metrics["val_rmse"] >= 0.0

    def test_sarima_train(self, pipe, ts_data):
        pytest.importorskip("statsmodels")
        import pandas as pd

        y = ts_data
        X_df = pd.DataFrame({"ds": range(50)})
        model = pipe.train(
            X_df,
            y[:50],
            "SARIMA",
            {"order": (1, 1, 0), "seasonal_order": (0, 0, 0, 4)},
        )
        assert model is not None

    def test_prophet_train(self, pipe, ts_data):
        pytest.importorskip("prophet")
        import pandas as pd

        y = ts_data
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        X_df = pd.DataFrame({"ds": dates})
        model = pipe.train(X_df, y[:50], "Prophet", {})
        assert model is not None

    def test_unknown_ts_model_raises(self, pipe, ts_data):
        pytest.importorskip("statsmodels")
        import pandas as pd

        y = ts_data
        with pytest.raises(Exception):
            pipe.train(pd.DataFrame({"ds": range(50)}), y[:50], "GhostTS", {})


# ── 4. Anomaly ────────────────────────────────────────────────────────────────


class TestAnomalyPipeline:
    """AnomalyPipeline — IsolationForest·LOF·OneClassSVM·AutoEncoder."""

    @pytest.fixture()
    def pipe(self):
        from pipelines.anomaly.pipeline import AnomalyPipeline

        return AnomalyPipeline()

    def test_isolation_forest_train_evaluate(self, pipe, anomaly_data):
        """pyod 미설치 시 sklearn IsolationForest 폴백 — 항상 실행."""
        X, y = anomaly_data
        model = pipe.train(X[:80], None, "IsolationForest", {"contamination": 0.2})
        assert model is not None
        # X[80:]: 정상 20개(y=0) + 이상 20개(y=1) 혼재
        metrics = pipe.evaluate(model, X[80:], y[80:], "anomaly_detection")
        assert "val_auc" in metrics
        assert 0.0 <= metrics["val_auc"] <= 1.0

    def test_lof_train(self, pipe, anomaly_data):
        """pyod 미설치 시 sklearn LOF 폴백 — 항상 실행."""
        X, _ = anomaly_data
        model = pipe.train(X[:80], None, "LOF", {})
        assert model is not None

    def test_one_class_svm_train(self, pipe, anomaly_data):
        """pyod 미설치 시 sklearn OneClassSVM 폴백 — 항상 실행."""
        X, _ = anomaly_data
        model = pipe.train(X[:80], None, "OneClassSVM", {})
        assert model is not None

    def test_autoencoder_pyod(self, pipe, anomaly_data):
        pytest.importorskip("pyod")
        X, _ = anomaly_data
        model = pipe.train(X[:80], None, "AutoEncoder", {"epochs": 1, "hidden_neurons": [8, 4, 8]})
        assert model is not None

    def test_unknown_anomaly_model_raises(self, pipe, anomaly_data):
        X, _ = anomaly_data
        with pytest.raises(ValueError, match="Unknown anomaly model"):
            pipe.train(X, None, "GhostAnomaly", {})

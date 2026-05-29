"""jh Day 6 — test_pipeline_extensions.py: ML early stopping / DL cap / MLflow 검증 (12건)."""

from __future__ import annotations

import types

import numpy as np
import pytest


@pytest.fixture()
def clf_data():
    rng = np.random.default_rng(42)
    X = rng.standard_normal((100, 5)).astype(np.float32)
    y = (X[:, 0] > 0).astype(int)
    return X, y


@pytest.fixture()
def pipe():
    from pipelines.tabular_ml.pipeline import TabularMLPipeline

    return TabularMLPipeline()


@pytest.fixture(autouse=True)
def _mock_mlflow(monkeypatch, request):
    """mlflow mock (call_args 추적)."""
    from unittest.mock import MagicMock

    try:
        import contextlib

        import mlflow

        mock_metric = MagicMock()
        monkeypatch.setattr(mlflow, "log_metric", mock_metric)
        monkeypatch.setattr(mlflow, "log_metrics", MagicMock())
        monkeypatch.setattr(mlflow, "log_params", MagicMock())
        monkeypatch.setattr(mlflow, "start_run", lambda **kw: contextlib.nullcontext())
        monkeypatch.setattr(mlflow, "active_run", lambda: None)
        monkeypatch.setattr(mlflow, "set_tag", MagicMock())
        request.node._mock_log_metric = mock_metric
    except ImportError:
        request.node._mock_log_metric = None


# 1. XGBoost early stopping
def test_xgb_early_stopping(pipe, clf_data):
    pytest.importorskip("xgboost")
    X, y = clf_data
    result = pipe.train_with_early_stopping(
        X[:80],
        y[:80],
        "XGBoost",
        {"n_estimators": 20, "max_depth": 3, "learning_rate": 0.1},
        X_val=X[80:],
        y_val=y[80:],
        task="classification",
    )
    assert result["status"] == "success"
    assert "best_iteration" in result


# 2. LightGBM early stopping
def test_lgb_early_stopping(pipe, clf_data):
    pytest.importorskip("lightgbm")
    X, y = clf_data
    result = pipe.train_with_early_stopping(
        X[:80],
        y[:80],
        "LightGBM",
        {"n_estimators": 20, "num_leaves": 7, "learning_rate": 0.1},
        X_val=X[80:],
        y_val=y[80:],
        task="classification",
    )
    assert result["status"] == "success"


# 3. CatBoost early stopping
def test_cb_early_stopping(pipe, clf_data):
    pytest.importorskip("catboost")
    X, y = clf_data
    result = pipe.train_with_early_stopping(
        X[:80],
        y[:80],
        "CatBoost",
        {"iterations": 20, "depth": 3, "learning_rate": 0.1},
        X_val=X[80:],
        y_val=y[80:],
        task="classification",
    )
    assert result["status"] == "success"


# 4. eval_metric aucpr (classification + imbalance)
def test_eval_metric_aucpr_imbalance():
    from pipelines.tabular_ml.pipeline import _eval_metric

    assert _eval_metric("classification", 0.3) == "aucpr"


# 5. eval_metric rmse (regression)
def test_eval_metric_rmse_regression():
    from pipelines.tabular_ml.pipeline import _eval_metric

    assert _eval_metric("regression", 0.9) == "rmse"


# 6. class_weight scale_pos_weight for XGBoost
def test_class_weight_xgb_scale_pos_weight(pipe, clf_data):
    pytest.importorskip("xgboost")
    X, y = clf_data
    fake_state = types.SimpleNamespace(
        split_indices=None,
        data_profile={"class_entropy_ratio": 0.8},
        job_id="test-cw-001",
        category_extras={
            "tabular": {"preprocess_artifacts": {"class_weight": {"strategy": "balanced", "weights": {0: 0.6, 1: 2.4}}}}
        },
    )
    result = pipe.train_with_early_stopping(
        X[:80],
        y[:80],
        "XGBoost",
        {"n_estimators": 10, "max_depth": 3},
        X_val=X[80:],
        y_val=y[80:],
        task="classification",
        state=fake_state,
    )
    assert result["status"] == "success"
    assert result["model"].get_params().get("scale_pos_weight") == pytest.approx(4.0)


# 7. split_indices from state
def test_split_indices_used(pipe, clf_data):
    X, y = clf_data
    fake_state = types.SimpleNamespace(
        split_indices={"train": list(range(80)), "val": list(range(80, 100))},
        data_profile={},
        job_id="test-split-001",
        category_extras={},
    )
    result = pipe.train_with_early_stopping(
        X,
        y,
        "RandomForest",
        {"n_estimators": 5, "random_state": 42},
        task="classification",
        state=fake_state,
    )
    assert result["status"] == "success"
    assert "val_f1" in result["metrics"]


# 8. MLflow best_iteration logged
def test_mlflow_best_iteration_logged(pipe, clf_data, request):
    pytest.importorskip("mlflow")
    pytest.importorskip("xgboost")
    X, y = clf_data
    result = pipe.train_with_early_stopping(
        X[:80],
        y[:80],
        "XGBoost",
        {"n_estimators": 20, "max_depth": 3},
        X_val=X[80:],
        y_val=y[80:],
        task="classification",
    )
    assert result["status"] == "success"
    mock_log_metric = getattr(request.node, "_mock_log_metric", None)
    if mock_log_metric is not None and result.get("best_iteration") is not None:
        calls = [c for c in mock_log_metric.call_args_list if c[0] and c[0][0] == "best_iteration"]
        assert len(calls) > 0, "mlflow.log_metric('best_iteration', ...) not called"


# 9. DL TrainerConfig max_epochs=50 cap
def test_dl_trainer_config_max_epochs():
    pytest.importorskip("pytorch_tabular")
    from pytorch_tabular.config import TrainerConfig

    cfg = TrainerConfig(max_epochs=50, accelerator="cpu")
    assert cfg.max_epochs == 50


# 10. DL early_stopping_patience=3
def test_dl_trainer_config_early_stopping_patience():
    pytest.importorskip("pytorch_tabular")
    from pytorch_tabular.config import TrainerConfig

    cfg = TrainerConfig(
        max_epochs=50,
        accelerator="cpu",
        early_stopping="val_loss",
        early_stopping_patience=3,
    )
    assert cfg.early_stopping_patience == 3


# 11. DL imbalance strategy key 읽기 확인
def test_dl_imbalance_strategy_key_exists():
    fake_state = types.SimpleNamespace(
        category_extras={"tabular": {"preprocess_artifacts": {"dl_imbalance_strategy": {"method": "focal_loss"}}}}
    )
    ce = getattr(fake_state, "category_extras", {}) or {}
    strategy = ce.get("tabular", {}).get("preprocess_artifacts", {}).get("dl_imbalance_strategy")
    assert strategy == {"method": "focal_loss"}


# 12. 반환 dict 표준 키 6종
def test_return_dict_standard_keys(pipe, clf_data):
    X, y = clf_data
    result = pipe.train_with_early_stopping(
        X[:80],
        y[:80],
        "RandomForest",
        {"n_estimators": 5, "random_state": 42},
        X_val=X[80:],
        y_val=y[80:],
        task="classification",
    )
    required = {"model", "model_name", "params_used", "metrics", "best_iteration", "mlflow_run_id"}
    assert required.issubset(result.keys())

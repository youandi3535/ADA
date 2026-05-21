"""tabular_ml.search_space — Optuna 탐색 공간 (Day07 §2)."""
from __future__ import annotations

from typing import Any


def get_search_space(model_name: str, trial: Any) -> dict[str, Any]:
    if model_name == "RandomForest":
        return {
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 15),
            "min_samples_split": trial.suggest_int("min_samples_split", 2, 10),
            "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 5),
            "max_features": trial.suggest_categorical(
                "max_features", ["sqrt", "log2", None],
            ),
            "class_weight": trial.suggest_categorical(
                "class_weight", ["balanced", None],
            ),
            "n_jobs": -1,
            "random_state": 42,
        }
    if model_name == "XGBoost":
        return {
            "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "eval_metric": "logloss",
            "random_state": 42,
            "n_jobs": -1,
        }
    if model_name == "LightGBM":
        return {
            "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 100, 1000),
            "num_leaves": trial.suggest_int("num_leaves", 20, 300),
            "min_child_samples": trial.suggest_int("min_child_samples", 5, 100),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.5, 1.0),
            "bagging_fraction": trial.suggest_float("bagging_fraction", 0.5, 1.0),
            "bagging_freq": trial.suggest_int("bagging_freq", 1, 7),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            "verbose": -1,
            "random_state": 42,
            "n_jobs": -1,
        }
    if model_name == "CatBoost":
        return {
            "learning_rate": trial.suggest_float("learning_rate", 1e-3, 0.3, log=True),
            "iterations": trial.suggest_int("iterations", 100, 500),
            "depth": trial.suggest_int("depth", 3, 10),
            "l2_leaf_reg": trial.suggest_float("l2_leaf_reg", 1e-8, 10.0, log=True),
            "border_count": trial.suggest_int("border_count", 32, 255),
            "verbose": 0,
            "random_state": 42,
        }
    raise ValueError(f"Unknown model: {model_name}")


# v2.4 — FLAML warm-start (R-1006)
def get_flaml_warm_start(task: str = "classification") -> dict[str, Any]:
    return {
        "time_budget": 60,
        "metric": "accuracy" if task == "classification" else "rmse",
        "task": task,
        "estimator_list": ["lgbm", "xgboost", "rf", "catboost"],
        "seed": 42,
    }

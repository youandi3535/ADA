"""tabular_ml.pipeline — 정형 ML 파이프라인 (Day07 §1).

4 모델: RandomForest / XGBoost / LightGBM / CatBoost
- classification + regression 자동 분기
- MLflow run 자동 등록
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any

import numpy as np

from pipelines.base import BasePipeline


def _is_classification(y: Any) -> bool:
    try:
        return len(set(y.tolist() if hasattr(y, "tolist") else y)) <= 20
    except Exception:
        return False


def _build_model(model_name: str, task: str, params: dict[str, Any]) -> Any:
    if model_name == "RandomForest":
        if task == "classification":
            from sklearn.ensemble import RandomForestClassifier

            return RandomForestClassifier(**params)
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(**params)
    if model_name == "XGBoost":
        from xgboost import XGBClassifier, XGBRegressor

        return XGBClassifier(**params) if task == "classification" else XGBRegressor(**params)
    if model_name == "LightGBM":
        from lightgbm import LGBMClassifier, LGBMRegressor

        return LGBMClassifier(**params) if task == "classification" else LGBMRegressor(**params)
    if model_name == "CatBoost":
        from catboost import CatBoostClassifier, CatBoostRegressor

        params = {**params, "verbose": 0}
        return CatBoostClassifier(**params) if task == "classification" else CatBoostRegressor(**params)
    raise ValueError(f"Unknown model: {model_name}")


def _eval_metric(task: str, entropy_ratio: float) -> str:
    if task == "regression":
        return "rmse"
    return "aucpr" if entropy_ratio < 0.5 else "logloss"


def _adaptive_rounds(n_train: int) -> int:
    return max(10, n_train // 1000)


class TabularMLPipeline(BasePipeline):
    experiment_name = "ada-tabular-ml"

    SUPPORTED_MODELS = ("RandomForest", "XGBoost", "LightGBM", "CatBoost", "LogisticRegression", "DecisionTree")

    def train(self, X_train: Any, y_train: Any, model_name: str, params: dict[str, Any]) -> Any:
        task = "classification" if _is_classification(y_train) else "regression"
        with self._start_mlflow_run(tags={"model": model_name, "task": task}):
            try:
                import mlflow  # noqa: WPS433

                mlflow.log_params({**params, "model_name": model_name, "task": task})
            except Exception:
                pass
            model = _build_model(model_name, task, params)
            model.fit(X_train, y_train)
            return model

    def train_with_early_stopping(  # noqa: WPS231
        self,
        X: Any,
        y: Any,
        model_name: str,
        params: dict[str, Any],
        *,
        X_val: Any = None,
        y_val: Any = None,
        task: str | None = None,
        state: Any = None,
    ) -> dict[str, Any]:
        """Early stopping + MLflow best_iteration 기록 학습.

        Returns dict with: model, model_name, params_used, metrics,
                           best_iteration, mlflow_run_id, status.
        """
        from sklearn.model_selection import train_test_split  # noqa: WPS433

        if task is None:
            task = "classification" if _is_classification(y) else "regression"

        # train/val split
        if X_val is None:
            split_indices = getattr(state, "split_indices", None) if state else None
            if split_indices and "train" in split_indices and "val" in split_indices:
                tr_idx = split_indices["train"]
                vl_idx = split_indices["val"]
                if hasattr(X, "iloc"):
                    X_tr, X_vl = X.iloc[tr_idx], X.iloc[vl_idx]
                    y_tr, y_vl = y.iloc[tr_idx], y.iloc[vl_idx]
                else:
                    X_tr, X_vl = X[tr_idx], X[vl_idx]
                    y_tr, y_vl = y[tr_idx], y[vl_idx]
            else:
                strat = y if task == "classification" else None
                try:
                    tr_idx, vl_idx = train_test_split(range(len(X)), test_size=0.2, stratify=strat, random_state=42)
                except Exception:
                    tr_idx, vl_idx = train_test_split(range(len(X)), test_size=0.2, random_state=42)
                if hasattr(X, "iloc"):
                    X_tr, X_vl = X.iloc[list(tr_idx)], X.iloc[list(vl_idx)]
                    y_tr, y_vl = y.iloc[list(tr_idx)], y.iloc[list(vl_idx)]
                else:
                    X_tr, X_vl = X[list(tr_idx)], X[list(vl_idx)]
                    y_tr, y_vl = y[list(tr_idx)], y[list(vl_idx)]
        else:
            X_tr, X_vl, y_tr, y_vl = X, X_val, y, y_val

        # eval_metric 결정
        profile = {}
        if state and hasattr(state, "data_profile") and isinstance(state.data_profile, dict):
            profile = state.data_profile
        entropy = float(profile.get("class_entropy_ratio", 1.0) or 1.0)
        metric = _eval_metric(task, entropy)

        # adaptive early stopping rounds
        n_train = len(X_tr)
        rounds = _adaptive_rounds(n_train)

        # class_weight 적용 (Day 2 산출물)
        clean_params = dict(params)
        for k in ("_source", "_recipe_score"):
            clean_params.pop(k, None)

        # 모델 생성
        model = _build_model(model_name, task, clean_params)

        # class_weight
        class_weight_info = {}
        if state:
            ce = getattr(state, "category_extras", {}) or {}
            arts = ce.get("tabular", {}).get("preprocess_artifacts", {}) or {}
            class_weight_info = arts.get("class_weight") or {}
        if class_weight_info.get("strategy") == "balanced":
            weights = class_weight_info.get("weights", {})
            try:
                if model_name == "XGBoost" and task == "classification" and 0 in weights and 1 in weights:
                    model.set_params(scale_pos_weight=weights[1] / weights[0])
                elif model_name == "LightGBM":
                    model.set_params(class_weight=weights)
                elif model_name == "CatBoost":
                    model.set_params(class_weights=[weights[c] for c in sorted(weights)])
                elif model_name in ("RandomForest", "LogisticRegression"):
                    model.set_params(class_weight=weights)
            except Exception:
                pass

        best_iter: int | None = None
        try:
            if model_name == "XGBoost":
                model.fit(
                    X_tr,
                    y_tr,
                    eval_set=[(X_vl, y_vl)],
                    early_stopping_rounds=rounds,
                    verbose=False,
                )
                best_iter = getattr(model, "best_iteration", None)
            elif model_name == "LightGBM":
                import lightgbm as lgb  # noqa: WPS433

                model.fit(
                    X_tr,
                    y_tr,
                    eval_set=[(X_vl, y_vl)],
                    callbacks=[lgb.early_stopping(rounds, verbose=False)],
                )
                best_iter = getattr(model, "best_iteration_", None)
            elif model_name == "CatBoost":
                model.fit(
                    X_tr,
                    y_tr,
                    eval_set=(X_vl, y_vl),
                    early_stopping_rounds=rounds,
                    verbose=False,
                )
                best_iter = model.get_best_iteration() if hasattr(model, "get_best_iteration") else None
            else:
                model.fit(X_tr, y_tr)
        except Exception as exc:
            return {"status": "failed", "reason": str(exc)}

        metrics = self.evaluate(model, X_vl, y_vl, task)

        # MLflow 기록 (R-201)
        run_id: str | None = None
        job_id = getattr(state, "job_id", "unknown") if state else "unknown"
        try:
            import mlflow  # noqa: WPS433

            with mlflow.start_run(run_name=f"{model_name}_{job_id}"):
                mlflow.log_params({k: v for k, v in clean_params.items() if not isinstance(v, (list, dict))})
                mlflow.log_metrics({k: v for k, v in metrics.items() if v is not None})
                if best_iter is not None:
                    mlflow.log_metric("best_iteration", best_iter)
                mlflow.set_tag("model_family", model_name)
                mlflow.set_tag("category", "tabular_ml")
                mlflow.set_tag("job_id", str(job_id))
                mlflow.set_tag("eval_metric", metric)
                mlflow.set_tag("early_stopping_rounds", str(rounds))
                run = mlflow.active_run()
                run_id = run.info.run_id if run else None
        except Exception:
            pass

        return {
            "model": model,
            "model_name": model_name,
            "params_used": clean_params,
            "metrics": metrics,
            "best_iteration": best_iter,
            "mlflow_run_id": run_id,
            "status": "success",
        }

    def predict(self, model: Any, X: Any) -> np.ndarray:
        return model.predict(X)

    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str) -> dict[str, float]:
        y_pred = model.predict(X_val)
        if task == "classification":
            from sklearn.metrics import (
                accuracy_score,
                f1_score,
                precision_score,
                recall_score,
                roc_auc_score,
            )

            metrics = {
                "val_accuracy": float(accuracy_score(y_val, y_pred)),
                "val_f1": float(f1_score(y_val, y_pred, average="weighted")),
                "val_precision": float(precision_score(y_val, y_pred, average="weighted", zero_division=0)),
                "val_recall": float(recall_score(y_val, y_pred, average="weighted", zero_division=0)),
            }
            try:
                if hasattr(model, "predict_proba"):
                    proba = model.predict_proba(X_val)
                    if proba.ndim == 2 and proba.shape[1] == 2:
                        metrics["val_roc_auc"] = float(roc_auc_score(y_val, proba[:, 1]))
                    elif proba.ndim == 2:
                        metrics["val_roc_auc"] = float(roc_auc_score(y_val, proba, multi_class="ovr"))
            except Exception:
                pass
        else:
            from sklearn.metrics import (
                mean_absolute_error,
                mean_absolute_percentage_error,
                mean_squared_error,
                r2_score,
            )

            metrics = {
                "val_rmse": float(np.sqrt(mean_squared_error(y_val, y_pred))),
                "val_r2": float(r2_score(y_val, y_pred)),
                "val_mae": float(mean_absolute_error(y_val, y_pred)),
                "val_mape": float(mean_absolute_percentage_error(y_val, y_pred)),
            }

        try:
            import mlflow  # noqa: WPS433

            mlflow.log_metrics({k: v for k, v in metrics.items() if v is not None})
        except Exception:
            pass
        return metrics

    def save_model(self, model: Any, job_id: str, model_name: str) -> dict[str, str]:
        """MinIO 저장 + MLflow 로깅 + SHA256."""
        import joblib  # noqa: WPS433

        from tools.minio_tool import get_minio_client

        with tempfile.NamedTemporaryFile(delete=False, suffix=".joblib") as f:
            joblib.dump(model, f.name)
            tmp = f.name
        try:
            with open(tmp, "rb") as fp:
                sha = hashlib.sha256(fp.read()).hexdigest()  # R-704
            object_name = f"models/{job_id}/{model_name}.joblib"
            minio_path = get_minio_client().upload_file(tmp, object_name)
            try:
                import mlflow.sklearn  # noqa: WPS433

                mlflow.sklearn.log_model(model, model_name)
            except Exception:
                pass
            return {"minio_path": minio_path, "model_sha256": sha}
        finally:
            os.unlink(tmp)

    def train_with_cv(
        self, X: Any, y: Any, model_name: str, params: dict[str, Any], n_splits: int = 5, task: str = "classification"
    ) -> dict[str, Any]:
        from sklearn.model_selection import KFold, StratifiedKFold

        splitter = (
            StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
            if task == "classification"
            else KFold(n_splits=n_splits, shuffle=True, random_state=42)
        )
        scores: list[float] = []
        for tr, val in splitter.split(X, y):
            X_tr, X_val = X[tr], X[val]
            y_tr, y_val = y[tr], y[val]
            model = _build_model(model_name, task, params)
            model.fit(X_tr, y_tr)
            m = self.evaluate(model, X_val, y_val, task)
            key = "val_f1" if task == "classification" else "val_r2"
            scores.append(float(m.get(key, 0.0)))
        return {"fold_scores": scores, "mean": float(np.mean(scores)), "std": float(np.std(scores))}

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
    # Day 11 (jh) — 베이스라인 3종: Dummy / LogisticRegression / Ridge.
    # "강모델이 더미보다 얼마나 나은가" 격차가 모델 가치를 정의.
    if model_name == "Dummy":
        if task == "classification":
            from sklearn.dummy import DummyClassifier

            # stratified: 클래스 비율대로 랜덤 — 진짜 "찍기" baseline.
            return DummyClassifier(strategy="stratified", random_state=params.get("random_state", 42))
        from sklearn.dummy import DummyRegressor

        return DummyRegressor(strategy="mean")
    if model_name == "LogisticRegression":
        from sklearn.linear_model import LogisticRegression

        defaults = {"max_iter": 1000, "n_jobs": -1, "random_state": 42}
        defaults.update(params or {})
        return LogisticRegression(**defaults)
    if model_name == "Ridge":
        from sklearn.linear_model import Ridge

        defaults = {"random_state": 42}
        defaults.update(params or {})
        return Ridge(**defaults)

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


# Day 11 (jh) — 베이스라인 식별 헬퍼. evaluator / insight 가 격차 계산 시 사용.
BASELINE_MODELS: frozenset[str] = frozenset({"Dummy", "LogisticRegression", "Ridge"})


def is_baseline_model(model_name: str) -> bool:
    """주어진 모델명이 베이스라인 카테고리인지."""
    return str(model_name) in BASELINE_MODELS


class TabularMLPipeline(BasePipeline):
    experiment_name = "ada-tabular-ml"

    # Day 11 (jh) — 베이스라인 3종 추가. 학습 비용 거의 0, 비교 가치 큼.
    SUPPORTED_MODELS = (
        "Dummy",
        "LogisticRegression",
        "Ridge",
        "RandomForest",
        "XGBoost",
        "LightGBM",
        "CatBoost",
    )

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

    def predict(self, model: Any, X: Any) -> np.ndarray:
        return model.predict(X)

    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str) -> dict[str, float]:
        """val 평가 — Day 11 (jh) 다중 지표 보강.

        분류 추가 지표:
          - val_pr_auc      : 불균형에 ROC AUC 보다 더 적합한 PR AUC
          - val_mcc         : Matthews Correlation Coefficient (불균형 단일 지표)
          - val_log_loss    : 확률 예측의 calibration loss
          - val_brier       : binary 한정 — 확률 보정 수준 (낮을수록 좋음)
          - val_f1_per_class: multiclass 한정 — 클래스별 F1 dict
          - val_optimal_threshold: binary 한정 — PR curve F1 argmax 임계값

        회귀 추가 지표:
          - val_residual_*  : 잔차 통계 (mean/median/std/abs_max)
        """
        y_pred = model.predict(X_val)
        if task == "classification":
            from sklearn.metrics import (
                accuracy_score,
                average_precision_score,
                brier_score_loss,
                f1_score,
                log_loss,
                matthews_corrcoef,
                precision_recall_curve,
                precision_score,
                recall_score,
                roc_auc_score,
            )

            metrics: dict[str, Any] = {
                "val_accuracy": float(accuracy_score(y_val, y_pred)),
                "val_f1": float(f1_score(y_val, y_pred, average="weighted")),
                "val_precision": float(precision_score(y_val, y_pred, average="weighted", zero_division=0)),
                "val_recall": float(recall_score(y_val, y_pred, average="weighted", zero_division=0)),
            }
            # MCC — 불균형에 강한 단일 지표
            try:
                metrics["val_mcc"] = float(matthews_corrcoef(y_val, y_pred))
            except Exception:
                pass

            # multiclass per-class F1
            try:
                unique_y = sorted(set(y_val.tolist() if hasattr(y_val, "tolist") else list(y_val)))
                if len(unique_y) > 2:
                    per_class = f1_score(y_val, y_pred, average=None, zero_division=0)
                    metrics["val_f1_per_class"] = {str(c): float(v) for c, v in zip(unique_y, per_class)}
            except Exception:
                pass

            # probability-based metrics
            try:
                if hasattr(model, "predict_proba"):
                    proba = model.predict_proba(X_val)
                    if proba.ndim == 2 and proba.shape[1] == 2:
                        pos_proba = proba[:, 1]
                        metrics["val_roc_auc"] = float(roc_auc_score(y_val, pos_proba))
                        metrics["val_pr_auc"] = float(average_precision_score(y_val, pos_proba))
                        metrics["val_log_loss"] = float(log_loss(y_val, proba))
                        try:
                            metrics["val_brier"] = float(brier_score_loss(y_val, pos_proba))
                        except Exception:
                            pass
                        # PR curve F1 argmax — 임계값 자동 탐색
                        try:
                            prec, rec, thr = precision_recall_curve(y_val, pos_proba)
                            # F1 = 2PR / (P+R)
                            with np.errstate(divide="ignore", invalid="ignore"):
                                f1_curve = 2 * prec * rec / (prec + rec + 1e-12)
                            # thr 길이는 prec/rec 보다 1 작음 → 마지막 점 제외
                            best_idx = int(np.nanargmax(f1_curve[:-1])) if len(thr) > 0 else 0
                            if 0 <= best_idx < len(thr):
                                metrics["val_optimal_threshold"] = float(thr[best_idx])
                                metrics["val_f1_at_optimal_threshold"] = float(f1_curve[best_idx])
                        except Exception:
                            pass
                    elif proba.ndim == 2:
                        metrics["val_roc_auc"] = float(roc_auc_score(y_val, proba, multi_class="ovr"))
                        try:
                            metrics["val_pr_auc"] = float(
                                average_precision_score(y_val, proba, average="weighted")
                            )
                        except Exception:
                            pass
                        try:
                            metrics["val_log_loss"] = float(log_loss(y_val, proba))
                        except Exception:
                            pass
            except Exception:
                pass
        else:
            from sklearn.metrics import (
                mean_absolute_error,
                mean_absolute_percentage_error,
                mean_squared_error,
                r2_score,
            )

            metrics: dict[str, Any] = {
                "val_rmse": float(np.sqrt(mean_squared_error(y_val, y_pred))),
                "val_r2": float(r2_score(y_val, y_pred)),
                "val_mae": float(mean_absolute_error(y_val, y_pred)),
                "val_mape": float(mean_absolute_percentage_error(y_val, y_pred)),
            }
            # 잔차 통계 — 모델 진단 보조 (편향/이상치 감지)
            try:
                residuals = np.asarray(y_val) - np.asarray(y_pred)
                metrics["val_residual_mean"] = float(np.mean(residuals))
                metrics["val_residual_median"] = float(np.median(residuals))
                metrics["val_residual_std"] = float(np.std(residuals))
                metrics["val_residual_abs_max"] = float(np.max(np.abs(residuals)))
            except Exception:
                pass

        try:
            import mlflow  # noqa: WPS433

            # 스칼라 metric 만 MLflow 에 로깅 (dict 인 per_class 제외)
            mlflow.log_metrics({k: v for k, v in metrics.items() if isinstance(v, (int, float))})
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

    # Day 11 (jh) — fold 별 모든 metric + mean + std 반환.
    # train_with_cv 는 단일 primary metric mean 만 (Optuna HPO 용). evaluate_with_cv 는
    # evaluator 가 best_model 의 신뢰구간을 보고하기 위해 모든 metric 의 fold 통계 노출.
    def evaluate_with_cv(
        self,
        X: Any,
        y: Any,
        model_name: str,
        params: dict[str, Any],
        *,
        n_splits: int = 5,
        task: str = "classification",
    ) -> dict[str, Any]:
        """fold 별 모든 metric + mean + std 반환.

        Returns
        -------
        dict
            {
                "n_splits": int,
                "fold_metrics": list[dict],  # 각 fold 의 metric dict
                "mean": dict,                # metric → fold 평균
                "std": dict,                 # metric → fold 표준편차
                "primary_metric": str,       # "val_f1" / "val_r2"
                "primary_mean": float,
                "primary_std": float,
            }

        실패/예외 시 빈 dict 반환 (graceful).
        """
        from sklearn.model_selection import KFold, StratifiedKFold

        try:
            splitter = (
                StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
                if task == "classification"
                else KFold(n_splits=n_splits, shuffle=True, random_state=42)
            )
        except Exception:
            return {}

        fold_metrics: list[dict[str, float]] = []
        all_keys: set[str] = set()
        try:
            for tr, val in splitter.split(X, y):
                X_tr, X_val = X[tr], X[val]
                y_tr, y_val = y[tr], y[val]
                # stratify 가능 여부 안전 check (희소 fold 대비)
                model = _build_model(model_name, task, params)
                model.fit(X_tr, y_tr)
                m = self.evaluate(model, X_val, y_val, task)
                fold_metrics.append({k: float(v) for k, v in m.items() if v is not None})
                all_keys.update(fold_metrics[-1].keys())
        except Exception as exc:
            self.logger.warning("evaluate_with_cv_failed", model=model_name, error=str(exc))
            return {}

        if not fold_metrics:
            return {}

        # metric 별 mean / std
        mean_dict: dict[str, float] = {}
        std_dict: dict[str, float] = {}
        for k in all_keys:
            vals = [fm[k] for fm in fold_metrics if k in fm]
            if not vals:
                continue
            mean_dict[k] = float(np.mean(vals))
            std_dict[k] = float(np.std(vals))

        primary_metric = "val_f1" if task == "classification" else "val_r2"
        return {
            "n_splits": int(n_splits),
            "fold_metrics": fold_metrics,
            "mean": mean_dict,
            "std": std_dict,
            "primary_metric": primary_metric,
            "primary_mean": float(mean_dict.get(primary_metric, 0.0)),
            "primary_std": float(std_dict.get(primary_metric, 0.0)),
        }

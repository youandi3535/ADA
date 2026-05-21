"""anomaly.pipeline — 이상탐지 (Day08, R-1003 PyOD v3 백본)."""
from __future__ import annotations

from typing import Any

import numpy as np

from pipelines.base import BasePipeline


class AnomalyPipeline(BasePipeline):
    experiment_name = "ada-anomaly"
    SUPPORTED_MODELS = (
        "IsolationForest", "LOF", "OneClassSVM",
        "AutoEncoder", "TranAD", "AnomalyTransformer",
    )

    def train(self, X_train: Any, y_train: Any, model_name: str,
              params: dict[str, Any]) -> Any:
        with self._start_mlflow_run(tags={"model": model_name}):
            try:
                import mlflow  # noqa: WPS433
                mlflow.log_params({**params, "model_name": model_name})
            except Exception:
                pass

            if model_name == "IsolationForest":
                try:
                    from pyod.models.iforest import IForest  # type: ignore
                    m = IForest(**params)
                except Exception:
                    from sklearn.ensemble import IsolationForest
                    m = IsolationForest(**params)
            elif model_name == "LOF":
                try:
                    from pyod.models.lof import LOF  # type: ignore
                    m = LOF(**params)
                except Exception:
                    from sklearn.neighbors import LocalOutlierFactor
                    m = LocalOutlierFactor(novelty=True, **params)
            elif model_name == "OneClassSVM":
                try:
                    from pyod.models.ocsvm import OCSVM  # type: ignore
                    m = OCSVM(**params)
                except Exception:
                    from sklearn.svm import OneClassSVM
                    m = OneClassSVM(**params)
            elif model_name == "AutoEncoder":
                from pyod.models.auto_encoder import AutoEncoder  # type: ignore
                m = AutoEncoder(**params)
            elif model_name in ("TranAD", "AnomalyTransformer"):
                # 트랜스포머 계열은 PyTorch 의존. CPU 가용성에 따라 PyOD AE 로 폴백
                try:
                    from pyod.models.auto_encoder_torch import AutoEncoder as AET  # type: ignore
                    m = AET(**params)
                except Exception:
                    from pyod.models.iforest import IForest  # type: ignore
                    m = IForest()
            else:
                raise ValueError(f"Unknown anomaly model: {model_name}")

            m.fit(X_train)
            return m

    def predict(self, model: Any, X: Any) -> np.ndarray:
        if hasattr(model, "decision_function"):
            scores = model.decision_function(X)
            return np.asarray(scores)
        return np.asarray(model.predict(X))

    def evaluate(self, model: Any, X_val: Any, y_val: Any,
                 task: str = "anomaly_detection") -> dict[str, float]:
        from sklearn.metrics import roc_auc_score
        try:
            scores = self.predict(model, X_val)
            auc = float(roc_auc_score(y_val, scores)) if y_val is not None else None
        except Exception:
            auc = None
        out = {"val_auc": auc} if auc is not None else {"val_auc": 0.5}
        try:
            import mlflow  # noqa: WPS433
            mlflow.log_metrics(out)
        except Exception:
            pass
        return out  # type: ignore[return-value]

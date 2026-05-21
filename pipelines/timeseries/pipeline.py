"""timeseries.pipeline — 시계열 파이프라인 (Day08).

지원: ARIMA, SARIMA, Prophet, Informer, TFT, PatchTST + StatsForecast(R-1007)
"""
from __future__ import annotations

from typing import Any

import numpy as np

from pipelines.base import BasePipeline


class TimeSeriesPipeline(BasePipeline):
    experiment_name = "ada-timeseries"
    SUPPORTED_MODELS = ("ARIMA", "SARIMA", "Prophet", "Informer", "TFT", "PatchTST")

    def train(self, X_train: Any, y_train: Any, model_name: str,
              params: dict[str, Any]) -> Any:
        """X_train: pd.DataFrame with date column. y_train: target series."""
        with self._start_mlflow_run(tags={"model": model_name}):
            try:
                import mlflow  # noqa: WPS433
                mlflow.log_params({**params, "model_name": model_name})
            except Exception:
                pass
            if model_name == "ARIMA":
                from statsmodels.tsa.arima.model import ARIMA
                return ARIMA(y_train, order=params.get("order", (1, 1, 1))).fit()
            if model_name == "SARIMA":
                from statsmodels.tsa.statespace.sarimax import SARIMAX
                return SARIMAX(
                    y_train,
                    order=params.get("order", (1, 1, 1)),
                    seasonal_order=params.get("seasonal_order", (1, 1, 1, 7)),
                ).fit(disp=False)
            if model_name == "Prophet":
                from prophet import Prophet  # type: ignore
                import pandas as pd  # noqa: WPS433
                df = pd.DataFrame({
                    "ds": X_train["ds"] if "ds" in X_train.columns else X_train.iloc[:, 0],
                    "y": y_train,
                })
                m = Prophet(**params)
                m.fit(df)
                return m
            if model_name in ("Informer", "TFT", "PatchTST"):
                return self._train_neural_ts(X_train, y_train, model_name, params)
            # StatsForecast fallback
            try:
                from statsforecast import StatsForecast  # type: ignore
                from statsforecast.models import AutoARIMA  # type: ignore
                import pandas as pd  # noqa: WPS433
                df = pd.DataFrame({"ds": range(len(y_train)),
                                    "y": y_train, "unique_id": "ts_1"})
                sf = StatsForecast(df=df, models=[AutoARIMA(season_length=7)], freq="D")
                sf.fit()
                return sf
            except Exception as e:
                raise ValueError(f"Unknown timeseries model: {model_name}") from e

    def _train_neural_ts(self, X: Any, y: Any, model_name: str,
                          params: dict[str, Any]) -> Any:
        try:
            from neuralforecast import NeuralForecast  # type: ignore
            from neuralforecast.models import TFT, PatchTST, Informer  # type: ignore
            import pandas as pd  # noqa: WPS433

            model_map = {"TFT": TFT, "PatchTST": PatchTST, "Informer": Informer}
            cls = model_map[model_name]
            horizon = params.get("horizon", 12)
            df = pd.DataFrame({"ds": range(len(y)), "y": y, "unique_id": "ts_1"})
            nf = NeuralForecast(models=[cls(h=horizon,
                                             input_size=params.get("input_size", 24))],
                                 freq="D")
            nf.fit(df)
            return nf
        except Exception as e:
            self.logger.warning("neuralforecast_unavailable", error=str(e))
            from statsmodels.tsa.arima.model import ARIMA
            return ARIMA(y, order=(1, 1, 1)).fit()

    def predict(self, model: Any, X: Any) -> np.ndarray:
        try:
            return np.asarray(model.forecast(steps=len(X)) if hasattr(model, "forecast")
                              else model.predict(X))
        except Exception:
            return np.asarray(model.predict(X))

    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str = "forecasting") -> dict[str, float]:
        from sklearn.metrics import mean_absolute_error, mean_squared_error
        y_pred = self.predict(model, X_val)
        y_pred = np.asarray(y_pred).flatten()[:len(y_val)]
        return {
            "val_rmse": float(np.sqrt(mean_squared_error(y_val[:len(y_pred)], y_pred))),
            "val_mae": float(mean_absolute_error(y_val[:len(y_pred)], y_pred)),
        }

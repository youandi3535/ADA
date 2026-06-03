"""timeseries.pipeline — 시계열 파이프라인 (Day08 + cs-day6 evaluate 확장).

지원: ARIMA, SARIMA, Prophet, Informer, TFT, PatchTST + StatsForecast(R-1007)

cs-day6 §F-Extension:
  - train() 시 instance 변수 저장 (_y_train_last / _seasonal_s / _model_obj)
  - evaluate() 확장 — naïve baseline + MASE + sMAPE + PI coverage (12 키)
    → cs-day7 evaluator 가 rmse_improvement_vs_naive 등 임계치 판정에 사용
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from pipelines.base import BasePipeline


class TimeSeriesPipeline(BasePipeline):
    experiment_name = "ada-timeseries"
    SUPPORTED_MODELS = ("ARIMA", "SARIMA", "Prophet", "Informer", "TFT", "PatchTST")

    def __init__(self) -> None:
        super().__init__()
        # cs-day6 F-ext-1 : 학습 시 보존하는 instance 변수
        self._y_train_last: Optional[np.ndarray] = None  # MASE 분모 + naïve baseline 용
        self._seasonal_s: int = 0  # seasonal period (0 = simple naïve)
        self._model_obj: Optional[Any] = None  # PI 추출용 (옵션)

    # ════════════════════════════════════════════════════════════
    # cs-day6 F-ext-1b : seasonal_period 추출
    # ════════════════════════════════════════════════════════════
    def _extract_seasonal_period(self, model_name: str, params: dict[str, Any]) -> int:
        """모델별 seasonal_period 추출 — 0 이면 simple naïve."""
        # SARIMA/SARIMAX : params["seasonal_order"][3]
        if model_name in ("SARIMA", "SARIMAX"):
            seasonal_order = params.get("seasonal_order", (0, 0, 0, 0))
            return int(seasonal_order[3]) if len(seasonal_order) >= 4 else 0
        # Prophet : 명시적 seasonal_period 없음
        if model_name == "Prophet":
            return int(params.get("seasonal_period", 0))
        # DL : freq 와 input_size 로 추정 (옵션)
        if model_name in ("Informer", "TFT", "PatchTST"):
            return int(params.get("seasonal_period", 0))
        # ARIMA / 기타 : 0 (simple naïve)
        return 0

    def train(self, X_train: Any, y_train: Any, model_name: str, params: dict[str, Any]) -> Any:
        """X_train: pd.DataFrame with date column. y_train: target series."""
        with self._start_mlflow_run(tags={"model": model_name}):
            try:
                import mlflow  # noqa: WPS433

                mlflow.log_params({**params, "model_name": model_name})
            except Exception:
                pass

            # ── F-ext-1a : 학습 전 instance 변수 저장 (모든 모델 공통) ──
            try:
                self._y_train_last = np.asarray(y_train, dtype=float).flatten()
            except Exception:
                self._y_train_last = None
            self._seasonal_s = self._extract_seasonal_period(model_name, params)

            model = self._train_dispatch(X_train, y_train, model_name, params)
            self._model_obj = model  # PI 추출 가능 모델 한정
            return model

    def _train_dispatch(self, X_train: Any, y_train: Any, model_name: str, params: dict[str, Any]) -> Any:
        if model_name == "ARIMA":
            from statsmodels.tsa.arima.model import ARIMA

            return ARIMA(
                y_train,
                order=params.get("order", (1, 1, 1)),
                trend=params.get("trend", "n"),
            ).fit()
        if model_name == "SARIMA":
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            return SARIMAX(
                y_train,
                order=params.get("order", (1, 1, 1)),
                seasonal_order=params.get("seasonal_order", (1, 1, 1, 7)),
            ).fit(disp=False)
        if model_name == "Prophet":
            import pandas as pd  # noqa: WPS433
            from prophet import Prophet  # type: ignore

            df = pd.DataFrame(
                {
                    "ds": X_train["ds"] if "ds" in X_train.columns else X_train.iloc[:, 0],
                    "y": y_train,
                }
            )
            m = Prophet(**params)
            m.fit(df)
            return m
        if model_name in ("Informer", "TFT", "PatchTST"):
            return self._train_neural_ts(X_train, y_train, model_name, params)
        # StatsForecast fallback
        try:
            import pandas as pd  # noqa: WPS433
            from statsforecast import StatsForecast  # type: ignore
            from statsforecast.models import AutoARIMA  # type: ignore

            df = pd.DataFrame({"ds": range(len(y_train)), "y": y_train, "unique_id": "ts_1"})
            sf = StatsForecast(df=df, models=[AutoARIMA(season_length=7)], freq="D")
            sf.fit()
            return sf
        except Exception as e:
            raise ValueError(f"Unknown timeseries model: {model_name}") from e

    def _train_neural_ts(self, X: Any, y: Any, model_name: str, params: dict[str, Any]) -> Any:
        try:
            import pandas as pd  # noqa: WPS433
            from neuralforecast import NeuralForecast  # type: ignore
            from neuralforecast.models import TFT, Informer, PatchTST  # type: ignore

            model_map = {"TFT": TFT, "PatchTST": PatchTST, "Informer": Informer}
            cls = model_map[model_name]
            horizon = params.get("horizon", 12)
            df = pd.DataFrame({"ds": range(len(y)), "y": y, "unique_id": "ts_1"})
            nf = NeuralForecast(models=[cls(h=horizon, input_size=params.get("input_size", 24))], freq="D")
            nf.fit(df)
            return nf
        except Exception as e:
            self._log_warning("neuralforecast_unavailable", error=str(e))
            from statsmodels.tsa.arima.model import ARIMA

            return ARIMA(y, order=(1, 1, 1)).fit()

    def predict(self, model: Any, X: Any) -> np.ndarray:
        try:
            return np.asarray(model.forecast(steps=len(X)) if hasattr(model, "forecast") else model.predict(X))
        except Exception:
            return np.asarray(model.predict(X))

    # ════════════════════════════════════════════════════════════
    # cs-day6 F-ext-2 : evaluate 확장 (naïve + MASE + sMAPE + PI)
    # ════════════════════════════════════════════════════════════
    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str = "forecasting") -> dict[str, float]:
        from sklearn.metrics import mean_absolute_error, mean_squared_error

        y_val = np.asarray(y_val).flatten()

        # ── F-1 ~ F-3 (기존) : val_rmse / val_mae ──
        y_pred = self.predict(model, X_val)
        y_pred = np.asarray(y_pred).flatten()[: len(y_val)]
        y_true = y_val[: len(y_pred)]
        val_rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        val_mae = float(mean_absolute_error(y_true, y_pred))

        y_train_last = self._y_train_last if self._y_train_last is not None else np.asarray([], dtype=float)

        # ── F-ext-2a : naïve baseline 선택 (seasonal vs simple) ──
        s = self._seasonal_s if (self._seasonal_s > 0 and self._seasonal_s <= len(y_train_last)) else 0
        naive_kind = "seasonal" if s > 0 else "simple"
        y_pred_naive = self._build_naive(y_train_last, s, len(y_true))

        # ── F-ext-2b : rmse_improvement_vs_naive (★ cs-day7 DoD 키) ──
        if len(y_true) > 0:
            rmse_naive = float(np.sqrt(mean_squared_error(y_true, y_pred_naive[: len(y_true)])))
        else:
            rmse_naive = 0.0
        if rmse_naive == 0.0:
            rmse_improvement: Optional[float] = None  # 분모 가드
        else:
            rmse_improvement = float((rmse_naive - val_rmse) / rmse_naive)

        # ── F-ext-2c : MASE ──
        if s > 0 and len(y_train_last) > s:
            scale = float(np.mean(np.abs(np.diff(y_train_last, n=s))))
        elif len(y_train_last) > 1:
            scale = float(np.mean(np.abs(np.diff(y_train_last))))
        else:
            scale = 0.0
        mase: Optional[float] = float(val_mae / scale) if scale > 0 else None

        # ── F-ext-2d : sMAPE ──
        denom = (np.abs(y_true) + np.abs(y_pred)) / 2.0
        mask = denom > 0
        smape: Optional[float] = (
            float(100.0 * np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask])) if mask.any() else None
        )

        # ── F-ext-2e : PI coverage (모델별 best-effort) ──
        pi_coverage, pi_lower, pi_upper = self._try_pi_coverage(model, X_val, y_true)

        # ── F-ext-2f : 확장된 metrics 반환 (12 키) ──
        return {
            "val_rmse": val_rmse,
            "val_mae": val_mae,
            "rmse_naive": rmse_naive,
            "rmse_improvement_vs_naive": rmse_improvement,  # ★ cs-day7 DoD 키
            "MASE": mase,
            "sMAPE": smape,
            "pi_coverage": pi_coverage,
            "pi_lower": pi_lower.tolist() if pi_lower is not None else None,
            "pi_upper": pi_upper.tolist() if pi_upper is not None else None,
            "naive_kind": naive_kind,
            "naive_s": s if s > 0 else None,
            "mlflow_run_id": self.mlflow_run_id,
        }

    # ── F-ext-2.1 : _build_naive (seasonal vs simple) ──
    def _build_naive(self, y_train_last: Any, s: int, n_val: int) -> np.ndarray:
        if s > 0 and len(y_train_last) >= s:
            return np.array([y_train_last[-s + (i % s)] for i in range(n_val)])
        last = y_train_last[-1] if len(y_train_last) > 0 else 0.0
        return np.full(n_val, last)

    # ── F-ext-2.2 : _try_pi_coverage (모델별 PI 추출 — best-effort) ──
    def _try_pi_coverage(self, model: Any, X_val: Any, y_true: Any, alpha: float = 0.05):
        """95% PI 추출 + coverage. 추출 불가 시 (None, None, None)."""
        try:
            # SARIMA / SARIMAX (statsmodels)
            if hasattr(model, "get_forecast"):
                fc = model.get_forecast(steps=len(y_true))
                ci = fc.conf_int(alpha=alpha)
                lower = np.asarray(ci.iloc[:, 0] if hasattr(ci, "iloc") else ci[:, 0])
                upper = np.asarray(ci.iloc[:, 1] if hasattr(ci, "iloc") else ci[:, 1])
            # Prophet
            elif hasattr(model, "predict") and hasattr(model, "make_future_dataframe"):
                future = model.make_future_dataframe(periods=len(y_true))
                forecast = model.predict(future)
                lower = forecast["yhat_lower"].values[-len(y_true) :]
                upper = forecast["yhat_upper"].values[-len(y_true) :]
            # NeuralForecast (level=[95] 사용 시)
            elif hasattr(model, "predict_intervals"):
                pi_df = model.predict_intervals(level=[95])
                lower = pi_df["lower_95"].values[: len(y_true)]
                upper = pi_df["upper_95"].values[: len(y_true)]
            else:
                return None, None, None

            L = min(len(lower), len(upper), len(y_true))
            coverage = float(np.mean((lower[:L] <= y_true[:L]) & (y_true[:L] <= upper[:L])))
            return coverage, lower[:L], upper[:L]
        except Exception as e:
            self._log_warning("pi_coverage_failed", error=str(e))
            return None, None, None

    # ── logger 안전 호출 (BasePipeline 에 logger 없을 수 있음) ──
    def _log_warning(self, event: str, **kw: Any) -> None:
        logger = getattr(self, "logger", None)
        if logger is not None:
            try:
                logger.warning(event, **kw)
            except Exception:
                pass

"""timeseries.pipeline — 시계열 파이프라인 (CS 담당, cs-day6 v3 디벨롭).

지원 9종: ARIMA / SARIMA / SARIMAX / Prophet / ETS / seasonal_naive
         + Informer / TFT / PatchTST
+ StatsForecast(R-1007) fallback

cs-day6 §F-Extension (기존, 불변):
  - train() 시 instance 변수 저장 (_y_train_last / _seasonal_s / _model_obj)
  - evaluate() 확장 — naïve baseline + MASE + sMAPE + PI coverage (12 키)
    → cs-day7 evaluator 가 rmse_improvement_vs_naive 등 임계치 판정에 사용

cs-day6 v3 디벨롭 (신규):
  - SUPPORTED_MODELS 9종으로 확장 (SARIMAX/ETS/seasonal_naive 추가)
  - _train_dispatch 신규 분기 3종
  - _SeasonalNaiveModel 내부 클래스 — naive 기준선 학습용 (방법론 4-2·6-5)
  - _extract_exog — SARIMAX 의 exog 컬럼/인덱스 안전 추출
  - evaluate() 15 키 — y_pred_val/y_val_actual/y_train_tail 추가
    (output_extras forecast_chart 단절 C-5 해소)
  - train_with_cv — TimeSeriesSplit + gap=horizon-1 (방법론 4-1·누수 1-4)
    반환 mean = improvement_vs_naive 평균 (HPO study.direction='maximize' 정합)
  - 회귀 0 — 기존 12 키 그대로, 신규 키만 추가
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from pipelines.base import BasePipeline


class _ConstantSeriesModel:
    """D3 (2026-06-05) — 상수 시계열 (분산 0) 용 graceful 폴백 모델.

    fit/predict 인터페이스 호환. forecast/predict 모두 동일 상수값 반환.
    cs-day10 §단계 3 의 "❌ 시리즈가 상수 → 예측 불가" 분기를 학습 단계에서
    구현. evaluate() 의 분산 0 시 MASE/sMAPE 분모 가드와 정합.
    """

    def __init__(self, const_value: float) -> None:
        self.const_value = float(const_value)
        self._ada_constant_series = True  # output_extras 가 "분석 불가" 메시지 판정용

    def forecast(self, steps: int = 1, exog: Any = None) -> Any:  # noqa: ARG002
        import numpy as _np

        return _np.full(int(steps), self.const_value, dtype=float)

    def predict(self, X: Any) -> Any:
        import numpy as _np

        try:
            n = len(X)
        except Exception:
            n = 1
        return _np.full(int(n), self.const_value, dtype=float)


class _SeasonalNaiveModel:
    """seasonal_naive 기준선 모델 — ARIMA-like 인터페이스 (forecast(steps)).

    방법론 4-2 · 6-5: "복잡한 모델이 seasonal naive 를 못 이기면 그 모델은
    쓸모없다." 본 클래스는 학습 데이터의 마지막 period 만큼을 순환 반복해서
    예측한다. period<=0 이거나 len(y)<period 면 마지막 값 반복 (simple naive).
    """

    def __init__(self, y_train: Any, period: int = 7) -> None:
        arr = np.asarray(y_train, dtype=float).flatten()
        # NaN 안전: NaN 만 있는 경우 0 으로 대체
        arr = arr[~np.isnan(arr)] if arr.size > 0 else arr
        self._y_train = arr if arr.size > 0 else np.asarray([0.0])
        p = int(period) if period and period >= 1 else 1
        self._period = p if p <= len(self._y_train) else 1

    def forecast(self, steps: int) -> np.ndarray:
        """다음 steps 스텝 예측 — 마지막 period 순환 반복."""
        if steps <= 0:
            return np.asarray([], dtype=float)
        p = self._period
        tail = self._y_train[-p:]
        return np.array([float(tail[i % p]) for i in range(int(steps))])

    def predict(self, X: Any) -> np.ndarray:
        """sklearn-like 호환 — len(X) 스텝 예측."""
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


class TimeSeriesPipeline(BasePipeline):
    experiment_name = "ada-timeseries"
    # 19종 확장 (2026-06-14, B 길) — CPU 중심 + GTX 1060 3GB 보조
    # 통계·고전(9) / 자동화(4) / ML 회귀(6) / 경량 DL(7)  + 기존 seasonal_naive 기준선
    # 표 정합: STL/VAR/VARMA/GARCH/RNN 신규. RNN 은 darts RNNModel(cell="RNN") 로 통합.
    # 신규 분기는 _train_dispatch 끝에서 graceful (라이브러리 미설치 시 fallback).
    SUPPORTED_MODELS = (
        # 통계·고전 (9, seasonal_naive 포함)
        "ARIMA",
        "SARIMA",
        "SARIMAX",
        "ETS",
        "STL",
        "seasonal_naive",
        "VAR",
        "VARMA",
        "GARCH",
        # 자동화·전용 (4)
        "Prophet",
        "AutoARIMA",
        "AutoETS",
        "NeuralProphet",
        # ML 회귀 (6, 피처 기반)
        "LightGBM",
        "XGBoost",
        "CatBoost",
        "RandomForest",
        "Ridge",
        "Lasso",
        # 경량 DL (7, darts 통합 — LSTM/GRU/RNN 은 cell 차이)
        "TCN",
        "NHiTS",
        "NBEATS",
        "LSTM",
        "GRU",
        "RNN",
        "DeepAR",
    )

    # 모델 family 분류 — selector / search_space / output_extras 공용
    MODEL_FAMILY = {
        "ARIMA": "stat",
        "SARIMA": "stat",
        "SARIMAX": "stat",
        "ETS": "stat",
        "STL": "stat",
        "seasonal_naive": "stat",
        "VAR": "stat",
        "VARMA": "stat",
        "GARCH": "stat",
        "Prophet": "auto",
        "AutoARIMA": "auto",
        "AutoETS": "auto",
        "NeuralProphet": "auto",
        "LightGBM": "ml",
        "XGBoost": "ml",
        "CatBoost": "ml",
        "RandomForest": "ml",
        "Ridge": "ml",
        "Lasso": "ml",
        "TCN": "dl",
        "NHiTS": "dl",
        "NBEATS": "dl",
        "LSTM": "dl",
        "GRU": "dl",
        "RNN": "dl",
        "DeepAR": "dl",
    }

    def __init__(self) -> None:
        super().__init__()
        # cs-day6 F-ext-1 : 학습 시 보존하는 instance 변수
        self._y_train_last: Optional[np.ndarray] = None  # MASE 분모 + naïve baseline 용
        self._seasonal_s: int = 0  # seasonal period (0 = simple naïve)
        self._model_obj: Optional[Any] = None  # PI 추출용 (옵션)

    # ════════════════════════════════════════════════════════════
    # cs-day6 F-ext-1b : seasonal_period 추출 (확장 — ETS/SN 포함)
    # ════════════════════════════════════════════════════════════
    def _extract_seasonal_period(self, model_name: str, params: dict[str, Any]) -> int:
        """모델별 seasonal_period 추출 — 0 이면 simple naïve."""
        # SARIMA/SARIMAX : params["seasonal_order"][3]
        if model_name in ("SARIMA", "SARIMAX"):
            seasonal_order = params.get("seasonal_order", (0, 0, 0, 0))
            return int(seasonal_order[3]) if len(seasonal_order) >= 4 else 0
        # ETS / seasonal_naive : params["seasonal_periods"]
        if model_name in ("ETS", "seasonal_naive"):
            return int(params.get("seasonal_periods") or 0)
        # Prophet : 명시적 seasonal_period 없음
        if model_name == "Prophet":
            return int(params.get("seasonal_period", 0))
        # ARIMA / 기타 : 0 (simple naïve)
        return 0

    # ════════════════════════════════════════════════════════════
    # 신규 — exog 안전 추출 (SARIMAX 용)
    # ════════════════════════════════════════════════════════════
    def _extract_exog(self, X_train: Any, params: dict[str, Any]) -> Any:
        """SARIMAX 용 exog 추출.

        우선순위:
          1. params["exog_columns"] + X_train 이 DataFrame 인 경우 — 컬럼명으로 추출
          2. params["exog_indices"] + X_train 이 ndarray 인 경우 — 열 인덱스로 추출
          3. 위 모두 실패 → None (단변량 SARIMAX 로 강등)
        """
        try:
            import pandas as pd  # noqa: WPS433
        except Exception:
            pd = None  # type: ignore

        cols = params.get("exog_columns") or []
        idxs = params.get("exog_indices") or []

        if pd is not None and isinstance(X_train, pd.DataFrame) and cols:
            valid = [c for c in cols if c in X_train.columns]
            if valid:
                exog = X_train[valid]
                return exog if not exog.empty else None
        if idxs and hasattr(X_train, "shape") and len(getattr(X_train, "shape", ())) >= 2:
            try:
                arr = np.asarray(X_train)
                valid_idx = [int(i) for i in idxs if 0 <= int(i) < arr.shape[1]]
                if valid_idx:
                    return arr[:, valid_idx]
            except Exception:
                return None
        return None

    # ════════════════════════════════════════════════════════════
    # G16 (2026-06-05) — 미래 결정론적 외생변수 자동 생성
    # ════════════════════════════════════════════════════════════
    @staticmethod
    def generate_future_exog(
        last_date: Any,
        n_steps: int,
        freq: str = "D",
        kinds: tuple[str, ...] = ("calendar", "fourier"),
        fourier_period: int = 7,
        fourier_n: int = 3,
    ) -> Any:
        """미래 horizon 동안의 결정론적 exog 자동 생성 — SARIMAX/Prophet forecast UX.

        Parameters
        ----------
        last_date : str | pd.Timestamp
            학습 데이터 마지막 날짜.
        n_steps : int
            예측 horizon.
        freq : str
            "D" (일) / "W" / "M" 등.
        kinds : tuple[str, ...]
            "calendar" — dayofweek/month/is_month_end/is_quarter_end 더미.
            "fourier"  — sin/cos pairs (fourier_period/fourier_n).
        fourier_period : int
        fourier_n : int

        Returns
        -------
        pd.DataFrame
            shape=(n_steps, k). 미래 시점별 exog 값. ds 컬럼 포함.
        """
        import numpy as _np  # noqa: WPS433
        import pandas as _pd  # noqa: WPS433

        try:
            last = _pd.to_datetime(last_date)
        except Exception:
            last = _pd.Timestamp.now()
        future_idx = _pd.date_range(start=last, periods=int(n_steps) + 1, freq=freq)[1:]

        out = _pd.DataFrame({"ds": future_idx})

        if "calendar" in kinds:
            out["cal_dayofweek"] = future_idx.dayofweek.astype("float")
            out["cal_month"] = future_idx.month.astype("float")
            out["cal_is_month_end"] = future_idx.is_month_end.astype("float")
            out["cal_is_quarter_end"] = future_idx.is_quarter_end.astype("float")

        if "fourier" in kinds and fourier_period and fourier_period >= 2:
            t = _np.arange(n_steps)
            for k in range(1, max(1, int(fourier_n)) + 1):
                out[f"fourier_sin_{k}"] = _np.sin(2.0 * _np.pi * k * t / fourier_period)
                out[f"fourier_cos_{k}"] = _np.cos(2.0 * _np.pi * k * t / fourier_period)

        return out

    # ════════════════════════════════════════════════════════════
    # train / _train_dispatch (확장 — SARIMAX/ETS/seasonal_naive 추가)
    # ════════════════════════════════════════════════════════════
    def train(self, X_train: Any, y_train: Any, model_name: str, params: dict[str, Any]) -> Any:
        """X_train: pd.DataFrame with date column or ndarray. y_train: target series."""
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

            # D3 (2026-06-05) — 상수 시계열 가드 (cs-day10 단계 3·9 "예측 불가, 상수 시계열")
            # 분산 0 (모든 값 동일) 시 어떤 통계 모델도 의미 없음 + ARIMA/SARIMA 가 ConvergenceWarning
            # 또는 LinAlgError 일으킬 수 있어 사전 차단. _ConstantSeriesModel 로 graceful 폴백.
            if self._y_train_last is not None and len(self._y_train_last) > 0:
                try:
                    if float(np.var(self._y_train_last)) < 1e-12:
                        const_val = float(self._y_train_last[-1])
                        self._model_obj = _ConstantSeriesModel(const_val)
                        return self._model_obj
                except Exception:
                    pass

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
        if model_name == "SARIMAX":
            # ── 신규 — SARIMAX 분기 (selector A안 호환) ──
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            exog_tr = self._extract_exog(X_train, params)
            fitted = SARIMAX(
                y_train,
                exog=exog_tr,
                order=params.get("order", (1, 1, 1)),
                seasonal_order=params.get("seasonal_order", (1, 1, 1, 7)),
            ).fit(disp=False)
            # D5 (2026-06-05) — exog 학습 여부 마커 (predict 시 누락 경고용)
            if exog_tr is not None:
                try:
                    fitted._ada_exog_required = True  # type: ignore[attr-defined]
                except Exception:
                    pass
            return fitted
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
        if model_name == "ETS":
            # ── 신규 — ETS / Holt-Winters (헌장 6-1 기준선) ──
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            y_arr = np.asarray(y_train, dtype=float).flatten()
            sp = params.get("seasonal_periods")
            seasonal = params.get("seasonal")
            # 데이터 부족하면 계절 성분 강등 (n >= 2*sp 필요)
            if seasonal is not None and sp and len(y_arr) < 2 * int(sp):
                seasonal = None
                sp = None
            # mul 은 양수 데이터 필요 — 음수 있으면 add 로 강등
            if (params.get("trend") == "mul" or seasonal == "mul") and (y_arr <= 0).any():
                trend = params.get("trend")
                if trend == "mul":
                    trend = "add"
                if seasonal == "mul":
                    seasonal = "add"
            else:
                trend = params.get("trend")
            return ExponentialSmoothing(
                y_arr,
                trend=trend,
                seasonal=seasonal,
                seasonal_periods=int(sp) if sp else None,
                damped_trend=bool(params.get("damped_trend", False)) if trend else False,
            ).fit(optimized=True)
        if model_name == "seasonal_naive":
            # ── 신규 — seasonal_naive 기준선 ──
            period = int(params.get("seasonal_periods") or self._seasonal_s or 7)
            return _SeasonalNaiveModel(y_train, period=period)
        # ─── Phase B (2026-06-14, B 길) — 통계·고전 확장 ───
        if model_name == "STL":
            from pipelines.timeseries.models_stat import STLModel

            return STLModel(
                y_train,
                period=int(params.get("seasonal_periods") or self._seasonal_s or 7),
                arima_order=tuple(params.get("arima_order") or (1, 1, 0)),
            )
        if model_name == "VAR":
            from pipelines.timeseries.models_stat import VARModel

            return VARModel(
                X_train if hasattr(X_train, "shape") and getattr(X_train, "shape", (0, 1))[-1] > 1 else y_train,
                maxlags=int(params.get("maxlags") or 5),
                ic=str(params.get("ic") or "aic"),
            )
        if model_name == "VARMA":
            from pipelines.timeseries.models_stat import VARMAModel

            return VARMAModel(
                X_train if hasattr(X_train, "shape") and getattr(X_train, "shape", (0, 1))[-1] > 1 else y_train,
                order=tuple(params.get("order") or (1, 0)),
            )
        if model_name == "GARCH":
            from pipelines.timeseries.models_stat import GARCHModel

            return GARCHModel(
                y_train,
                p=int(params.get("p") or 1),
                q=int(params.get("q") or 1),
                egarch=bool(params.get("egarch", False)),
            )
        # ─── Phase C (2026-06-14, B 길) — 자동화·전용 확장 ───
        if model_name == "AutoARIMA":
            from pipelines.timeseries.models_auto import AutoARIMAModel

            return AutoARIMAModel(
                y_train,
                season_length=int(params.get("season_length") or self._seasonal_s or 7),
            )
        if model_name == "AutoETS":
            from pipelines.timeseries.models_auto import AutoETSModel

            return AutoETSModel(
                y_train,
                season_length=int(params.get("season_length") or self._seasonal_s or 7),
            )
        if model_name == "NeuralProphet":
            from pipelines.timeseries.models_auto import NeuralProphetModel

            return NeuralProphetModel(
                y_train,
                ds=params.get("ds"),
                freq=str(params.get("freq") or "D"),
                epochs=int(params.get("epochs") or 10),
                n_lags=int(params.get("n_lags") or 0),
            )
        # ─── Phase D (2026-06-14, B 길) — ML 회귀 확장 (6 종) ───
        if model_name == "LightGBM":
            from pipelines.timeseries.models_ml import LightGBMModel

            return LightGBMModel(X_train, y_train, **{k: v for k, v in params.items() if k != "exog_columns"})
        if model_name == "XGBoost":
            from pipelines.timeseries.models_ml import XGBoostModel

            return XGBoostModel(X_train, y_train, **{k: v for k, v in params.items() if k != "exog_columns"})
        if model_name == "CatBoost":
            from pipelines.timeseries.models_ml import CatBoostModel

            return CatBoostModel(X_train, y_train, **{k: v for k, v in params.items() if k != "exog_columns"})
        if model_name == "RandomForest":
            from pipelines.timeseries.models_ml import RandomForestModel

            return RandomForestModel(X_train, y_train, **{k: v for k, v in params.items() if k != "exog_columns"})
        if model_name == "Ridge":
            from pipelines.timeseries.models_ml import RidgeModel

            return RidgeModel(X_train, y_train, **{k: v for k, v in params.items() if k != "exog_columns"})
        if model_name == "Lasso":
            from pipelines.timeseries.models_ml import LassoModel

            return LassoModel(X_train, y_train, **{k: v for k, v in params.items() if k != "exog_columns"})
        # ─── Phase E (2026-06-14, B 길) — 경량 DL 확장 (7 종, darts) ───
        if model_name == "TCN":
            from pipelines.timeseries.models_dl import TCNModel

            return TCNModel(
                y_train, freq=str(params.get("freq") or "D"), **{k: v for k, v in params.items() if k != "freq"}
            )
        if model_name == "NHiTS":
            from pipelines.timeseries.models_dl import NHiTSModel

            return NHiTSModel(
                y_train, freq=str(params.get("freq") or "D"), **{k: v for k, v in params.items() if k != "freq"}
            )
        if model_name == "NBEATS":
            from pipelines.timeseries.models_dl import NBEATSModel

            return NBEATSModel(
                y_train, freq=str(params.get("freq") or "D"), **{k: v for k, v in params.items() if k != "freq"}
            )
        if model_name == "LSTM":
            from pipelines.timeseries.models_dl import LSTMModel

            return LSTMModel(
                y_train, freq=str(params.get("freq") or "D"), **{k: v for k, v in params.items() if k != "freq"}
            )
        if model_name == "GRU":
            from pipelines.timeseries.models_dl import GRUModel

            return GRUModel(
                y_train, freq=str(params.get("freq") or "D"), **{k: v for k, v in params.items() if k != "freq"}
            )
        if model_name == "RNN":
            from pipelines.timeseries.models_dl import RNNModel as _RNN

            return _RNN(
                y_train, freq=str(params.get("freq") or "D"), **{k: v for k, v in params.items() if k != "freq"}
            )
        if model_name == "DeepAR":
            from pipelines.timeseries.models_dl import DeepARModel

            return DeepARModel(
                y_train, freq=str(params.get("freq") or "D"), **{k: v for k, v in params.items() if k != "freq"}
            )
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

    # ════════════════════════════════════════════════════════════
    # predict — BasePipeline 추상 메서드 구현
    # ════════════════════════════════════════════════════════════
    def predict(self, model: Any, X: Any) -> np.ndarray:
        """예측 분기 :
        1) hasattr(model, "forecast") → forecast(steps=len(X)) (SARIMAX 는 exog 동반)
        2) 1) TypeError (exog 인자 미지원) → exog 없이 model.forecast(steps)
        3) model.forecast 없음 → model.predict(X)
        4) 1·2 둘 다 실패 + sklearn-like predict 보유 → model.predict(X)
        """
        try:
            if hasattr(model, "forecast"):
                # exog 동반 forecast 시도 — SARIMAX 등
                exog_attempted = False
                try:
                    import pandas as pd  # noqa: WPS433

                    if isinstance(X, pd.DataFrame):
                        exog_cols = [c for c in X.columns if c != "ds"]
                        if exog_cols:
                            exog = X[exog_cols].select_dtypes(include="number")
                            if not exog.empty:
                                exog_attempted = True
                                try:
                                    return np.asarray(model.forecast(steps=len(X), exog=exog))
                                except TypeError:
                                    pass  # exog 인자 미지원 모델 → 다음 단계
                except Exception:
                    pass
                # D5 (2026-06-05) — SARIMAX 학습됐는데 미래 exog 미제공 시 경고 로그
                if exog_attempted is False and getattr(model, "_ada_exog_required", False):
                    try:
                        import logging as _log

                        _log.getLogger(__name__).warning(
                            "predict_exog_missing — SARIMAX 학습 시 exog 사용했으나 예측 X 에 exog 미포함, 점예측만 반환"
                        )
                    except Exception:
                        pass
                # exog 없이 forecast (ARIMA/SARIMA 단변량/ETS/seasonal_naive)
                return np.asarray(model.forecast(steps=len(X)))
            return np.asarray(model.predict(X))
        except Exception:
            return np.asarray(model.predict(X))

    # ════════════════════════════════════════════════════════════
    # cs-day6 F-ext-2 : evaluate 확장 (12 키 → 15 키, 신규 3 키 추가)
    # ════════════════════════════════════════════════════════════
    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str = "forecasting") -> dict[str, Any]:
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

        # ── OF4 (2026-06-05) : train_rmse + overfit_gap 계산 ──
        # 과적합 감지 핵심 지표. 모델이 train 에 self.predict() 가능하면 fit 잔차 추출.
        train_rmse: Optional[float] = None
        overfit_gap: Optional[float] = None
        try:
            if model is not None and len(y_train_last) >= 5:
                # model 별 in-sample fit 추출
                y_train_fit = None
                if hasattr(model, "fittedvalues"):  # statsmodels (ARIMA/SARIMA/SARIMAX/ETS)
                    fv = np.asarray(model.fittedvalues).flatten()
                    y_train_fit = fv[-len(y_train_last) :] if len(fv) >= len(y_train_last) else fv
                elif hasattr(model, "predict") and not getattr(model, "_ada_constant_series", False):
                    # 시도 — sklearn-like
                    try:
                        y_train_fit = np.asarray(model.predict(y_train_last)).flatten()
                    except Exception:
                        y_train_fit = None
                if y_train_fit is not None and len(y_train_fit) >= 5:
                    # 길이 정렬
                    L = min(len(y_train_fit), len(y_train_last))
                    y_train_fit = y_train_fit[-L:]
                    y_train_true = y_train_last[-L:]
                    # NaN 제거
                    mask = ~(np.isnan(y_train_fit) | np.isnan(y_train_true))
                    if int(mask.sum()) >= 5:
                        train_rmse = float(np.sqrt(mean_squared_error(y_train_true[mask], y_train_fit[mask])))
                        # overfit_gap = (val_rmse - train_rmse) / train_rmse
                        if train_rmse > 1e-9:
                            overfit_gap = float((val_rmse - train_rmse) / train_rmse)
        except Exception:
            train_rmse = None
            overfit_gap = None

        # ── F-ext-2f : 기존 12 키 + OF4 신규 2 키 ──
        out: dict[str, Any] = {
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
            # OF4 (2026-06-05) — 과적합 감지 키
            "train_rmse": train_rmse,
            "overfit_gap": overfit_gap,
        }

        # ── 신규 3 키 — output_extras forecast_chart 단절 C-5 해소 ──
        # 작은 list 라 직렬화 부담 적음. NaN 가드 (training_monitor 의 float NaN
        # 검사는 list 무시 → 안전).
        try:
            out["y_pred_val"] = [float(v) for v in y_pred]
            out["y_val_actual"] = [float(v) for v in y_true]
            tail_len = min(200, len(y_train_last))
            out["y_train_tail"] = [float(v) for v in y_train_last[-tail_len:]] if tail_len > 0 else []
        except Exception:
            out["y_pred_val"] = None
            out["y_val_actual"] = None
            out["y_train_tail"] = None
        return out

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

    # ════════════════════════════════════════════════════════════
    # 신규 — train_with_cv (rolling-origin walk-forward, 방법론 4-1·누수 1-4)
    # ════════════════════════════════════════════════════════════
    def train_with_cv(
        self,
        X: Any,
        y: Any,
        model_name: str,
        params: dict[str, Any],
        n_splits: int = 3,
        task: str = "forecasting",
        cv_strategy: str = "expanding",
    ) -> dict[str, Any]:
        """rolling-origin walk-forward CV — HyperparameterTunerAgent 가 호출.

        TimeSeriesSplit + gap=horizon-1 (누수 1-4 차단). 각 fold 안에서 self.train
        → self.evaluate 호출 → improvement_vs_naive 수집.

        반환 ``mean`` = mean(improvement_vs_naive) — HPO study.direction="maximize"
        와 정합 (클수록 좋음). 실패 fold 는 0.0 (neutral, trial prune 회피).

        Parameters
        ----------
        n_splits : int
            기본 3. 데이터가 작으면 자동 축소.
        """
        from sklearn.model_selection import TimeSeriesSplit

        horizon = int(params.get("horizon") or 1)
        gap = max(0, horizon - 1)
        n = len(y) if hasattr(y, "__len__") else 0

        if n < 10:
            # 데이터 너무 짧음 — CV 의미 없음, neutral 반환
            return {
                "fold_scores": [],
                "fold_metrics": [],
                "mean": 0.0,
                "std": 0.0,
                "n_splits": 0,
                "gap": gap,
                "skip_reason": "n<10",
            }

        # n_splits 가 너무 크면 자동 축소 (min fold size >= 5 보장)
        min_fold = 5
        max_possible = max(2, (n - gap) // (min_fold + 1))
        n_splits_eff = max(2, min(int(n_splits), max_possible))

        # PB (2026-06-14) — cv_strategy 토글: "expanding" (기본) / "rolling"
        # rolling 모드: max_train_size 를 fold 당 일정하게 제한 → window 슬라이딩
        max_train_size = None
        if str(cv_strategy).lower() == "rolling":
            # 마지막 fold 가 사용하게 될 train 크기 = n - (n_splits * test_size) - gap
            # → train 크기를 그 값으로 고정해 모든 fold 가 동일 크기 window 사용
            test_size = max(min_fold, (n - gap) // (n_splits_eff + 1))
            max_train_size = max(min_fold, test_size * n_splits_eff)
        try:
            if max_train_size is not None:
                splitter = TimeSeriesSplit(n_splits=n_splits_eff, gap=gap, max_train_size=max_train_size)
            else:
                splitter = TimeSeriesSplit(n_splits=n_splits_eff, gap=gap)
        except TypeError:
            # 구버전 sklearn — gap/max_train_size 인자 미지원
            try:
                splitter = TimeSeriesSplit(n_splits=n_splits_eff, max_train_size=max_train_size)
            except TypeError:
                splitter = TimeSeriesSplit(n_splits=n_splits_eff)

        fold_scores: list[float] = []
        fold_metrics_list: list[dict[str, Any]] = []

        idx_arr = np.arange(n)
        for tr_idx, val_idx in splitter.split(idx_arr):
            try:
                # 인덱싱 — DataFrame/Series 는 iloc, ndarray 는 fancy indexing
                X_tr = X.iloc[tr_idx] if hasattr(X, "iloc") else X[tr_idx]
                X_val = X.iloc[val_idx] if hasattr(X, "iloc") else X[val_idx]
                y_tr = y.iloc[tr_idx] if hasattr(y, "iloc") else y[tr_idx]
                y_val = y.iloc[val_idx] if hasattr(y, "iloc") else y[val_idx]

                model = self.train(X_tr, y_tr, model_name=model_name, params=params)
                m = self.evaluate(model, X_val, y_val, task=task)
                imp = m.get("rmse_improvement_vs_naive")
                fold_scores.append(float(imp) if imp is not None else 0.0)
                fold_metrics_list.append(
                    {
                        "val_rmse": m.get("val_rmse"),
                        "val_mae": m.get("val_mae"),
                        "MASE": m.get("MASE"),
                        "rmse_improvement_vs_naive": m.get("rmse_improvement_vs_naive"),
                    }
                )
            except Exception as e:
                self._log_warning("fold_failed", model=model_name, error=str(e))
                fold_scores.append(0.0)
                fold_metrics_list.append({})

        mean = float(np.mean(fold_scores)) if fold_scores else 0.0
        std = float(np.std(fold_scores)) if fold_scores else 0.0
        return {
            "fold_scores": fold_scores,
            "fold_metrics": fold_metrics_list,
            "mean": mean,
            "std": std,
            "n_splits": n_splits_eff,
            "gap": gap,
            "cv_strategy": str(cv_strategy).lower(),
            "max_train_size": max_train_size,
        }

    def _log_warning(self, event: str, **kw: Any) -> None:
        logger = getattr(self, "logger", None)
        if logger is not None:
            try:
                logger.warning(event, **kw)
            except Exception:
                pass

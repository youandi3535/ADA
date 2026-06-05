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
    # 9종으로 확장 — selector A안의 SARIMAX 후보 + 헌장 6-1 ETS 기준선
    # + 헌장 4-2·6-5 seasonal_naive 기준선
    SUPPORTED_MODELS = (
        "ARIMA",
        "SARIMA",
        "SARIMAX",
        "Prophet",
        "ETS",
        "seasonal_naive",
        "Informer",
        "TFT",
        "PatchTST",
    )

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
        # DL : freq 와 input_size 로 추정 (옵션)
        if model_name in ("Informer", "TFT", "PatchTST"):
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
            return SARIMAX(
                y_train,
                exog=exog_tr,
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
        """예측 — SARIMAX 등 exog 동반 모델 자동 처리.

        ── 순서 (cs-day6 v3 보완) ──
        1) model.forecast 보유 + X 가 DataFrame + 'ds' 외 수치형 컬럼 존재
           → exog 동반 forecast 시도 (SARIMAX/SARIMA with exog 전용 호출)
        2) 1) TypeError (exog 인자 미지원) → exog 없이 model.forecast(steps)
        3) model.forecast 없음 → model.predict(X)
        4) 1·2 둘 다 실패 + sklearn-like predict 보유 → model.predict(X)
        """
        try:
            if hasattr(model, "forecast"):
                # exog 동반 forecast 시도 — SARIMAX 등
                try:
                    import pandas as pd  # noqa: WPS433

                    if isinstance(X, pd.DataFrame):
                        exog_cols = [c for c in X.columns if c != "ds"]
                        if exog_cols:
                            exog = X[exog_cols].select_dtypes(include="number")
                            if not exog.empty:
                                try:
                                    return np.asarray(model.forecast(steps=len(X), exog=exog))
                                except TypeError:
                                    pass  # exog 인자 미지원 모델 → 다음 단계
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

        # ── F-ext-2f : 기존 12 키 ──
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

        try:
            splitter = TimeSeriesSplit(n_splits=n_splits_eff, gap=gap)
        except TypeError:
            # 구버전 sklearn — gap 인자 미지원
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
        }

    # ── logger 안전 호출 (BasePipeline 에 logger 없을 수 있음) ──
    def _log_warning(self, event: str, **kw: Any) -> None:
        logger = getattr(self, "logger", None)
        if logger is not None:
            try:
                logger.warning(event, **kw)
            except Exception:
                pass

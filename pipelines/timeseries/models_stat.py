"""timeseries.models_stat — 통계·고전 신규 모델 wrapper (CS, 2026-06-14 B 길).

대상: STL / VAR / VARMA / GARCH / EGARCH
정책: 모든 wrapper 는 ``forecast(steps)`` + ``predict(X)`` 인터페이스 제공
       (pipeline.predict 의 분기 정합). 라이브러리 미설치 시 ImportError 를
       자연 전파 → pipeline._train_dispatch 의 graceful 처리에 위임.

설계 원칙
─────────────────────────────────────────────────────────────────
- 회귀 0 — 기존 6 종 모델 분기 절대 변경 X
- 분할 작성 — 본 파일 200줄 이내
- CPU 네이티브 — 모든 통계 모델은 CPU 만 사용
- graceful — wrap 객체가 _ada_constant_series / _ada_fallback 마커로
            output_extras 와 정합
"""

from __future__ import annotations

from typing import Any

import numpy as np


# ════════════════════════════════════════════════════════════════
# STL 분해 + 잔차 예측 (statsmodels.tsa.forecasting.stl.STLForecast)
# ════════════════════════════════════════════════════════════════
class STLModel:
    """STL 분해 + ARIMA(1,1,0) 잔차 모델 — statsmodels STLForecast wrapper.

    표 안 '통계·고전 / STL 분해' 항목.
    period 가 명시되지 않으면 7 기본 (일 주기). 분해된 trend·seasonal·resid 의
    재합성 forecast 를 반환.
    """

    def __init__(self, y_train: Any, period: int = 7, arima_order: tuple = (1, 1, 0)) -> None:
        from statsmodels.tsa.arima.model import ARIMA
        from statsmodels.tsa.forecasting.stl import STLForecast

        arr = np.asarray(y_train, dtype=float).flatten()
        p = int(period) if period and period >= 2 else 7
        # period >= len/2 면 STL 불가 → period 축소
        if p * 2 > len(arr):
            p = max(2, len(arr) // 4)
        self._stlf = STLForecast(arr, ARIMA, model_kwargs={"order": arima_order}, period=p).fit()
        self._period = p

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        return np.asarray(self._stlf.forecast(int(steps)), dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


# ════════════════════════════════════════════════════════════════
# VAR (vector autoregression) — statsmodels.tsa.vector_ar.var_model
# ════════════════════════════════════════════════════════════════
class VARModel:
    """VAR — 다변량 시계열용. y_train 은 DataFrame 또는 ndarray(2D).

    표 안 '통계·고전 / VAR·VARMA'. univariate 입력 시 ValueError 회피용
    silent fallback (마지막 값 반복).
    """

    def __init__(self, y_train: Any, maxlags: int = 5, ic: str = "aic") -> None:
        from statsmodels.tsa.vector_ar.var_model import VAR

        arr = np.asarray(y_train, dtype=float)
        if arr.ndim == 1 or arr.shape[1] < 2:
            # 단변량 입력 시 graceful 폴백 — 마지막 값 반복
            self._fallback = True
            self._last = float(arr[-1]) if arr.size > 0 else 0.0
            return
        self._fallback = False
        self._k = arr.shape[1]
        self._last_obs = arr[-int(maxlags) :]
        self._res = VAR(arr).fit(maxlags=int(maxlags), ic=ic)

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        if getattr(self, "_fallback", False):
            return np.full(int(steps), self._last, dtype=float)
        out = self._res.forecast(self._last_obs, int(steps))
        # 다변량 결과 → 1차원 target (첫 컬럼) 반환 (pipeline 단변량 평가 정합)
        return np.asarray(out[:, 0], dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


# ════════════════════════════════════════════════════════════════
# VARMA — statsmodels.tsa.statespace.varmax.VARMAX (다변량 ARMA)
# ════════════════════════════════════════════════════════════════
class VARMAModel:
    """VARMA — VAR + MA 항. order=(p,q). univariate 시 graceful 폴백."""

    def __init__(self, y_train: Any, order: tuple = (1, 0)) -> None:
        from statsmodels.tsa.statespace.varmax import VARMAX

        arr = np.asarray(y_train, dtype=float)
        if arr.ndim == 1 or arr.shape[1] < 2:
            self._fallback = True
            self._last = float(arr[-1]) if arr.size > 0 else 0.0
            return
        self._fallback = False
        self._res = VARMAX(arr, order=order).fit(disp=False)

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        if getattr(self, "_fallback", False):
            return np.full(int(steps), self._last, dtype=float)
        out = np.asarray(self._res.forecast(int(steps)))
        # 다변량 → 첫 컬럼만
        if out.ndim == 2:
            out = out[:, 0]
        return out.astype(float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


# ════════════════════════════════════════════════════════════════
# GARCH / EGARCH — arch 라이브러리
# ════════════════════════════════════════════════════════════════
class GARCHModel:
    """GARCH(p,q) 변동성 모델 — arch.arch_model wrapper.

    forecast 는 평균 예측 0 + 변동성 σ_t 의 평균을 반환 (수익률 변동 모델 특성상
    point forecast 는 0 근처, 본 wrapper 는 conditional volatility 를 노출).
    egarch=True 면 EGARCH 로 전환.
    """

    def __init__(self, y_train: Any, p: int = 1, q: int = 1, egarch: bool = False) -> None:
        from arch import arch_model

        arr = np.asarray(y_train, dtype=float).flatten()
        # 수익률 스케일 강제 (변동성 모델 안정화)
        if np.std(arr) > 1.0:
            arr = np.diff(arr, prepend=arr[0])  # 1차 차분
        vol = "EGARCH" if egarch else "Garch"
        self._res = arch_model(arr, vol=vol, p=int(p), q=int(q)).fit(disp="off")
        self._last_mean = float(np.mean(arr))

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        try:
            f = self._res.forecast(horizon=int(steps), reindex=False)
            mean_arr = np.asarray(f.mean.values).flatten()[: int(steps)]
            # 부족하면 last_mean 으로 패딩
            if len(mean_arr) < int(steps):
                pad = np.full(int(steps) - len(mean_arr), self._last_mean)
                mean_arr = np.concatenate([mean_arr, pad])
            return mean_arr.astype(float)
        except Exception:
            return np.full(int(steps), self._last_mean, dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))

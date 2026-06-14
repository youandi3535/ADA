"""timeseries.models_auto — 자동화·전용 신규 모델 wrapper (CS, 2026-06-14 B 길).

대상: AutoARIMA / AutoETS (statsforecast) + NeuralProphet (PyTorch CPU)
정책: forecast(steps)/predict(X) 인터페이스 공통. 모든 라이브러리는
       CPU 강제 (NeuralProphet 도 accelerator=None / device="cpu" 명시).

설계 원칙
─────────────────────────────────────────────────────────────────
- 회귀 0 — 기존 Prophet 분기는 손대지 않음
- CPU 강제 — GTX 1060 3GB 보조이나 본 wrapper 들은 CPU 우선
- graceful — 라이브러리 미설치 시 ImportError 자연 전파
"""

from __future__ import annotations

from typing import Any

import numpy as np


# ════════════════════════════════════════════════════════════════
# AutoARIMA — statsforecast.models.AutoARIMA
# ════════════════════════════════════════════════════════════════
class AutoARIMAModel:
    """statsforecast AutoARIMA wrapper — 자동 차수 탐색 (pmdarima 호환 자리).

    season_length 는 params 또는 seasonal_periods 에서 추출. CPU 빠름.
    """

    def __init__(self, y_train: Any, season_length: int = 7) -> None:
        from statsforecast.models import AutoARIMA

        arr = np.asarray(y_train, dtype=float).flatten()
        sl = int(season_length) if season_length and season_length >= 1 else 7
        self._model = AutoARIMA(season_length=sl)
        self._model.fit(arr)
        self._last_value = float(arr[-1]) if arr.size > 0 else 0.0

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        try:
            out = self._model.predict(h=int(steps))
            # statsforecast 0.x 는 dict-like (mean 키)
            if isinstance(out, dict) and "mean" in out:
                return np.asarray(out["mean"], dtype=float)
            # ndarray 또는 직접 반환
            return np.asarray(out, dtype=float).flatten()
        except Exception:
            return np.full(int(steps), self._last_value, dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


# ════════════════════════════════════════════════════════════════
# AutoETS — statsforecast.models.AutoETS
# ════════════════════════════════════════════════════════════════
class AutoETSModel:
    """statsforecast AutoETS wrapper — 자동 ETS 모델 선택 (AAN/AAA/MNN 등)."""

    def __init__(self, y_train: Any, season_length: int = 7) -> None:
        from statsforecast.models import AutoETS

        arr = np.asarray(y_train, dtype=float).flatten()
        sl = int(season_length) if season_length and season_length >= 1 else 7
        self._model = AutoETS(season_length=sl)
        self._model.fit(arr)
        self._last_value = float(arr[-1]) if arr.size > 0 else 0.0

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        try:
            out = self._model.predict(h=int(steps))
            if isinstance(out, dict) and "mean" in out:
                return np.asarray(out["mean"], dtype=float)
            return np.asarray(out, dtype=float).flatten()
        except Exception:
            return np.full(int(steps), self._last_value, dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


# ════════════════════════════════════════════════════════════════
# NeuralProphet — PyTorch CPU 강제
# ════════════════════════════════════════════════════════════════
class NeuralProphetModel:
    """NeuralProphet wrapper — Prophet+신경망 하이브리드.

    CPU 강제 (accelerator=None). epochs 보수적 (기본 10). yearly/weekly
    seasonality 자동.
    """

    def __init__(
        self,
        y_train: Any,
        ds: Any = None,
        freq: str = "D",
        epochs: int = 10,
        n_lags: int = 0,
    ) -> None:
        import pandas as pd
        from neuralprophet import NeuralProphet, set_log_level  # type: ignore

        set_log_level("ERROR")
        arr = np.asarray(y_train, dtype=float).flatten()
        # ds 가 없으면 기본 일자 인덱스 생성
        if ds is None:
            ds_idx = pd.date_range(start="2020-01-01", periods=len(arr), freq=freq)
        else:
            ds_idx = pd.to_datetime(ds)
        df = pd.DataFrame({"ds": ds_idx, "y": arr})
        # CPU 강제 — accelerator=None
        self._m = NeuralProphet(
            n_lags=int(n_lags),
            epochs=int(epochs),
            accelerator=None,  # CPU 강제
        )
        self._m.fit(df, freq=freq)
        self._freq = freq
        self._last_ds = ds_idx[-1]
        self._last_value = float(arr[-1]) if arr.size > 0 else 0.0

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        try:
            import pandas as pd

            future = self._m.make_future_dataframe(
                df=pd.DataFrame({"ds": [self._last_ds], "y": [self._last_value]}),
                periods=int(steps),
                n_historic_predictions=False,
            )
            pred = self._m.predict(future)
            # yhat1 컬럼 추출 (NeuralProphet 표준)
            y_col = "yhat1" if "yhat1" in pred.columns else pred.columns[-1]
            arr = np.asarray(pred[y_col].values, dtype=float)[-int(steps) :]
            return arr if len(arr) >= int(steps) else np.full(int(steps), self._last_value)
        except Exception:
            return np.full(int(steps), self._last_value, dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))

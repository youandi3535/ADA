"""timeseries.models_dl — 경량 딥러닝 wrapper (CS, 2026-06-14 B 길).

대상: TCN / NHiTS / NBEATS / LSTM / GRU / RNN / DeepAR  (darts 통합 API)
정책: CPU 우선 + GTX 1060 3GB 보조. n_epochs/batch/hidden 보수 디폴트.

설계 원칙
─────────────────────────────────────────────────────────────────
- darts.TimeSeries 변환은 wrapper 내부에서 처리 (외부는 그냥 y_train 전달)
- LSTM/GRU/RNN/DeepAR 는 darts.RNNModel(model="LSTM"|"GRU"|"RNN") 로 통합.
  DeepAR 는 likelihood=GaussianLikelihood() 로 차별화 (확률 예측).
- CPU 강제 — pl_trainer_kwargs={"accelerator": "cpu"}.
  GPU 사용 시 환경변수 ADA_DARTS_DEVICE=gpu 로 토글.
- 회귀 0 — 기존 분기 손대지 않음. darts 미설치 시 ImportError 자연 전파.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np


def _device_kwargs() -> dict[str, Any]:
    """ADA_DARTS_DEVICE 환경변수로 CPU/GPU 토글. 기본 CPU."""
    dev = os.environ.get("ADA_DARTS_DEVICE", "cpu").lower()
    if dev == "gpu":
        return {"accelerator": "gpu", "devices": 1}
    return {"accelerator": "cpu"}


def _to_timeseries(y_train: Any, freq: str = "D") -> Any:
    """y_train (np/list/Series) → darts.TimeSeries."""
    import pandas as pd
    from darts import TimeSeries

    arr = np.asarray(y_train, dtype=float).flatten()
    idx = pd.date_range(start="2020-01-01", periods=len(arr), freq=freq)
    return TimeSeries.from_times_and_values(idx, arr)


# ════════════════════════════════════════════════════════════════
# 공통 베이스 — darts 모델 wrapper
# ════════════════════════════════════════════════════════════════
class _DLBase:
    """공통 베이스 — fit(y), forecast(steps), predict(X)."""

    def __init__(self, y_train: Any, freq: str = "D", **kwargs: Any) -> None:
        self._ts = _to_timeseries(y_train, freq=freq)
        self._last_value = float(np.asarray(y_train, dtype=float).flatten()[-1]) if len(y_train) > 0 else 0.0
        self._freq = freq
        self._model = self._build_model(**kwargs)
        try:
            self._model.fit(self._ts)
            self._fitted = True
        except Exception:
            self._fitted = False

    def _build_model(self, **kwargs: Any) -> Any:  # 서브클래스 override
        raise NotImplementedError

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        if not getattr(self, "_fitted", False):
            return np.full(int(steps), self._last_value, dtype=float)
        try:
            pred = self._model.predict(n=int(steps))
            return np.asarray(pred.values(), dtype=float).flatten()[: int(steps)]
        except Exception:
            return np.full(int(steps), self._last_value, dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


# ════════════════════════════════════════════════════════════════
# TCN — Temporal Convolutional Network
# ════════════════════════════════════════════════════════════════
class TCNModel(_DLBase):
    def _build_model(self, **kwargs: Any) -> Any:
        from darts.models import TCNModel as _TCN

        return _TCN(
            input_chunk_length=int(kwargs.get("input_chunk_length", 14)),
            output_chunk_length=int(kwargs.get("output_chunk_length", 7)),
            n_epochs=int(kwargs.get("n_epochs", 30)),
            batch_size=int(kwargs.get("batch_size", 32)),
            dropout=float(kwargs.get("dropout", 0.1)),
            num_filters=int(kwargs.get("num_filters", 8)),
            random_state=42,
            pl_trainer_kwargs=_device_kwargs(),
        )


# ════════════════════════════════════════════════════════════════
# N-HiTS — Neural Hierarchical Interpolation
# ════════════════════════════════════════════════════════════════
class NHiTSModel(_DLBase):
    def _build_model(self, **kwargs: Any) -> Any:
        from darts.models import NHiTSModel as _NHiTS

        return _NHiTS(
            input_chunk_length=int(kwargs.get("input_chunk_length", 14)),
            output_chunk_length=int(kwargs.get("output_chunk_length", 7)),
            n_epochs=int(kwargs.get("n_epochs", 30)),
            batch_size=int(kwargs.get("batch_size", 32)),
            num_blocks=int(kwargs.get("num_blocks", 1)),
            num_layers=int(kwargs.get("num_layers", 2)),
            random_state=42,
            pl_trainer_kwargs=_device_kwargs(),
        )


# ════════════════════════════════════════════════════════════════
# N-BEATS — interpretable Generic blocks
# ════════════════════════════════════════════════════════════════
class NBEATSModel(_DLBase):
    def _build_model(self, **kwargs: Any) -> Any:
        from darts.models import NBEATSModel as _NBEATS

        return _NBEATS(
            input_chunk_length=int(kwargs.get("input_chunk_length", 14)),
            output_chunk_length=int(kwargs.get("output_chunk_length", 7)),
            n_epochs=int(kwargs.get("n_epochs", 30)),
            batch_size=int(kwargs.get("batch_size", 32)),
            num_blocks=int(kwargs.get("num_blocks", 1)),
            num_layers=int(kwargs.get("num_layers", 2)),
            random_state=42,
            pl_trainer_kwargs=_device_kwargs(),
        )


# ════════════════════════════════════════════════════════════════
# LSTM / GRU / RNN — darts.RNNModel cell 차이
# ════════════════════════════════════════════════════════════════
class _RNNBase(_DLBase):
    _CELL = "LSTM"
    _LIKELIHOOD: Any = None  # DeepAR 만 GaussianLikelihood 사용

    def _build_model(self, **kwargs: Any) -> Any:
        from darts.models import RNNModel as _RNN

        m_kwargs = {
            "input_chunk_length": int(kwargs.get("input_chunk_length", 14)),
            "model": self._CELL,
            "hidden_dim": int(kwargs.get("hidden_dim", 16)),
            "n_rnn_layers": int(kwargs.get("n_rnn_layers", 1)),
            "training_length": int(kwargs.get("training_length", 20)),
            "n_epochs": int(kwargs.get("n_epochs", 30)),
            "batch_size": int(kwargs.get("batch_size", 32)),
            "random_state": 42,
            "pl_trainer_kwargs": _device_kwargs(),
        }
        if self._LIKELIHOOD is not None:
            m_kwargs["likelihood"] = self._LIKELIHOOD
        return _RNN(**m_kwargs)


class LSTMModel(_RNNBase):
    _CELL = "LSTM"


class GRUModel(_RNNBase):
    _CELL = "GRU"


class RNNModel(_RNNBase):
    _CELL = "RNN"


# ════════════════════════════════════════════════════════════════
# DeepAR — RNNModel + Gaussian likelihood (확률 예측)
# ════════════════════════════════════════════════════════════════
class DeepARModel(_DLBase):
    def _build_model(self, **kwargs: Any) -> Any:
        from darts.models import RNNModel as _RNN

        try:
            from darts.utils.likelihood_models import GaussianLikelihood

            likelihood = GaussianLikelihood()
        except Exception:
            likelihood = None
        m_kwargs = {
            "input_chunk_length": int(kwargs.get("input_chunk_length", 14)),
            "model": "LSTM",
            "hidden_dim": int(kwargs.get("hidden_dim", 16)),
            "n_rnn_layers": int(kwargs.get("n_rnn_layers", 2)),
            "training_length": int(kwargs.get("training_length", 20)),
            "n_epochs": int(kwargs.get("n_epochs", 30)),
            "batch_size": int(kwargs.get("batch_size", 32)),
            "random_state": 42,
            "pl_trainer_kwargs": _device_kwargs(),
        }
        if likelihood is not None:
            m_kwargs["likelihood"] = likelihood
        return _RNN(**m_kwargs)

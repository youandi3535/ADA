"""timeseries.models_dl_transformer — Transformer 류 경량 wrapper (CS, 2026-06-14).

대상: Transformer / TFT (Temporal Fusion Transformer)  — darts 통합

⚠️ 활성화 상태 (2026-06-14, 본인 결정 대기)
─────────────────────────────────────────────────────────────────
본 모듈의 클래스는 **SUPPORTED_MODELS 에 등록되지 않은 상태**입니다.
즉 pipeline._train_dispatch 에서 호출되지 않음 = 비활성.

추후 활성화 절차 (CS 본인 결정 후):
  1. pipelines/timeseries/pipeline.py 의 SUPPORTED_MODELS 에 추가:
       "Transformer", "TFT"
  2. MODEL_FAMILY 에 추가:
       "Transformer": "dl", "TFT": "dl"
  3. _train_dispatch 에 분기 추가:
       if model_name == "Transformer":
           from pipelines.timeseries.models_dl_transformer import TransformerModelLite
           return TransformerModelLite(y_train, freq=..., **params)
       if model_name == "TFT":
           from pipelines.timeseries.models_dl_transformer import TFTModelLite
           return TFTModelLite(y_train, freq=..., **params)
  4. search_space.py 에 파라미터 분기 추가
  5. selector.EXPERT_DIMENSIONS 에 점수 행 추가
  6. selector candidate 풀에 합류 룰 추가 (n_rows 충분 시)

CPU 사양 (CPU 중심 + GTX 1060 3GB 보조)
─────────────────────────────────────────────────────────────────
- d_model 작게 (16~32) — full Transformer 의 d_model=64 보다 4배 축소
- nhead 적게 (2) — full 4 보다 2배 축소
- num_encoder/decoder_layers 1 — full 3 보다 3배 축소
- input_chunk_length 14 — 짧은 컨텍스트
- batch_size 16 — VRAM 3GB 안전
- n_epochs 20 — early stopping 권장

GTX 1060 사용 시 환경변수: ADA_DARTS_DEVICE=gpu
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
# Transformer (encoder-decoder) — darts.models.TransformerModel
# ════════════════════════════════════════════════════════════════
class TransformerModelLite:
    """경량 Transformer wrapper — darts.models.TransformerModel.

    원본 시그니처와 비교한 경량화 :
      - d_model: 64 → 16
      - nhead: 4 → 2
      - num_encoder_layers / num_decoder_layers: 3 → 1
      - dim_feedforward: 512 → 64
      - batch_size: 32 → 16
      - n_epochs: 100 → 20

    이 설정으로 short context (14 시점) + horizon 7 에서 CPU 학습 1~3 분 예상.
    """

    def __init__(self, y_train: Any, freq: str = "D", **kwargs: Any) -> None:
        from darts.models import TransformerModel

        self._ts = _to_timeseries(y_train, freq=freq)
        arr = np.asarray(y_train, dtype=float).flatten()
        self._last_value = float(arr[-1]) if len(arr) > 0 else 0.0
        self._model = TransformerModel(
            input_chunk_length=int(kwargs.get("input_chunk_length", 14)),
            output_chunk_length=int(kwargs.get("output_chunk_length", 7)),
            d_model=int(kwargs.get("d_model", 16)),
            nhead=int(kwargs.get("nhead", 2)),
            num_encoder_layers=int(kwargs.get("num_encoder_layers", 1)),
            num_decoder_layers=int(kwargs.get("num_decoder_layers", 1)),
            dim_feedforward=int(kwargs.get("dim_feedforward", 64)),
            dropout=float(kwargs.get("dropout", 0.1)),
            activation=str(kwargs.get("activation", "relu")),
            n_epochs=int(kwargs.get("n_epochs", 20)),
            batch_size=int(kwargs.get("batch_size", 16)),
            random_state=42,
            pl_trainer_kwargs=_device_kwargs(),
        )
        try:
            self._model.fit(self._ts)
            self._fitted = True
        except Exception:
            self._fitted = False

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
# TFT — Temporal Fusion Transformer (darts.models.TFTModel)
# ════════════════════════════════════════════════════════════════
class TFTModelLite:
    """경량 TFT wrapper — darts.models.TFTModel.

    경량화 :
      - hidden_size: 16 → 8
      - lstm_layers: 1 (그대로)
      - num_attention_heads: 4 → 2
      - hidden_continuous_size: 8 → 4
      - batch_size: 32 → 16
      - n_epochs: 100 → 20

    TFT 는 외생변수·정적 covariate 활용 시 강력하나 CPU 학습 비용 큼.
    GTX 1060 3GB 사용 권장 (ADA_DARTS_DEVICE=gpu).
    """

    def __init__(self, y_train: Any, freq: str = "D", **kwargs: Any) -> None:
        from darts.models import TFTModel

        self._ts = _to_timeseries(y_train, freq=freq)
        arr = np.asarray(y_train, dtype=float).flatten()
        self._last_value = float(arr[-1]) if len(arr) > 0 else 0.0

        try:
            from darts.utils.likelihood_models import QuantileRegression

            likelihood: Any = QuantileRegression(quantiles=[0.1, 0.5, 0.9])
        except Exception:
            likelihood = None

        m_kwargs: dict[str, Any] = {
            "input_chunk_length": int(kwargs.get("input_chunk_length", 14)),
            "output_chunk_length": int(kwargs.get("output_chunk_length", 7)),
            "hidden_size": int(kwargs.get("hidden_size", 8)),
            "lstm_layers": int(kwargs.get("lstm_layers", 1)),
            "num_attention_heads": int(kwargs.get("num_attention_heads", 2)),
            "hidden_continuous_size": int(kwargs.get("hidden_continuous_size", 4)),
            "dropout": float(kwargs.get("dropout", 0.1)),
            "n_epochs": int(kwargs.get("n_epochs", 20)),
            "batch_size": int(kwargs.get("batch_size", 16)),
            "add_relative_index": True,  # 시간 covariate 미주입 시 안전 동작
            "random_state": 42,
            "pl_trainer_kwargs": _device_kwargs(),
        }
        if likelihood is not None:
            m_kwargs["likelihood"] = likelihood

        self._model = TFTModel(**m_kwargs)
        try:
            self._model.fit(self._ts)
            self._fitted = True
        except Exception:
            self._fitted = False

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
# 활성화 표 (참고용, 코드 실행 X)
# ════════════════════════════════════════════════════════════════
# 본 클래스를 활성화 하려면 pipeline.py 에 다음 코드를 추가:
#
#     # pipelines/timeseries/pipeline.py 의 SUPPORTED_MODELS 끝에 추가:
#     # "Transformer", "TFT"
#
#     # MODEL_FAMILY 에 추가:
#     # "Transformer": "dl", "TFT": "dl"
#
#     # _train_dispatch 끝부분 (StatsForecast fallback 위) 에 분기 추가:
#     # if model_name == "Transformer":
#     #     from pipelines.timeseries.models_dl_transformer import TransformerModelLite
#     #     return TransformerModelLite(
#     #         y_train, freq=str(params.get("freq") or "D"),
#     #         **{k: v for k, v in params.items() if k != "freq"}
#     #     )
#     # if model_name == "TFT":
#     #     from pipelines.timeseries.models_dl_transformer import TFTModelLite
#     #     return TFTModelLite(
#     #         y_train, freq=str(params.get("freq") or "D"),
#     #         **{k: v for k, v in params.items() if k != "freq"}
#     #     )

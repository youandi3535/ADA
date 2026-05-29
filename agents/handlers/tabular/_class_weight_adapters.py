"""agents.handlers.tabular._class_weight_adapters — 백본별 class_weight 변환 (jh 담당).

Day 2: selector.py / training_executor 가 import해서 백본별 형식으로 변환.
"""

from __future__ import annotations

from typing import Any


def to_sklearn(weights: dict[int, float]) -> dict[int, float]:
    """sklearn LogReg/RF/SVC class_weight 인자 그대로 dict 반환."""
    return {int(k): float(v) for k, v in weights.items()}


def to_xgboost_binary(weights: dict[int, float]) -> float:
    """XGBoost binary scale_pos_weight = w[minority] / w[majority]."""
    if len(weights) != 2:
        raise ValueError(f"Binary XGBoost requires exactly 2 classes, got {len(weights)}")
    sorted_w = sorted(weights.items(), key=lambda x: x[1])
    w_majority = float(sorted_w[0][1])
    w_minority = float(sorted_w[1][1])
    if w_majority == 0:
        return 1.0
    return w_minority / w_majority


def to_xgboost_multiclass(weights: dict[int, float], y: Any) -> Any:
    """XGBoost multiclass per-sample weight 벡터 (sample_weight= 인자용)."""
    import numpy as np

    w_map = {int(k): float(v) for k, v in weights.items()}
    return np.array([w_map.get(int(label), 1.0) for label in y])


def to_lightgbm(weights: dict[int, float]) -> dict[int, float]:
    """LightGBM class_weight dict 반환 (lgb.train의 class_weight 인자)."""
    return {int(k): float(v) for k, v in weights.items()}


def to_catboost(weights: dict[int, float]) -> list[float]:
    """CatBoost class_weights 리스트 반환 (클래스 정수 오름차순)."""
    sorted_classes = sorted(weights.keys())
    return [float(weights[c]) for c in sorted_classes]


def to_pytorch(weights: dict[int, float]) -> Any:
    """PyTorch CrossEntropyLoss weight tensor (클래스 정수 오름차순)."""
    try:
        import torch

        sorted_classes = sorted(weights.keys())
        w_list = [float(weights[c]) for c in sorted_classes]
        return torch.tensor(w_list, dtype=torch.float32)
    except ImportError:
        sorted_classes = sorted(weights.keys())
        return [float(weights[c]) for c in sorted_classes]

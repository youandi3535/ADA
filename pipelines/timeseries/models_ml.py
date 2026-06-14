"""timeseries.models_ml — 피처 기반 ML 회귀 wrapper (CS, 2026-06-14 B 길).

대상: LightGBM / XGBoost / CatBoost / RandomForest / Ridge / Lasso
정책: 시계열 → preprocessor 가 만든 피처 매트릭스(X) + 타깃(y) →
       sklearn-like ML 회귀. forecast(steps) 는 recursive 1-step 반복.

설계 원칙
─────────────────────────────────────────────────────────────────
- preprocessor 가 lag/rolling/calendar/fourier 피처 이미 생성 → wrapper 는
  fit(X, y) 만 호출. forecast 시점에서는 X 의 마지막 행을 시드로 사용.
- 회귀 0 — 기존 분기 손대지 않음
- CPU 빠름 — n_jobs 자동, tree depth/leaves 보수 디폴트
- graceful — 라이브러리 미설치 시 ImportError 자연 전파
"""

from __future__ import annotations

from typing import Any

import numpy as np


# ════════════════════════════════════════════════════════════════
# 공통 베이스 — sklearn-like 회귀 wrapper
# ════════════════════════════════════════════════════════════════
class _MLBase:
    """공통 베이스 — fit(X_train, y_train), forecast(steps), predict(X)."""

    _model: Any = None  # 서브클래스가 _build_model() 로 채움

    def __init__(self, X_train: Any, y_train: Any) -> None:
        import pandas as pd

        # X_train 이 None 이면 1열 dummy (시간 인덱스만)
        if X_train is None:
            X_train = pd.DataFrame({"t": np.arange(len(y_train))})

        # NaN 안전: 숫자형만 사용, NaN→0 (시계열 lag warmup 보호)
        if isinstance(X_train, pd.DataFrame):
            X_num = X_train.select_dtypes(include=[np.number]).fillna(0.0)
            self._feature_names = list(X_num.columns)
            X_arr = X_num.values
        else:
            X_arr = np.asarray(X_train, dtype=float)
            if X_arr.ndim == 1:
                X_arr = X_arr.reshape(-1, 1)
            X_arr = np.nan_to_num(X_arr, nan=0.0)
            self._feature_names = [f"f{i}" for i in range(X_arr.shape[1])]

        y_arr = np.asarray(y_train, dtype=float).flatten()
        # 길이 정렬
        L = min(len(X_arr), len(y_arr))
        X_arr, y_arr = X_arr[:L], y_arr[:L]

        self._model = self._build_model()
        self._model.fit(X_arr, y_arr)
        # forecast 시드 — 마지막 행 보존
        self._last_X = X_arr[-1:].copy() if len(X_arr) > 0 else np.zeros((1, X_arr.shape[1]))
        self._last_value = float(y_arr[-1]) if y_arr.size > 0 else 0.0

    def _build_model(self) -> Any:  # 서브클래스 override
        raise NotImplementedError

    def forecast(self, steps: int = 1, exog: Any = None) -> np.ndarray:  # noqa: ARG002
        """recursive multistep — 마지막 행 반복. exog 가 미래 X 라면 사용."""
        try:
            if exog is not None:
                import pandas as pd

                if isinstance(exog, pd.DataFrame):
                    cols = [c for c in self._feature_names if c in exog.columns]
                    if cols:
                        X_future = exog[cols].fillna(0.0).values[: int(steps)]
                    else:
                        X_future = np.tile(self._last_X, (int(steps), 1))
                else:
                    X_future = np.asarray(exog, dtype=float)
                    if X_future.ndim == 1:
                        X_future = X_future.reshape(-1, 1)
                    X_future = X_future[: int(steps)]
                # 부족 시 last_X 로 패딩
                if len(X_future) < int(steps):
                    pad = np.tile(self._last_X, (int(steps) - len(X_future), 1))
                    X_future = np.vstack([X_future, pad])
            else:
                X_future = np.tile(self._last_X, (int(steps), 1))
            return np.asarray(self._model.predict(X_future), dtype=float).flatten()
        except Exception:
            return np.full(int(steps), self._last_value, dtype=float)

    def predict(self, X: Any) -> np.ndarray:
        import pandas as pd

        try:
            if isinstance(X, pd.DataFrame):
                cols = [c for c in self._feature_names if c in X.columns]
                X_arr = X[cols].fillna(0.0).values if cols else np.tile(self._last_X, (len(X), 1))
            else:
                X_arr = np.asarray(X, dtype=float)
                if X_arr.ndim == 1:
                    X_arr = X_arr.reshape(-1, 1)
                X_arr = np.nan_to_num(X_arr, nan=0.0)
            return np.asarray(self._model.predict(X_arr), dtype=float).flatten()
        except Exception:
            n = len(X) if hasattr(X, "__len__") else 1
            return np.full(n, self._last_value, dtype=float)


# ════════════════════════════════════════════════════════════════
# 개별 모델 — 보수적 디폴트 (CPU 빠름·과적합 방어)
# ════════════════════════════════════════════════════════════════
class LightGBMModel(_MLBase):
    def __init__(self, X_train: Any, y_train: Any, **params: Any) -> None:
        self._params = {
            "n_estimators": int(params.get("n_estimators", 200)),
            "learning_rate": float(params.get("learning_rate", 0.05)),
            "num_leaves": int(params.get("num_leaves", 31)),
            "max_depth": int(params.get("max_depth", -1)),
            "n_jobs": -1,
            "verbose": -1,
            "random_state": 42,
        }
        super().__init__(X_train, y_train)

    def _build_model(self) -> Any:
        from lightgbm import LGBMRegressor

        return LGBMRegressor(**self._params)


class XGBoostModel(_MLBase):
    def __init__(self, X_train: Any, y_train: Any, **params: Any) -> None:
        self._params = {
            "n_estimators": int(params.get("n_estimators", 200)),
            "learning_rate": float(params.get("learning_rate", 0.05)),
            "max_depth": int(params.get("max_depth", 6)),
            "n_jobs": -1,
            "verbosity": 0,
            "random_state": 42,
            "tree_method": "hist",  # CPU 빠름
        }
        super().__init__(X_train, y_train)

    def _build_model(self) -> Any:
        from xgboost import XGBRegressor

        return XGBRegressor(**self._params)


class CatBoostModel(_MLBase):
    def __init__(self, X_train: Any, y_train: Any, **params: Any) -> None:
        self._params = {
            "iterations": int(params.get("iterations", 200)),
            "learning_rate": float(params.get("learning_rate", 0.05)),
            "depth": int(params.get("depth", 6)),
            "verbose": False,
            "random_seed": 42,
            "thread_count": -1,
        }
        super().__init__(X_train, y_train)

    def _build_model(self) -> Any:
        from catboost import CatBoostRegressor

        return CatBoostRegressor(**self._params)


class RandomForestModel(_MLBase):
    def __init__(self, X_train: Any, y_train: Any, **params: Any) -> None:
        self._params = {
            "n_estimators": int(params.get("n_estimators", 300)),
            "max_depth": params.get("max_depth"),  # None 허용
            "n_jobs": -1,
            "random_state": 42,
        }
        super().__init__(X_train, y_train)

    def _build_model(self) -> Any:
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(**self._params)


class RidgeModel(_MLBase):
    """Ridge wrapper — StandardScaler 자동 적용 (PA, 2026-06-14).

    선형 모델은 피처 스케일에 민감 — 시계열 lag/rolling 피처 분산이 다르면
    L2 정규화 불균등 적용 → 자동 StandardScaler + Ridge 파이프라인.
    """

    def __init__(self, X_train: Any, y_train: Any, **params: Any) -> None:
        self._params = {"alpha": float(params.get("alpha", 1.0)), "random_state": 42}
        super().__init__(X_train, y_train)

    def _build_model(self) -> Any:
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        return Pipeline([("scaler", StandardScaler()), ("ridge", Ridge(**self._params))])


class LassoModel(_MLBase):
    """Lasso wrapper — StandardScaler 자동 적용 (PA, 2026-06-14)."""

    def __init__(self, X_train: Any, y_train: Any, **params: Any) -> None:
        self._params = {
            "alpha": float(params.get("alpha", 0.001)),
            "max_iter": int(params.get("max_iter", 5000)),
            "random_state": 42,
        }
        super().__init__(X_train, y_train)

    def _build_model(self) -> Any:
        from sklearn.linear_model import Lasso
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        return Pipeline([("scaler", StandardScaler()), ("lasso", Lasso(**self._params))])

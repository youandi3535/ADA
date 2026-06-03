"""pipelines.base — BasePipeline 추상 클래스 (Day04 §3)."""

from __future__ import annotations

import abc
from functools import cached_property
from typing import Any, Optional

try:
    import mlflow  # noqa: WPS433
except Exception:  # pragma: no cover
    mlflow = None  # type: ignore

from ada.core.config import settings


class BasePipeline(abc.ABC):
    mlflow_run_id: Optional[str] = None

    #: MLflow 실험명 — 서브클래스에서 ada-{category}
    experiment_name: str = "ada-default"

    @cached_property
    def logger(self) -> Any:
        """구조화 로거 (지연 생성).

        BasePipeline 은 __init__ 이 없으므로, 모든 서브클래스가 별도 초기화 없이
        self.logger 를 안전하게 사용할 수 있도록 cached_property 로 제공한다.
        """
        from ada.core.logger import get_logger

        return get_logger(self.__class__.__name__)

    @abc.abstractmethod
    def train(
        self,
        X_train: Any,
        y_train: Any,
        model_name: str,
        params: dict[str, Any],
    ) -> Any:
        """모델 학습 후 학습된 모델 객체 반환."""

    @abc.abstractmethod
    def predict(self, model: Any, X: Any) -> Any:
        """예측 결과 ndarray 반환."""

    @abc.abstractmethod
    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str) -> dict[str, float]:
        """평가 메트릭 dict 반환."""

    # --- MLflow 유틸 ---------------------------------------------------
    def _start_mlflow_run(
        self,
        *,
        experiment_name: Optional[str] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> Any:
        if mlflow is None:

            class _Noop:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def info(self) -> dict:
                    return {}

            return _Noop()

        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(experiment_name or self.experiment_name)
        nested = mlflow.active_run() is not None
        run = mlflow.start_run(tags=tags or {}, nested=nested)
        self.mlflow_run_id = run.info.run_id
        return run

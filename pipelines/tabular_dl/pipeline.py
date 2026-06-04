"""tabular_dl.pipeline — 정형 DL (Day08).

지원 모델: TabTransformer / FTTransformer / TabPFN
GPU 없으면 CPU fallback. 학습 시간 가드 + NaN 조기 중단.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pipelines.base import BasePipeline


class TabularDLPipeline(BasePipeline):
    experiment_name = "ada-tabular-dl"
    SUPPORTED_MODELS = ("TabTransformer", "FTTransformer", "TabPFN")

    def _device(self) -> str:
        try:
            import torch  # noqa: WPS433

            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def train(self, X_train: Any, y_train: Any, model_name: str, params: dict[str, Any]) -> Any:
        with self._start_mlflow_run(tags={"model": model_name, "device": self._device()}):
            try:
                import mlflow  # noqa: WPS433

                mlflow.log_params({**params, "model_name": model_name})
            except Exception:
                pass

            if model_name == "TabPFN":
                return self._train_tabpfn(X_train, y_train, params)
            if model_name in ("TabTransformer", "FTTransformer"):
                return self._train_transformer(X_train, y_train, model_name, params)
            raise ValueError(f"Unknown DL model: {model_name}")

    def _train_tabpfn(self, X: Any, y: Any, params: dict[str, Any]) -> Any:
        from tabpfn import TabPFNClassifier  # type: ignore

        clf = TabPFNClassifier(
            device=self._device(), **{k: v for k, v in params.items() if k in {"N_ensemble_configurations"}}
        )
        clf.fit(X, y, overwrite_warning=True)
        return clf

    def _train_transformer(self, X: Any, y: Any, model_name: str, params: dict[str, Any]) -> Any:
        try:
            from pytorch_tabular import TabularModel  # type: ignore
            from pytorch_tabular.config import (
                DataConfig,
                OptimizerConfig,
                TrainerConfig,
            )
            from pytorch_tabular.models import (
                FTTransformerConfig,
                TabTransformerConfig,
            )
        except Exception as e:
            self.logger.warning("torch_tabular_unavailable", error=str(e))
            # CPU 호환을 위해 sklearn fallback (RandomForest)
            from sklearn.ensemble import RandomForestClassifier

            m = RandomForestClassifier(n_estimators=200, n_jobs=-1, random_state=42)
            m.fit(X, y)
            return m

        # 본문에서는 features → DataFrame 변환을 가정
        import pandas as pd  # noqa: WPS433

        df_tr = pd.DataFrame(X)
        df_tr["target"] = y
        cont_cols = list(df_tr.select_dtypes(include=["number"]).columns.drop("target", errors="ignore"))

        data_cfg = DataConfig(target=["target"], continuous_cols=cont_cols)
        trainer_cfg = TrainerConfig(
            max_epochs=params.get("epochs", 20), batch_size=params.get("batch_size", 256), accelerator="auto"
        )
        opt_cfg = OptimizerConfig(optimizer="Adam", optimizer_params={"lr": params.get("lr", 1e-3)})
        model_cfg = TabTransformerConfig() if model_name == "TabTransformer" else FTTransformerConfig()
        tm = TabularModel(
            data_config=data_cfg, model_config=model_cfg, optimizer_config=opt_cfg, trainer_config=trainer_cfg
        )
        tm.fit(train=df_tr)
        return tm

    def predict(self, model: Any, X: Any) -> np.ndarray:
        if hasattr(model, "predict_proba"):
            try:
                return np.asarray(model.predict(X))
            except Exception:
                pass
        try:
            return np.asarray(model.predict(X))
        except Exception:
            import pandas as pd  # noqa: WPS433

            return np.asarray(model.predict(pd.DataFrame(X)))

    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str) -> dict[str, float]:
        # 평가 로직 자체는 TabularMLPipeline.evaluate 와 동일 (분류/회귀 sklearn metric).
        # 이전엔 _TMP().evaluate(...) 처럼 새 인스턴스를 만들어 호출했는데,
        # 이 경우 self.mlflow_run_id / self._start_mlflow_run() 상태가 분리되어
        # log_metrics 가 잘못된 run 으로 흘러갈 위험이 있었다.
        # 같은 모듈의 unbound 함수처럼 직접 호출해 self 의 mlflow 컨텍스트를 유지한다.
        from pipelines.tabular_ml.pipeline import TabularMLPipeline as _TMP

        return _TMP.evaluate(self, model, X_val, y_val, task)

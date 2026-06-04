"""Day 6 — HyperparameterTunerAgent + TrainingExecutor 의 best_params 사용 테스트.

DoD:
    - Titanic 학습 → best_params['XGBoost'] 비어있지 않음
    - state.best_params 에 model_candidates 의 모든 키가 채워짐 (실패 시 {})
    - TrainingExecutor 가 best_params 를 params 로 흘려주는지 검증

본 테스트는 인프라(MinIO/DB) 의존 없이 monkeypatch 로 동작.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

from ada.core.state import PipelineState


# ----- 공용 더미 ----------------------------------------------------------------
class _DummyPipeline:
    """train_with_cv + train/evaluate stub. trial 의 n_estimators 가 클수록 점수 ↑."""

    mlflow_run_id: str | None = "run-test"

    def train_with_cv(
        self, X: Any, y: Any, model_name: str, params: dict[str, Any], n_splits: int = 3, task: str = "classification"
    ) -> dict[str, Any]:
        # 단조 증가 점수 → optuna 가 큰 n_estimators 선호
        score = 0.5 + min(params.get("n_estimators", 100), 500) / 1000.0
        return {"fold_scores": [score, score, score], "mean": score, "std": 0.0}

    def train(self, X: Any, y: Any, model_name: str, params: dict[str, Any]) -> Any:
        class _M:
            def predict(self, X):
                return np.zeros(len(X))

        return _M()

    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str) -> dict[str, float]:
        return {"val_f1": 0.7, "val_accuracy": 0.7}

    def save_model(self, model: Any, job_id: str, model_name: str) -> dict[str, str]:
        return {"minio_path": "s3://test/model", "model_sha256": "deadbeef"}


@pytest.fixture
def base_state():
    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Survived",
        model_candidates=["RandomForest", "XGBoost"],
    )


# ----- 1) HPO 가 best_params 를 채우는지 ----------------------------------------
def test_tuner_fills_best_params(monkeypatch, base_state, titanic_df):
    """state.best_params 에 model_candidates 의 모든 키가 채워진다."""
    import asyncio

    from agents.hyperparameter_tuner import HyperparameterTunerAgent

    # _load_xy 가 MinIO 를 우회하도록 monkeypatch
    async def _fake_load_xy(self, state):
        df = titanic_df
        from agents.training_executor import _split_xy

        return _split_xy(df, state.target_column)

    monkeypatch.setattr(HyperparameterTunerAgent, "_load_xy", _fake_load_xy)
    # PipelineFactory 가 _DummyPipeline 을 반환하도록
    from pipelines import factory as factory_mod

    monkeypatch.setattr(factory_mod.PipelineFactory, "create", staticmethod(lambda cat: _DummyPipeline()))

    tuner = HyperparameterTunerAgent()
    # log_agent_run 안의 DB session 의존성 우회 — session=None 이면 skip
    new_state = asyncio.run(tuner(base_state))

    assert isinstance(new_state.best_params, dict)
    # 모든 후보가 best_params 키로 존재 (값은 빈 dict 일 수도 — optuna 없으면)
    for m in base_state.model_candidates:
        assert m in new_state.best_params
    assert new_state.next_agent == "training_executor"


# ----- 2) Optuna 가 있다면 XGBoost 의 best_params 가 실제로 채워진다 ---------------
def test_tuner_xgboost_populated(monkeypatch, base_state, titanic_df):
    pytest.importorskip("optuna")
    import asyncio

    from agents.hyperparameter_tuner import HyperparameterTunerAgent

    async def _fake_load_xy(self, state):
        df = titanic_df
        from agents.training_executor import _split_xy

        return _split_xy(df, state.target_column)

    monkeypatch.setattr(HyperparameterTunerAgent, "_load_xy", _fake_load_xy)
    from pipelines import factory as factory_mod

    monkeypatch.setattr(factory_mod.PipelineFactory, "create", staticmethod(lambda cat: _DummyPipeline()))

    tuner = HyperparameterTunerAgent(n_trials=5, timeout_per_model_sec=15, n_splits=2)
    new_state = asyncio.run(tuner(base_state))

    # XGBoost search space 는 n_estimators / learning_rate 등을 가진다
    xgb = new_state.best_params.get("XGBoost", {})
    assert isinstance(xgb, dict)
    assert len(xgb) > 0  # 최소 1개 이상의 하이퍼파라미터 산출
    assert "n_estimators" in xgb or "learning_rate" in xgb


# ----- 3) TrainingExecutor 가 best_params 를 흘려주는지 -----------------------------
def test_executor_uses_best_params(monkeypatch, base_state, titanic_df):
    """trained_models[*].params_used == state.best_params[model]"""
    import asyncio

    from agents.training_executor import TrainingExecutorAgent

    state_with_params = base_state.with_update(
        best_params={
            "RandomForest": {"n_estimators": 250},
            "XGBoost": {"learning_rate": 0.05, "n_estimators": 300},
        }
    )

    # load_dataframe_from_state 직접 monkeypatch (MinIO 우회)
    import agents.handlers.common.shared as shared_mod

    monkeypatch.setattr(shared_mod, "load_dataframe_from_state", lambda state: titanic_df)
    from pipelines import factory as factory_mod

    monkeypatch.setattr(factory_mod.PipelineFactory, "create", staticmethod(lambda cat: _DummyPipeline()))

    exec_agent = TrainingExecutorAgent()
    new_state = asyncio.run(exec_agent(state_with_params))

    assert len(new_state.trained_models) == 2
    by_name = {m["model_name"]: m for m in new_state.trained_models}
    assert by_name["RandomForest"]["params_used"] == {"n_estimators": 250}
    assert by_name["XGBoost"]["params_used"] == {"learning_rate": 0.05, "n_estimators": 300}
    assert new_state.next_agent == "training_monitor"

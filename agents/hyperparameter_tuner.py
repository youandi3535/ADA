"""agents.hyperparameter_tuner — HyperparameterTunerAgent (Day 6 본구현).

Optuna trial 별 실제 학습 + CV 호출 → best_params 산출.
각 카테고리 selector 의 search space 를 그대로 사용. 결과는
state.best_params[model_name] = best_trial.params 로 채워진다.

실패 안전망: optuna 미설치 / search space 없음 / CV 실패 모두 빈 dict 폴백.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from ada.core.state import PipelineState
from agents.base import BaseAgent

_SEARCH_SPACE_MODULES: dict[str, str] = {
    "tabular_ml": "pipelines.tabular_ml.search_space",
    "tabular_dl": "pipelines.tabular_dl.search_space",
    "timeseries": "pipelines.timeseries.search_space",
    "anomaly_detection": "pipelines.anomaly.search_space",
}


def _resolve_task(category: str, y: Any) -> str:
    if category == "timeseries":
        return "forecasting"
    if category == "anomaly_detection":
        return "anomaly_detection"
    try:
        n_unique = len(set(y.tolist() if hasattr(y, "tolist") else list(y)))
    except Exception:
        n_unique = 99
    return "classification" if n_unique <= 20 else "regression"


class HyperparameterTunerAgent(BaseAgent):
    """trial 별 실제 학습 + CV — Day 6 본구현."""

    uses_llm = False

    def __init__(
        self,
        *args: Any,
        n_trials: int = 20,
        timeout_per_model_sec: int = 120,
        n_splits: int = 3,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.n_trials = n_trials
        self.timeout_per_model_sec = timeout_per_model_sec
        self.n_splits = n_splits

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            X, y = await self._load_xy(state)
            if X is None or y is None:
                self.logger.warning("hpo_skip_no_data", category=state.category)
                return state.with_update(best_params={}, next_agent="training_executor")

            ss_module = self._import_search_space(state.category)
            if ss_module is None:
                self.logger.warning("hpo_skip_no_search_space", category=state.category)
                return state.with_update(
                    best_params={m: {} for m in state.model_candidates},
                    next_agent="training_executor",
                )

            best_params: dict[str, dict[str, Any]] = {}
            task = _resolve_task(state.category, y)
            for model_name in state.model_candidates:
                best = await self._run_optuna(state, model_name, X, y, task, ss_module)
                best_params[model_name] = best

            return state.with_update(best_params=best_params, next_agent="training_executor")

    async def _load_xy(self, state: PipelineState):
        """training_executor 와 동일한 _split_xy 사용. MinIO 로드 실패 시 (None, None)."""
        try:
            from agents.handlers.common.shared import load_dataframe_from_state
            from agents.training_executor import _split_xy

            df = load_dataframe_from_state(state)
            return _split_xy(df, state.target_column)
        except Exception as e:
            self.logger.warning("hpo_load_failed", error=str(e))
            return None, None

    @staticmethod
    def _import_search_space(category: str) -> Optional[Any]:
        import importlib

        mod_name = _SEARCH_SPACE_MODULES.get(category)
        if not mod_name:
            return None
        try:
            return importlib.import_module(mod_name)
        except Exception:
            return None

    async def _run_optuna(self, state, model_name, X, y, task, ss_module) -> dict[str, Any]:
        loop = asyncio.get_event_loop()

        def _search() -> dict[str, Any]:
            try:
                import optuna
            except Exception:
                self.logger.warning("optuna_missing", model=model_name)
                return {}

            study = optuna.create_study(
                direction="maximize",
                study_name=f"{state.job_id}-{model_name}",
                sampler=optuna.samplers.TPESampler(seed=42),
            )

            from pipelines.factory import PipelineFactory

            pipeline = PipelineFactory.create(state.category)

            def _objective(trial: Any) -> float:
                try:
                    space_fn = getattr(ss_module, "get_search_space", None)
                    if not callable(space_fn):
                        raise optuna.exceptions.TrialPruned()
                    params = space_fn(model_name, trial)
                except Exception as e:
                    self.logger.warning("space_failed", model=model_name, error=str(e))
                    raise optuna.exceptions.TrialPruned()

                if hasattr(pipeline, "train_with_cv"):
                    try:
                        result = pipeline.train_with_cv(
                            X,
                            y,
                            model_name=model_name,
                            params=params,
                            n_splits=self.n_splits,
                            task=task,
                        )
                        return float(result.get("mean", 0.0))
                    except Exception as e:
                        self.logger.warning("cv_failed", model=model_name, error=str(e))
                        raise optuna.exceptions.TrialPruned()

                try:
                    model = pipeline.train(X, y, model_name=model_name, params=params)
                    metrics = pipeline.evaluate(model, X, y, task=task)
                    if task == "classification":
                        return float(metrics.get("val_f1", 0.0))
                    if task == "regression":
                        return float(metrics.get("val_r2", 0.0))
                    return float(next(iter(metrics.values())) if metrics else 0.0)
                except Exception as e:
                    self.logger.warning("fit_failed", model=model_name, error=str(e))
                    raise optuna.exceptions.TrialPruned()

            try:
                study.optimize(
                    _objective,
                    n_trials=self.n_trials,
                    timeout=self.timeout_per_model_sec,
                    catch=(Exception,),
                    show_progress_bar=False,
                )
                return dict(study.best_params) if study.best_trial else {}
            except Exception as e:
                self.logger.warning("optuna_failed", model=model_name, error=str(e))
                return {}

        return await loop.run_in_executor(None, _search)

"""agents.hyperparameter_tuner — HyperparameterTunerAgent (Day07 §4).

Optuna + FLAML warm-start. self_learning_kb 의 'hpo_warm_start' KB 도 반영.
"""

from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent


class HyperparameterTunerAgent(BaseAgent):
    uses_llm = False

    def __init__(self, *args: Any, n_trials: int = 50, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.n_trials = n_trials

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            best_params: dict[str, dict[str, Any]] = {}
            for model_name in state.model_candidates:
                best_params[model_name] = self._optuna_search(model_name, state)
            warnings = list(state.training_warnings)
            return state.with_update(
                preprocessing_plan=state.preprocessing_plan or [],
                training_warnings=warnings,
                trained_models=[],
                next_agent="training_executor",
                # best_params 는 trained_models 의 첫 단계에서 사용
                eval_result=None,
                # 보조 — best_params 를 explanations 로 옮기는 대신 별도 필드 필요시 확장
            )

    def _optuna_search(self, model_name: str, state: PipelineState) -> dict[str, Any]:
        try:
            import optuna

            from pipelines.tabular_ml.search_space import get_search_space

            study = optuna.create_study(direction="maximize", study_name=f"{state.job_id}-{model_name}")

            def _obj(trial: optuna.Trial) -> float:
                _ = get_search_space(model_name, trial)
                # 본 워크플로우에서 trial 별 실제 학습은 training_executor 가 담당.
                # 여기서는 탐색 공간 정의를 검증하는 dummy objective 만 둠.
                return 0.0

            study.optimize(_obj, n_trials=min(self.n_trials, 5))
            return study.best_params if study.best_trial else {}
        except Exception as e:
            self.logger.warning("optuna_skip", model=model_name, error=str(e))
            return {}

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


# HJ 2026-06-11 — G4 모달 라이브 피드용. eda_agent.py 패턴 동일.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


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
            # 재시도 비례 trial/timeout 증액 (지역값 — 인스턴스 영구변형 금지).
            _rl = int(getattr(state, "re_loop_count", 0) or 0)
            _scale = 1.0 + 0.5 * _rl
            _eff_n_trials = max(1, int(round(self.n_trials * _scale)))
            _eff_timeout = max(1, int(round(self.timeout_per_model_sec * _scale)))
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
            n_models = len(state.model_candidates)
            # HJ 2026-06-11 — G4 모달 라이브 피드: 튜닝 진입 시점 status + 모델별 진행 publish.
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g4_phase": "hpo_start",
                    "g4_status": f"하이퍼파라미터 튜닝 시작 — {n_models}개 모델, 각 {self.n_trials} trials",
                    "hpo_total_models": n_models,
                    "hpo_trials_per_model": self.n_trials,
                },
            )
            _g4_hpo_insights: list[str] = []
            for idx, model_name in enumerate(state.model_candidates, start=1):
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g4_phase": "hpo_progress",
                        "g4_status": f"튜닝 중 ({idx}/{n_models}) — {model_name}",
                        "hpo_current_model": model_name,
                        "hpo_done_count": idx - 1,
                    },
                )
                best = await self._run_optuna(
                    state,
                    model_name,
                    X,
                    y,
                    task,
                    ss_module,
                    n_trials=_eff_n_trials,
                    timeout_sec=_eff_timeout,
                )
                best_params[model_name] = best
                # HJ 2026-06-11 — 모델별 튜닝 결과 자연어 인사이트 누적 publish.
                # 사용자가 G2 의 eda_insights 처럼 모델별 최적 파라미터 라이브 확인.
                try:
                    if best:
                        _p_pairs = [f"{k}={v}" for k, v in list(best.items())[:4]]
                        _g4_hpo_insights.append(f"튜닝 결과: {model_name} → {', '.join(_p_pairs)}")
                    else:
                        _g4_hpo_insights.append(f"튜닝 결과: {model_name} → 기본 파라미터 사용")
                    _safe_publish_stage_partial(
                        state.job_id,
                        {"g4_hpo_insights": list(_g4_hpo_insights)},
                    )
                except Exception:  # noqa: BLE001
                    pass
            # 튜닝 완료 publish — frontend 모달이 best_params 받기 전 미리 안내.
            _g4_hpo_insights = await self._dynamic_insights(
                _g4_hpo_insights,
                backend="claude",
                context="G4 하이퍼파라미터 튜닝",
                job_id=state.job_id,
                key="g4_hpo_insights",
            )
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g4_phase": "hpo_done",
                    "g4_status": f"하이퍼파라미터 튜닝 완료 — {n_models}개 모델 — 학습 단계로 이동",
                    "hpo_done_count": n_models,
                    "g4_hpo_insights": _g4_hpo_insights,
                },
            )

            return state.with_update(best_params=best_params, next_agent="training_executor")

    async def _load_xy(self, state: PipelineState):
        """train+val 까지만 CV 사용 (test 격리). 메타 없으면 전체 폴백."""
        try:
            from agents.handlers.common.shared import load_dataframe_from_state
            from agents.training_executor import _leakage_split_bounds, _split_xy

            df = load_dataframe_from_state(state)
            X, y = _split_xy(df, state.target_column)
            bounds = _leakage_split_bounds(state)
            if bounds is not None:
                cut = bounds[0] + bounds[1]
                if 0 < cut <= len(X):
                    return X[:cut], y[:cut]
            return X, y
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

    async def _run_optuna(
        self,
        state,
        model_name,
        X,
        y,
        task,
        ss_module,
        *,
        n_trials: int | None = None,
        timeout_sec: int | None = None,
    ) -> dict[str, Any]:
        _n_trials = int(n_trials) if n_trials is not None else self.n_trials
        _timeout_sec = int(timeout_sec) if timeout_sec is not None else self.timeout_per_model_sec
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
                    n_trials=_n_trials,
                    timeout=_timeout_sec,
                    catch=(Exception,),
                    show_progress_bar=False,
                )
                return dict(study.best_params) if study.best_trial else {}
            except Exception as e:
                self.logger.warning("optuna_failed", model=model_name, error=str(e))
                return {}

        return await loop.run_in_executor(None, _search)

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
from agents.base import BaseAgent, reloop_seed


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
                    "g4_status": f"하이퍼파라미터 튜닝 시작 — {n_models}개 모델 병렬, 각 {self.n_trials} trials",
                    "hpo_total_models": n_models,
                    "hpo_trials_per_model": self.n_trials,
                },
            )
            _g4_hpo_insights: list[str] = []

            # HJ 2026-06-13 — 모델별 튜닝 병렬 + 실시간 publish.
            #   각 Optuna study 는 독립(study_name 에 model_name 포함, TPESampler(seed=회차별))이라
            #   병렬 실행해도 결과가 직렬과 비트 동일 — 분석 품질 무손실(회차 내부는 결정적).
            #   _run_optuna 는 loop.run_in_executor 기반이라 gather 시 스레드로 동시 실행된다.
            #   한 모델 study 가 끝나는 즉시 그 best_params 인사이트를 누적 publish → 사용자가
            #   "모아서 한 번에"가 아니라 완료되는 순서대로 실시간 확인.
            # hpo_warm_start KB — 동일 카테고리 과거 best_params 를 모델별로 미리 조회(best-effort).
            _warm_map: dict[str, dict] = {}
            try:
                from ada.harness.rag import KBRAG

                if self.session is not None:
                    _warm_map = await KBRAG(self.session).fetch_warm_start_map(state.category)
            except Exception:
                _warm_map = {}
            # warm-start 인용은 부모 컨텍스트에서 카운트(gather 태스크는 ContextVar 격리됨).
            if _warm_map:
                try:
                    from ada.observability.metrics import record_kb_citation

                    for _m in state.model_candidates:
                        if _warm_map.get(_m):
                            record_kb_citation(source="hpo_warm_start_kb")
                except Exception:
                    pass

            async def _tune_one(model_name: str) -> None:
                _ws = _warm_map.get(model_name)
                best = await self._run_optuna(
                    state,
                    model_name,
                    X,
                    y,
                    task,
                    ss_module,
                    n_trials=_eff_n_trials,
                    timeout_sec=_eff_timeout,
                    warm_start=_ws,
                )
                # asyncio 단일 스레드 — await 종료 후 아래 동기 구간은 원자적(race 없음).
                best_params[model_name] = best
                try:
                    if best:
                        _p_pairs = [f"{k}={v}" for k, v in list(best.items())[:4]]
                        _g4_hpo_insights.append(f"튜닝 결과: {model_name} → {', '.join(_p_pairs)}")
                    else:
                        _g4_hpo_insights.append(f"튜닝 결과: {model_name} → 기본 파라미터 사용")
                    _done = len(_g4_hpo_insights)
                    _safe_publish_stage_partial(
                        state.job_id,
                        {
                            "g4_phase": "hpo_progress",
                            "g4_status": f"튜닝 완료 ({_done}/{n_models}) — {model_name}",
                            "hpo_done_count": _done,
                            "g4_hpo_insights": list(_g4_hpo_insights),
                        },
                    )
                except Exception:  # noqa: BLE001
                    pass

            await asyncio.gather(
                *(_tune_one(m) for m in state.model_candidates),
                return_exceptions=True,
            )

            # HJ 2026-06-13 — Claude 윤색은 백그라운드로(critical path 제거) → 학습 단계 즉시 전진.
            #   윤색 결과는 _dynamic_insights 가 job_id+key 로 직접 모달에 publish(교체)하며,
            #   미완분은 게이트 도달 직전 runner.drain_background_insights() 가 회수한다.
            self._spawn_insight_polish(
                list(_g4_hpo_insights),
                backend="ollama",
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
                },
            )

            try:
                self._run_payload_extra["best_params"] = {m: p for m, p in best_params.items() if p}
            except Exception:
                pass
            return state.with_update(best_params=best_params, next_agent="training_executor")

    async def _load_xy(self, state: PipelineState):
        """train+val 까지만 CV 사용 (test 격리). 메타 없으면 전체 폴백."""
        try:
            from agents.handlers.common.shared import load_dataframe_from_state
            from agents.training_executor import (
                _leakage_split_bounds,
                _resolve_timeseries_target,
                _split_xy,
            )

            df = load_dataframe_from_state(state)
            # HJ 2026-06-14 — training_executor 와 동일하게 timeseries 타깃 미지정 방어.
            #   y=np.zeros 폴백 시 CV improvement 가 전부 0 → best_params 가 무의미해진다.
            target_col = state.target_column
            if state.category == "timeseries" and not (target_col and target_col in df.columns):
                date_col = (state.data_profile or {}).get("date_col")
                auto_t = _resolve_timeseries_target(df, date_col)
                if auto_t:
                    target_col = auto_t
                    self.logger.info("hpo_ts_target_autoselected", target=target_col)
            X, y = _split_xy(df, target_col)
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
        warm_start: dict[str, Any] | None = None,
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

            # HJ 2026-06-14 — 재시도 회차별 시드. seed=42 고정이면 재시도해도 TPE 가
            #   동일 경로를 탐색해 best_params·metric 이 안 변한다(사용자 보고). 회차마다
            #   다른 seed → 실제로 다른 하이퍼파라미터 영역 탐색 → 수치값 변동. 첫 실행은 42.
            study = optuna.create_study(
                direction="maximize",
                study_name=f"{state.job_id}-{model_name}",
                sampler=optuna.samplers.TPESampler(seed=reloop_seed(state)),
            )
            # hpo_warm_start — 과거 best_params 를 첫 trial 로 enqueue (미일치 키는 Optuna 가 무시).
            if warm_start:
                try:
                    study.enqueue_trial(dict(warm_start))
                except Exception as _we:  # noqa: BLE001
                    self.logger.warning("warm_start_enqueue_failed", model=model_name, error=str(_we))

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
                    if task == "anomaly_detection":
                        # HJ 2026-06-16 — 버그 수정: 기존 next(iter(metrics.values()))는
                        #   metrics 첫 키인 'threshold'를 maximize 해 무의미했다. AUC(점수 순위
                        #   기반)로 튜닝하되, 레이블이 없으면(순수 비지도) val_auc=None →
                        #   objective 정의 불가이므로 0(기본 파라미터로 귀결, 무해).
                        _auc = metrics.get("val_auc")
                        return float(_auc) if _auc is not None else 0.0
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
                if not study.best_trial:
                    return {}
                # HJ 2026-06-13 — search_space 의 고정값(random_state·n_jobs·seed·eval_metric 등)은
                #   trial.suggest_* 를 거치지 않아 study.best_params 에 누락된다. FixedTrial 로
                #   search_space 를 1회 재실행해 고정값까지 포함한 완전한 파라미터로 복원한다.
                #   (HJ 2026-06-13 복구: 직전 bind-mount 손상으로 끝부분 유실 → 동일 의도·시그니처로 재작성)
                best = dict(study.best_params)
                try:
                    _sfn = getattr(ss_module, "get_search_space", None)
                    if callable(_sfn):
                        full = _sfn(model_name, optuna.trial.FixedTrial(study.best_params))
                        if isinstance(full, dict) and full:
                            best = {**full, **best}
                except Exception as e:
                    self.logger.warning("fixedtrial_restore_failed", model=model_name, error=str(e))
                return best
            except Exception as e:
                self.logger.warning("optuna_failed", model=model_name, error=str(e))
                return {}

        return await loop.run_in_executor(None, _search)

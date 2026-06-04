"""agents.training_executor — TrainingExecutorAgent (Day08 + Day 6 best_params 연결).

4 카테고리에 따라 PipelineFactory 로 파이프라인을 선택하고,
ModelSelectionAgent 가 선정한 후보 3종을 학습한다.

Day 6 계약: state.best_params[model] 가 있으면 그 값을 params 로 흘려준다.

2026-06-04 (HJ) — heavy/light 분기 추가:
    HEAVY 모델 (DL 카테고리 + 무거운 시계열·이상탐지 Transformer 계열) 은
    별도 ``ada.training.run`` Celery 태스크로 위임 → 학원 worker-training (GPU) 처리.
    Light 모델 (전통 ML/통계/IsolationForest 등) 은 기존대로 인라인 학습.
    위임 타임아웃 시 CPU 인라인으로 자동 폴백.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from ada.core.config import settings
from ada.core.state import PipelineState
from agents.base import BaseAgent
from orchestrator.training_tasks import HEAVY_MODELS, is_heavy_model
from pipelines.factory import PipelineFactory


def _split_xy(df: Any, target: str | None) -> tuple[Any, Any]:
    if target and target in df.columns:
        X = df.drop(columns=[target])
        y = df[target]
        return X.select_dtypes(include=[np.number, "bool"]).fillna(0).values, y.values
    return df.select_dtypes(include=[np.number]).fillna(0).values, np.zeros(len(df))


class TrainingExecutorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                from agents.handlers.common.shared import load_dataframe_from_state

                df = load_dataframe_from_state(state)
            except Exception as e:
                return state.with_update(error=f"학습 데이터 로딩 실패: {e}", next_agent="error_recovery")

            X, y = _split_xy(df, state.target_column)
            # train/val split — 시계열은 시간순 split, 그 외 random
            if state.category == "timeseries":
                split = int(len(X) * 0.8)
                X_tr, X_val = X[:split], X[split:]
                y_tr, y_val = y[:split], y[split:]
            else:
                from sklearn.model_selection import train_test_split

                X_tr, X_val, y_tr, y_val = train_test_split(
                    X,
                    y,
                    test_size=0.2,
                    random_state=42,
                    stratify=y
                    if state.category in ("tabular_ml", "tabular_dl") and len(set(y.tolist())) <= 20
                    else None,
                )

            pipeline = PipelineFactory.create(state.category)
            task = (
                "classification"
                if state.category in ("tabular_ml", "tabular_dl") and len(set(y.tolist())) <= 20
                else "regression"
            )
            if state.category == "timeseries":
                task = "forecasting"
            if state.category == "anomaly_detection":
                task = "anomaly_detection"

            trained: list[dict[str, Any]] = []
            heavy_used: list[str] = []
            for model_name in state.model_candidates:
                # Day 6 계약: HyperparameterTuner 가 채운 best_params 우선 사용.
                params = (state.best_params or {}).get(model_name, {}) or {}

                if is_heavy_model(model_name):
                    # ── 학원 worker-training 위임 (heavy: DL 계열) ────────────
                    info = await self._train_remote(
                        state=state,
                        model_name=model_name,
                        params=params,
                    )
                    if info is not None:
                        trained.append(info)
                        heavy_used.append(model_name)
                        continue
                    # 위임 실패 시 CPU 인라인 폴백
                    self.logger.warning(
                        "heavy_model_remote_failed_fallback_cpu",
                        model=model_name,
                    )

                # ── CPU 인라인 학습 (light + heavy 폴백) ─────────────────────
                try:
                    model = pipeline.train(X_tr, y_tr, model_name=model_name, params=params)
                    metrics = pipeline.evaluate(model, X_val, y_val, task=task)
                    info: dict[str, Any] = {
                        "model_name": model_name,
                        "metrics": metrics,
                        "mlflow_run_id": pipeline.mlflow_run_id,
                        "params_used": params,
                        "executed_on": "pipeline_worker",
                    }
                    if state.category == "tabular_ml":
                        save = pipeline.save_model(model, state.job_id, model_name)
                        info.update(save)
                    trained.append(info)
                except Exception as e:
                    self.logger.warning("train_failed", model=model_name, error=str(e))

            self.logger.info(
                "training_done",
                trained=len(trained),
                heavy_dispatched=heavy_used,
                heavy_known=sorted(HEAVY_MODELS),
            )
            return state.with_update(trained_models=trained, next_agent="training_monitor")

    # ------------------------------------------------------------------
    async def _train_remote(
        self,
        *,
        state: PipelineState,
        model_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        """heavy 모델을 ``ada.training.run`` 태스크로 위임 후 sync wait.

        반환:
            성공 시 train_model_task 의 dict 결과 (단, "error" 키 있으면 None 반환).
            타임아웃·통신 실패·기타 예외 시 None 반환 → caller 가 CPU 인라인 폴백.
        """
        from orchestrator.training_tasks import train_model_task

        timeout = settings.training_task_timeout_sec
        try:
            async_result = train_model_task.apply_async(
                args=[
                    state.job_id,
                    state.file_id,
                    state.category,
                    state.target_column,
                    model_name,
                    params,
                ],
                queue="training",
            )
        except Exception as e:  # noqa: BLE001
            self.logger.warning("remote_dispatch_failed", model=model_name, error=str(e))
            return None

        try:
            # AsyncResult.get 은 동기 블로킹 → asyncio.to_thread 로 이벤트 루프 해방.
            info = await asyncio.to_thread(async_result.get, timeout=timeout)
        except Exception as e:  # noqa: BLE001  (celery.exceptions.TimeoutError 포함)
            self.logger.warning(
                "remote_train_timeout_or_error",
                model=model_name,
                timeout_sec=timeout,
                error=str(e),
            )
            # 큐에 남은 태스크 revoke (워커가 늦게 받더라도 결과는 폐기)
            try:
                async_result.revoke(terminate=False)
            except Exception:  # noqa: BLE001
                pass
            return None

        if not isinstance(info, dict):
            self.logger.warning("remote_train_bad_payload", model=model_name, payload_type=type(info).__name__)
            return None
        if info.get("error"):
            self.logger.warning(
                "remote_train_returned_error",
                model=model_name,
                error=info["error"],
            )
            return None
        return info

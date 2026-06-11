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
from datetime import datetime
from typing import Any

import numpy as np

from ada.core.config import settings
from ada.core.state import PipelineState
from agents.base import BaseAgent


# HJ 2026-06-11 — G4 모달 라이브 피드용 (모델별 학습 진행 상황 publish).
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass
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
            # HJ — 학습 시작 시각 기록 (TrainingMonitor 의 timeout 기준).
            # 매 retry 마다 새 시점으로 리셋돼 retry-after-timeout 무한루프 방지.
            # 데이터 로딩 시간도 학습 walltime 에 포함 (사용자 관점에서 "학습 단계" 전체).
            training_started = datetime.utcnow()

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
            n_models = len(state.model_candidates)
            # HJ 2026-06-11 — 학습 시작 publish.
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g4_phase": "training_start",
                    "g4_status": f"모델 학습 시작 — {n_models}개 모델 후보",
                    "training_total_models": n_models,
                },
            )
            for _idx, model_name in enumerate(state.model_candidates, start=1):
                # HJ 2026-06-11 — 모델별 학습 진행 publish.
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g4_phase": "training_progress",
                        "g4_status": f"학습 중 ({_idx}/{n_models}) — {model_name}",
                        "training_current_model": model_name,
                        "training_done_count": _idx - 1,
                    },
                )
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

            # HJ 2026-06-11 — G4 모달 라이브 피드: 모델별 학습 메트릭을 자연어 인사이트로 publish.
            # G2 의 eda_insights 패턴 — 사용자가 어떤 모델이 어떤 점수 받았는지 즉시 확인.
            try:
                _g4_train_insights: list[str] = []
                for info in trained:
                    mn = info.get("model_name", "?")
                    metrics = info.get("metrics") or {}
                    if metrics:
                        # 상위 4개 메트릭만 표시
                        _m_pairs = []
                        for k in list(metrics.keys())[:4]:
                            v = metrics[k]
                            try:
                                _m_pairs.append(f"{k}={float(v):.3f}")
                            except (TypeError, ValueError):
                                _m_pairs.append(f"{k}={v}")
                        _g4_train_insights.append(f"학습 결과: {mn} → {', '.join(_m_pairs)}")
                    else:
                        _g4_train_insights.append(f"학습 결과: {mn} (메트릭 미산출)")
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g4_phase": "training_done",
                        "g4_status": f"학습 완료 — {len(trained)}개 모델 학습 완료, 메트릭 집계 단계로 이동",
                        "g4_train_insights": _g4_train_insights,
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("g4_train_insights_publish_failed", error=str(e))

            return state.with_update(
                trained_models=trained,
                training_started_at=training_started,
                next_agent="training_monitor",
            )

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

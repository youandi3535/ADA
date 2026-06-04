"""orchestrator.training_tasks — ``ada.training.*`` Celery 태스크.

운영 의도:
    무거운 학습(특히 GPU 가속이 필요한 DL 모델)을 별도 워커 컨테이너
    (학원 서버 worker-training, GTX 1060 3GB) 로 위임해 VPS worker-pipeline
    이 다른 단계(전처리·EDA·평가·인사이트) 를 빠르게 진행하도록 한다.

라우팅:
    ``orchestrator.runner.celery_app.conf.task_routes`` 에 이미
    ``"ada.training.*": {"queue": "training"}`` 패턴이 정의돼 있어,
    본 모듈의 task 들은 자동으로 training 큐로 흘러간다.

호출 패턴:
    TrainingExecutorAgent 가 heavy 모델 한 종마다:

        async_result = train_model_task.apply_async(
            args=[job_id, file_id, category, target_column, model_name, params, seed],
            queue="training",
        )
        info = async_result.get(timeout=settings.training_task_timeout_sec)

    학원 워커가 응답 없으면 타임아웃 → caller 가 CPU 인라인 폴백.

수정 권한: **HJ 단독** (orchestrator/ 전체).
"""

from __future__ import annotations

import time
from typing import Any

from ada.core.config import settings
from ada.core.logger import get_logger
from orchestrator.runner import celery_app, publish_progress

_log = get_logger("training_tasks")


# ---------------------------------------------------------------------------
# 무거운 모델 화이트리스트 — TrainingExecutorAgent 도 동일 셋을 import.
# 한 곳에서 관리해 두 파일이 어긋나지 않게 함.
# ---------------------------------------------------------------------------
HEAVY_MODELS: frozenset[str] = frozenset(
    {
        # tabular_dl — 전부 무거움 (Transformer 계열)
        "TabTransformer",
        "FTTransformer",
        "TabPFN",
        # timeseries DL — Transformer 계열만. ARIMA/SARIMA/Prophet 은 CPU 인라인.
        "Informer",
        "TFT",
        "PatchTST",
        # anomaly DL — AutoEncoder + Transformer 계열. IsolationForest/LOF/OCSVM 은 CPU.
        "AutoEncoder",
        "TranAD",
        "AnomalyTransformer",
    }
)


def is_heavy_model(model_name: str) -> bool:
    """주어진 model_name 이 GPU 워커 위임 대상인지."""
    return model_name in HEAVY_MODELS


# ---------------------------------------------------------------------------
# train_model_task — 단일 모델 학습을 학원 워커에 위임
# ---------------------------------------------------------------------------
@celery_app.task(
    bind=True,
    name="ada.training.run",
    queue="training",
    # 학원 GPU 워커 hard time limit — pipeline 큐와 동일 30 분.
    time_limit=settings.pipeline_timeout_min * 60,
    soft_time_limit=settings.pipeline_timeout_min * 60 - 60,
    max_retries=0,  # 학습은 재시도 비용이 커서 caller 가 폴백 결정.
)
def train_model_task(
    self: Any,
    job_id: str,
    file_id: str,
    category: str,
    target_column: str | None,
    model_name: str,
    params: dict[str, Any] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """단일 모델 학습 → 평가 → MinIO 저장 → 메타데이터 반환.

    state 객체는 Celery 직렬화에 부적합하므로 **스칼라 + file_id** 만 인자로 받는다.
    데이터는 MinIO 에서 직접 로드한다 (``load_dataframe_from_state`` 와 동일 경로).

    Returns
    -------
    dict
        ``{"model_name", "metrics", "mlflow_run_id", "params_used",
            "minio_path"?, "model_sha256"?, "executed_on": "training_worker",
            "elapsed_sec": float}``
        에러 시 ``{"model_name", "error": str, "executed_on": "training_worker"}``.
    """
    import numpy as np

    t0 = time.perf_counter()
    publish_progress(job_id, "training_executor", f"{model_name} 학습 시작 (GPU 워커)")

    try:
        # 1) 데이터 로드 — load_dataframe_from_state 와 동일한 MinIO 경로 규약.
        #    state.file_id 가 인자 file_id 와 동일하므로 가벼운 어댑터 사용.
        from tools.minio_tool import get_minio_client

        client = get_minio_client()
        keys = client.list_objects(prefix=f"uploads/{file_id}/")
        if keys:
            object_name = keys[0]
            fmt = object_name.rsplit(".", 1)[-1].lower() if "." in object_name else "csv"
            df = client.load_dataframe(object_name, fmt=fmt)
        else:
            fmt = file_id.rsplit(".", 1)[-1].lower() if "." in file_id else "csv"
            df = client.load_dataframe(file_id, fmt=fmt)

        # 2) X / y 분리 — TrainingExecutorAgent._split_xy 와 동일 로직
        if target_column and target_column in df.columns:
            X = df.drop(columns=[target_column])
            y = df[target_column]
            X_arr = X.select_dtypes(include=[np.number, "bool"]).fillna(0).values
            y_arr = y.values
        else:
            X_arr = df.select_dtypes(include=[np.number]).fillna(0).values
            y_arr = np.zeros(len(df))

        # 3) train / val split — 시계열은 시간순
        if category == "timeseries":
            split = int(len(X_arr) * 0.8)
            X_tr, X_val = X_arr[:split], X_arr[split:]
            y_tr, y_val = y_arr[:split], y_arr[split:]
        else:
            from sklearn.model_selection import train_test_split

            X_tr, X_val, y_tr, y_val = train_test_split(
                X_arr,
                y_arr,
                test_size=0.2,
                random_state=seed,
                stratify=y_arr if category in ("tabular_ml", "tabular_dl") and len(set(y_arr.tolist())) <= 20 else None,
            )

        # 4) 카테고리 task 결정
        if category in ("tabular_ml", "tabular_dl") and len(set(y_arr.tolist())) <= 20:
            task_kind = "classification"
        elif category == "timeseries":
            task_kind = "forecasting"
        elif category == "anomaly_detection":
            task_kind = "anomaly_detection"
        else:
            task_kind = "regression"

        # 5) 학습 + 평가
        from pipelines.factory import PipelineFactory

        pipeline = PipelineFactory.create(category)
        model = pipeline.train(X_tr, y_tr, model_name=model_name, params=params or {})
        metrics = pipeline.evaluate(model, X_val, y_val, task=task_kind)

        info: dict[str, Any] = {
            "model_name": model_name,
            "metrics": metrics,
            "mlflow_run_id": pipeline.mlflow_run_id,
            "params_used": params or {},
            "executed_on": "training_worker",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }

        # 6) 모델 저장 — 카테고리에 save_model 이 있으면 호출 (tabular_ml 만 보유 중)
        if hasattr(pipeline, "save_model"):
            try:
                save_info = pipeline.save_model(model, job_id, model_name)
                if isinstance(save_info, dict):
                    info.update(save_info)
            except Exception as e:  # noqa: BLE001
                _log.warning("save_model_failed", model=model_name, error=str(e))

        publish_progress(
            job_id,
            "training_executor",
            f"{model_name} 학습 완료 ({info['elapsed_sec']}s, GPU 워커)",
        )
        _log.info(
            "train_model_task_ok",
            job_id=job_id,
            model=model_name,
            category=category,
            elapsed_sec=info["elapsed_sec"],
        )
        return info

    except Exception as e:  # noqa: BLE001
        import traceback as _tb

        tb = _tb.format_exc()
        _log.error(
            "train_model_task_failed",
            job_id=job_id,
            model=model_name,
            error=str(e),
            traceback=tb[:1000],
        )
        # AutoErrorHandler 위임 (Tier 0~3 학습 트리거) — fire-and-forget
        try:
            import asyncio as _aio

            from ada.error_handler.auto_handler import capture_and_handle

            _aio.run(
                capture_and_handle(
                    error_message=f"train_model_task: {e}",
                    stack_trace=tb,
                    job_id=job_id,
                    source="training_worker",
                )
            )
        except Exception:  # noqa: BLE001
            pass

        return {
            "model_name": model_name,
            "error": str(e),
            "executed_on": "training_worker",
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }


# ---------------------------------------------------------------------------
# ping — 학원 워커 헬스체크용 (toplogy B 가이드의 셋업 검증 단계)
# ---------------------------------------------------------------------------
@celery_app.task(name="ada.training.ping", queue="training")
def training_ping() -> str:
    """학원 worker-training 가 task 를 실제로 수신하는지 확인용.

    셋업 가이드:
        from orchestrator.training_tasks import training_ping
        training_ping.apply_async(queue="training").get(timeout=10)
        # → "pong:training_worker" 면 OK
    """
    return "pong:training_worker"

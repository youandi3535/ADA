"""serving/main.py — MLflow 모델 서빙 진입점.

로딩 우선순위:
  1. MLflow pyfunc  (mlflow_run_id 가 있는 경우)
  2. MinIO joblib   (minio_path 가 있는 경우)
  3. 둘 다 없으면 503

아티팩트 검색 우선순위:
  1. model_id (str UUID) 명시 → models DB 테이블에서 해당 행 검색
  2. 미지정 → models 테이블에서 job 기준 is_best=True 행,
                없으면 created_at DESC 첫 번째 행
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ADA v2 Serving",
    version="0.2.0",
    description="ADA v2 모델 추론 서비스 — joblib(MinIO) / MLflow pyfunc 이중 로딩",
)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class PredictRequest(BaseModel):
    """POST /predict 요청 스키마.

    features: list of dicts — 각 dict 가 row 1개 (feature name → value).
    model_id: optional UUID str — 지정 시 해당 모델만, 미지정 시 최신 best 모델.
    """

    features: list[dict[str, Any]] = Field(..., min_length=1, description="1개 이상의 feature record")
    model_id: Optional[str] = Field(None, description="models 테이블 UUID (생략 시 최신 best)")


class PredictResponse(BaseModel):
    """POST /predict 응답 스키마."""

    model_id: Optional[str]
    model_name: Optional[str]
    framework: Optional[str]
    predictions: list[Any]
    probabilities: Optional[list[Any]] = None  # classification predict_proba
    scores: Optional[list[float]] = None  # anomaly decision score
    n_samples: int


# ---------------------------------------------------------------------------
# Model cache  (thread-safe, process-local)
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
# key → (loaded_model, model_meta_dict)
_model_cache: dict[str, tuple[Any, dict[str, Any]]] = {}


def _cache_key(model_id: Optional[str]) -> str:
    return model_id or "__latest__"


# ---------------------------------------------------------------------------
# DB helpers  (async SQLAlchemy)
# ---------------------------------------------------------------------------


async def _get_model_meta(model_id: Optional[str]) -> dict[str, Any]:
    """models 테이블에서 메타데이터를 조회한다.

    반환: {"id", "model_name", "framework", "minio_path", "mlflow_run_id", ...}
    DB 연결 불가 / 행 없음 → {} 반환 (호출자가 503 판단).
    """
    try:
        from sqlalchemy import desc, select

        from ada.db.models import Model
        from ada.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            if model_id:
                import uuid as _uuid

                stmt = select(Model).where(Model.id == _uuid.UUID(model_id))
            else:
                # is_best=True 우선, 없으면 최신
                stmt_best = select(Model).where(Model.is_best.is_(True)).order_by(desc(Model.created_at)).limit(1)
                result_best = await session.execute(stmt_best)
                row = result_best.scalar_one_or_none()
                if row is None:
                    stmt = select(Model).order_by(desc(Model.created_at)).limit(1)
                else:
                    return {
                        "id": str(row.id),
                        "model_name": row.model_name,
                        "framework": row.framework,
                        "minio_path": row.minio_path,
                        "mlflow_run_id": row.mlflow_run_id,
                        "metrics": row.metrics,
                        "model_sha256": row.model_sha256,
                    }

            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            if row is None:
                return {}
            return {
                "id": str(row.id),
                "model_name": row.model_name,
                "framework": row.framework,
                "minio_path": row.minio_path,
                "mlflow_run_id": row.mlflow_run_id,
                "metrics": row.metrics,
                "model_sha256": row.model_sha256,
            }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Model loaders
# ---------------------------------------------------------------------------


def _load_via_mlflow(run_id: str) -> Any:
    """mlflow.pyfunc.load_model 로 모델 로드 (runs:/ URI 사용)."""
    import mlflow.pyfunc  # noqa: WPS433

    from ada.core.config import settings

    mlflow_uri = os.environ.get("MLFLOW_TRACKING_URI", settings.mlflow_tracking_uri)
    import mlflow  # noqa: WPS433

    mlflow.set_tracking_uri(mlflow_uri)
    model_uri = f"runs:/{run_id}/model"
    return mlflow.pyfunc.load_model(model_uri)


def _load_via_minio(minio_path: str, expected_sha256: Optional[str] = None) -> Any:
    """MinIO 에서 joblib 아티팩트를 다운로드해 역직렬화한다.

    R-704: model_sha256 이 있으면 무결성 검증 후 로딩.
    """
    import joblib  # noqa: WPS433

    from tools.minio_tool import get_minio_client

    mc = get_minio_client()
    object_name = mc.object_key(minio_path)  # 버킷명 무관 s3:// 접두 제거 (단일 진입점)

    raw_bytes = mc.download_bytes(object_name)

    # R-704 무결성 검사
    if expected_sha256:
        actual = hashlib.sha256(raw_bytes).hexdigest()
        if actual != expected_sha256:
            raise ValueError(f"모델 SHA256 불일치: expected={expected_sha256}, actual={actual}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".joblib") as tf:
        tf.write(raw_bytes)
        tmp_path = tf.name
    try:
        return joblib.load(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def _resolve_model(model_id: Optional[str]) -> tuple[Any, dict[str, Any]]:
    """캐시에서 모델을 가져오거나 새로 로드한다.

    반환: (loaded_model_obj, meta_dict)
    로드 불가 시 HTTPException 발생.
    """
    key = _cache_key(model_id)
    with _cache_lock:
        if key in _model_cache:
            return _model_cache[key]

    meta = await _get_model_meta(model_id)
    if not meta:
        if model_id:
            raise HTTPException(status_code=404, detail=f"model_id={model_id} 를 찾을 수 없습니다.")
        raise HTTPException(status_code=503, detail="사용 가능한 모델이 없습니다. 파이프라인 실행 후 재시도하세요.")

    loaded: Optional[Any] = None
    last_exc: Optional[Exception] = None

    # 1순위: MLflow pyfunc
    run_id = meta.get("mlflow_run_id")
    if run_id:
        try:
            loaded = _load_via_mlflow(run_id)
        except Exception as exc:
            last_exc = exc

    # 2순위: MinIO joblib
    if loaded is None:
        minio_path = meta.get("minio_path")
        if minio_path:
            try:
                loaded = _load_via_minio(minio_path, meta.get("model_sha256"))
            except Exception as exc:
                last_exc = exc

    if loaded is None:
        detail = f"모델 로딩 실패: {last_exc}" if last_exc else "minio_path 및 mlflow_run_id 모두 없음"
        raise HTTPException(status_code=503, detail=detail)

    with _cache_lock:
        _model_cache[key] = (loaded, meta)

    return loaded, meta


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------


def _features_to_array(features: list[dict[str, Any]]) -> Any:
    """feature record 목록을 numpy array 로 변환한다.

    float/int 컬럼만 추출하고 NaN 은 0 으로 채운다.
    """
    try:
        import numpy as np
        import pandas as pd  # noqa: WPS433

        df = pd.DataFrame(features)
        numeric_df = df.select_dtypes(include=[np.number, "bool"]).fillna(0)
        if numeric_df.empty:
            raise ValueError("numeric feature 가 없습니다. 입력 dict 의 값이 숫자인지 확인하세요.")
        return numeric_df.values, list(numeric_df.columns)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"pandas/numpy 미설치: {exc}") from exc


def _run_inference(model: Any, X: Any) -> tuple[list[Any], Optional[list[Any]], Optional[list[float]]]:
    """예측 실행. 반환: (predictions, probabilities, scores).

    - classification: predictions + probabilities (predict_proba 있으면)
    - regression / forecasting: predictions only
    - anomaly (score_samples / decision_function): scores
    """
    import numpy as np  # noqa: WPS433

    # MLflow pyfunc — 다양한 MLflow 버전에서 안전한 식별:
    #   - 신버전: PyFuncModel 클래스 또는 _model_impl 속성
    #   - 구버전: metadata 속성 (flavor 정보)
    # 어느 쪽이든 실패 시 sklearn-style 폴백.
    _is_mlflow_pyfunc = (
        type(model).__module__.startswith("mlflow.") or hasattr(model, "_model_impl") or hasattr(model, "metadata")
    )
    if hasattr(model, "predict") and _is_mlflow_pyfunc:
        try:
            import pandas as pd  # noqa: WPS433

            result = model.predict(pd.DataFrame(X))
            preds = np.asarray(result).flatten().tolist()
            return preds, None, None
        except Exception:
            pass

    # sklearn-style
    try:
        preds = np.asarray(model.predict(X)).flatten().tolist()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"predict 실패: {exc}") from exc

    probas: Optional[list[Any]] = None
    scores_out: Optional[list[float]] = None

    # classification: probabilities
    if hasattr(model, "predict_proba"):
        try:
            p = model.predict_proba(X)
            # binary: return 1-D (positive class probability)
            if p.ndim == 2 and p.shape[1] == 2:
                probas = p[:, 1].tolist()
            else:
                probas = p.tolist()
        except Exception:
            pass

    # anomaly: raw anomaly score (higher = more anomalous, PyOD convention)
    if probas is None:
        if hasattr(model, "decision_function"):
            try:
                sc = np.asarray(model.decision_function(X)).flatten()
                scores_out = sc.tolist()
            except Exception:
                pass
        elif hasattr(model, "score_samples"):
            try:
                sc = -np.asarray(model.score_samples(X)).flatten()
                scores_out = sc.tolist()
            except Exception:
                pass

    return preds, probas, scores_out


# ---------------------------------------------------------------------------
# Lifespan & exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(RequestValidationError)
async def _validation_exc(_req: Any, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "validation_error", "details": exc.errors()})


@app.exception_handler(Exception)
async def _generic_exc(_req: Any, exc: Exception) -> JSONResponse:
    import asyncio
    import traceback as _tb
    import uuid as _uuid

    err_id = str(_uuid.uuid4())
    try:
        from ada.core.logger import get_logger as _get_log

        _get_log("serving").error("unhandled_exception", err_id=err_id, error=str(exc))
    except Exception:  # noqa: BLE001
        pass

    try:
        from ada.error_handler.auto_handler import capture_and_handle

        asyncio.create_task(
            capture_and_handle(
                error_message=str(exc),
                stack_trace=_tb.format_exc(),
                source="serving",
            )
        )
    except Exception:  # noqa: BLE001
        pass

    return JSONResponse(status_code=500, content={"error": "internal_error", "error_id": err_id})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "serving",
        "mlflow": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
    }


@app.post("/predict", response_model=PredictResponse, tags=["inference"])
async def predict(body: PredictRequest) -> PredictResponse:
    """모델 추론 엔드포인트.

    요청:
        {
          "features": [{"col1": 1.0, "col2": 2.5}, ...],
          "model_id": "<UUID>"   // 선택 — 생략 시 latest best
        }

    응답:
        {
          "model_id": "...",
          "model_name": "RandomForest",
          "framework": "sklearn",
          "predictions": [...],
          "probabilities": [...],   // classification 전용
          "scores": [...],          // anomaly 전용
          "n_samples": 10
        }

    오류:
        503 — 가용 모델 없음 / 로딩 실패
        404 — model_id 미존재
        422 — 입력 검증 실패 / predict 오류
    """
    model, meta = await _resolve_model(body.model_id)

    try:
        X, _columns = _features_to_array(body.features)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"feature 변환 실패: {exc}") from exc

    predictions, probabilities, scores = _run_inference(model, X)

    return PredictResponse(
        model_id=meta.get("id"),
        model_name=meta.get("model_name"),
        framework=meta.get("framework"),
        predictions=predictions,
        probabilities=probabilities,
        scores=scores,
        n_samples=len(predictions),
    )


@app.delete("/cache", tags=["admin"], status_code=200)
async def clear_cache() -> dict[str, int]:
    """인메모리 모델 캐시를 제거한다 (재배포 없이 모델 갱신 시 사용)."""
    with _cache_lock:
        n = len(_model_cache)
        _model_cache.clear()
    return {"evicted": n}

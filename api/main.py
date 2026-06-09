"""api/main.py — FastAPI 진입점 (Day06 본격 라우터 통합).

Day13/Day17 에서 인증·rate-limit·SSE 추가.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from ada.core.config import settings
from ada.core.logger import bind_context, get_logger
from api.routes import pipeline as pipeline_routes, upload as upload_routes

log = get_logger("api")


async def _ollama_warmup() -> None:
    """HJ 2026-06-09 — G1 단축: Ollama 모델 사전 로드.

    qwen2.5:7b 첫 호출은 모델 가중치 로드로 +10~20s 비용. KEEP_ALIVE=30m 이라 두 번째부터는
    무료. 서버 시작 직후 짧은 ping 한 번으로 첫 사용자의 cold start 부담 제거.
    Ollama 가 안 떠있어도 silent fail — 본 서비스 흐름 영향 없음.
    """
    import asyncio
    import json
    import urllib.error
    import urllib.request

    if not getattr(settings, "use_ollama_for_analysis", False):
        return

    base_url = settings.ollama_base_url.rstrip("/")
    model = settings.ollama_model_analysis
    payload = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "options": {"num_predict": 1, "num_gpu": settings.ollama_num_gpu, "num_thread": settings.ollama_num_thread},
        }
    ).encode("utf-8")

    def _do_ping() -> None:
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()  # 결과 무시
        except (urllib.error.URLError, TimeoutError, OSError):
            pass  # silent

    try:
        await asyncio.wait_for(asyncio.to_thread(_do_ping), timeout=35.0)
        log.info("ollama_warmup_ok", model=model)
    except Exception as e:  # noqa: BLE001
        log.warning("ollama_warmup_failed", error=str(e), model=model)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import asyncio as _asyncio

    log.info("api_startup", env=settings.environment)
    # DB 초기화는 Alembic 책임. MinIO 버킷만 보장.
    try:
        from tools.minio_tool import get_minio_client

        get_minio_client()  # _ensure_bucket
    except Exception as e:
        log.warning("minio_init_failed", error=str(e))
    # G1 단축 — Ollama 모델 사전 로드 (fire-and-forget, startup 차단 안 함)
    _asyncio.create_task(_ollama_warmup())
    yield
    log.info("api_shutdown")
    # ADR-007 L3.3 — Langfuse 버퍼 강제 전송 (graceful shutdown)
    try:
        from ada.core.langfuse_client import flush

        flush(timeout_sec=5.0)
    except Exception as e:
        log.warning("langfuse_flush_failed_at_shutdown", error=str(e))


app = FastAPI(
    title="ADA v2 API",
    version="0.2.0",
    description="Adaptive AutoAI Pipeline Agent — 27 에이전트 / 5게이트 HITL / 5종 산출물",
    lifespan=lifespan,
)

# --- 미들웨어 -----------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://localhost:8000", "http://frontend:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next: Any) -> Any:
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    bind_context(request_id=req_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


# --- 예외 핸들러 ---------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": "validation_error",
            "details": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def generic_exc(request: Request, exc: Exception) -> JSONResponse:
    import asyncio
    import traceback as _tb

    err_id = str(uuid.uuid4())
    log.error("unhandled_exception", err_id=err_id, error=str(exc))

    # FastAPI 미처리 예외 → AutoErrorHandler fire-and-forget
    # job_id 는 알 수 없으므로 None. source="api" 로 FailureLog 적재.
    try:
        from ada.error_handler.auto_handler import capture_and_handle

        asyncio.create_task(
            capture_and_handle(
                error_message=str(exc),
                stack_trace=_tb.format_exc(),
                job_id=None,
                source="api",
            )
        )
    except Exception:  # noqa: BLE001
        pass

    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "error_id": err_id,
        },
    )


# --- 라우터 ------------------------------------------------------------------
app.include_router(upload_routes.router, prefix="/upload", tags=["Upload"])
app.include_router(pipeline_routes.router, prefix="/pipeline", tags=["Pipeline"])

# SSE 진행률 (Day13)
from api.routes import stream as stream_routes  # noqa: E402

app.include_router(stream_routes.router, prefix="/stream", tags=["Stream"])

# 인증/JWT (Day17)
from api.routes import auth as auth_routes  # noqa: E402

app.include_router(auth_routes.router, prefix="/auth", tags=["Auth"])

# 자체학습 KB (Day19)
from api.routes import kb as kb_routes  # noqa: E402

app.include_router(kb_routes.router, prefix="/kb", tags=["KB"])

# Prometheus metrics (Day 1)
from api.routes import metrics as metrics_routes  # noqa: E402

app.include_router(metrics_routes.router, tags=["Metrics"])

# Admin audit + observability (Day 3)
from api.routes import admin as admin_routes  # noqa: E402

app.include_router(admin_routes.router, tags=["Admin"])

# KPI 측정 — Day 10 (HJ)
from api.routes import observability as observability_routes  # noqa: E402

app.include_router(observability_routes.router)

# 오류 자동처리 & KB 모니터링 대시보드
from api.routes import error_dashboard as error_dashboard_routes  # noqa: E402

app.include_router(error_dashboard_routes.router)

# 팀 Q&A 수집 & 조회 (KB 학습 원천)
from api.routes import conversation_kb as conversation_kb_routes  # noqa: E402

app.include_router(conversation_kb_routes.router)

# 팀 Q&A KB 검색 (1순위 KB, 2순위 Claude 폴백)
from api.routes import kb_search as kb_search_routes  # noqa: E402

app.include_router(kb_search_routes.router)


# --- 메타 ---------------------------------------------------------------------
@app.get("/health", tags=["meta"])
async def health() -> dict[str, Any]:
    return {"status": "ok", "service": "api", "env": settings.environment, "version": "0.2.0"}


@app.get("/version", tags=["meta"])
async def version() -> dict[str, str]:
    return {"version": "0.2.0"}


@app.get("/", tags=["meta"])
async def root() -> dict[str, Any]:
    return {
        "name": "ADA v2",
        "categories": ["tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"],
        "outputs": ["OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"],
        "gates": ["G1", "G2", "G3", "G4", "G5", "G6"],
        "agents": 27,
    }

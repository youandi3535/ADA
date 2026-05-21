"""serving/main.py — MLflow 모델 서빙 진입점 (Day01 스켈레톤).

Day13/Day19 에서 mlflow.pyfunc.load_model() 로 실제 모델 로딩.
"""
from __future__ import annotations

import os

from fastapi import FastAPI

app = FastAPI(
    title="ADA v2 Serving",
    version="0.1.0",
)


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "serving",
        "mlflow": os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
    }

"""outputs.base — 산출물 생성기 추상 클래스."""
from __future__ import annotations

import abc
import tempfile
import time
from pathlib import Path
from typing import Any


class OutputGenerator(abc.ABC):
    output_code: str = "OUT-XX"
    extension: str = "bin"

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    @abc.abstractmethod
    def generate(self, *, insights: str, best_model: dict[str, Any],
                 eda_charts: list[str], category: str,
                 user_intent: str, eval_result: dict[str, Any] | None) -> str:
        """생성 후 MinIO 경로 반환."""

    # ------------------------------------------------------------------
    def _upload(self, local_path: str) -> str:
        from tools.minio_tool import get_minio_client
        return get_minio_client().save_artifact(
            local_path, f"outputs/{self.output_code}", self.job_id
        )

    def _tmp(self) -> str:
        return tempfile.NamedTemporaryFile(
            delete=False, suffix=f".{self.extension}",
        ).name

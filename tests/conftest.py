"""pytest 공통 fixture — Day14."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
os.environ.setdefault("MINIO_ACCESS_KEY", "test")
os.environ.setdefault("MINIO_SECRET_KEY", "test")


@pytest.fixture
def titanic_df():
    import pandas as pd

    return pd.DataFrame({
        "Pclass":   [1, 2, 3, 1, 3, 2, 1, 3, 2, 3] * 12,
        "Age":      [22, 35, 26, 54, 2, 27, 14, 4, 58, 20] * 12,
        "Fare":     [7.25, 71.83, 7.92, 51.86, 21.07, 11.13, 30.07, 16.7,
                     26.55, 8.05] * 12,
        "Sex_male": [1, 0, 0, 0, 1, 1, 1, 0, 0, 1] * 12,
        "Survived": [0, 1, 1, 1, 0, 0, 0, 1, 1, 0] * 12,
    })


@pytest.fixture
def pipeline_state_min():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="uploads/test/iris.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="고객 생존 예측",
    )

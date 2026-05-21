"""A 단독 — timeseries 테스트 fixture."""
from __future__ import annotations

import pytest


@pytest.fixture
def ts_state():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000a01",
        file_id="uploads/test/sales.csv",
        category="timeseries",
        target_column="sales",
        user_intent="다음 7일 매출 예측",
    )


@pytest.fixture
def ts_df():
    import pandas as pd
    import numpy as np
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=120, freq="D"),
        "sales": (1000 + rng.normal(0, 50, 120).cumsum() +
                  np.sin(np.arange(120) * 2 * np.pi / 7) * 30),
    })

"""B 단독 — anomaly 테스트 fixture."""
from __future__ import annotations

import pytest


@pytest.fixture
def anomaly_state():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000b01",
        file_id="uploads/test/transactions.csv",
        category="anomaly_detection",
        target_column=None,
        user_intent="이상 거래 탐지",
    )


@pytest.fixture
def anomaly_df():
    import pandas as pd
    import numpy as np
    rng = np.random.default_rng(7)
    df = pd.DataFrame({
        "amount": np.concatenate([rng.normal(100, 10, 950), rng.normal(500, 50, 50)]),
        "freq":   np.concatenate([rng.normal(5, 1, 950), rng.normal(20, 5, 50)]),
    })
    return df

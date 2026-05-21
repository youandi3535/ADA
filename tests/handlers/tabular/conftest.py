"""C 단독 — tabular 테스트 fixture."""
from __future__ import annotations

import pytest


@pytest.fixture
def tab_state():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000c01",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="고객 생존 예측",
    )


@pytest.fixture
def tab_df():
    import pandas as pd
    return pd.DataFrame({
        "Pclass":   [1, 2, 3, 1, 3, 2, 1, 3, 2, 3] * 12,
        "Age":      [22, 35, 26, 54, 2, 27, 14, 4, 58, 20] * 12,
        "Fare":     [7.25, 71.83, 7.92, 51.86, 21.07, 11.13, 30.07, 16.7,
                     26.55, 8.05] * 12,
        "Sex":      ["male", "female", "female", "female", "male", "male",
                     "male", "female", "female", "male"] * 12,
        "Survived": [0, 1, 1, 1, 0, 0, 0, 1, 1, 0] * 12,
    })

"""jh 단독 — tabular 테스트 fixture."""

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

    return pd.DataFrame(
        {
            "Pclass": [1, 2, 3, 1, 3, 2, 1, 3, 2, 3] * 12,
            "Age": [22, 35, 26, 54, 2, 27, 14, 4, 58, 20] * 12,
            "Fare": [7.25, 71.83, 7.92, 51.86, 21.07, 11.13, 30.07, 16.7, 26.55, 8.05] * 12,
            "Sex": ["male", "female", "female", "female", "male", "male", "male", "female", "female", "male"] * 12,
            "Survived": [0, 1, 1, 1, 0, 0, 0, 1, 1, 0] * 12,
        }
    )


# ── Day 2 신규 fixture ────────────────────────────────────────────────────────


@pytest.fixture
def tab_dl_state():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000c02",
        file_id="uploads/test/titanic.csv",
        category="tabular_dl",
        target_column="Survived",
        user_intent="딥러닝 생존 예측",
    )


@pytest.fixture
def tab_df_skewed():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(42)
    n = 120
    return pd.DataFrame(
        {
            "Fare": np.exp(rng.normal(2, 1, n)),  # log-normal → high positive skew
            "Age": rng.uniform(1, 80, n),
            "Pclass": rng.integers(1, 4, n),
            "Cabin": rng.exponential(5, n),
            "Survived": rng.integers(0, 2, n).tolist(),
        }
    )


@pytest.fixture
def tab_df_unsupervised():
    import pandas as pd

    return pd.DataFrame(
        {
            "Pclass": [1, 2, 3] * 40,
            "Age": [22, 35, 26] * 40,
            "Fare": [7.25, 71.83, 7.92] * 40,
        }
    )


@pytest.fixture
def tab_state_regression():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000c03",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Fare",
        task="regression",
        user_intent="운임 예측",
    )


@pytest.fixture
def tab_df_with_outliers():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(99)
    df = pd.DataFrame(
        {
            "Age": rng.uniform(10, 70, 120).tolist(),
            "Fare": rng.uniform(5, 100, 120).tolist(),
            "Pclass": ([1, 2, 3] * 40),
            "Survived": ([0, 1] * 60),
        }
    )
    # inject extreme outliers
    df.loc[0, "Age"] = 9999.0
    df.loc[1, "Fare"] = -9999.0
    return df


@pytest.fixture
def tab_df_with_missing():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(7)
    df = pd.DataFrame(
        {
            "Pclass": ([1, 2, 3] * 40),
            "Age": rng.uniform(10, 70, 120).tolist(),
            "Fare": rng.uniform(5, 100, 120).tolist(),
            "Sex": (["male", "female"] * 60),
            "Survived": ([0, 1] * 60),
        }
    )
    idx = rng.choice(120, 20, replace=False)
    df.loc[idx, "Age"] = np.nan
    return df


# ── Day 3 신규 4종 fixture ────────────────────────────────────────────────────


@pytest.fixture
def tab_state_after_day2_smote():
    """Day 2 SMOTE/label_encoder/distribution_transforms/fitted_scalers 시뮬레이션."""
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d30",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="고객 생존 예측",
        category_extras={
            "tabular": {
                "preprocess_artifacts": {
                    "smote_meta": {
                        "applied": True,
                        "class_distribution_before": {0: 90, 1: 30},
                        "class_distribution_after": {0: 90, 1: 90},
                        "synthetic_row_idx": list(range(120, 180)),
                    },
                    "label_encoder": {0: "No", 1: "Yes"},
                    "distribution_transforms": {
                        "Fare": {"method": "yeo-johnson", "lambda": 0.23},
                    },
                    "fitted_scalers": {
                        "Fare": {"method": "robust"},
                        "Age": {"method": "standard"},
                    },
                }
            }
        },
    )


@pytest.fixture
def tab_df_wide():
    """tab_df 기반 + 95개 추가 numeric 컬럼 (총 ~100개) — heatmap cap 검증."""
    import numpy as np
    import pandas as pd

    base = {
        "Pclass": [1, 2, 3, 1, 3, 2, 1, 3, 2, 3] * 12,
        "Age": [22, 35, 26, 54, 2, 27, 14, 4, 58, 20] * 12,
        "Fare": [7.25, 71.83, 7.92, 51.86, 21.07, 11.13, 30.07, 16.7, 26.55, 8.05] * 12,
        "Survived": [0, 1, 1, 1, 0, 0, 0, 1, 1, 0] * 12,
    }
    rng = np.random.default_rng(42)
    for i in range(95):
        base[f"feat_{i:03d}"] = rng.standard_normal(120).tolist()
    return pd.DataFrame(base)


@pytest.fixture
def tab_df_with_mar_missing():
    """Age/Fare가 같은 행에서 동시 결측 (MAR 패턴) — 차트 5 검증."""
    import numpy as np
    import pandas as pd

    n = 120
    rng = np.random.default_rng(7)
    df = pd.DataFrame(
        {
            "Pclass": ([1, 2, 3] * 40),
            "Age": rng.uniform(10, 70, n).tolist(),
            "Fare": rng.uniform(5, 100, n).tolist(),
            "Cabin": rng.uniform(0, 1, n).tolist(),
            "Survived": ([0, 1] * 60),
        }
    )
    # 30행에서 Age + Fare 동시 결측 → MAR 의심
    mar_idx = list(range(0, 60, 2))
    df.loc[mar_idx, "Age"] = np.nan
    df.loc[mar_idx, "Fare"] = np.nan
    # Cabin도 일부 결측 (독립적)
    df.loc[list(range(90, 120)), "Cabin"] = np.nan
    return df


@pytest.fixture
def tab_df_high_card():
    """tab_df + 50개 unique city 컬럼 — 차트 7 categorical_frequency 검증."""
    import pandas as pd

    base = pd.DataFrame(
        {
            "Pclass": [1, 2, 3, 1, 3, 2, 1, 3, 2, 3] * 12,
            "Age": [22, 35, 26, 54, 2, 27, 14, 4, 58, 20] * 12,
            "Fare": [7.25, 71.83, 7.92, 51.86, 21.07, 11.13, 30.07, 16.7, 26.55, 8.05] * 12,
            "Survived": [0, 1, 1, 1, 0, 0, 0, 1, 1, 0] * 12,
        }
    )
    cities = [f"city_{i:03d}" for i in range(50)]
    base["city"] = (cities * 3)[:120]
    return base

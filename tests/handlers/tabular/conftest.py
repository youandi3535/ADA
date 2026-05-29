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


# ── 공통 fixture ──────────────────────────────────────────────────────────────


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
            "Fare": np.exp(rng.normal(2, 1, n)),
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
    df.loc[idx, "Age"] = float("nan")
    return df


# ── Day 3 fixture ─────────────────────────────────────────────────────────────


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
    mar_idx = list(range(0, 60, 2))
    df.loc[mar_idx, "Age"] = float("nan")
    df.loc[mar_idx, "Fare"] = float("nan")
    df.loc[list(range(90, 120)), "Cabin"] = float("nan")
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


# ── Day 4 fixture ─────────────────────────────────────────────────────────────


@pytest.fixture
def tab_state_with_eda_baseline():
    """tab_state + eda_baseline 채움 (G2 complexity_signal 검증)."""
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d40",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="고객 생존 예측",
        data_profile={"rows": 120, "columns": 4, "class_distribution": {0: 72, 1: 48}},
        category_extras={
            "tabular": {
                "eda_baseline": {
                    "cv_score": 0.72,
                    "metric": "f1_macro",
                    "top_feature_concentration": 0.55,
                    "nonlinearity_estimate": 0.08,
                }
            }
        },
    )


@pytest.fixture
def tab_state_large():
    """rows=10000, classes=5 — DoD DL 트리거 검증."""
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d41",
        file_id="uploads/test/large.csv",
        category="tabular_ml",
        target_column="label",
        user_intent="분류 예측",
        data_profile={
            "rows": 10000,
            "columns": 10,
            "class_distribution": {0: 2000, 1: 2000, 2: 2000, 3: 2000, 4: 2000},
        },
        category_extras={
            "tabular": {
                "eda_baseline": {
                    "cv_score": 0.68,
                    "metric": "f1_macro",
                    "top_feature_concentration": 0.35,
                    "nonlinearity_estimate": 0.18,
                }
            }
        },
    )


@pytest.fixture
def tab_state_huge():
    """rows=1000000, classes=2, baseline_cv=0.95 — 큰데 단순 시나리오."""
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d42",
        file_id="uploads/test/huge.csv",
        category="tabular_ml",
        target_column="label",
        user_intent="대규모 분류",
        data_profile={
            "rows": 1000000,
            "columns": 20,
            "class_distribution": {0: 500000, 1: 500000},
        },
        category_extras={
            "tabular": {
                "eda_baseline": {
                    "cv_score": 0.95,
                    "metric": "f1_macro",
                    "top_feature_concentration": 0.80,
                    "nonlinearity_estimate": 0.03,
                }
            }
        },
    )


@pytest.fixture
def tab_state_complex_medium():
    """rows=10000, classes=5, baseline_cv=0.55, 강한 불균형 — 작은데 복잡 시나리오."""
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d43",
        file_id="uploads/test/complex.csv",
        category="tabular_ml",
        target_column="label",
        user_intent="복잡 분류",
        data_profile={
            "rows": 10000,
            "columns": 15,
            "class_distribution": {0: 8000, 1: 500, 2: 300, 3: 150, 4: 50},
            "class_entropy_ratio": 0.25,
            "outlier_ratio": 0.12,
        },
        category_extras={
            "tabular": {
                "eda_baseline": {
                    "cv_score": 0.55,
                    "metric": "f1_macro",
                    "top_feature_concentration": 0.30,
                    "nonlinearity_estimate": 0.25,
                }
            }
        },
    )


@pytest.fixture
def tab_state_with_intent_predict():
    """user_intent에 '예측'+'해석' 키워드 포함 — 키워드 매칭 검증."""
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d44",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="매출 예측 및 결과 해석",
        data_profile={"rows": 120, "columns": 4},
    )


# ── Day 5 fixture ─────────────────────────────────────────────────────────────


@pytest.fixture
def tab_state_with_g2_ml_light():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d50",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="빠른 분류",
        data_profile={"rows": 120, "columns": 5, "class_distribution": {0: 60, 1: 60}},
        gate_responses={"g2": "g2_ml_light"},
    )


@pytest.fixture
def tab_state_with_g2_dl_heavy():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d51",
        file_id="uploads/test/large.csv",
        category="tabular_ml",
        target_column="label",
        user_intent="정밀 분류",
        data_profile={
            "rows": 50000,
            "columns": 20,
            "class_distribution": {0: 25000, 1: 25000},
        },
        gate_responses={"g2": "g2_dl_heavy"},
        category_extras={
            "tabular": {
                "eda_baseline": {"cv_score": 0.60, "metric": "f1_macro"},
            }
        },
    )


@pytest.fixture
def tab_state_with_g1_segment():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d52",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column=None,
        user_intent="데이터 군집 탐색",
        data_profile={"rows": 500, "columns": 5},
        gate_responses={"g1": "g1_segment"},
    )


@pytest.fixture
def tab_state_medical_keywords():
    from ada.core.state import PipelineState

    return PipelineState(
        job_id="00000000-0000-0000-0000-000000000d53",
        file_id="uploads/test/titanic.csv",
        category="tabular_ml",
        target_column="Survived",
        user_intent="환자의 진단 이유 설명",
        data_profile={
            "rows": 2000,
            "columns": 10,
            "class_distribution": {0: 1000, 1: 1000},
            "column_names": ["patient_id", "diagnosis", "age", "Survived"],
        },
        gate_responses={"g2": "g2_ml_standard"},
        category_extras={
            "tabular": {
                "eda_baseline": {"cv_score": 0.72, "metric": "f1_macro"},
            }
        },
    )


@pytest.fixture
def mock_recipes_list():
    return [
        {
            "hash": "recipe_abc001",
            "model": "XGBoost",
            "profile": {"rows": 2000, "columns": 10, "n_classes": 2, "imbalance_ratio": 1.0},
            "best_params": {"n_estimators": 200, "max_depth": 5, "learning_rate": 0.05, "subsample": 0.9},
            "quality_score": 0.90,
        },
        {
            "hash": "recipe_abc002",
            "model": "LightGBM",
            "profile": {"rows": 1800, "columns": 12, "n_classes": 2, "imbalance_ratio": 1.2},
            "best_params": {"n_estimators": 150, "num_leaves": 63, "learning_rate": 0.05, "min_child_samples": 30},
            "quality_score": 0.88,
        },
        {
            "hash": "recipe_abc003",
            "model": "CatBoost",
            "profile": {"rows": 500000, "columns": 30, "n_classes": 5, "imbalance_ratio": 3.0},
            "best_params": {"iterations": 300, "depth": 8, "learning_rate": 0.05},
            "quality_score": 0.55,
        },
        {
            "hash": "recipe_abc004",
            "model": "XGBoost",
            "profile": {"rows": 100, "columns": 5, "n_classes": 10, "imbalance_ratio": 5.0},
            "best_params": {"n_estimators": 50, "max_depth": 3, "learning_rate": 0.2, "subsample": 0.7},
            "quality_score": 0.40,
        },
        {
            "hash": "recipe_abc005",
            "model": "LightGBM",
            "profile": {"rows": 2500, "columns": 11, "n_classes": 2, "imbalance_ratio": 1.1},
            "best_params": {"n_estimators": 180, "num_leaves": 50, "learning_rate": 0.07, "min_child_samples": 25},
            "quality_score": 0.85,
        },
    ]

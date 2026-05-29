"""jh 단독 — tabular 테스트 fixture."""

from __future__ import annotations

import numpy as np
import pandas as pd
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
    return pd.DataFrame(
        {
            "Pclass": [1, 2, 3, 1, 3, 2, 1, 3, 2, 3] * 12,
            "Age": [22, 35, 26, 54, 2, 27, 14, 4, 58, 20] * 12,
            "Fare": [7.25, 71.83, 7.92, 51.86, 21.07, 11.13, 30.07, 16.7, 26.55, 8.05] * 12,
            "Sex": ["male", "female", "female", "female", "male", "male", "male", "female", "female", "male"] * 12,
            "Survived": [0, 1, 1, 1, 0, 0, 0, 1, 1, 0] * 12,
        }
    )


# ---------------------------------------------------------------------------
# Day 2 — 신규 fixture (tab_df 변형, 외부 fetch 0건)
# ---------------------------------------------------------------------------


@pytest.fixture
def tab_dl_state(tab_state):
    return tab_state.with_update(category="tabular_dl")


@pytest.fixture
def tab_df_skewed(tab_df):
    df = tab_df.copy()
    df["Fare"] = df["Fare"] ** 3  # skew 강화 (양수)
    return df


@pytest.fixture
def tab_df_negative_skewed(tab_df):
    df = tab_df.copy()
    df["Diff"] = (df["Fare"] - 50) ** 3  # 음수 포함 skew
    return df


@pytest.fixture
def tab_df_with_datetime(tab_df):
    df = tab_df.copy()
    df["booking_date"] = pd.date_range("2026-01-01", periods=len(df), freq="D")
    return df


@pytest.fixture
def tab_df_with_datetime_tz(tab_df_with_datetime):
    df = tab_df_with_datetime.copy()
    df["booking_date"] = df["booking_date"].dt.tz_localize("Asia/Seoul")
    return df


@pytest.fixture
def tab_df_with_nat(tab_df_with_datetime):
    df = tab_df_with_datetime.copy()
    df.loc[:5, "booking_date"] = pd.NaT
    return df


@pytest.fixture
def tab_df_with_missing(request, tab_df):
    pct = getattr(request, "param", 0.10)
    df = tab_df.copy()
    rng = np.random.RandomState(42)
    mask = rng.random(len(df)) < pct
    df.loc[mask, "Age"] = np.nan
    return df


@pytest.fixture
def tab_df_with_outliers(tab_df):
    df = tab_df.copy()
    df.loc[:11, "Fare"] = 5000  # ~10% outlier
    return df


@pytest.fixture
def tab_df_extreme_imbalance(tab_df):
    df = tab_df.copy()
    minority_mask = df["Survived"] == 1
    keep_idx = df[minority_mask].index[:3]
    df = pd.concat([df[~minority_mask], df.loc[keep_idx]])
    return df.reset_index(drop=True)


@pytest.fixture
def tab_df_tiny_minority(tab_df):
    df = tab_df.copy()
    minority_idx = df[df["Survived"] == 1].index[:4]
    df = pd.concat([df[df["Survived"] == 0], df.loc[minority_idx]])
    return df.reset_index(drop=True)


@pytest.fixture
def tab_df_collinear(tab_df):
    df = tab_df.copy()
    for i in range(5):
        df[f"Age_copy_{i}"] = df["Age"] + np.random.RandomState(i).normal(0, 0.01, len(df))
    return df


@pytest.fixture
def tab_df_unsupervised(tab_df):
    return tab_df.drop(columns=["Survived"])


@pytest.fixture
def tab_state_regression(tab_state):
    return tab_state.with_update(
        target_column="Fare",
        task="regression",
    )

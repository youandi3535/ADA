"""CS 단독 — timeseries preprocessor 단위 테스트 (재설계 반영).

Phase 0~8 설계의 순서 의도와 각 step 동작을 검증한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.handlers.timeseries.preprocessor import (
    _apply_boxcox,
    _apply_diff,
    _apply_ewm_mean,
    _apply_exog,
    _apply_fill_feature_nans,
    _apply_fill_missing,
    _apply_lag,
    _apply_rolling_mean,
    _apply_rolling_std,
    _apply_sort_by_time,
    _apply_time_order_split,
    _bc_col_or_target,
    _decide_lags,
    _decide_windows,
    apply,
    plan,
)

# ════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════


@pytest.fixture
def base_df():
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=120, freq="D"),
            "sales": 1000 + rng.normal(0, 50, 120).cumsum(),
            "promo": rng.integers(0, 2, 120).astype(float),
        }
    )


@pytest.fixture
def state_no_profile(ts_state):
    return ts_state


@pytest.fixture
def state_nonstationary(ts_state):
    """ADF p=0.32 > 0.1 -> diff orders=[1,2], boxcox."""
    return ts_state.with_update(
        data_profile={
            "rows": 120,
            "stationarity": {"adf_p_value": 0.32, "is_stationary": False},
            "seasonality": {"has_seasonality": False, "period": None},
            "date_col": "date",
        }
    )


@pytest.fixture
def state_borderline(ts_state):
    """ADF p=0.07: 0.05 < p <= 0.1 -> diff orders=[1] only."""
    return ts_state.with_update(
        data_profile={
            "rows": 120,
            "stationarity": {"adf_p_value": 0.07, "is_stationary": False},
            "seasonality": {"has_seasonality": False, "period": None},
            "date_col": "date",
        }
    )


@pytest.fixture
def state_stationary(ts_state):
    """ADF p=0.02 -> boxcox/diff 불필요."""
    return ts_state.with_update(
        data_profile={
            "rows": 120,
            "stationarity": {"adf_p_value": 0.02, "is_stationary": True},
            "seasonality": {"has_seasonality": False, "period": None},
            "date_col": "date",
        }
    )


@pytest.fixture
def state_seasonal_7(ts_state):
    """period=7 -> lags=[1,7,14]."""
    return ts_state.with_update(
        data_profile={
            "rows": 120,
            "stationarity": {"adf_p_value": 0.15, "is_stationary": False},
            "seasonality": {"has_seasonality": True, "period": 7},
            "date_col": "date",
        }
    )


@pytest.fixture
def state_seasonal_12(ts_state):
    """period=12, n=120 -> max_lag=30 -> lags=[1,12,24]."""
    return ts_state.with_update(
        data_profile={
            "rows": 120,
            "stationarity": {"adf_p_value": 0.10, "is_stationary": False},
            "seasonality": {"has_seasonality": True, "period": 12},
            "date_col": "date",
        }
    )


@pytest.fixture
def state_with_exog(ts_state):
    return ts_state.with_update(
        data_profile={
            "rows": 120,
            "stationarity": {"adf_p_value": 0.02, "is_stationary": True},
            "seasonality": {"has_seasonality": False, "period": None},
            "date_col": "date",
        },
        category_extras={"timeseries": {"exog_columns": ["promo"]}},
    )


# ════════════════════════════════════════════════════════
# 1. plan() — Phase 순서 및 파라미터 검증
# ════════════════════════════════════════════════════════


class TestPlan:
    def test_phase_order_first_is_sort(self, state_no_profile):
        assert plan(state_no_profile)[0]["name"] == "sort_by_time"

    def test_phase_order_last_is_split(self, state_no_profile):
        assert plan(state_no_profile)[-1]["name"] == "time_order_split"

    def test_fill_feature_nans_before_split(self, state_no_profile):
        names = [s["name"] for s in plan(state_no_profile)]
        assert names.index("fill_feature_nans") == names.index("time_order_split") - 1

    def test_boxcox_before_lag_and_rolling(self, state_nonstationary):
        names = [s["name"] for s in plan(state_nonstationary)]
        bc = names.index("boxcox")
        assert bc < names.index("lag_features")
        assert bc < names.index("rolling_mean")

    def test_diff_before_lag(self, state_nonstationary):
        names = [s["name"] for s in plan(state_nonstationary)]
        assert names.index("diff") < names.index("lag_features")

    def test_nonstationary_adf_032_diff_orders_1_2(self, state_nonstationary):
        steps = plan(state_nonstationary)
        diff_step = next(s for s in steps if s["name"] == "diff")
        assert diff_step["orders"] == [1, 2]

    def test_borderline_adf_007_diff_orders_1_only(self, state_borderline):
        steps = plan(state_borderline)
        diff_step = next(s for s in steps if s["name"] == "diff")
        assert diff_step["orders"] == [1]

    def test_stationary_no_boxcox_no_diff_in_name_check(self, state_stationary):
        names = [s["name"] for s in plan(state_stationary)]
        assert "boxcox" not in names
        assert "diff" in names  # diff 는 정상 여부 무관하게 항상 포함

    def test_seasonal_7_lag_list(self, state_seasonal_7):
        steps = plan(state_seasonal_7)
        lags = next(s for s in steps if s["name"] == "lag_features")["lags"]
        assert 1 in lags and 7 in lags and 14 in lags

    def test_seasonal_12_lag_list(self, state_seasonal_12):
        steps = plan(state_seasonal_12)
        lags = next(s for s in steps if s["name"] == "lag_features")["lags"]
        assert 1 in lags and 12 in lags and 24 in lags

    def test_no_exog_step_without_columns(self, state_stationary):
        names = [s["name"] for s in plan(state_stationary)]
        assert "exog" not in names

    def test_exog_step_included_with_columns(self, state_with_exog):
        steps = plan(state_with_exog)
        names = [s["name"] for s in steps]
        assert "exog" in names
        exog_step = next(s for s in steps if s["name"] == "exog")
        assert "promo" in exog_step["columns"]

    def test_all_steps_have_leakage_safe_true(self, state_nonstationary):
        for s in plan(state_nonstationary):
            assert s.get("leakage_safe") is True, f"step={s['name']} leakage_safe 누락"

    def test_use_bc_if_available_in_lag_rolling_ewm(self, state_nonstationary):
        steps = plan(state_nonstationary)
        for name in ("lag_features", "rolling_mean", "rolling_std", "ewm_mean"):
            step = next((s for s in steps if s["name"] == name), None)
            if step:
                assert step.get("use_bc_if_available") is True

    def test_fill_feature_nans_strategy_drop(self, state_no_profile):
        steps = plan(state_no_profile)
        nan_step = next(s for s in steps if s["name"] == "fill_feature_nans")
        assert nan_step["strategy"] == "drop"


# ════════════════════════════════════════════════════════
# 2. sort_by_time
# ════════════════════════════════════════════════════════


class TestSortByTime:
    def test_sorts_ascending_by_date(self, state_stationary):
        rng = np.random.default_rng(0)
        n = 20
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        perm = rng.permutation(n)
        df = pd.DataFrame({"date": dates[perm], "sales": np.arange(n, dtype=float)[perm]})
        out = _apply_sort_by_time(df, state_stationary)
        assert list(out["date"]) == list(sorted(dates))

    def test_index_reset_after_sort(self, state_stationary):
        rng = np.random.default_rng(1)
        n = 10
        df = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n, freq="D")[rng.permutation(n)],
                "sales": np.arange(n, dtype=float),
            }
        )
        out = _apply_sort_by_time(df, state_stationary)
        assert list(out.index) == list(range(len(out)))

    def test_no_date_col_returns_original_order(self, state_no_profile):
        df = pd.DataFrame({"sales": [3.0, 1.0, 2.0]})
        out = _apply_sort_by_time(df, state_no_profile)
        pd.testing.assert_frame_equal(out.reset_index(drop=True), df.reset_index(drop=True))


# ════════════════════════════════════════════════════════
# 3. fill_missing
# ════════════════════════════════════════════════════════


class TestFillMissing:
    def test_ffill_fills_within_limit(self):
        vals = [1.0] + [np.nan] * 5 + [2.0] + [np.nan] * 10
        df = pd.DataFrame({"sales": vals})
        out = _apply_fill_missing(df, "sales", ffill_limit=7, bfill_limit=3)
        assert out["sales"].iloc[1] == 1.0
        assert out["sales"].iloc[5] == 1.0
        assert not out["sales"].isna().any()

    def test_does_not_use_global_mean(self):
        vals = [100.0, np.nan, np.nan, 0.0, 0.0]
        df = pd.DataFrame({"sales": vals})
        out = _apply_fill_missing(df, "sales", ffill_limit=7, bfill_limit=3)
        assert out["sales"].iloc[1] == 100.0  # ffill: 이전 값
        assert out["sales"].iloc[1] != 40.0  # global mean != ffill

    def test_bfill_covers_leading_nans(self):
        vals = [np.nan, np.nan, 5.0, 6.0, 7.0]
        df = pd.DataFrame({"sales": vals})
        out = _apply_fill_missing(df, "sales", ffill_limit=7, bfill_limit=3)
        assert out["sales"].iloc[0] == 5.0
        assert out["sales"].iloc[1] == 5.0

    def test_no_nan_after_fill(self, base_df):
        df_with_nan = base_df.copy()
        df_with_nan.loc[[5, 10, 20], "sales"] = np.nan
        out = _apply_fill_missing(df_with_nan, "sales", ffill_limit=7, bfill_limit=3)
        assert not out["sales"].isna().any()


# ════════════════════════════════════════════════════════
# 4. boxcox (Phase 2 — lag/rolling 이전)
# ════════════════════════════════════════════════════════


class TestBoxcox:
    def test_bc_column_created(self, base_df):
        out = _apply_boxcox(base_df, "sales")
        assert "sales_bc" in out.columns

    def test_original_target_preserved(self, base_df):
        out = _apply_boxcox(base_df, "sales")
        pd.testing.assert_series_equal(out["sales"], base_df["sales"])

    def test_attrs_stored_correctly(self, base_df):
        out = _apply_boxcox(base_df, "sales")
        assert "boxcox_lambda" in out.attrs
        assert "boxcox_offset" in out.attrs
        assert out.attrs["boxcox_target"] == "sales"

    def test_negative_values_handled(self):
        df = pd.DataFrame({"val": [-5.0, -2.0, 0.0, 3.0, 7.0, 10.0, 15.0, 20.0, 25.0, 30.0]})
        out = _apply_boxcox(df, "val", shift_min=True)
        assert "val_bc" in out.columns
        assert out.attrs["boxcox_offset"] == pytest.approx(6.0)
        assert out["val_bc"].dropna().apply(np.isfinite).all()

    def test_lambda_clipped_to_range(self):
        df = pd.DataFrame({"val": np.linspace(1.0, 100.0, 50)})
        out = _apply_boxcox(df, "val", lambda_clip=(-5.0, 5.0))
        lam = out.attrs["boxcox_lambda"]
        assert -5.0 <= lam <= 5.0

    def test_fallback_log1p_on_constant_series(self):
        df = pd.DataFrame({"val": [5.0] * 10})
        out = _apply_boxcox(df, "val", fallback="log1p")
        assert "val_bc" in out.columns
        assert out["val_bc"].dropna().iloc[0] == pytest.approx(np.log1p(5.0), rel=1e-4)

    def test_bc_values_are_finite(self, base_df):
        out = _apply_boxcox(base_df, "sales")
        assert out["sales_bc"].dropna().apply(np.isfinite).all()


# ════════════════════════════════════════════════════════
# 5. diff (Phase 3 — 추가 feature)
# ════════════════════════════════════════════════════════


class TestDiff:
    def test_diff1_column_created(self, base_df):
        out = _apply_diff(base_df, "sales", [1])
        assert "sales_diff1" in out.columns

    def test_diff1_equals_shift1_diff1(self, base_df):
        out = _apply_diff(base_df, "sales", [1])
        expected = base_df["sales"].shift(1).diff(1)
        pd.testing.assert_series_equal(out["sales_diff1"], expected, check_names=False)

    def test_first_two_rows_nan(self, base_df):
        out = _apply_diff(base_df, "sales", [1])
        assert out["sales_diff1"].iloc[:2].isna().all()

    def test_third_row_is_not_nan(self, base_df):
        out = _apply_diff(base_df, "sales", [1])
        assert pd.notna(out["sales_diff1"].iloc[2])

    def test_orders_1_and_2_both_created(self, base_df):
        out = _apply_diff(base_df, "sales", [1, 2])
        assert "sales_diff1" in out.columns
        assert "sales_diff2" in out.columns

    def test_original_target_not_modified(self, base_df):
        out = _apply_diff(base_df, "sales", [1, 2])
        pd.testing.assert_series_equal(out["sales"], base_df["sales"])


# ════════════════════════════════════════════════════════
# 6. lag_features (Phase 4 — bc 컬럼 우선)
# ════════════════════════════════════════════════════════


class TestLag:
    def test_uses_bc_when_available(self, base_df):
        df_bc = base_df.copy()
        df_bc["sales_bc"] = base_df["sales"] * 2
        out = _apply_lag(df_bc, "sales_bc", [1], label_base="sales")
        expected = df_bc["sales_bc"].shift(1)
        pd.testing.assert_series_equal(out["sales_lag1"], expected, check_names=False)

    def test_falls_back_to_target_without_bc(self, base_df):
        out = _apply_lag(base_df, "sales", [1], label_base="sales")
        expected = base_df["sales"].shift(1)
        pd.testing.assert_series_equal(out["sales_lag1"], expected, check_names=False)

    def test_label_base_used_for_column_name(self, base_df):
        df_bc = base_df.copy()
        df_bc["sales_bc"] = base_df["sales"]
        out = _apply_lag(df_bc, "sales_bc", [7], label_base="sales")
        assert "sales_lag7" in out.columns

    def test_first_lag_rows_are_nan(self, base_df):
        out = _apply_lag(base_df, "sales", [7], label_base="sales")
        assert out["sales_lag7"].iloc[:7].isna().all()
        assert pd.notna(out["sales_lag7"].iloc[7])

    def test_bc_col_or_target_helper_bc_present(self, base_df):
        df_bc = base_df.copy()
        df_bc["sales_bc"] = base_df["sales"]
        assert _bc_col_or_target(df_bc, "sales", True) == "sales_bc"

    def test_bc_col_or_target_helper_no_bc(self, base_df):
        assert _bc_col_or_target(base_df, "sales", True) == "sales"

    def test_bc_col_or_target_helper_use_bc_false(self, base_df):
        df_bc = base_df.copy()
        df_bc["sales_bc"] = base_df["sales"]
        assert _bc_col_or_target(df_bc, "sales", False) == "sales"


# ════════════════════════════════════════════════════════
# 7. rolling_mean (Phase 5a)
# ════════════════════════════════════════════════════════


class TestRollingMean:
    def test_columns_created(self, base_df):
        out = _apply_rolling_mean(base_df, "sales", [7, 14], label_base="sales")
        assert "sales_rmean7" in out.columns
        assert "sales_rmean14" in out.columns

    def test_shift1_applied(self, base_df):
        out = _apply_rolling_mean(base_df, "sales", [7], min_periods_ratio=0.5, label_base="sales")
        mp = max(2, int(7 * 0.5))
        expected = base_df["sales"].shift(1).rolling(7, min_periods=mp).mean()
        pd.testing.assert_series_equal(out["sales_rmean7"], expected, check_names=False)

    def test_no_future_leakage_row0(self, base_df):
        out = _apply_rolling_mean(base_df, "sales", [7], label_base="sales")
        assert pd.isna(out["sales_rmean7"].iloc[0])

    def test_min_periods_allows_partial_window(self):
        short = pd.DataFrame({"sales": [10.0, 20.0, 30.0, 40.0, 50.0]})
        out = _apply_rolling_mean(short, "sales", [7], min_periods_ratio=0.5, label_base="sales")
        non_nan = out["sales_rmean7"].notna().sum()
        assert non_nan >= 1

    def test_uses_bc_column_when_provided(self, base_df):
        df_bc = base_df.copy()
        df_bc["sales_bc"] = base_df["sales"] * 3
        out = _apply_rolling_mean(df_bc, "sales_bc", [7], label_base="sales")
        mp = max(2, int(7 * 0.5))
        expected = df_bc["sales_bc"].shift(1).rolling(7, min_periods=mp).mean()
        pd.testing.assert_series_equal(out["sales_rmean7"], expected, check_names=False)


# ════════════════════════════════════════════════════════
# 8. rolling_std (Phase 5b)
# ════════════════════════════════════════════════════════


class TestRollingStd:
    def test_rstd_columns_created(self, base_df):
        out = _apply_rolling_std(base_df, "sales", [7, 14], label_base="sales")
        assert "sales_rstd7" in out.columns
        assert "sales_rstd14" in out.columns

    def test_min_periods_at_least_2(self, base_df):
        out = _apply_rolling_std(base_df, "sales", [7], min_periods_ratio=0.5, label_base="sales")
        assert out["sales_rstd7"].first_valid_index() is not None

    def test_no_future_leakage(self, base_df):
        out = _apply_rolling_std(base_df, "sales", [7], label_base="sales")
        assert pd.isna(out["sales_rstd7"].iloc[0])

    def test_plan_always_includes_rolling_std(self, state_stationary):
        names = [s["name"] for s in plan(state_stationary)]
        assert "rolling_std" in names


# ════════════════════════════════════════════════════════
# 9. ewm_mean (Phase 5c)
# ════════════════════════════════════════════════════════


class TestEwmMean:
    def test_columns_created(self, base_df):
        out = _apply_ewm_mean(base_df, "sales", [0.3, 0.1], label_base="sales")
        assert "sales_ewm30" in out.columns
        assert "sales_ewm10" in out.columns

    def test_shift1_applied(self, base_df):
        out = _apply_ewm_mean(base_df, "sales", [0.3], label_base="sales")
        expected = base_df["sales"].shift(1).ewm(alpha=0.3, adjust=False).mean()
        pd.testing.assert_series_equal(out["sales_ewm30"], expected, check_names=False)

    def test_no_future_leakage_row0(self, base_df):
        out = _apply_ewm_mean(base_df, "sales", [0.3], label_base="sales")
        assert pd.isna(out["sales_ewm30"].iloc[0])

    def test_alpha_column_name_pct(self, base_df):
        out = _apply_ewm_mean(base_df, "sales", [0.3, 0.1, 0.05], label_base="sales")
        assert "sales_ewm30" in out.columns
        assert "sales_ewm10" in out.columns
        assert "sales_ewm5" in out.columns


# ════════════════════════════════════════════════════════
# 10. exog (Phase 6)
# ════════════════════════════════════════════════════════


class TestExog:
    def test_exog_lag_created(self, base_df):
        out = _apply_exog(base_df, ["promo"], [1, 7], [])
        assert "promo_lag1" in out.columns
        assert "promo_lag7" in out.columns

    def test_exog_rolling_created(self, base_df):
        out = _apply_exog(base_df, ["promo"], [], [7])
        assert "promo_rmean7" in out.columns

    def test_no_future_leakage(self, base_df):
        out = _apply_exog(base_df, ["promo"], [1], [])
        assert pd.isna(out["promo_lag1"].iloc[0])

    def test_missing_column_skipped(self, base_df):
        out = _apply_exog(base_df, ["nonexistent"], [1], [])
        assert "nonexistent_lag1" not in out.columns

    def test_original_col_preserved(self, base_df):
        out = _apply_exog(base_df, ["promo"], [1], [7])
        pd.testing.assert_series_equal(out["promo"], base_df["promo"])


# ════════════════════════════════════════════════════════
# 11. fill_feature_nans (Phase 7)
# ════════════════════════════════════════════════════════


class TestFillFeatureNans:
    def _df_with_nans(self):
        n = 50
        return pd.DataFrame(
            {
                "sales": np.ones(n),
                "sales_lag7": [np.nan] * 7 + list(np.ones(n - 7)),
                "sales_rmean14": [np.nan] * 14 + list(np.ones(n - 14)),
            }
        )

    def test_drop_removes_warmup_rows(self):
        df = self._df_with_nans()
        out = _apply_fill_feature_nans(df, "sales", strategy="drop", max_warmup=20)
        assert len(out) == 36
        feature_cols = [c for c in out.columns if c != "sales"]
        assert out[feature_cols].isna().sum().sum() == 0

    def test_drop_resets_index(self):
        df = self._df_with_nans()
        out = _apply_fill_feature_nans(df, "sales", strategy="drop", max_warmup=20)
        assert list(out.index) == list(range(len(out)))

    def test_zero_fills_feature_nans(self):
        df = self._df_with_nans()
        out = _apply_fill_feature_nans(df, "sales", strategy="zero", max_warmup=20)
        assert out["sales_lag7"].isna().sum() == 0
        assert (out["sales_lag7"].iloc[:7] == 0.0).all()

    def test_zero_protects_target_nan(self):
        df = pd.DataFrame(
            {
                "sales": [np.nan, 1.0, 2.0],
                "sales_lag1": [np.nan, np.nan, 1.0],
            }
        )
        out = _apply_fill_feature_nans(df, "sales", strategy="zero", protect_target=True)
        assert pd.isna(out["sales"].iloc[0])
        assert out["sales_lag1"].iloc[1] == 0.0

    def test_none_does_nothing(self):
        df = self._df_with_nans()
        out = _apply_fill_feature_nans(df, "sales", strategy="none", max_warmup=20)
        assert len(out) == len(df)
        assert out.isna().sum().sum() == df.isna().sum().sum()


# ════════════════════════════════════════════════════════
# 12. time_order_split (Phase 8)
# ════════════════════════════════════════════════════════


class TestTimeOrderSplit:
    def test_split_column_created(self, base_df):
        out = _apply_time_order_split(base_df, 0.2, 0)
        assert "_split" in out.columns

    def test_no_gap_has_only_train_test(self, base_df):
        out = _apply_time_order_split(base_df, 0.2, 0)
        assert set(out["_split"].unique()) <= {"train", "test"}

    def test_gap_creates_gap_label(self, base_df):
        out = _apply_time_order_split(base_df, 0.2, 7)
        assert "gap" in out["_split"].values
        assert (out["_split"] == "gap").sum() == 7

    def test_order_train_gap_test(self, base_df):
        out = _apply_time_order_split(base_df, 0.2, 7)
        train_idx = out.index[out["_split"] == "train"]
        gap_idx = out.index[out["_split"] == "gap"]
        test_idx = out.index[out["_split"] == "test"]
        assert train_idx.max() < gap_idx.min()
        assert gap_idx.max() < test_idx.min()

    def test_no_shuffle_train_before_test(self, base_df):
        out = _apply_time_order_split(base_df, 0.2, 0)
        train_max = out.index[out["_split"] == "train"].max()
        test_min = out.index[out["_split"] == "test"].min()
        assert train_max < test_min

    def test_test_ratio_approximate(self, base_df):
        out = _apply_time_order_split(base_df, 0.2, 0)
        actual = (out["_split"] == "test").sum() / len(out)
        assert abs(actual - 0.2) < 0.02

    def test_no_data_loss(self, base_df):
        out = _apply_time_order_split(base_df, 0.2, 7)
        assert len(out) == len(base_df)


# ════════════════════════════════════════════════════════
# 13. apply() 통합 파이프라인
# ════════════════════════════════════════════════════════


class TestApplyIntegration:
    def test_lag1_and_rmean7_auto_generated(self, base_df, state_stationary):
        out = apply(base_df, plan(state_stationary), state_stationary)
        assert "sales_lag1" in out.columns
        assert "sales_rmean7" in out.columns

    def test_ewm_columns_generated(self, base_df, state_stationary):
        out = apply(base_df, plan(state_stationary), state_stationary)
        assert "sales_ewm30" in out.columns
        assert "sales_ewm10" in out.columns

    def test_lag_based_on_bc_when_boxcox_applied(self, base_df, state_nonstationary):
        out = apply(base_df, plan(state_nonstationary), state_nonstationary)
        assert "sales_bc" in out.columns
        assert "sales_lag1" in out.columns
        # fill_feature_nans(drop) + reset_index 이후 검증:
        # sales_lag1[i] == sales_bc[i-1] (pruned df 기준 인접 행 비교).
        # 이유: lag 는 drop 이전 원본 bc 기준으로 생성됐고,
        #       drop + reset_index 로 연속 인덱스가 됐으므로
        #       pruned df 내에서 lag1[i] = bc[i-1] 관계가 유지된다.
        lag1 = out["sales_lag1"]
        bc = out["sales_bc"]
        for i in range(1, min(20, len(out))):
            assert abs(lag1.iloc[i] - bc.iloc[i - 1]) < 1e-9, (
                f"row {i}: lag1={lag1.iloc[i]:.6f} != bc[i-1]={bc.iloc[i - 1]:.6f}"
            )

    def test_fill_feature_nans_drops_warmup(self, base_df, state_stationary):
        out = apply(base_df, plan(state_stationary), state_stationary)
        feature_cols = [c for c in out.columns if c not in ("sales", "_split", "date", "promo")]
        assert out[feature_cols].isna().sum().sum() == 0

    def test_split_column_present(self, base_df, state_stationary):
        out = apply(base_df, plan(state_stationary), state_stationary)
        assert "_split" in out.columns

    def test_target_never_overwritten(self, base_df, state_nonstationary):
        out = apply(base_df, plan(state_nonstationary), state_nonstationary)
        if "date" in out.columns:
            orig = base_df.set_index("date")["sales"]
            out_s = out.set_index("date")["sales"]
            common = orig.index.intersection(out_s.index)
            pd.testing.assert_series_equal(orig.loc[common], out_s.loc[common])

    def test_no_error_on_short_series(self, state_stationary):
        short = pd.DataFrame({"sales": [100.0, 102.0, 98.0, 105.0, 99.0]})
        steps = [
            {"name": "lag_features", "lags": [1], "use_bc_if_available": False, "leakage_safe": True},
            {
                "name": "rolling_mean",
                "windows": [7],
                "min_periods_ratio": 0.5,
                "use_bc_if_available": False,
                "leakage_safe": True,
            },
        ]
        out = apply(short, steps, state_stationary)
        assert "sales_lag1" in out.columns

    def test_missing_target_returns_original(self, base_df):
        from ada.core.state import PipelineState

        s = PipelineState(job_id="t", file_id="f", category="timeseries", target_column=None)
        out = apply(base_df, [{"name": "lag_features", "lags": [1]}], s)
        pd.testing.assert_frame_equal(out, base_df)

    def test_unknown_step_skipped(self, base_df, state_stationary):
        out = apply(base_df, [{"name": "future_unknown_step", "leakage_safe": True}], state_stationary)
        pd.testing.assert_frame_equal(out, base_df)

    def test_exog_features_in_full_pipeline(self, base_df, state_with_exog):
        out = apply(base_df, plan(state_with_exog), state_with_exog)
        assert "promo_lag1" in out.columns
        assert "promo_rmean7" in out.columns


# ════════════════════════════════════════════════════════
# 14. 헬퍼 함수
# ════════════════════════════════════════════════════════


class TestHelpers:
    def test_decide_lags_seasonal_period(self):
        from ada.core.state import PipelineState

        s = PipelineState(
            job_id="t",
            file_id="f",
            category="timeseries",
            data_profile={"stationarity": {"adf_p_value": 0.1}, "seasonality": {"has_seasonality": True, "period": 7}},
        )
        lags = _decide_lags(s, 120)
        assert 1 in lags and 7 in lags and 14 in lags

    def test_decide_lags_max_bound(self):
        from ada.core.state import PipelineState

        s = PipelineState(
            job_id="t",
            file_id="f",
            category="timeseries",
            data_profile={
                "stationarity": {"adf_p_value": 0.1},
                "seasonality": {"has_seasonality": False, "period": None},
            },
        )
        lags = _decide_lags(s, 20)  # max_lag = min(20//4, 28) = 5
        assert all(lag <= 5 for lag in lags)

    def test_decide_windows_adds_28_long_series(self):
        assert 28 in _decide_windows(120)

    def test_decide_windows_no_28_short_series(self):
        assert 28 not in _decide_windows(30)

    def test_decide_windows_upper_bound(self):
        windows = _decide_windows(20)  # max_w = 5
        assert all(w <= 5 for w in windows)

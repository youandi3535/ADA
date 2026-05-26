"""CS 단독 — timeseries profiler 테스트.

DoD: pytest 그린 + profile dict 키 8개
  date_col / freq / stationarity / acf_pacf / stl_decompose / seasonality / trend / outlier_iqr_ratio
"""

from __future__ import annotations

import pytest

REQUIRED_KEYS = {
    "date_col",
    "freq",
    "stationarity",
    "acf_pacf",
    "stl_decompose",
    "seasonality",
    "trend",
    "outlier_iqr_ratio",
}


# ── 키 존재 확인 ──────────────────────────────────────────────────────────────


def test_profile_returns_8_keys(ts_df, ts_state):
    """DoD 핵심: 반환 dict 에 8개 키가 모두 있어야 함."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"누락된 키: {missing}"


# ── date_col / freq ───────────────────────────────────────────────────────────


def test_date_col_detected(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    assert result["date_col"] == "date"


def test_freq_daily(ts_df, ts_state):
    """conftest ts_df 는 일별 데이터 → freq 가 'D' 계열이어야 함."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    assert result["freq"] is not None
    assert result["freq"].startswith("D") or result["freq"] == "unknown"


# ── stationarity ─────────────────────────────────────────────────────────────


def test_stationarity_has_adf_and_kpss(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert "adf_p_value" in stat
    assert "adf_is_stationary" in stat
    assert "kpss_p_value" in stat
    assert "kpss_is_stationary" in stat
    assert "is_stationary" in stat
    assert isinstance(stat["is_stationary"], bool)


def test_stationarity_p_value_range(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert 0.0 <= stat["adf_p_value"] <= 1.0


# ── acf_pacf ─────────────────────────────────────────────────────────────────


def test_acf_pacf_structure(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert "acf" in ap and "pacf" in ap
    assert "significant_lags_acf" in ap
    assert "significance_threshold" in ap


def test_acf_pacf_length(ts_df, ts_state):
    """lag 0 포함 최소 2개 이상이어야 함."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert len(ap["acf"]) >= 2
    assert len(ap["pacf"]) >= 2


def test_acf_lag0_is_one(ts_df, ts_state):
    """ACF lag=0 은 자기 자신과의 상관 → 항상 1.0."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert abs(ap["acf"][0] - 1.0) < 1e-3


# ── stl_decompose ─────────────────────────────────────────────────────────────


def test_stl_available(ts_df, ts_state):
    """120행 + period=7 → STL 분해 가능."""
    from agents.handlers.timeseries.profiler import profile

    stl = profile(ts_df, ts_state)["stl_decompose"]
    assert stl["available"] is True


def test_stl_has_strength_fields(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    stl = profile(ts_df, ts_state)["stl_decompose"]
    assert "seasonal_strength" in stl
    assert "trend_strength" in stl
    assert 0.0 <= stl["seasonal_strength"] <= 1.0
    assert 0.0 <= stl["trend_strength"] <= 1.0


def test_stl_period_matches_freq(ts_df, ts_state):
    """일별 데이터 → period=7."""
    from agents.handlers.timeseries.profiler import profile

    stl = profile(ts_df, ts_state)["stl_decompose"]
    assert stl["period"] == 7


# ── seasonality ───────────────────────────────────────────────────────────────


def test_seasonality_structure(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    sea = profile(ts_df, ts_state)["seasonality"]
    assert "has_seasonality" in sea
    assert "period" in sea
    assert "seasonal_strength" in sea
    assert isinstance(sea["has_seasonality"], bool)


def test_seasonality_period_7(ts_df, ts_state):
    """conftest ts_df 는 sin(2π/7) 계절성 → period=7."""
    from agents.handlers.timeseries.profiler import profile

    sea = profile(ts_df, ts_state)["seasonality"]
    assert sea["period"] == 7


# ── trend ─────────────────────────────────────────────────────────────────────


def test_trend_structure(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert "has_trend" in trend
    assert "direction" in trend
    assert trend["direction"] in ("increasing", "decreasing", "none")


def test_trend_direction_valid(ts_df, ts_state):
    """direction 값은 세 가지 중 하나여야 함."""
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert trend["direction"] in ("increasing", "decreasing", "none")


# ── outlier_iqr_ratio ─────────────────────────────────────────────────────────


def test_outlier_iqr_ratio_range(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    ratio = profile(ts_df, ts_state)["outlier_iqr_ratio"]
    assert 0.0 <= ratio <= 1.0


def test_outlier_iqr_ratio_is_float(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    ratio = profile(ts_df, ts_state)["outlier_iqr_ratio"]
    assert isinstance(ratio, float)


# ── 엣지 케이스 ───────────────────────────────────────────────────────────────


def test_missing_target_returns_warning(ts_df, ts_state):
    """target_column 없어도 에러 없이 warning 반환."""
    from agents.handlers.timeseries.profiler import profile

    bad_state = ts_state.with_update(target_column=None)
    result = profile(ts_df, bad_state)
    assert "timeseries_warning" in result


def test_missing_target_still_has_all_keys(ts_df, ts_state):
    """target 없어도 키 8개는 있어야 함 (None 으로라도)."""
    from agents.handlers.timeseries.profiler import profile

    bad_state = ts_state.with_update(target_column=None)
    result = profile(ts_df, bad_state)
    assert REQUIRED_KEYS.issubset(result.keys())

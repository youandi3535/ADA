"""CS 단독 — timeseries profiler 테스트.

DoD: pytest 그린 + profile dict 키 8개
  date_col / freq / stationarity / acf_pacf / stl_decompose / seasonality / trend / outlier_iqr_ratio

테스트 구성
-----------
  ① 키 존재 (DoD 핵심)
  ② date_col / freq
  ③ stationarity — ADF/KPSS 기본값 + 4-case consensus + diff_order
  ④ acf_pacf     — 구조·길이·lag0 + AR/MA 힌트 + seasonal_lags + Ljung-Box
  ⑤ stl_decompose — available·period·강도·resid_std·total_var
  ⑥ seasonality  — 구조·period·dominant_period 타입·period_confirmed 타입
  ⑦ trend        — 구조·direction 값·MK 범위·Hurst 범위
  ⑧ outlier_iqr_ratio — float·범위
  ⑨ 엣지 케이스   — target 없음
  ⑩ AirPassengers (월별, period=12) 시나리오
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

# ── ① 키 존재 (DoD) ───────────────────────────────────────────────────────────


def test_profile_returns_8_keys(ts_df, ts_state):
    """DoD 핵심: 반환 dict 에 8개 키가 모두 있어야 함."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    missing = REQUIRED_KEYS - result.keys()
    assert not missing, f"누락된 키: {missing}"


# ── ② date_col / freq ────────────────────────────────────────────────────────


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


# ── ③ stationarity ──────────────────────────────────────────────────────────


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


def test_stationarity_consensus_valid(ts_df, ts_state):
    """consensus 는 4가지 케이스 중 하나여야 함."""
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert "consensus" in stat
    assert stat["consensus"] in ("stationary", "non_stationary", "trend_stationary", "diff_stationary")


def test_stationarity_diff_order_valid(ts_df, ts_state):
    """diff_order 는 0·1·2 중 하나."""
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert "diff_order" in stat
    assert stat["diff_order"] in (0, 1, 2)


def test_stationarity_recommended_action_is_string(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert isinstance(stat["recommended_action"], str)
    assert len(stat["recommended_action"]) > 0


# ── ④ acf_pacf ───────────────────────────────────────────────────────────────


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


def test_acf_pacf_ar_ma_hints_are_int(ts_df, ts_state):
    """ar_order_hint / ma_order_hint 는 음수 아닌 정수."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert isinstance(ap["ar_order_hint"], int) and ap["ar_order_hint"] >= 0
    assert isinstance(ap["ma_order_hint"], int) and ap["ma_order_hint"] >= 0


def test_acf_pacf_seasonal_lags_is_list(ts_df, ts_state):
    """seasonal_lags 는 정수 리스트 (period 배수 위치 spike)."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert isinstance(ap["seasonal_lags"], list)
    for lag in ap["seasonal_lags"]:
        assert isinstance(lag, int) and lag > 0


def test_acf_pacf_ljung_box_p_range(ts_df, ts_state):
    """Ljung-Box p-value 는 None 이거나 [0, 1] 범위."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    if ap["ljung_box_p"] is not None:
        assert 0.0 <= ap["ljung_box_p"] <= 1.0


def test_acf_pacf_used_diff_order_matches_stationarity(ts_df, ts_state):
    """used_diff_order 는 stationarity.diff_order 와 일치해야 함."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    assert result["acf_pacf"]["used_diff_order"] == result["stationarity"]["diff_order"]


# ── ⑤ stl_decompose ──────────────────────────────────────────────────────────


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


def test_stl_has_resid_std(ts_df, ts_state):
    """resid_std: 잔차 표준편차 — 음수 없음."""
    from agents.handlers.timeseries.profiler import profile

    stl = profile(ts_df, ts_state)["stl_decompose"]
    assert "resid_std" in stl
    assert stl["resid_std"] >= 0.0


def test_stl_total_var_is_sum(ts_df, ts_state):
    """total_var ≈ trend_var + seasonal_var + resid_var."""
    from agents.handlers.timeseries.profiler import profile

    stl = profile(ts_df, ts_state)["stl_decompose"]
    assert "total_var" in stl
    expected = stl["trend_var"] + stl["seasonal_var"] + stl["resid_var"]
    assert abs(stl["total_var"] - expected) < 1.0


# ── ⑥ seasonality ────────────────────────────────────────────────────────────


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


def test_seasonality_dominant_period_type(ts_df, ts_state):
    """dominant_period 는 None 이거나 양의 정수."""
    from agents.handlers.timeseries.profiler import profile

    sea = profile(ts_df, ts_state)["seasonality"]
    assert "dominant_period" in sea
    dp = sea["dominant_period"]
    if dp is not None:
        assert isinstance(dp, int) and dp > 0


def test_seasonality_period_confirmed_is_bool(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    sea = profile(ts_df, ts_state)["seasonality"]
    assert isinstance(sea["period_confirmed"], bool)


def test_seasonality_period_confidence_range(ts_df, ts_state):
    """period_confidence 는 [0, 1] 범위."""
    from agents.handlers.timeseries.profiler import profile

    sea = profile(ts_df, ts_state)["seasonality"]
    assert 0.0 <= sea["period_confidence"] <= 1.0


# ── ⑦ trend ──────────────────────────────────────────────────────────────────


def test_trend_structure(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert "has_trend" in trend
    assert "direction" in trend
    assert trend["direction"] in ("increasing", "decreasing", "none")


def test_trend_direction_valid(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert trend["direction"] in ("increasing", "decreasing", "none")


def test_trend_mk_significant_for_cumsum(ts_df, ts_state):
    """cumsum 랜덤워크는 방향에 관계없이 MK 검정으로 유의미한 추세가 검출되어야 함."""
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert trend["has_trend"] is True
    assert trend["mk_significant"] is True


def test_trend_slope_per_obs_is_float(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert isinstance(trend["slope_per_obs"], float)


def test_trend_mk_tau_range(ts_df, ts_state):
    """Mann-Kendall tau 는 [-1, 1] 범위."""
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert "mk_tau" in trend
    assert -1.0 <= trend["mk_tau"] <= 1.0


def test_trend_mk_p_value_range(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert "mk_p_value" in trend
    assert 0.0 <= trend["mk_p_value"] <= 1.0


def test_trend_mk_significant_is_bool(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert isinstance(trend["mk_significant"], bool)


def test_trend_hurst_exponent_range(ts_df, ts_state):
    """Hurst 지수는 None 이거나 [0, 1] 범위."""
    from agents.handlers.timeseries.profiler import profile

    trend = profile(ts_df, ts_state)["trend"]
    assert "hurst_exponent" in trend
    h = trend["hurst_exponent"]
    if h is not None:
        assert 0.0 <= h <= 1.0


# ── ⑧ outlier_iqr_ratio ──────────────────────────────────────────────────────


def test_outlier_iqr_ratio_range(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    ratio = profile(ts_df, ts_state)["outlier_iqr_ratio"]
    assert 0.0 <= ratio <= 1.0


def test_outlier_iqr_ratio_is_float(ts_df, ts_state):
    from agents.handlers.timeseries.profiler import profile

    ratio = profile(ts_df, ts_state)["outlier_iqr_ratio"]
    assert isinstance(ratio, float)


# ── ⑨ 엣지 케이스 ────────────────────────────────────────────────────────────


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


# ── ⑩ AirPassengers 시나리오 (월별, period=12) ────────────────────────────────


def test_airpassengers_freq_monthly(air_passengers_df, air_passengers_state):
    """AirPassengers 는 월별 → freq 가 'M' 또는 'MS' 계열이어야 함."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(air_passengers_df, air_passengers_state)
    freq = result["freq"]
    assert freq.startswith("M") or freq == "unknown", f"unexpected freq: {freq}"


def test_airpassengers_stl_period_12(air_passengers_df, air_passengers_state):
    """월별 데이터 → STL period=12."""
    from agents.handlers.timeseries.profiler import profile

    stl = profile(air_passengers_df, air_passengers_state)["stl_decompose"]
    assert stl["period"] == 12


def test_airpassengers_has_seasonality(air_passengers_df, air_passengers_state):
    """AirPassengers 는 강한 연간 계절성 → has_seasonality=True."""
    from agents.handlers.timeseries.profiler import profile

    sea = profile(air_passengers_df, air_passengers_state)["seasonality"]
    assert sea["has_seasonality"] is True


def test_airpassengers_trend_increasing(air_passengers_df, air_passengers_state):
    """AirPassengers 는 명확한 상승 추세."""
    from agents.handlers.timeseries.profiler import profile

    trend = profile(air_passengers_df, air_passengers_state)["trend"]
    assert trend["direction"] == "increasing"
    assert trend["mk_significant"] is True


# ── ⑪ Phase 단위 (L1 unit) ───────────────────────────────────────────────────


def test_phase2_white_noise_diff_order_zero():
    """백색잡음은 정상 시계열 → diff_order=0."""
    import numpy as np
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase2_stationarity

    series = pd.Series(np.random.default_rng(0).normal(0, 1, 200))
    result = _phase2_stationarity(series)
    assert result["diff_order"] == 0
    assert result["consensus"] in ("stationary", "trend_stationary")


def test_phase2_random_walk_diff_order_at_least_one():
    """랜덤워크는 I(1) → diff_order >= 1."""
    import numpy as np
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase2_stationarity

    series = pd.Series(np.random.default_rng(0).normal(0, 1, 200).cumsum())
    result = _phase2_stationarity(series)
    assert result["diff_order"] >= 1
    assert result["consensus"] in ("non_stationary", "diff_stationary")


def test_phase7_constant_series_returns_zero():
    """분산 0 시계열에서 _phase7 가 throw 안 하고 0.0 반환."""
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase7_outliers

    series = pd.Series([100.0] * 120)
    result = _phase7_outliers(series)
    assert result == 0.0
    assert isinstance(result, float)


# ── ⑫ Stress / Edge (L5) ────────────────────────────────────────────────────


def test_profile_does_not_crash_on_constant_series(ts_state):
    """S14: 분산 0 시계열에서 Phase 2 실패해도 8키 보장 + IQR=0.0 살아있음.

    Task 1 (Phase try 분해) 의 핵심 효과 검증.
    """
    import pandas as pd

    from agents.handlers.timeseries.profiler import profile

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=120, freq="D"),
            "sales": [100.0] * 120,
        }
    )
    result = profile(df, ts_state)
    assert REQUIRED_KEYS.issubset(result.keys())
    assert result["outlier_iqr_ratio"] == 0.0
    assert isinstance(result["stl_decompose"], dict)


def test_profile_does_not_crash_on_very_short_series(ts_state):
    """S6: n=10 시계열 (STL 미가용 임계) — STL 실패해도 나머지 살아남음."""
    import pandas as pd

    from agents.handlers.timeseries.profiler import profile

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=10, freq="D"),
            "sales": [1.0, 2.0, 3.0, 4.0, 5.0, 4.0, 3.0, 2.0, 1.0, 2.0],
        }
    )
    result = profile(df, ts_state)
    assert REQUIRED_KEYS.issubset(result.keys())
    assert result["stl_decompose"]["available"] is False
    assert result["stl_decompose"]["period"] == 7
    assert isinstance(result["outlier_iqr_ratio"], float)


def test_diagnostic_keys_present(ts_df, ts_state):
    """Task 2: 진단 키 4개가 항상 존재하고 타입이 올바름."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    for key in ("target_min", "target_max", "target_has_zeros", "target_has_negatives"):
        assert key in result, f"진단 키 누락: {key}"
    assert isinstance(result["target_min"], float)
    assert isinstance(result["target_max"], float)
    assert isinstance(result["target_has_zeros"], bool)
    assert isinstance(result["target_has_negatives"], bool)

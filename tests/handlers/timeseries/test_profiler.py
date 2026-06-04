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


def test_stationarity_has_adf_and_kpss(ts_df, ts_state, require_statsmodels):
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert "adf_p_value" in stat
    assert "adf_is_stationary" in stat
    assert "kpss_p_value" in stat
    assert "kpss_is_stationary" in stat
    assert "is_stationary" in stat
    assert isinstance(stat["is_stationary"], bool)


def test_stationarity_p_value_range(ts_df, ts_state, require_statsmodels):
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert 0.0 <= stat["adf_p_value"] <= 1.0


def test_stationarity_consensus_valid(ts_df, ts_state, require_statsmodels):
    """consensus 는 4가지 케이스 중 하나여야 함."""
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert "consensus" in stat
    assert stat["consensus"] in ("stationary", "non_stationary", "trend_stationary", "diff_stationary")


def test_stationarity_diff_order_valid(ts_df, ts_state, require_statsmodels):
    """diff_order 는 0·1·2 중 하나."""
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert "diff_order" in stat
    assert stat["diff_order"] in (0, 1, 2)


def test_stationarity_recommended_action_is_string(ts_df, ts_state, require_statsmodels):
    from agents.handlers.timeseries.profiler import profile

    stat = profile(ts_df, ts_state)["stationarity"]
    assert isinstance(stat["recommended_action"], str)
    assert len(stat["recommended_action"]) > 0


# ── ④ acf_pacf ───────────────────────────────────────────────────────────────


def test_acf_pacf_structure(ts_df, ts_state, require_statsmodels):
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert "acf" in ap and "pacf" in ap
    assert "significant_lags_acf" in ap
    assert "significance_threshold" in ap


def test_acf_pacf_length(ts_df, ts_state, require_statsmodels):
    """lag 0 포함 최소 2개 이상이어야 함."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert len(ap["acf"]) >= 2
    assert len(ap["pacf"]) >= 2


def test_acf_lag0_is_one(ts_df, ts_state, require_statsmodels):
    """ACF lag=0 은 자기 자신과의 상관 → 항상 1.0."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert abs(ap["acf"][0] - 1.0) < 1e-3


def test_acf_pacf_ar_ma_hints_are_int(ts_df, ts_state, require_statsmodels):
    """ar_order_hint / ma_order_hint 는 음수 아닌 정수."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert isinstance(ap["ar_order_hint"], int) and ap["ar_order_hint"] >= 0
    assert isinstance(ap["ma_order_hint"], int) and ap["ma_order_hint"] >= 0


def test_acf_pacf_seasonal_lags_is_list(ts_df, ts_state, require_statsmodels):
    """seasonal_lags 는 정수 리스트 (period 배수 위치 spike)."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    assert isinstance(ap["seasonal_lags"], list)
    for lag in ap["seasonal_lags"]:
        assert isinstance(lag, int) and lag > 0


def test_acf_pacf_ljung_box_p_range(ts_df, ts_state, require_statsmodels):
    """Ljung-Box p-value 는 None 이거나 [0, 1] 범위."""
    from agents.handlers.timeseries.profiler import profile

    ap = profile(ts_df, ts_state)["acf_pacf"]
    if ap["ljung_box_p"] is not None:
        assert 0.0 <= ap["ljung_box_p"] <= 1.0


def test_acf_pacf_used_diff_order_matches_stationarity(ts_df, ts_state, require_statsmodels):
    """used_diff_order 는 stationarity.diff_order 와 일치해야 함."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    assert result["acf_pacf"]["used_diff_order"] == result["stationarity"]["diff_order"]


# ── ⑤ stl_decompose ──────────────────────────────────────────────────────────


def test_stl_available(ts_df, ts_state, require_statsmodels):
    """120행 + period=7 → STL 분해 가능."""
    from agents.handlers.timeseries.profiler import profile

    stl = profile(ts_df, ts_state)["stl_decompose"]
    assert stl["available"] is True


def test_stl_has_strength_fields(ts_df, ts_state, require_statsmodels):
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


def test_stl_has_resid_std(ts_df, ts_state, require_statsmodels):
    """resid_std: 잔차 표준편차 — 음수 없음."""
    from agents.handlers.timeseries.profiler import profile

    stl = profile(ts_df, ts_state)["stl_decompose"]
    assert "resid_std" in stl
    assert stl["resid_std"] >= 0.0


def test_stl_total_var_is_sum(ts_df, ts_state, require_statsmodels):
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


def test_airpassengers_has_seasonality(air_passengers_df, air_passengers_state, require_statsmodels):
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


def test_phase2_white_noise_diff_order_zero(require_statsmodels):
    """백색잡음은 정상 시계열 → diff_order=0."""
    import numpy as np
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase2_stationarity

    series = pd.Series(np.random.default_rng(0).normal(0, 1, 200))
    result = _phase2_stationarity(series)
    assert result["diff_order"] == 0
    assert result["consensus"] in ("stationary", "trend_stationary")


def test_phase2_random_walk_diff_order_at_least_one(require_statsmodels):
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


# ══════════════════════════════════════════════════════════════════════════════
#  신규 Phase 8~12 + §6 테스트 (cs-profiler 디벨롭, 설계 §10-2)
# ══════════════════════════════════════════════════════════════════════════════


# ── Phase 8 — 시간축 무결성 ───────────────────────────────────────────────────


def test_phase8_duplicate_ts():
    """중복 타임스탬프 → duplicate_ts_count > 0."""
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase8_timeaxis_integrity

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "sales": [1, 2, 3, 4, 5],
        }
    )
    res = _phase8_timeaxis_integrity(df, "date", 7)
    assert res["duplicate_ts_count"] > 0


def test_phase8_missing_ts():
    """결측 시점(행 누락) → missing_ts_count > 0."""
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase8_timeaxis_integrity

    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-04", "2024-01-05", "2024-01-06"])
    df = pd.DataFrame({"date": dates, "sales": range(len(dates))})
    res = _phase8_timeaxis_integrity(df, "date", 7)
    assert res["missing_ts_count"] > 0


def test_phase8_reverse_not_monotonic():
    """역순 정렬 df → is_monotonic == False."""
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase8_timeaxis_integrity

    dates = pd.to_datetime(["2024-01-05", "2024-01-04", "2024-01-03", "2024-01-02", "2024-01-01"])
    df = pd.DataFrame({"date": dates, "sales": range(5)})
    res = _phase8_timeaxis_integrity(df, "date", 7)
    assert res["is_monotonic"] is False


def test_phase8_no_date_col():
    """정수 인덱스(date_col=None) → has_time_axis=False, 크래시 X."""
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase8_timeaxis_integrity

    df = pd.DataFrame({"sales": [1, 2, 3, 4, 5]})
    res = _phase8_timeaxis_integrity(df, None, 7)
    assert res["has_time_axis"] is False
    assert res["is_monotonic"] is None


# ── Phase 9 — 가법/승법 ───────────────────────────────────────────────────────


def test_phase9_airpassengers_multiplicative(air_passengers_df):
    """AirPassengers (분산∝레벨) → is_multiplicative=True, confidence 높음."""
    from agents.handlers.timeseries.profiler import _phase9_multiplicative

    series = air_passengers_df["passengers"].astype(float)
    res = _phase9_multiplicative(series, 12)
    assert res["is_multiplicative"] is True
    assert res["confidence"] > 0.5


def test_phase9_additive_false():
    """합성 가법 시계열(일정 분산) → False."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase9_multiplicative

    rng = np.random.default_rng(0)
    n = 120
    series = np.arange(n) * 2.0 + rng.normal(0, 5, n)  # 레벨 상승, 분산 일정
    res = _phase9_multiplicative(series, 12)
    assert res["is_multiplicative"] is False


def test_phase9_constant_none():
    """상수 시계열 → None, basis='no_level_variation'."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase9_multiplicative

    series = np.full(120, 5.0)
    res = _phase9_multiplicative(series, 12)
    assert res["is_multiplicative"] is None
    assert res["basis"] == "no_level_variation"


def test_phase9_insufficient_data_none():
    """n < 2*period → None, basis='insufficient_data'."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase9_multiplicative

    res = _phase9_multiplicative(np.arange(10.0), 12)
    assert res["is_multiplicative"] is None
    assert res["basis"] == "insufficient_data"


# ── Phase 10 — 레짐 변화 ──────────────────────────────────────────────────────


def test_phase10_levelshift_detected():
    """level-shift 합성(중간 +30 점프) → count ≥ 1."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase10_changepoints

    rng = np.random.default_rng(1)
    n = 120
    series = rng.normal(0, 1, n)
    series[60:] += 30.0
    res = _phase10_changepoints(series, {}, 7)
    assert res["count"] >= 1


def test_phase10_smooth_low_count(air_passengers_df):
    """매끈한 추세(AirPassengers) → 과검출 안 함."""
    from agents.handlers.timeseries.profiler import _phase10_changepoints

    series = air_passengers_df["passengers"].astype(float)
    res = _phase10_changepoints(series, {}, 12)
    assert res["count"] <= 5


def test_phase10_short_series_zero():
    """n<20 → count=0, 크래시 X."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase10_changepoints

    res = _phase10_changepoints(np.arange(10.0), {}, 7)
    assert res["count"] == 0


def test_phase10_constant_zero():
    """상수 → count=0."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase10_changepoints

    res = _phase10_changepoints(np.full(60, 3.0), {}, 7)
    assert res["count"] == 0


# ── Phase 11 — 누적/증분 ──────────────────────────────────────────────────────


def test_phase11_cumsum_cumulative():
    """np.cumsum(positive) → 'cumulative'."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase11_target_kind

    rng = np.random.default_rng(2)
    series = np.cumsum(np.abs(rng.normal(5, 1, 120)))
    res = _phase11_target_kind(series, {"hurst_exponent": 0.95})
    assert res["target_kind"] == "cumulative"


def test_phase11_level():
    """정상 변동 시계열 → 'level'."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase11_target_kind

    rng = np.random.default_rng(3)
    series = rng.normal(0, 1, 120)
    res = _phase11_target_kind(series, {"hurst_exponent": 0.5})
    assert res["target_kind"] == "level"


def test_phase11_short_unknown():
    """n<10 → 'unknown'."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase11_target_kind

    res = _phase11_target_kind(np.arange(5.0), {})
    assert res["target_kind"] == "unknown"


# ── Phase 12 — CCF + 누수 ─────────────────────────────────────────────────────


def test_phase12_leakage_detected():
    """타겟 복사 컬럼 → leakage_suspect 에 잡힘."""
    import numpy as np
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase12_ccf_leakage

    rng = np.random.default_rng(4)
    n = 120
    target = rng.normal(0, 1, n).cumsum()
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "sales": target,
            "leak": target,
        }
    )
    res = _phase12_ccf_leakage(df, "sales", "date")
    assert "leak" in res["leakage_suspect_cols"]


def test_phase12_ccf_lag():
    """lag-3 시프트 컬럼 → ccf_top_lags 에 lag≈3."""
    import numpy as np
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase12_ccf_leakage

    rng = np.random.default_rng(5)
    n = 200
    base = rng.normal(0, 1, n)
    target = base.cumsum()
    exog = np.empty(n)
    exog[:] = np.nan
    exog[: n - 3] = base[3:]  # exog 가 target 변화를 3 시점 선행
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
            "sales": target,
            "lead": exog,
        }
    )
    res = _phase12_ccf_leakage(df, "sales", "date", max_lag=10)
    assert "lead" in res["ccf_top_lags"]
    assert abs(res["ccf_top_lags"]["lead"]["lag"] - 3) <= 1


def test_phase12_no_exog():
    """exog 없음 → is_multivariate=False, 빈 dict."""
    import numpy as np
    import pandas as pd

    from agents.handlers.timeseries.profiler import _phase12_ccf_leakage

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=50, freq="D"),
            "sales": np.random.default_rng(6).normal(0, 1, 50),
        }
    )
    res = _phase12_ccf_leakage(df, "sales", "date")
    assert res["is_multivariate"] is False
    assert res["ccf_top_lags"] == {}


# ── 통합 / 견고성 ─────────────────────────────────────────────────────────────


def test_new_keys_present(ts_df, ts_state):
    """profile() 반환에 신규 키 전부 존재."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    for key in (
        "timeaxis_integrity",
        "is_multiplicative",
        "changepoints",
        "changepoints_detail",
        "target_kind",
        "ccf_leakage",
    ):
        assert key in result, f"신규 키 누락: {key}"


def test_new_keys_none_when_no_target(ts_df):
    """target 없음 → 신규 진단 키 None, timeaxis_integrity 는 측정됨."""
    from ada.core.state import PipelineState
    from agents.handlers.timeseries.profiler import profile

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000a03",
        file_id="uploads/test/no_target.csv",
        category="timeseries",
        target_column="nonexistent_col",
        user_intent="x",
    )
    result = profile(ts_df, state)
    assert result["is_multiplicative"] is None
    assert result["changepoints"] is None
    assert result["target_kind"] is None
    assert result["ccf_leakage"] is None
    assert result["timeaxis_integrity"]["has_time_axis"] is True


def test_dirty_data_no_crash():
    """엣지 5종 — 크래시 0 (전부 NaN/상수/초단기/중복/비수치 exog)."""
    import numpy as np
    import pandas as pd

    from ada.core.state import PipelineState
    from agents.handlers.timeseries.profiler import profile

    def _state(target="sales"):
        return PipelineState(
            job_id="00000000-0000-0000-0000-000000000a04",
            file_id="uploads/test/dirty.csv",
            category="timeseries",
            target_column=target,
            user_intent="x",
        )

    df1 = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=30, freq="D"), "sales": [np.nan] * 30})
    df2 = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=60, freq="D"), "sales": [5.0] * 60})
    df3 = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5, freq="D"), "sales": [1, 2, 3, 4, 5]})
    df4 = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"] * 30), "sales": np.arange(30.0)})
    df5 = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=60, freq="D"),
            "sales": np.random.default_rng(7).normal(0, 1, 60).cumsum(),
            "junk": ["a", "b"] * 30,
        }
    )

    for df in (df1, df2, df3, df4, df5):
        result = profile(df, _state())
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════════════════════
#  Phase 13~15 테스트 (이분산 · 이상치성격 · 0vsNaN) — 방법론 1·2단계 보강
# ══════════════════════════════════════════════════════════════════════════════


# ── Phase 13 — 이분산 ─────────────────────────────────────────────────────────


def test_phase13_heteroscedastic_detected():
    """후반 분산이 전반보다 크게 증가 → is_heteroscedastic=True."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase13_heteroscedasticity

    rng = np.random.default_rng(0)
    n = 120
    first = rng.normal(0, 1, n // 2)
    second = rng.normal(0, 5, n // 2)  # 분산 5배
    series = np.concatenate([first, second])
    res = _phase13_heteroscedasticity(series, 7)
    assert res["is_heteroscedastic"] is True
    assert res["var_ratio"] > 2.0


def test_phase13_homoscedastic_false():
    """일정 분산 → False."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase13_heteroscedasticity

    rng = np.random.default_rng(1)
    series = rng.normal(0, 1, 120)
    res = _phase13_heteroscedasticity(series, 7)
    assert res["is_heteroscedastic"] is False


def test_phase13_constant_none():
    """상수 → None, basis=no_variance."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase13_heteroscedasticity

    res = _phase13_heteroscedasticity(np.full(60, 3.0), 7)
    assert res["is_heteroscedastic"] is None
    assert res["basis"] == "no_variance"


def test_phase13_short_insufficient():
    """n<20 → None, insufficient_data."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase13_heteroscedasticity

    res = _phase13_heteroscedasticity(np.arange(10.0), 7)
    assert res["is_heteroscedastic"] is None
    assert res["basis"] == "insufficient_data"


# ── Phase 14 — 이상치 성격 ────────────────────────────────────────────────────


def test_phase14_error_suspect_negative():
    """전부 양수 계열에 음수 이상치 → error_suspect, investigate_errors."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase14_outlier_kind

    vals = np.concatenate([np.full(50, 100.0) + np.random.default_rng(2).normal(0, 5, 50), [-999.0]])
    res = _phase14_outlier_kind(vals)
    assert res["error_suspect_count"] >= 1
    assert res["recommend"] == "investigate_errors"


def test_phase14_event_suspect():
    """양수 계열에 중간 z 이상치(세일 스파이크) → event_suspect, flag_as_event."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase14_outlier_kind

    rng = np.random.default_rng(3)
    vals = np.concatenate([rng.normal(100, 5, 60), [140.0, 145.0]])  # 적당히 높은 스파이크
    res = _phase14_outlier_kind(vals)
    assert res["outlier_count"] >= 1
    assert res["event_suspect_count"] >= 1


def test_phase14_no_outlier():
    """이상치 없음 → count 0, none."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase14_outlier_kind

    rng = np.random.default_rng(4)
    res = _phase14_outlier_kind(rng.normal(100, 1, 60))
    assert res["recommend"] in ("none", "flag_as_event")  # 깨끗하면 none, 약한 꼬리면 event


# ── Phase 15 — 0 vs NaN ───────────────────────────────────────────────────────


def test_phase15_zero_suspect_long_run():
    """긴 연속 0 런 → zero_suspect=True."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase15_zero_vs_nan

    vals = np.concatenate([np.full(40, 5.0), np.zeros(10), np.full(40, 5.0)])  # 10연속 0
    res = _phase15_zero_vs_nan(vals)
    assert res["max_zero_run"] >= 7
    assert res["zero_suspect"] is True


def test_phase15_clean_no_suspect():
    """0 거의 없음 → zero_suspect=False."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase15_zero_vs_nan

    rng = np.random.default_rng(5)
    res = _phase15_zero_vs_nan(rng.normal(100, 5, 100))
    assert res["zero_suspect"] is False


def test_phase15_has_nan_flag():
    """NaN 혼재 감지 → has_nan=True."""
    import numpy as np

    from agents.handlers.timeseries.profiler import _phase15_zero_vs_nan

    vals = np.array([1.0, 2.0, np.nan, 0.0, 0.0, 3.0])
    res = _phase15_zero_vs_nan(vals)
    assert res["has_nan"] is True


# ── 통합 — profile() 에 신규 키 존재 ──────────────────────────────────────────


def test_phase13_15_keys_present(ts_df, ts_state):
    """profile() 반환에 heteroscedasticity·outlier_kind·zero_vs_nan 존재."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    for key in ("heteroscedasticity", "outlier_kind", "zero_vs_nan"):
        assert key in result, f"신규 키 누락: {key}"


def test_phase13_15_none_when_no_target(ts_df):
    """target 없음 → 신규 3키 None."""
    from ada.core.state import PipelineState
    from agents.handlers.timeseries.profiler import profile

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000a05",
        file_id="x",
        category="timeseries",
        target_column="nonexistent",
        user_intent="x",
    )
    result = profile(ts_df, state)
    assert result["heteroscedasticity"] is None
    assert result["outlier_kind"] is None
    assert result["zero_vs_nan"] is None


def test_profile_exposes_n_rows(ts_df, ts_state):
    """profile() 가 n_rows 를 직접 노출 (proposer/preprocessor fallback 용 — 중간점검 보강)."""
    from agents.handlers.timeseries.profiler import profile

    result = profile(ts_df, ts_state)
    assert result["n_rows"] == len(ts_df)
    assert isinstance(result["n_rows"], int)

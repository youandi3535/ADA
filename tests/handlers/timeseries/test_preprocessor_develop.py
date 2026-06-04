"""CS 단독 — timeseries preprocessor 디벨롭 테스트 (cs-day2 v3).

A 누수 수정: 양방향보간→forward / boxcox train_ratio fit / horizon-aware lag
B 도메인 피처: calendar / fourier / event_flags
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from agents.handlers.timeseries.preprocessor import (
    _apply_boxcox,
    _apply_calendar,
    _apply_event_flags,
    _apply_fill_missing,
    _apply_fourier,
    _decide_lags,
    _horizon,
    plan,
)


def _state(profile=None, extras=None):
    class _S:
        data_profile = profile if profile is not None else {"rows": 120, "freq": "D"}
        category_extras = extras or {}
        target_column = "sales"

    return _S()


# ════════════════════════════════════════════════════════
# A-1. 양방향 보간 제거 (누수 1-3)
# ════════════════════════════════════════════════════════


def test_fill_no_backward_leak_in_middle():
    """중간 결측이 미래값으로 안 채워짐 — ffill(과거값)으로 채워야."""
    # 100 다음 결측 2개, 그 뒤 0 → 양방향이면 보간으로 100~0 사이값, forward면 100 유지
    df = pd.DataFrame({"sales": [100.0, np.nan, np.nan, 0.0, 0.0]})
    out = _apply_fill_missing(df, "sales", ffill_limit=7, bfill_limit=3)
    assert out["sales"].iloc[1] == 100.0  # 과거값 복사 (미래 0 안 끌어옴)
    assert out["sales"].iloc[2] == 100.0


def test_fill_leading_nan_still_bfill():
    """시작 구간 leading NaN 은 여전히 bfill (불가피 — 과거 없음)."""
    df = pd.DataFrame({"sales": [np.nan, np.nan, 5.0, 6.0]})
    out = _apply_fill_missing(df, "sales", ffill_limit=7, bfill_limit=3)
    assert out["sales"].iloc[0] == 5.0


# ════════════════════════════════════════════════════════
# A-2. boxcox train_ratio fit (누수 1-3)
# ════════════════════════════════════════════════════════


def test_boxcox_train_ratio_no_crash():
    """train_ratio 지정 시 λ 를 앞 구간만으로 추정해도 전체 변환 + 크래시 X."""
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"sales": np.abs(rng.normal(100, 20, 120)) + 1})
    out = _apply_boxcox(df, "sales", train_ratio=0.8)
    assert "sales_bc" in out.columns
    assert out["sales_bc"].notna().sum() > 0
    assert "boxcox_lambda" in out.attrs


def test_boxcox_default_unchanged():
    """train_ratio None(기본) 이면 기존 동작 — 전체로 λ 추정."""
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"sales": np.abs(rng.normal(100, 20, 60)) + 1})
    out = _apply_boxcox(df, "sales")  # train_ratio 미지정
    assert "sales_bc" in out.columns


# ════════════════════════════════════════════════════════
# A-3. horizon-aware lag (누수 1-2)
# ════════════════════════════════════════════════════════


def test_decide_lags_horizon_1_default():
    """horizon=1(기본) 이면 lag-1 포함 (기존 동작)."""
    lags = _decide_lags(_state(), 120)  # 2-인자 호출 (호환)
    assert 1 in lags


def test_decide_lags_horizon_excludes_short():
    """horizon=7 이면 lag<7 제외 (다단계 누수 차단)."""
    lags = _decide_lags(_state(), 120, horizon=7)
    assert all(lag >= 7 for lag in lags)
    assert 1 not in lags


def test_decide_lags_horizon_guarantees_one():
    """모든 후보가 horizon 미만이어도 최소 horizon lag 1개 보장."""
    # period 없음 → [1,7,14], horizon=10 → 14 만 남음 (10 이상)
    lags = _decide_lags(_state(profile={"rows": 200}), 200, horizon=10)
    assert len(lags) >= 1
    assert all(lag >= 10 for lag in lags)


def test_horizon_from_extras():
    """category_extras 에서 horizon 읽기."""
    assert _horizon(_state(extras={"timeseries": {"horizon": 7}})) == 7
    assert _horizon(_state()) == 1  # 없으면 1


# ════════════════════════════════════════════════════════
# B. 도메인 피처 (방법론 3-2)
# ════════════════════════════════════════════════════════


def test_calendar_features_created():
    """달력 피처 — datetime 컬럼 있으면 생성."""
    df = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=30, freq="D"), "sales": range(30)})
    out = _apply_calendar(df, _state(profile={"date_col": "date"}))
    for c in ("cal_dayofweek", "cal_month", "cal_quarter", "cal_is_month_start", "cal_is_month_end"):
        assert c in out.columns


def test_calendar_no_date_skip():
    """날짜 컬럼 없으면 skip (크래시 X)."""
    df = pd.DataFrame({"sales": range(10)})
    out = _apply_calendar(df, _state(profile={}))
    assert "cal_dayofweek" not in out.columns
    assert len(out) == 10


def test_fourier_features_created():
    """푸리에 — period 있으면 sin/cos 쌍 생성."""
    df = pd.DataFrame({"sales": range(60)})
    out = _apply_fourier(df, _state(), period=12, n_terms=2)
    assert "fourier_sin1_p12" in out.columns
    assert "fourier_cos1_p12" in out.columns
    assert "fourier_sin2_p12" in out.columns


def test_fourier_no_period_skip():
    """period 없으면 skip."""
    df = pd.DataFrame({"sales": range(30)})
    out = _apply_fourier(df, _state(), period=None)
    assert not any(c.startswith("fourier_") for c in out.columns)


def test_event_flags_from_changepoints():
    """profiler changepoints_detail → event_regime 더미."""
    df = pd.DataFrame({"sales": range(100)})
    state = _state(profile={"changepoints_detail": {"indices": [40, 80]}})
    out = _apply_event_flags(df, state)
    assert "event_regime" in out.columns
    assert out["event_regime"].iloc[0] == 0.0  # 첫 changepoint 이전
    assert out["event_regime"].iloc[90] >= 1.0  # changepoint 이후


def test_event_flags_no_cp_skip():
    """changepoint 없으면 skip."""
    df = pd.DataFrame({"sales": range(50)})
    out = _apply_event_flags(df, _state(profile={}))
    assert "event_regime" not in out.columns


# ════════════════════════════════════════════════════════
# 통합 — plan() 에 신규 step 등록되는지
# ════════════════════════════════════════════════════════


def test_plan_includes_domain_steps():
    """plan() 에 calendar/fourier/event_flags step 포함 (period 있을 때)."""
    state = _state(profile={"rows": 144, "seasonality": {"has_seasonality": True, "period": 12}})
    steps = plan(state)
    names = [s["name"] for s in steps]
    assert "calendar" in names
    assert "fourier" in names
    assert "event_flags" in names
    # 순서: 신규 피처는 fill_feature_nans 이전
    assert names.index("calendar") < names.index("fill_feature_nans")

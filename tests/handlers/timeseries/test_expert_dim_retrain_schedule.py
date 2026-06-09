"""Phase 1-B 테스트 — 재학습 비용 자동 추천 (_recommend_retrain_schedule).

검증 항목:
  - 기본 (변동 없음) 시 표준 주기 + urgency='low'
  - changepoint 빈도 ≥5% 시 주기 단축 + urgency='high'
  - fold 안정성 very_unstable 시 주기 50% 단축 + urgency='high'
  - 장기 horizon (≥30) 시 horizon/2 주기 제한
  - 짧은 계열 (n<100) 시 데이터 누적 우선 — 주기 길게
  - 빈도 multiplier (D/W/M) 정확 적용
  - 최소·최대 가드 (7 ≤ interval_days ≤ 365)
  - expert_voice 한국어 정합 (긴급·주의·표준)
"""

from __future__ import annotations

import pytest


def test_retrain_default_low_urgency(ts_state):
    """변동 없는 표준 데이터 → low urgency."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={"rows": 500, "freq": "D"},
        eda_summary={"seasonal_period": 7, "changepoints": 0},
        eval_result={"fold_diagnostics": {"stability": "stable"}},
    )
    r = _recommend_retrain_schedule(state)
    assert r["urgency"] == "low"
    assert r["interval_days"] >= 14
    assert r["interval_days"] <= 365
    assert "표준" in r["urgency_ko"] or "표준" in r["expert_voice"]


def test_retrain_high_urgency_on_changepoints(ts_state):
    """changepoint 빈도 ≥5% → high urgency + 주기 단축."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    # 200 rows, 15 changepoints → 7.5% 빈도
    state = ts_state.with_update(
        data_profile={"rows": 200, "freq": "D"},
        eda_summary={"seasonal_period": 7, "changepoints": 15},
        eval_result={"fold_diagnostics": {"stability": "stable"}},
    )
    r = _recommend_retrain_schedule(state)
    assert r["urgency"] == "high"
    assert any("changepoint" in t for t in r["triggers"])


def test_retrain_high_urgency_on_unstable_fold(ts_state):
    """fold very_unstable → high urgency."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={"rows": 500, "freq": "D"},
        eda_summary={"seasonal_period": 7, "changepoints": 0},
        eval_result={"fold_diagnostics": {"stability": "very_unstable"}},
    )
    r = _recommend_retrain_schedule(state)
    assert r["urgency"] == "high"
    assert any("fold 안정성" in t for t in r["triggers"])


def test_retrain_long_horizon_caps_interval(ts_state):
    """장기 예측 (horizon≥30) → horizon/2 주기 제한."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={"rows": 500, "freq": "D"},
        eda_summary={"seasonal_period": 7, "changepoints": 0, "horizon": 60},
        eval_result={"fold_diagnostics": {"stability": "stable"}},
        category_extras={"timeseries": {"horizon": 60}},
    )
    r = _recommend_retrain_schedule(state)
    assert r["interval_days"] <= 30  # horizon/2


def test_retrain_short_series_data_accumulation(ts_state):
    """짧은 계열 (n<100) → 데이터 누적 우선, 주기 길게, low urgency."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={"rows": 60, "freq": "D"},
        eda_summary={"seasonal_period": 7, "changepoints": 0},
        eval_result={"fold_diagnostics": {"stability": "stable"}},
    )
    r = _recommend_retrain_schedule(state)
    assert r["urgency"] == "low"
    assert any("짧은 계열" in t or "누적" in t for t in r["triggers"])


def test_retrain_min_max_guards(ts_state):
    """interval_days 는 [7, 365] 범위."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={"rows": 1000, "freq": "M"},
        eda_summary={"seasonal_period": 12, "changepoints": 0},
        eval_result={"fold_diagnostics": {"stability": "stable"}},
    )
    r = _recommend_retrain_schedule(state)
    assert 7 <= r["interval_days"] <= 365


def test_retrain_korean_voice(ts_state):
    """expert_voice 한국어 자연어 + 일수 인용."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={"rows": 200, "freq": "D"},
        eda_summary={"seasonal_period": 7, "changepoints": 0},
        eval_result={"fold_diagnostics": {"stability": "stable"}},
    )
    r = _recommend_retrain_schedule(state)
    voice = r["expert_voice"]
    assert "일" in voice
    assert "재학습" in voice
    # 한글 포함
    has_hangul = any("가" <= c <= "힣" for c in voice)
    assert has_hangul


def test_retrain_freq_multiplier_weekly(ts_state):
    """주별 (W) freq → 일별 대비 7× 환산."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={"rows": 200, "freq": "W"},
        eda_summary={"seasonal_period": 52, "changepoints": 0},
        eval_result={"fold_diagnostics": {"stability": "stable"}},
    )
    r = _recommend_retrain_schedule(state)
    # 52주 × 4 × 7일 = 1456일이지만 365 cap
    assert r["interval_days"] == 365


def test_retrain_graceful_empty_state(ts_state):
    """data_profile/eda 비어있어도 graceful (기본값으로 동작)."""
    from agents.handlers.timeseries.insight import _recommend_retrain_schedule

    state = ts_state.with_update(
        data_profile={},
        eda_summary={},
        eval_result={},
    )
    r = _recommend_retrain_schedule(state)
    assert "interval_days" in r
    assert "urgency" in r
    assert "expert_voice" in r

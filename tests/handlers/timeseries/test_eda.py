"""CS 단독 — timeseries eda 테스트 (cs-day3 v3 디벨롭).

검증:
  ① _carry_from_profile — profiler 진단 승계 (changepoints·is_multiplicative·ccf·이분산·정상성)
  ② _infer_seasonal_period — 3단 우선순위
  ③ _exog_columns — category_extras 우선 + 수치형 추론
  ④ charts() 통합 — save_chart_to_minio monkeypatch, eda_summary 계약 + carry 전달
  ⑤ 엣지 — data_profile None / target 없음 / n<10 크래시·롤백
"""

from __future__ import annotations

import pytest

# ── ① _carry_from_profile ─────────────────────────────────────────────────────


def test_carry_changepoints_and_multiplicative():
    """profiler changepoints·is_multiplicative 가 평탄화되어 승계."""
    from agents.handlers.timeseries.eda import _carry_from_profile

    profile = {
        "changepoints": 3,
        "is_multiplicative": {"is_multiplicative": True, "confidence": 0.9},
        "heteroscedasticity": {"is_heteroscedastic": True, "var_ratio": 5.0},
        "ccf_leakage": {
            "is_multivariate": True,
            "ccf_top_lags": {"x": {"lag": 3, "corr": 0.5}},
            "leakage_suspect_cols": ["leak"],
        },
        "target_kind": {"target_kind": "level"},
        "stationarity": {"is_stationary": False, "consensus": "non_stationary"},
    }
    c = _carry_from_profile(profile)
    assert c["changepoints"] == 3
    assert c["is_multiplicative"] is True
    assert c["heteroscedastic"] is True
    assert c["ccf_top_lags"] == {"x": {"lag": 3, "corr": 0.5}}
    assert c["leakage_suspect_cols"] == ["leak"]
    assert c["is_multivariate"] is True
    assert c["target_kind"] == "level"
    assert c["stationary"] is False
    assert c["stationarity_consensus"] == "non_stationary"


def test_carry_empty_profile():
    """data_profile None/빈 → 빈 dict (None 키 제거), 크래시 X."""
    from agents.handlers.timeseries.eda import _carry_from_profile

    assert _carry_from_profile({}) == {}
    assert _carry_from_profile(None) == {}


def test_carry_partial_profile():
    """일부 키만 있어도 있는 것만 승계."""
    from agents.handlers.timeseries.eda import _carry_from_profile

    c = _carry_from_profile({"changepoints": 1})
    assert c["changepoints"] == 1
    assert "is_multiplicative" not in c  # None 은 제거됨


# ── ② _infer_seasonal_period ──────────────────────────────────────────────────


def test_infer_period_eda_priority():
    """eda 명시값 우선."""
    from agents.handlers.timeseries.eda import _infer_seasonal_period

    assert _infer_seasonal_period({"seasonal_period": 12}, "D", [7], 144) == 12


def test_infer_period_acf_fallback():
    """eda 없으면 acf peak."""
    from agents.handlers.timeseries.eda import _infer_seasonal_period

    assert _infer_seasonal_period({}, "D", [7, 14], 100) == 7


def test_infer_period_freq_fallback():
    """eda·acf 없으면 freq fallback."""
    from agents.handlers.timeseries.eda import _infer_seasonal_period

    assert _infer_seasonal_period({}, "M", [], 100) == 12


# ── ③ _exog_columns ───────────────────────────────────────────────────────────


def test_exog_from_category_extras():
    """category_extras 우선."""
    import pandas as pd

    from agents.handlers.timeseries.eda import _exog_columns

    df = pd.DataFrame({"sales": [1, 2, 3], "temp": [10, 11, 12], "promo": [0, 1, 0]})

    class _S:
        category_extras = {"timeseries": {"exog_columns": ["temp"]}}

    assert _exog_columns(_S(), df, "sales") == ["temp"]


def test_exog_numeric_inference():
    """category_extras 없으면 수치형 추론(target·date 제외)."""
    import pandas as pd

    from agents.handlers.timeseries.eda import _exog_columns

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "sales": [1, 2, 3],
            "temp": [10, 11, 12],
        }
    )

    class _S:
        category_extras = {}

    out = _exog_columns(_S(), df, "sales")
    assert "temp" in out and "sales" not in out and "date" not in out


# ── ④ charts() 통합 (save_chart_to_minio monkeypatch) ─────────────────────────


@pytest.fixture
def _patch_minio(monkeypatch):
    """save_chart_to_minio 를 가짜 경로 반환으로 대체 (MinIO 의존 제거)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    calls = {"kinds": []}

    def _fake(fig, *, kind, job_id):
        calls["kinds"].append(kind)
        plt.close(fig)
        return f"minio://{kind}/{job_id}.png"

    monkeypatch.setattr("agents.handlers.common.shared.save_chart_to_minio", _fake)
    return calls


def test_charts_carry_into_summary(ts_df, ts_state, _patch_minio, require_statsmodels):
    """profiler 진단이 last_eda_summary 로 전달되는지 (단절 B 핸들러측 해소)."""
    from agents.handlers.timeseries.eda import charts

    # data_profile 에 profiler 진단 주입
    state = ts_state.with_update(
        data_profile={
            "freq": "D",
            "rows": len(ts_df),
            "changepoints": 2,
            "is_multiplicative": {"is_multiplicative": True},
            "heteroscedasticity": {"is_heteroscedastic": False},
            "stationarity": {"is_stationary": False, "consensus": "non_stationary"},
            "changepoints_detail": {"indices": [40, 80]},
        }
    )
    paths = charts(ts_df, state)
    assert len(paths) >= 1
    summary = charts.last_eda_summary
    # ★ carry 전달 확인
    assert summary["changepoints"] == 2
    assert summary["is_multiplicative"] is True
    assert summary["stationary"] is False  # profiler 정상성이 자체 ADF 를 덮어씀
    assert "seasonal_period" in summary
    assert "charts" in summary


def test_charts_new_chart_kinds(ts_df, ts_state, _patch_minio, require_statsmodels):
    """신규 차트(pacf·rolling_std 등) 종류가 생성 시도되는지."""
    from agents.handlers.timeseries.eda import charts

    state = ts_state.with_update(
        data_profile={"freq": "D", "rows": len(ts_df), "changepoints_detail": {"indices": [50]}}
    )
    charts(ts_df, state)
    kinds = _patch_minio["kinds"]
    # 기존 + 신규 — 최소 line/acf/pacf 또는 rolling_std 중 신규가 하나라도
    assert any("pacf" in k or "rolling_std" in k or "changepoints" in k for k in kinds)


# ── ⑤ 엣지 / 롤백 ─────────────────────────────────────────────────────────────


def test_charts_no_target_raises(ts_df):
    """target 없음 → ValueError (RB-1)."""
    from ada.core.state import PipelineState
    from agents.handlers.timeseries.eda import charts

    state = PipelineState(
        job_id="00000000-0000-0000-0000-000000000e01",
        file_id="x",
        category="timeseries",
        target_column="nonexistent",
        user_intent="x",
    )
    with pytest.raises(ValueError):
        charts(ts_df, state)


def test_charts_short_raises(ts_state, _patch_minio):
    """n<10 → ValueError (RB-2)."""
    import pandas as pd

    from agents.handlers.timeseries.eda import charts

    short = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5, freq="D"), "sales": [1, 2, 3, 4, 5]})
    with pytest.raises(ValueError):
        charts(short, ts_state)


def test_charts_profile_none_no_crash(ts_df, ts_state, _patch_minio, require_statsmodels):
    """data_profile None 이어도 carry 빈 dict, 크래시 X, 기존 차트 생성."""
    from agents.handlers.timeseries.eda import charts

    state = ts_state.with_update(data_profile=None)
    paths = charts(ts_df, state)
    assert len(paths) >= 1  # 기존 차트로 paths≥1 보장 (회귀 0)

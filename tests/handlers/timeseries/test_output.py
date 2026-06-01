"""CS 단독 — timeseries output_extras 단위 테스트.

MinIO / matplotlib 의존 없이 순수 로직만 검증.
MinIO 호출은 monkeypatch 로 격리.
"""

from __future__ import annotations

import numpy as np
import pytest

from agents.handlers.timeseries.output_extras import (
    _build_recommendations,
    _eda_dict,
    assets,
    build,
)

# ════════════════════════════════════════════════════════
# Fixtures
# ════════════════════════════════════════════════════════


@pytest.fixture
def state_no_model(ts_state):
    return ts_state


@pytest.fixture
def state_with_model(ts_state):
    return ts_state.with_update(
        best_model={
            "model_name": "SARIMA",
            "metrics": {
                "val_rmse": 12.3,
                "val_mae": 9.1,
                "MASE": 0.75,
                "sMAPE": 8.5,
                "rmse_improvement_vs_naive": 0.12,
                "y_pred_val": [100.0, 102.0, 98.0, 105.0],
                "y_val_actual": [101.0, 103.0, 97.0, 106.0],
            },
        }
    )


@pytest.fixture
def state_poor_model(ts_state):
    return ts_state.with_update(
        best_model={
            "model_name": "NaiveModel",
            "metrics": {
                "MASE": 1.5,
                "rmse_improvement_vs_naive": -0.05,
                "y_pred_val": [50.0, 50.0],
                "y_val_actual": [80.0, 90.0],
            },
        }
    )


@pytest.fixture
def state_with_pi(ts_state):
    return ts_state.with_update(
        best_model={
            "model_name": "SARIMA",
            "metrics": {
                "MASE": 0.4,
                "y_pred_val": [100.0, 102.0, 98.0],
                "y_val_actual": [101.0, 103.0, 97.0],
                "pi_lower": [95.0, 97.0, 93.0],
                "pi_upper": [105.0, 107.0, 103.0],
            },
        }
    )


@pytest.fixture
def state_with_eda(ts_state):
    return ts_state.with_update(
        best_model={"model_name": "Prophet", "metrics": {"MASE": 0.3}},
        eda_summary={"seasonal_period": 7, "stationary": False},
    )


@pytest.fixture
def state_with_insights(ts_state):
    return ts_state.with_update(
        best_model={"model_name": "SARIMA", "metrics": {"MASE": 0.6}},
        insights="매출은 7일 주기 계절성을 보이며 상승 추세입니다.",
    )


# ════════════════════════════════════════════════════════
# 1. 반환 구조 (contract 검증)
# ════════════════════════════════════════════════════════


class TestReturnContract:
    def test_three_keys_present(self, state_with_model):
        result = build(state_with_model)
        assert set(result.keys()) == {"charts", "tables", "text_blocks"}

    def test_charts_is_list(self, state_with_model):
        assert isinstance(build(state_with_model)["charts"], list)

    def test_tables_is_list(self, state_with_model):
        assert isinstance(build(state_with_model)["tables"], list)

    def test_text_blocks_is_list(self, state_with_model):
        assert isinstance(build(state_with_model)["text_blocks"], list)

    def test_assets_delegates_to_build(self, state_with_model):
        assert assets(state_with_model) == build(state_with_model)

    def test_assets_accepts_ctx(self, state_with_model):
        result = assets(state_with_model, ctx={"output_code": "OUT-01", "category": "timeseries"})
        assert set(result.keys()) == {"charts", "tables", "text_blocks"}


# ════════════════════════════════════════════════════════
# 2. RB-1 롤백 — best_model 부재
# ════════════════════════════════════════════════════════


class TestRollback:
    def test_no_best_model_returns_empty_dict(self, state_no_model):
        assert build(state_no_model) == {}

    def test_best_model_none_returns_empty_dict(self, ts_state):
        s = ts_state.with_update(best_model=None)
        assert build(s) == {}

    def test_best_model_empty_dict_returns_empty(self, ts_state):
        s = ts_state.with_update(best_model={})
        assert build(s) == {}


# ════════════════════════════════════════════════════════
# 3. tables — §E
# ════════════════════════════════════════════════════════


class TestTables:
    def test_forecast_table_created(self, state_with_model):
        tables = build(state_with_model)["tables"]
        titles = [t["title"] for t in tables]
        assert any("예측" in title for title in titles)

    def test_forecast_table_has_required_keys(self, state_with_model):
        tables = build(state_with_model)["tables"]
        forecast = next(t for t in tables if "예측" in t["title"])
        assert "title" in forecast
        assert "columns" in forecast
        assert "rows" in forecast

    def test_forecast_table_row_count(self, state_with_model):
        tables = build(state_with_model)["tables"]
        forecast = next(t for t in tables if "예측" in t["title"])
        assert len(forecast["rows"]) == 4  # y_pred_val 에 4개 값

    def test_perf_table_created_when_metrics_present(self, state_with_model):
        tables = build(state_with_model)["tables"]
        titles = [t["title"] for t in tables]
        assert any("성능" in title for title in titles)

    def test_perf_table_contains_rmse(self, state_with_model):
        tables = build(state_with_model)["tables"]
        perf = next(t for t in tables if "성능" in t["title"])
        metric_labels = [row[0] for row in perf["rows"]]
        assert "RMSE" in metric_labels

    def test_pi_columns_present_when_pi_available(self, state_with_pi):
        tables = build(state_with_pi)["tables"]
        forecast = next((t for t in tables if "예측" in t["title"]), None)
        assert forecast is not None
        assert "하한 (95%)" in forecast["columns"]

    def test_forecast_rows_capped_at_max(self, ts_state):
        long_pred = list(range(30))
        s = ts_state.with_update(best_model={"model_name": "M", "metrics": {"y_pred_val": long_pred}})
        tables = build(s)["tables"]
        forecast = next((t for t in tables if "예측" in t["title"]), None)
        assert forecast is not None
        assert len(forecast["rows"]) <= 20


# ════════════════════════════════════════════════════════
# 4. text_blocks — §D
# ════════════════════════════════════════════════════════


class TestTextBlocks:
    def test_recommendation_added_when_mase_available(self, state_with_model):
        text_blocks = build(state_with_model)["text_blocks"]
        assert any(b.get("type") == "action" for b in text_blocks)

    def test_insights_reused_when_present(self, state_with_insights):
        text_blocks = build(state_with_insights)["text_blocks"]
        assert any(b.get("type") == "insight" for b in text_blocks)

    def test_insight_body_matches_state(self, state_with_insights):
        text_blocks = build(state_with_insights)["text_blocks"]
        insight = next(b for b in text_blocks if b.get("type") == "insight")
        assert "7일" in insight["body"]

    def test_no_insight_block_when_empty(self, state_with_model):
        text_blocks = build(state_with_model)["text_blocks"]
        assert not any(b.get("type") == "insight" for b in text_blocks)

    def test_text_block_items_have_required_keys(self, state_with_model):
        for block in build(state_with_model)["text_blocks"]:
            assert "type" in block
            assert "title" in block
            assert "body" in block


# ════════════════════════════════════════════════════════
# 5. _build_recommendations 규칙 검증
# ════════════════════════════════════════════════════════


class TestBuildRecommendations:
    def test_mase_below_05_excellent(self):
        msg = _build_recommendations({"MASE": 0.3}, "D", {})
        assert "매우 우수" in msg

    def test_mase_between_05_and_1_good(self):
        msg = _build_recommendations({"MASE": 0.75}, "D", {})
        assert "양호" in msg

    def test_mase_above_1_warning(self):
        msg = _build_recommendations({"MASE": 1.5}, "D", {})
        assert "주의" in msg

    def test_negative_improvement_flagged(self):
        msg = _build_recommendations({"rmse_improvement_vs_naive": -0.05}, "D", {})
        assert "열위" in msg

    def test_seasonal_period_7_weekly(self):
        msg = _build_recommendations({}, "D", {"seasonal_period": 7})
        assert "주간" in msg

    def test_seasonal_period_12_monthly(self):
        msg = _build_recommendations({}, "M", {"seasonal_period": 12})
        assert "월간" in msg

    def test_empty_metrics_returns_empty_string(self):
        assert _build_recommendations({}, "D", {}) == ""

    def test_no_crash_on_none_mase(self):
        msg = _build_recommendations({"MASE": None}, "D", {})
        assert isinstance(msg, str)


# ════════════════════════════════════════════════════════
# 6. _eda_dict 헬퍼
# ════════════════════════════════════════════════════════


class TestEdaDict:
    def test_returns_dict_when_eda_summary_is_dict(self, ts_state):
        s = ts_state.with_update(eda_summary={"seasonal_period": 7})
        assert _eda_dict(s) == {"seasonal_period": 7}

    def test_returns_empty_dict_when_no_eda_summary(self, ts_state):
        assert _eda_dict(ts_state) == {}

    def test_returns_empty_dict_when_eda_summary_is_string(self, ts_state):
        s = ts_state.with_update(eda_summary="분석 요약 텍스트")
        assert _eda_dict(s) == {}


# ════════════════════════════════════════════════════════
# 7. MinIO 격리 — monkeypatch
# ════════════════════════════════════════════════════════


class TestMinIOIsolation:
    def test_charts_empty_when_minio_unavailable(self, state_with_model):
        """MinIO 미연결 시 charts=[] 이어야 하며 예외 전파 없어야 함."""
        result = build(state_with_model)
        assert isinstance(result["charts"], list)

    def test_tables_still_populated_when_minio_fails(self, state_with_model):
        """MinIO 실패해도 tables 는 채워져야 한다."""
        result = build(state_with_model)
        assert len(result["tables"]) > 0

    def test_build_does_not_raise_on_minio_error(self, state_with_model):
        result = build(state_with_model)
        assert result is not None

    def test_charts_list_populated_when_minio_mocked(self, state_with_model, monkeypatch):
        """save_chart_to_minio mock 시 차트 경로가 charts 에 추가된다."""
        monkeypatch.setattr(
            "agents.handlers.timeseries.output_extras.build.__module__",
            "agents.handlers.timeseries.output_extras",
        )
        import agents.handlers.common.shared as shared_mod

        monkeypatch.setattr(
            shared_mod,
            "save_chart_to_minio",
            lambda fig, kind, job_id: f"s3://autoai-artifacts/eda/{kind}/test.png",
        )
        result = build(state_with_model)
        assert len(result["charts"]) >= 1
        assert result["charts"][0].startswith("s3://")

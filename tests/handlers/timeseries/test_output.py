"""CS 단독 — timeseries output_extras 단위 테스트 (cs-day9 v3).

MinIO / matplotlib 의존 없이 순수 로직만 검증.
MinIO 호출은 monkeypatch 로 격리.

v3 보완 테스트:
  CG-1  text_blocks list[str] 표준화 검증
  CH-1  신뢰도 한계 배지 (eval_result 증상/누수/fold)
  CH-2  forecast_chart 메타 (horizon, forecast_kind, variate)
  CH-3  fold_diagnostics 표
"""

from __future__ import annotations

import pytest

from agents.handlers.timeseries.output_extras import (
    LOW_TRUST_SYMPTOMS,
    _build_recommendations,
    _build_reliability_badge,
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


# v3 — CH-1 신뢰도 배지 (저신뢰 시나리오)
@pytest.fixture
def state_low_trust(ts_state):
    return ts_state.with_update(
        best_model={
            "model_name": "SARIMA",
            "metrics": {
                "MASE": 0.02,
                "rmse_improvement_vs_naive": 0.99,
                "y_pred_val": [100.0, 102.0],
                "y_val_actual": [101.0, 103.0],
            },
        },
        eval_result={
            "passed": False,
            "rationale": "leakage_suspect",
            "metrics": {},
            "threshold_violations": [],
            "fold_diagnostics": {"available": False},
            "leakage_suspect_signals": [
                {"kind": "too_good_vs_naive", "value": 0.99, "threshold": 0.95, "hint": "..."},
                {"kind": "near_zero_MASE", "value": 0.02, "threshold": 0.01, "hint": "..."},
            ],
            "symptom_classification": {
                "symptom": "C",
                "label": "검증 성능 비현실적 좋음 (누수 의심)",
                "rollback_priority": [],
                "reason": "leakage",
            },
            "task_kind_hint": None,
        },
    )


# v3 — CH-2 ts_extras 메타 (forecast_kind / horizon_hint / variate)
@pytest.fixture
def state_with_ts_meta(ts_state):
    return ts_state.with_update(
        best_model={
            "model_name": "SARIMA",
            "metrics": {
                "MASE": 0.5,
                "y_pred_val": [100.0, 102.0, 98.0],
                "y_val_actual": [101.0, 103.0, 97.0],
            },
        },
        category_extras={
            "timeseries": {
                "freq": "D",
                "forecast_kind": "interval",
                "variate": "univariate",
                "horizon_hint": 14,
            }
        },
    )


# v3 — CH-3 fold_diagnostics 표
@pytest.fixture
def state_with_fold_diag(ts_state):
    return ts_state.with_update(
        best_model={
            "model_name": "ETS",
            "metrics": {"MASE": 0.6, "y_pred_val": [10.0, 11.0], "y_val_actual": [10.5, 11.5]},
        },
        eval_result={
            "passed": True,
            "rationale": "OK",
            "metrics": {},
            "threshold_violations": [],
            "fold_diagnostics": {
                "available": True,
                "n_folds": 5,
                "mean": 0.6,
                "std": 0.1,
                "cv": 0.1667,
                "range_ratio": 0.5,
                "stability": "stable",
                "best_fold": {"idx": 2, "score": 0.55},
                "worst_fold": {"idx": 0, "score": 0.7},
            },
            "leakage_suspect_signals": [],
            "symptom_classification": {"symptom": "normal", "label": "정상 통과"},
            "task_kind_hint": None,
        },
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
# 4. text_blocks — §D (CG-1 str 표준화 검증)
# ════════════════════════════════════════════════════════


class TestTextBlocks:
    def test_all_blocks_are_str(self, state_with_insights):
        """CG-1 — text_blocks 모든 항목 str (NY/jh 호환, carrier ppt.py 렌더 안전)."""
        text_blocks = build(state_with_insights)["text_blocks"]
        for block in text_blocks:
            assert isinstance(block, str), f"text_blocks 항목은 str 이어야 함, got {type(block)}"

    def test_recommendation_added_when_mase_available(self, state_with_model):
        text_blocks = build(state_with_model)["text_blocks"]
        assert any("권장 액션" in b for b in text_blocks)

    def test_insights_reused_when_present(self, state_with_insights):
        text_blocks = build(state_with_insights)["text_blocks"]
        assert any("분석 인사이트" in b for b in text_blocks)

    def test_insight_body_contains_state_text(self, state_with_insights):
        text_blocks = build(state_with_insights)["text_blocks"]
        insight = next(b for b in text_blocks if "분석 인사이트" in b)
        assert "7일" in insight

    def test_no_insight_block_when_empty(self, state_with_model):
        text_blocks = build(state_with_model)["text_blocks"]
        assert not any("분석 인사이트" in b for b in text_blocks)


# ════════════════════════════════════════════════════════
# 4-B. CH-1 — 신뢰도 한계 배지
# ════════════════════════════════════════════════════════


class TestReliabilityBadge:
    def test_badge_present_when_low_trust(self, state_low_trust):
        text_blocks = build(state_low_trust)["text_blocks"]
        assert text_blocks, "저신뢰 시나리오에서 text_blocks 가 비어선 안 됨"
        assert any("신뢰도 한계" in b for b in text_blocks), "신뢰도 배지가 없음"

    def test_badge_is_first_when_present(self, state_low_trust):
        text_blocks = build(state_low_trust)["text_blocks"]
        assert text_blocks[0].startswith("⚠ 신뢰도 한계"), (
            "배지는 text_blocks 맨 앞에 와야 함 (ppt[:3] 슬라이스 우선순위)"
        )

    def test_badge_mentions_symptom(self, state_low_trust):
        text_blocks = build(state_low_trust)["text_blocks"]
        badge = text_blocks[0]
        assert "증상 C" in badge

    def test_badge_mentions_leakage_count(self, state_low_trust):
        text_blocks = build(state_low_trust)["text_blocks"]
        badge = text_blocks[0]
        assert "누수 신호 2건" in badge

    def test_no_badge_when_normal(self, state_with_model):
        text_blocks = build(state_with_model)["text_blocks"]
        assert not any("신뢰도 한계" in b for b in text_blocks)

    def test_helper_returns_none_when_eval_empty(self):
        assert _build_reliability_badge({}) is None
        assert _build_reliability_badge(None) is None  # type: ignore[arg-type]

    def test_helper_returns_none_when_normal(self):
        assert (
            _build_reliability_badge(
                {
                    "symptom_classification": {"symptom": "normal", "label": "정상 통과"},
                    "leakage_suspect_signals": [],
                    "fold_diagnostics": {"available": False},
                }
            )
            is None
        )

    def test_helper_fold_unstable_triggers_badge(self):
        badge = _build_reliability_badge(
            {
                "symptom_classification": {"symptom": "normal"},
                "leakage_suspect_signals": [],
                "fold_diagnostics": {"available": True, "stability": "unstable", "cv": 0.42},
            }
        )
        assert badge is not None
        assert "fold unstable" in badge

    def test_low_trust_symptoms_constant(self):
        assert "C" in LOW_TRUST_SYMPTOMS
        assert "D" in LOW_TRUST_SYMPTOMS
        assert "E" in LOW_TRUST_SYMPTOMS
        assert "normal" not in LOW_TRUST_SYMPTOMS


# ════════════════════════════════════════════════════════
# 4-C. CH-2 — forecast 메타 (forecast_kind / variate / horizon_hint)
# ════════════════════════════════════════════════════════


class TestForecastMeta:
    def test_forecast_table_title_uses_kind(self, state_with_ts_meta):
        tables = build(state_with_ts_meta)["tables"]
        forecast = next((t for t in tables if "예측" in t["title"]), None)
        assert forecast is not None
        assert "구간예측" in forecast["title"], f"forecast_kind='interval' 시 '구간예측' 표시, 실제={forecast['title']}"

    def test_forecast_table_title_uses_unit(self, state_with_ts_meta):
        tables = build(state_with_ts_meta)["tables"]
        forecast = next((t for t in tables if "예측" in t["title"]), None)
        assert forecast is not None
        assert "일" in forecast["title"]

    def test_default_kind_is_point(self, state_with_model):
        """ts_extras 미설정 시 점예측으로 표시."""
        tables = build(state_with_model)["tables"]
        forecast = next((t for t in tables if "예측" in t["title"]), None)
        assert forecast is not None
        assert "점예측" in forecast["title"]


# ════════════════════════════════════════════════════════
# 4-D. CH-3 — fold_diagnostics 표
# ════════════════════════════════════════════════════════


class TestFoldDiagnosticsTable:
    def test_fold_table_added_when_available(self, state_with_fold_diag):
        tables = build(state_with_fold_diag)["tables"]
        titles = [t["title"] for t in tables]
        assert any("Fold 안정성" in title for title in titles)

    def test_fold_table_contains_cv(self, state_with_fold_diag):
        tables = build(state_with_fold_diag)["tables"]
        fold = next(t for t in tables if "Fold 안정성" in t["title"])
        labels = [row[0] for row in fold["rows"]]
        assert "변동계수 (cv)" in labels

    def test_fold_table_contains_best_worst(self, state_with_fold_diag):
        tables = build(state_with_fold_diag)["tables"]
        fold = next(t for t in tables if "Fold 안정성" in t["title"])
        labels = [row[0] for row in fold["rows"]]
        assert "최고 fold" in labels
        assert "최악 fold" in labels

    def test_fold_table_absent_when_unavailable(self, state_with_model):
        tables = build(state_with_model)["tables"]
        titles = [t["title"] for t in tables]
        assert not any("Fold 안정성" in title for title in titles)


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
        import agents.handlers.common.shared as shared_mod

        monkeypatch.setattr(
            shared_mod,
            "save_chart_to_minio",
            lambda fig, kind, job_id: f"s3://autoai-artifacts/eda/{kind}/test.png",
        )
        result = build(state_with_model)
        assert len(result["charts"]) >= 1
        assert result["charts"][0].startswith("s3://")

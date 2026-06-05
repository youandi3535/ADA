"""테스트 — selector 주제 적합도 디벨롭 (2026-06-05).

검증:
  - _topic_signals : user_intent 키워드 + chosen_recipe.meta → 신호 dict
  - _apply_topic_bonus : 신호 활성 토픽의 모델 가중치 적용
  - score(): meta 에 topic_signals + intent_match 노출 + rationale 인용
  - 회귀 0: user_intent 미상 + chosen_recipe 미세팅 시 기존 동작 유지
"""

from __future__ import annotations

import pytest

from agents.handlers.timeseries.selector import (
    TOPIC_BONUS,
    TOPIC_KEYWORDS,
    _apply_topic_bonus,
    _topic_signals,
    score,
)


# ════════════════════════════════════════════════════════
# 1. _topic_signals — 키워드 + meta 매핑
# ════════════════════════════════════════════════════════
class TestTopicSignals:
    def test_long_term_intent_detected(self, ts_state):
        s = ts_state.with_update(user_intent="다음 90일 장기 매출 예측")
        signals = _topic_signals(s, {}, horizon=0, n_rows=500)
        assert signals["long_term"] is True

    def test_short_term_intent_detected(self, ts_state):
        s = ts_state.with_update(user_intent="내일 단기 매출 예측")
        signals = _topic_signals(s, {}, horizon=0, n_rows=500)
        assert signals["short_term"] is True

    def test_multivariate_intent_detected(self, ts_state):
        s = ts_state.with_update(user_intent="공휴일과 프로모션을 외생변수로 활용한 다변량 예측")
        signals = _topic_signals(s, {}, horizon=7, n_rows=500)
        assert signals["multivariate"] is True

    def test_interval_intent_detected(self, ts_state):
        s = ts_state.with_update(user_intent="95% 신뢰구간 포함 7일 예측")
        signals = _topic_signals(s, {}, horizon=7, n_rows=500)
        assert signals["interval"] is True

    def test_anomaly_intent_detected(self, ts_state):
        s = ts_state.with_update(user_intent="이상치 탐지")
        signals = _topic_signals(s, {}, horizon=7, n_rows=500)
        assert signals["anomaly"] is True

    def test_meta_forecast_kind_interval_activates(self, ts_state):
        signals = _topic_signals(ts_state, {"forecast_kind": "interval"}, horizon=7, n_rows=500)
        assert signals["interval"] is True

    def test_meta_variate_multivariate_activates(self, ts_state):
        signals = _topic_signals(ts_state, {"variate": "multivariate"}, horizon=7, n_rows=500)
        assert signals["multivariate"] is True

    def test_meta_task_kind_classification_activates_anomaly(self, ts_state):
        signals = _topic_signals(ts_state, {"task_kind": "classification"}, horizon=7, n_rows=500)
        assert signals["anomaly"] is True

    def test_horizon_fallback_short(self, ts_state):
        """intent 미상 + horizon 으로 fallback 분류."""
        signals = _topic_signals(ts_state, {}, horizon=3, n_rows=500)
        assert signals["short_term"] is True

    def test_horizon_fallback_long(self, ts_state):
        signals = _topic_signals(ts_state, {}, horizon=60, n_rows=500)
        assert signals["long_term"] is True

    def test_short_series_activates_baseline_and_interpretable(self, ts_state):
        """n<100 → baseline + interpretable 자동 활성."""
        signals = _topic_signals(ts_state, {}, horizon=0, n_rows=50)
        assert signals["baseline"] is True
        assert signals["interpretable"] is True

    def test_no_intent_no_meta_returns_all_false(self, ts_state):
        """완전 빈 입력 → 토픽 신호 모두 False (horizon=0 + n_rows=0)."""
        signals = _topic_signals(ts_state, {}, horizon=0, n_rows=0)
        assert not any(signals.values())


# ════════════════════════════════════════════════════════
# 2. _apply_topic_bonus — 신호 → 점수 보너스
# ════════════════════════════════════════════════════════
class TestApplyTopicBonus:
    def test_long_term_bonus_to_prophet(self):
        """장기 토픽 → Prophet 양수 보너스, 통계 모델 음수 (DL 제거됨)."""
        adj = {"ARIMA": 0.0, "SARIMA": 0.0, "Prophet": 0.0, "ETS": 0.0}
        signals = {k: False for k in TOPIC_KEYWORDS}
        signals["long_term"] = True
        applied = _apply_topic_bonus(adj, signals)
        assert adj["Prophet"] > 0
        assert adj["ARIMA"] < 0
        assert any("long_term" in s for s in applied["Prophet"])

    def test_multivariate_bonus_to_sarimax(self):
        adj = {"SARIMAX": 0.0, "ARIMA": 0.0, "ETS": 0.0}
        signals = {k: False for k in TOPIC_KEYWORDS}
        signals["multivariate"] = True
        _apply_topic_bonus(adj, signals)
        assert adj["SARIMAX"] > 0
        assert adj["ARIMA"] < 0

    def test_baseline_bonus_to_simple_models(self):
        adj = {"seasonal_naive": 0.0, "ETS": 0.0, "ARIMA": 0.0, "Prophet": 0.0}
        signals = {k: False for k in TOPIC_KEYWORDS}
        signals["baseline"] = True
        _apply_topic_bonus(adj, signals)
        assert adj["seasonal_naive"] > 0
        assert adj["ETS"] > 0
        assert adj["Prophet"] == 0  # 매트릭스에 없음

    def test_no_active_signals_no_change(self):
        adj = {"ARIMA": 0.0, "Prophet": 0.0}
        signals = {k: False for k in TOPIC_KEYWORDS}
        _apply_topic_bonus(adj, signals)
        assert adj["ARIMA"] == 0.0
        assert adj["Prophet"] == 0.0


# ════════════════════════════════════════════════════════
# 3. score() 통합 — meta 노출 + 회귀 0
# ════════════════════════════════════════════════════════
class TestScoreIntegration:
    def test_meta_includes_topic_signals_when_intent_set(self, ts_state):
        s = ts_state.with_update(user_intent="장기 30일 예측", data_profile={"rows": 500})
        result = score(s)
        meta = result["meta"]
        assert "topic_signals" in meta
        assert "intent_match" in meta

    def test_long_term_intent_promotes_prophet(self, ts_state):
        """장기 의도 + 계절 분해 recipe → Prophet 상위에 와야."""
        s = ts_state.with_update(
            user_intent="장기 90일 예측",
            data_profile={"rows": 500},
            chosen_recipe={"title": "계절성 분해"},
            eda_summary={"seasonal_period": 7, "stationary": False},
        )
        result = score(s)
        # Prophet 점수가 다른 통계 모델보다 높아야
        scores_map = result["meta"]["scores"]
        if "Prophet" in scores_map and "ARIMA" in scores_map:
            assert scores_map["Prophet"] >= scores_map["ARIMA"]

    def test_short_term_intent_promotes_stat_models(self, ts_state):
        """단기 의도 → ARIMA/ETS 양수 보너스 (DL 제거됨)."""
        s = ts_state.with_update(
            user_intent="단기 1일 예측",
            data_profile={"rows": 500},
            chosen_recipe={"title": "단기 예측"},
        )
        result = score(s)
        scores_map = result["meta"]["scores"]
        # 단기 토픽 → ARIMA/SARIMA/ETS 가 base 보다 점수 ≥
        if "ARIMA" in scores_map:
            assert scores_map["ARIMA"] >= 0.70  # base + short_term bonus

    def test_rationale_includes_topics_when_active(self, ts_state):
        s = ts_state.with_update(user_intent="장기 예측", data_profile={"rows": 500})
        result = score(s)
        assert "topics=" in result["rationale"]

    def test_no_intent_no_change_to_existing_keys(self, ts_state):
        """user_intent + chosen_recipe + meta 빈 경우 — 기존 4 키 (top3·rationale·citations·meta) 유지."""
        result = score(ts_state)
        assert set(result.keys()) == {"top3", "rationale", "citations", "meta"}
        assert len(result["top3"]) >= 3

    def test_regression_baseline_top3_length(self, ts_state):
        """회귀 0 — top3 길이 보장 (기존 DoD 불변)."""
        result = score(ts_state)
        assert len(result["top3"]) >= 3

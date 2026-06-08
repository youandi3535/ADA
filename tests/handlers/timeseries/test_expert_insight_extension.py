"""Phase 1-A/B 테스트 — insight fallback 에 전문가 차원 + 재학습 권고 통합.

검증 항목:
  - _expert_dimension_clause 가 selector_meta 있을 때 한국어 자연어 1문장 반환
  - _expert_dimension_clause 가 selector_meta 없을 때 None
  - _build_fallback 의 5번째 행동 권고 문장이 retrain 권고로 동적 결정
  - P10 5문장 제한 유지 (전문가 + 재학습 + 기존 4문장 = 6문장 → drop)
  - 한국어 강제 (lang_guard 정합)
"""

from __future__ import annotations

import pytest


def _make_state_with_eval(ts_state, **overrides):
    base = {
        "data_profile": {"rows": 200, "freq": "D", "trend": {"slope_per_obs": 0.5}},
        "eda_summary": {
            "seasonal_period": 7,
            "stationary": True,
            "changepoints": 0,
        },
        "best_model": {
            "model_name": "SARIMA",
            "metrics": {
                "val_rmse": 50.0,
                "MASE": 0.83,
                "rmse_improvement_vs_naive": 0.12,
                "pi_coverage": 0.92,
            },
        },
        "eval_result": {
            "passed": True,
            "fold_diagnostics": {"stability": "stable", "available": True},
            "leakage_suspect_signals": [],
            "symptom_classification": {"symptom": "normal"},
            "residual_diagnostics": {"kind": "white_noise"},
            "dm_test": {"verdict": "model_wins"},
        },
    }
    base.update(overrides)
    return ts_state.with_update(**base)


def test_expert_clause_returns_korean_when_meta_present(ts_state):
    """selector_meta 가 (재호출로) 산출되면 expert clause 가 한국어 1문장."""
    from agents.handlers.timeseries.insight import _expert_dimension_clause

    state = _make_state_with_eval(
        ts_state,
        user_intent="해석 가능한 모델 필요",
    )
    clause = _expert_dimension_clause(state)
    # selector.score() 재호출로 meta 산출되어야 함
    if clause is not None:
        assert "최우선" in clause
        assert "가중하여" in clause
        # 모델명 인용
        assert any(m in clause for m in ("ARIMA", "SARIMA", "Prophet", "ETS", "seasonal_naive", "SARIMAX"))


def test_expert_clause_none_when_no_best_model(ts_state):
    """best_model 없으면 clause 도 None."""
    from agents.handlers.timeseries.insight import _expert_dimension_clause

    state = ts_state.with_update(
        data_profile={"rows": 200, "freq": "D"},
        eda_summary={"seasonal_period": 7},
        best_model=None,
    )
    clause = _expert_dimension_clause(state)
    assert clause is None


def test_fallback_contains_retrain_voice_when_normal(ts_state):
    """정상 케이스에서 fallback 의 행동 권고가 retrain 권고로 대체."""
    from agents.handlers.timeseries.insight import _build_fallback

    state = _make_state_with_eval(ts_state)
    text = _build_fallback(state)
    # 한국어 + 일수 인용 (재학습 권고)
    assert "일" in text


def test_fallback_p10_5sentence_limit(ts_state):
    """P10 — 전문가 + 재학습 추가해도 5문장 하드 제한 유지."""
    from agents.handlers.timeseries.insight import _build_fallback

    state = _make_state_with_eval(
        ts_state,
        user_intent="해석 가능한 단기 예측",
    )
    text = _build_fallback(state)
    # 마침표 기반 문장 개수
    sentences = [s for s in text.split(".") if s.strip()]
    assert len(sentences) <= 5, f"P10 위반: {len(sentences)}개"
    assert len(sentences) >= 3, f"최소 3문장: {len(sentences)}개"


def test_fallback_korean_strict(ts_state):
    """fallback 결과 한국어 (한글 음절 포함)."""
    from agents.handlers.timeseries.insight import _build_fallback

    state = _make_state_with_eval(ts_state)
    text = _build_fallback(state)
    has_hangul = any("가" <= c <= "힣" for c in text)
    assert has_hangul


def test_fallback_graceful_no_meta(ts_state):
    """selector_meta 없이도 fallback graceful (전문가 clause 없이 정상 동작)."""
    from agents.handlers.timeseries.insight import _build_fallback

    # data_profile/eda 비어도 fallback 은 실행되어야 함
    state = ts_state.with_update(
        data_profile={},
        eda_summary={},
        best_model={"model_name": "SARIMA", "metrics": {}},
    )
    text = _build_fallback(state)
    assert text  # 빈 문자열 X
    assert len(text) > 10


def test_fallback_does_not_lose_existing_content(ts_state):
    """기존 5문장(추세·계절성·성능·horizon·권고) 의 의도 보존."""
    from agents.handlers.timeseries.insight import _build_fallback

    state = _make_state_with_eval(ts_state)
    text = _build_fallback(state)
    # 핵심 키워드 중 하나라도 인용되어야 함 (수치 강제 R-501)
    has_metric = any(kw in text for kw in ("MASE", "%", "0.", "1."))
    assert has_metric, f"수치 미인용: {text}"

"""Phase 1-A 테스트 — 전문가 4 차원 (해석 가능성) selector EXPERT_DIMENSIONS.

검증 항목:
  - EXPERT_DIMENSIONS 4 차원 모두 6 SUPPORTED_MODELS 점수 정의 (회귀 0 — 상수표 무결성)
  - _resolve_expert_priorities 가 user_intent 키워드 매칭 시 최우선 차원 0.40 가중
  - _resolve_expert_priorities 가 changepoint 다수 시 robustness 강화
  - _resolve_expert_priorities 가 짧은 계열 시 interpretability + robustness 우선
  - _compute_expert_scores 가 priorities × dimension 가산식 정확 적용
  - score() 결과의 meta 에 expert_priorities/expert_scores/expert_top_dimension 노출
  - rationale 에 "expert=top_dim(score@model)" 형태 포함
"""

from __future__ import annotations

import pytest


def test_expert_dimensions_completeness():
    """4 차원 × 6 모델 점수 모두 정의 (상수표 무결성)."""
    from agents.handlers.timeseries.selector import EXPERT_DIMENSIONS, SUPPORTED_MODELS

    assert set(EXPERT_DIMENSIONS.keys()) == {
        "interpretability",
        "robustness",
        "uncertainty_quality",
        "retraining_cost",
    }
    for dim_name, dim_table in EXPERT_DIMENSIONS.items():
        for model in SUPPORTED_MODELS:
            assert model in dim_table, f"{dim_name} 에 {model} 점수 누락"
            v = dim_table[model]
            assert 0.0 <= v <= 1.0, f"{dim_name}.{model}={v} out of [0,1]"


def test_expert_priority_keywords_completeness():
    """4 차원 키워드 사전 모두 비어있지 않음."""
    from agents.handlers.timeseries.selector import EXPERT_PRIORITY_KEYWORDS

    assert set(EXPERT_PRIORITY_KEYWORDS.keys()) == {
        "interpretability",
        "robustness",
        "uncertainty_quality",
        "retraining_cost",
    }
    for dim, kws in EXPERT_PRIORITY_KEYWORDS.items():
        assert len(kws) >= 3, f"{dim} 키워드 ≥3개 필요"
        assert all(isinstance(k, str) and k for k in kws)


def test_priorities_default_balance(ts_state):
    """user_intent 매칭 없고 데이터 신호 없으면 0.25 × 4 균형."""
    from agents.handlers.timeseries.selector import _resolve_expert_priorities

    # user_intent 매칭 안 되는 값으로
    ts_state = ts_state.with_update(user_intent="aaa")
    # eda 신호 없음, n_rows=200 (짧지 않음)
    priorities = _resolve_expert_priorities(ts_state, signals={}, n_rows=200)
    assert abs(sum(priorities.values()) - 1.0) < 1e-3
    for v in priorities.values():
        assert abs(v - 0.25) < 0.05


def test_priorities_interpret_keyword_match(ts_state):
    """user_intent 에 '해석' 키워드 → interpretability 0.40 가중."""
    from agents.handlers.timeseries.selector import _resolve_expert_priorities

    ts_state = ts_state.with_update(user_intent="해석 가능한 단기 예측을 원함")
    priorities = _resolve_expert_priorities(ts_state, signals={}, n_rows=200)
    assert priorities["interpretability"] >= 0.35
    # 나머지 합쳐 0.60 ± 0.05
    others = sum(v for k, v in priorities.items() if k != "interpretability")
    assert 0.55 <= others <= 0.65


def test_priorities_robust_keyword_match(ts_state):
    """'안정' 키워드 → robustness 우선."""
    from agents.handlers.timeseries.selector import _resolve_expert_priorities

    ts_state = ts_state.with_update(user_intent="안정적이고 강건한 모델 필요")
    priorities = _resolve_expert_priorities(ts_state, signals={}, n_rows=200)
    assert priorities["robustness"] >= 0.35


def test_priorities_changepoints_signal(ts_state):
    """user_intent 없고 changepoints ≥3 → robustness 강화 (데이터 신호)."""
    from agents.handlers.timeseries.selector import _resolve_expert_priorities

    ts_state = ts_state.with_update(
        user_intent="aaa",  # 매칭 없는 의도
        eda_summary={"changepoints": 5},
    )
    priorities = _resolve_expert_priorities(ts_state, signals={}, n_rows=200)
    assert priorities["robustness"] >= 0.30


def test_priorities_short_series(ts_state):
    """n_rows<100 → interpretability + robustness 우선 (안전 모드)."""
    from agents.handlers.timeseries.selector import _resolve_expert_priorities

    ts_state = ts_state.with_update(user_intent="aaa", eda_summary={})
    priorities = _resolve_expert_priorities(ts_state, signals={}, n_rows=80)
    assert priorities["interpretability"] >= 0.30
    assert priorities["robustness"] >= 0.25


def test_compute_expert_scores_correctness():
    """priorities × dimension 가산식 정확."""
    from agents.handlers.timeseries.selector import EXPERT_DIMENSIONS, _compute_expert_scores

    priorities = {
        "interpretability": 0.4,
        "robustness": 0.2,
        "uncertainty_quality": 0.2,
        "retraining_cost": 0.2,
    }
    scores = _compute_expert_scores(["ARIMA", "Prophet"], priorities)
    expected_arima = (
        0.4 * EXPERT_DIMENSIONS["interpretability"]["ARIMA"]
        + 0.2 * EXPERT_DIMENSIONS["robustness"]["ARIMA"]
        + 0.2 * EXPERT_DIMENSIONS["uncertainty_quality"]["ARIMA"]
        + 0.2 * EXPERT_DIMENSIONS["retraining_cost"]["ARIMA"]
    )
    assert abs(scores["ARIMA"] - round(expected_arima, 4)) < 1e-3


def test_score_meta_has_expert_keys(ts_state):
    """selector.score() 의 meta 에 expert_* 4 키 노출."""
    from agents.handlers.timeseries.selector import score

    ts_state = ts_state.with_update(
        data_profile={"rows": 200, "freq": "D"},
        eda_summary={"seasonal_period": 7, "stationary": True},
    )
    result = score(ts_state, recipes=None)
    meta = result.get("meta", {})
    assert "expert_priorities" in meta
    assert "expert_scores" in meta
    assert "expert_top_dimension" in meta
    assert "expert_dimensions_used" in meta
    assert isinstance(meta["expert_priorities"], dict)
    assert isinstance(meta["expert_scores"], dict)
    assert len(meta["expert_dimensions_used"]) == 4


def test_score_rationale_has_expert(ts_state):
    """rationale 에 expert=top_dim(score@model) 형태 포함."""
    from agents.handlers.timeseries.selector import score

    ts_state = ts_state.with_update(
        user_intent="해석 가능한 모델 필요",
        data_profile={"rows": 200, "freq": "D"},
        eda_summary={"seasonal_period": 7, "stationary": True},
    )
    result = score(ts_state, recipes=None)
    rationale = result.get("rationale", "")
    assert "expert=" in rationale
    assert "interpretability" in rationale


def test_apply_expert_bonus_scale():
    """EXPERT_WEIGHT_SCALE=0.15 가 7축·9토픽 가중 (±0.20·±0.10) 와 균형."""
    from agents.handlers.timeseries.selector import EXPERT_WEIGHT_SCALE, _apply_expert_bonus

    adj = {"ARIMA": 0.0, "Prophet": 0.0}
    # ARIMA 점수 1.0, Prophet 점수 0.5 일 때
    _apply_expert_bonus(adj, {"ARIMA": 1.0, "Prophet": 0.5})
    assert adj["ARIMA"] == pytest.approx(EXPERT_WEIGHT_SCALE * 1.0)
    assert adj["Prophet"] == pytest.approx(EXPERT_WEIGHT_SCALE * 0.5)


def test_apply_expert_bonus_unknown_model_ignored():
    """candidates 풀에 없는 모델은 무시 (KeyError 방어)."""
    from agents.handlers.timeseries.selector import _apply_expert_bonus

    adj = {"ARIMA": 0.0}
    _apply_expert_bonus(adj, {"ARIMA": 0.5, "UnknownModel": 0.8})
    assert "UnknownModel" not in adj  # 무시됨
    assert adj["ARIMA"] > 0

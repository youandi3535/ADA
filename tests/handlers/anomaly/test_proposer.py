"""NY Day 4 — anomaly proposer 단위 테스트 (8 케이스).

5 그룹:
  A 스키마 (#1·#2)
  B 정확성·DoD (#3·#4·#5·#6)
  E 엣지 (#7)
  F 설계 검증 (#8 — LLM X)
"""

from __future__ import annotations

import inspect
from copy import deepcopy

import pytest

# ── Day 4 전용 fixture ────────────────────────────────────────────


@pytest.fixture
def state_low_contamination(anomaly_state):
    """contamination < 0.05 — ★ OCSVM 1 위 검증용."""
    state = deepcopy(anomaly_state)
    state.data_profile = {
        "contamination_estimate": 0.02,
        "has_time_column": False,
        "n_rows": 1000,
        "is_approximately_gaussian": True,
        "intrinsic_dim_ratio": 0.8,
    }
    state.category_extras = {"anomaly": {"preprocessing": {"n_cols_out": 5}}}
    return state


@pytest.fixture
def state_with_time_column(anomaly_state):
    """has_time_column True — 6 종 카드 검증용."""
    state = deepcopy(anomaly_state)
    state.data_profile = {
        "contamination_estimate": 0.1,
        "has_time_column": True,
        "n_rows": 5000,
        "is_approximately_gaussian": False,
        "intrinsic_dim_ratio": 1.0,
    }
    state.category_extras = {"anomaly": {"preprocessing": {"n_cols_out": 10}}}
    return state


@pytest.fixture
def state_no_time(anomaly_state):
    """has_time_column False — 4 종 카드 검증용."""
    state = deepcopy(anomaly_state)
    state.data_profile = {
        "contamination_estimate": 0.1,
        "has_time_column": False,
        "n_rows": 1000,
        "is_approximately_gaussian": False,
        "intrinsic_dim_ratio": 1.0,
    }
    state.category_extras = {"anomaly": {"preprocessing": {"n_cols_out": 5}}}
    return state


@pytest.fixture
def state_empty(anomaly_state):
    """state 비어있음 (엣지)."""
    state = deepcopy(anomaly_state)
    state.data_profile = None
    state.category_extras = {}
    return state


# === A. 스키마 ====================================================


def test_g1_returns_three_options(state_no_time):
    """#1 — G1 = 3 안 list, 각 5 키."""
    from agents.handlers.anomaly.proposer import g1

    result = g1(state_no_time)
    assert isinstance(result, list)
    assert len(result) == 3
    for item in result:
        assert {"id", "title", "rationale", "score", "needs_review"}.issubset(item.keys())


def test_g2_returns_at_least_four_cards(state_no_time):
    """#2 — D1: G2 ≥ 4 종."""
    from agents.handlers.anomaly.proposer import g2

    result = g2(state_no_time)
    assert len(result) >= 4


# === B. 정확성·DoD ================================================


def test_g2_sorted_by_score_desc(state_no_time):
    """#3 — D1·D4: score 내림차순 정렬."""
    from agents.handlers.anomaly.proposer import g2

    result = g2(state_no_time)
    scores = [c["score"] for c in result]
    assert scores == sorted(scores, reverse=True)


def test_g2_ocsvm_first_when_low_contamination(state_low_contamination):
    """#4 ★ DoD — contamination < 0.05 시 OCSVM 1 위."""
    from agents.handlers.anomaly.proposer import g2

    result = g2(state_low_contamination)
    assert result[0]["title"] == "OneClassSVM"


def test_g2_includes_transformers_when_time_column(state_with_time_column):
    """#5 — D1·D8: has_time → TranAD·AnomalyTransformer 추가."""
    from agents.handlers.anomaly.proposer import g2

    result = g2(state_with_time_column)
    titles = {c["title"] for c in result}
    assert "TranAD" in titles
    assert "AnomalyTransformer" in titles


def test_g2_excludes_transformers_when_no_time(state_no_time):
    """#6 — D1: no time → TranAD·AT 제외 (정확히 4 종)."""
    from agents.handlers.anomaly.proposer import g2

    result = g2(state_no_time)
    titles = {c["title"] for c in result}
    assert "TranAD" not in titles
    assert "AnomalyTransformer" not in titles
    assert len(result) == 4


# === E. 엣지 ======================================================


def test_empty_state_returns_default_cards(state_empty):
    """#7 — state 비어있어도 default."""
    from agents.handlers.anomaly.proposer import g1, g2

    g1_result = g1(state_empty)
    g2_result = g2(state_empty)
    assert len(g1_result) == 3
    assert len(g2_result) >= 1  # 최소 IForest (score=0.7)


# === F. 설계 검증 (D2: LLM X) =====================================


def test_no_llm_call_in_module():
    """#8 — D2: 모듈에 LLM 호출 없음."""
    import agents.handlers.anomaly.proposer as mod

    source = inspect.getsource(mod)
    forbidden = ["call_llm", "anthropic", "openai", "_call_llm"]
    for keyword in forbidden:
        assert keyword.lower() not in source.lower(), f"D2 위반: 모듈에 '{keyword}' 발견 — LLM 호출 X 룰 어김"

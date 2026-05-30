"""NY Day 5 — anomaly selector 단위 테스트 (9 케이스).

5 그룹:
  A 스키마 (#1·#2)
  B 정확성 (#3·#4·#5) ★ #3 DoD
  D 분기 (#6·#7)
  E 엣지 (#8·#9)

mock 핵심: proposer.g2() 를 autouse fixture 로 자동 주입.
실제 proposer 호출 X. 테스트 격리 보장.
"""

from __future__ import annotations

import pytest

# ── 기본 mock proposer.g2() ──────────────────────────────────────


_DEFAULT_CARDS = [
    {"id": 1, "title": "IsolationForest", "score": 0.85, "rationale": "범용", "needs_review": False},
    {"id": 2, "title": "LOF", "score": 0.70, "rationale": "지역 밀도", "needs_review": False},
    {"id": 3, "title": "OneClassSVM", "score": 0.75, "rationale": "정상 학습", "needs_review": False},
    {"id": 4, "title": "AutoEncoder", "score": 0.65, "rationale": "재구성", "needs_review": False},
]


@pytest.fixture(autouse=True)
def mock_proposer_g2(monkeypatch):
    """proposer.g2() 기본 mock — 4 종 카드 반환."""
    monkeypatch.setattr(
        "agents.handlers.anomaly.selector.proposer.g2",
        lambda state: list(_DEFAULT_CARDS),
    )


# ── Day 5 전용 state fixture ──────────────────────────────────────


@pytest.fixture
def anomaly_state_with_time_profile(anomaly_state):
    """has_time_column=True 인 state (★ DoD)."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "rows": 5000,
        "dim": 10,
        "has_time_column": True,
        "contamination_estimate": 0.05,
    }
    return state


@pytest.fixture
def anomaly_state_small_data(anomaly_state):
    """n_rows<1000 인 state (DL 페널티)."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "rows": 500,
        "dim": 10,
        "has_time_column": False,
        "contamination_estimate": 0.05,
    }
    return state


@pytest.fixture
def anomaly_state_low_contam(anomaly_state):
    """contamination<0.02 인 state (OCSVM 보너스)."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "rows": 5000,
        "dim": 10,
        "has_time_column": False,
        "contamination_estimate": 0.01,
    }
    return state


@pytest.fixture
def anomaly_state_high_dim(anomaly_state):
    """n_dim>50 인 state (LOF 페널티)."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "rows": 5000,
        "dim": 100,
        "has_time_column": False,
        "contamination_estimate": 0.05,
    }
    return state


@pytest.fixture
def model_cards_with_time():
    """has_time=True 때 proposer.g2() 가 반환할 카드 (6 종)."""
    return [
        {"id": 1, "title": "IsolationForest", "score": 0.85},
        {"id": 2, "title": "LOF", "score": 0.70},
        {"id": 3, "title": "OneClassSVM", "score": 0.75},
        {"id": 4, "title": "AutoEncoder", "score": 0.65},
        {"id": 5, "title": "TranAD", "score": 0.55},
        {"id": 6, "title": "AnomalyTransformer", "score": 0.50},
    ]


# === A. 스키마 ====================================================


def test_score_returns_dict_with_keys(anomaly_state):
    """#1 — 반환 dict 의 필수 키 3 개 보장."""
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state, recipes=[])
    assert isinstance(result, dict)
    assert "top3" in result
    assert "rationale" in result
    assert "citations" in result


def test_score_top3_max_three(anomaly_state):
    """#2 — top3 길이 ≤ 3."""
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state)
    assert len(result["top3"]) <= 3


# === B. 정확성 ====================================================


def test_time_column_boosts_tranad(anomaly_state_with_time_profile, model_cards_with_time, monkeypatch):
    """#3 ★ DoD — has_time=True → TranAD top3 안 (list[dict])."""
    monkeypatch.setattr(
        "agents.handlers.anomaly.selector.proposer.g2",
        lambda state: model_cards_with_time,
    )
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state_with_time_profile)
    titles = result["top3"]
    assert "TranAD" in titles


def test_low_contamination_boosts_ocsvm(anomaly_state_low_contam):
    """#4 — contam<0.02 → OCSVM top3."""
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state_low_contam)
    titles = result["top3"]
    assert "OneClassSVM" in titles


def test_high_dim_penalizes_lof(anomaly_state_high_dim):
    """#5 — n_dim>50 → LOF total ≤ IForest total (white-box, 헬퍼 직접 호출)."""
    from agents.handlers.anomaly.selector import _build_score_matrix

    model_cards = [
        {"id": 1, "title": "LOF", "score": 0.7},
        {"id": 2, "title": "IsolationForest", "score": 0.85},
    ]
    matrix = _build_score_matrix(anomaly_state_high_dim, model_cards)
    assert matrix["LOF"]["total"] <= matrix["IsolationForest"]["total"]


# === D. 분기 ======================================================


def test_small_data_excludes_dl_top3(anomaly_state_small_data):
    """#6 — n_rows<1000 → DL 모델 (AE) top3 밀림."""
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state_small_data)
    titles = result["top3"]
    assert "AutoEncoder" not in titles


def test_empty_proposer_returns_empty(anomaly_state, monkeypatch):
    """#7 — proposer.g2() empty → top3=[]."""
    monkeypatch.setattr(
        "agents.handlers.anomaly.selector.proposer.g2",
        lambda state: [],
    )
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state)
    assert result["top3"] == []


# === E. 엣지 ======================================================


def test_no_data_profile_returns_default(anomaly_state):
    """#8 — state.data_profile=None → 표준 분기 (TypeError 없이)."""
    from copy import deepcopy

    from agents.handlers.anomaly.selector import score

    state = deepcopy(anomaly_state)
    state.data_profile = None
    result = score(state)
    assert isinstance(result["top3"], list)
    assert isinstance(result["rationale"], str)


def test_recipes_none_returns_empty_citations(anomaly_state):
    """#9 — R-501: recipes=None → citations=[] (KB 비사용)."""
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state, recipes=None)
    assert result["citations"] == []


# === ★ A-1 결정 후 추가 ===========================================


def test_interpretability_boosts_iforest():
    """#10 ★ A-1 — 설명 가능 모델 (IForest) > black-box (AnomalyTransformer).

    이상탐지 도메인 본질: '왜 이상?' 설명 가능성이 Day 8 Insight 직결.
    """
    from agents.handlers.anomaly.selector import _compute_interp_bonus

    assert _compute_interp_bonus("IsolationForest") > _compute_interp_bonus("AnomalyTransformer")
    assert _compute_interp_bonus("IsolationForest") > 0
    assert _compute_interp_bonus("AnomalyTransformer") < 0


# ── ★ C-1 결정 fixture (2026-05-28) ─────────────────────────────


@pytest.fixture
def anomaly_state_time_and_low_contam(anomaly_state):
    """has_time=True AND contamination<0.02 동시 (C-1 검증용)."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "rows": 5000,
        "dim": 10,
        "has_time_column": True,
        "contamination_estimate": 0.01,
    }
    return state


def test_time_and_low_contam_both_in_top3(anomaly_state_time_and_low_contam, model_cards_with_time, monkeypatch):
    """#11 ★ C-1 — 시간성+저오염 동시 → TranAD AND OCSVM 둘 다 top3 (DoD 보장).

    TIME_BONUS_TRANAD=0.4 (A-2 결정 갱신) 로 TranAD 가 LOF (interp +0.1) 못 따라잡지 않음.
    """
    monkeypatch.setattr(
        "agents.handlers.anomaly.selector.proposer.g2",
        lambda state: model_cards_with_time,
    )
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state_time_and_low_contam)
    titles = result["top3"]
    assert "TranAD" in titles  # ★ DoD 핵심
    assert "OneClassSVM" in titles  # 저오염 분기


# === ★ X-1 (2026-05-29): top3 = 모델명 list[str] 계약 ===============


def test_top3_is_model_name_strings(anomaly_state):
    """★ X-1 — top3 = 모델명 list[str] (model_candidates 계약), 상세는 'cards' 키."""
    from agents.handlers.anomaly.selector import score

    result = score(anomaly_state, recipes=[])
    assert isinstance(result["top3"], list)
    assert all(isinstance(t, str) for t in result["top3"])

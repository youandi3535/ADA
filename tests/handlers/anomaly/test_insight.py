"""NY Day 8 — anomaly insight 단위 테스트 (11 케이스).

5 그룹:
  A 스키마 (#1·#2)
  B 정확성 (#3·#4·#5) ★ #3 DoD σ 형식
  D 분기 (#6·#7)
  E 엣지 (#8·#9)
  F 회귀 (#10·#11)

LLM 호출 없음 — NY handler R-004 룰 (BaseAgent 상속 X).
fallback = generate 패턴 (한국어 보장).
"""

from __future__ import annotations

import re

import numpy as np
import pytest

# ── Day 8 전용 fixture ────────────────────────────────────────────


@pytest.fixture
def state_with_full_context(anomaly_state):
    """Day 1·6·7 결과 모두 mock (DoD 검증용)."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    rng = np.random.default_rng(42)
    n = 1000
    n_anom = 50

    scores_normal = rng.normal(0.3, 0.1, n - n_anom)
    scores_anom = rng.normal(0.85, 0.05, n_anom)
    scores = np.concatenate([scores_normal, scores_anom])
    y_true = np.concatenate([np.zeros(n - n_anom), np.ones(n_anom)])
    idx = rng.permutation(n)
    scores, y_true = scores[idx], y_true[idx]

    # ★ X-3/X-6 ①: per-row + metrics = state.eval_result (top-level)
    state.eval_result = {
        "ensemble_scores": scores,
        "threshold": 0.7,
        "predicted_anomalies": (scores > 0.7).astype(bool),
        "auc": 0.92,
        "pr_at_10": 0.85,
        "pr_auc": 0.88,
        "f1": 0.78,
        "threshold_curve_path": "minio://test/threshold_curve.png",
    }
    state.data_profile = {
        "contamination_estimate": 0.05,
        "permutation_importance_per_dim": {
            "amount": 0.65,
            "freq": 0.42,
            "elapsed": 0.28,
        },
    }
    state.user_intent = "fraud detection"
    state.job_id = "test_job_42"
    return state


@pytest.fixture
def state_without_pipeline(anomaly_state):
    """Day 6 결과 없음 — fallback 기본 검증용."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.eval_result = {}
    state.data_profile = {"contamination_estimate": 0.05}
    state.job_id = "test_no_pipeline"
    return state


@pytest.fixture
def state_no_predictions(anomaly_state):
    """Day 6 있지만 predicted_anomalies 모두 False."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.eval_result = {
        "ensemble_scores": np.zeros(500),
        "predicted_anomalies": np.zeros(500).astype(bool),
        "threshold": 0.5,
    }
    state.data_profile = {
        "contamination_estimate": 0.05,
        "permutation_importance_per_dim": {"amount": 0.5},
    }
    state.job_id = "test_no_pred"
    return state


@pytest.fixture
def state_no_permutation(anomaly_state):
    """Day 1 permutation_importance 없음."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.eval_result = {
        "ensemble_scores": np.array([0.8, 0.9, 0.3]),
        "predicted_anomalies": np.array([True, True, False]),
        "threshold": 0.5,
    }
    state.data_profile = {"contamination_estimate": 0.05}
    state.job_id = "test_no_perm"
    return state


# === A. 스키마 ====================================================


def test_generate_returns_string(state_with_full_context):
    """#1 — generate → str 반환."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_with_full_context)
    assert isinstance(result, str)
    assert len(result) > 0


def test_prompt_payload_returns_dict(state_with_full_context):
    """#2 — prompt_payload → dict + 필수 키."""
    from agents.handlers.anomaly.insight import prompt_payload

    payload = prompt_payload(state_with_full_context)
    assert isinstance(payload, dict)
    for key in ("category", "top_n_anomalies", "top_features", "contamination_estimate", "auc"):
        assert key in payload


# === B. 정확성 ====================================================


def test_generate_contains_sigma_format(state_with_full_context):
    """#3 ★ DoD — '거래 #X 가 Y 평균 대비 Nσ 벗어남' 형식."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_with_full_context)
    pattern = r"거래 #\d+ 가 .+ 평균 대비 [\d.]+σ"
    assert re.search(pattern, result), f"DoD 형식 미발견: {result}"


def test_generate_3_to_5_sentences(state_with_full_context):
    """#4 Contract Day — 3~5 문장."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_with_full_context)
    sentences = [s for s in result.split(".") if s.strip()]
    assert 3 <= len(sentences) <= 5, f"3~5 문장 위반: {len(sentences)} 문장"


def test_generate_includes_top_feature(state_with_full_context):
    """#5 Contract Day — top3 피처 1+ 언급."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_with_full_context)
    top_features = ["amount", "freq", "elapsed"]
    assert any(f in result for f in top_features), f"top3 피처 미언급: {result}"


# === D. 분기 ======================================================


def test_no_pipeline_returns_fallback_default(state_without_pipeline):
    """#6 — Day 6 결과 없음 → 한국어 기본 메시지."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_without_pipeline)
    assert isinstance(result, str) and len(result) > 0
    assert any(0xAC00 <= ord(c) <= 0xD7A3 for c in result)


def test_no_predictions_returns_default(state_no_predictions):
    """#7 — predicted_anomalies 모두 False → 한국어 기본 + '거래' 사례 없음."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_no_predictions)
    assert isinstance(result, str) and len(result) > 0
    # 한국어 포함
    assert any(0xAC00 <= ord(c) <= 0xD7A3 for c in result)


# === E. 엣지 ======================================================


def test_empty_state_handled(anomaly_state):
    """#8 — 빈 state → exception X + 한국어."""
    from copy import deepcopy

    from agents.handlers.anomaly.insight import generate

    state = deepcopy(anomaly_state)
    state.category_extras = {}
    state.data_profile = None

    result = generate(state)
    assert isinstance(result, str) and len(result) > 0


def test_no_permutation_importance_handled(state_no_permutation):
    """#9 — Day 1 permutation 없음 → top_features=[] 가능."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_no_permutation)
    assert isinstance(result, str) and len(result) > 0


# === F. 회귀 ======================================================


def test_top_n_anomalies_helper(state_with_full_context):
    """#10 — _extract_top_n_anomalies 헬퍼 단위."""
    from agents.handlers.anomaly.insight import _extract_top_n_anomalies

    top_n = _extract_top_n_anomalies(state_with_full_context, n=5)
    assert isinstance(top_n, list)
    assert len(top_n) <= 5
    if top_n:
        for item in top_n:
            assert "idx" in item and "score" in item
            assert isinstance(item["idx"], int)
            assert isinstance(item["score"], float)
        # 내림차순 정렬 확인
        scores = [item["score"] for item in top_n]
        assert scores == sorted(scores, reverse=True)


def test_korean_only_unicode(state_with_full_context):
    """#11 ★ 한국어 강제 (CLAUDE.md Day 8 한국어 강제 룰)."""
    from agents.handlers.anomaly.insight import generate

    result = generate(state_with_full_context)
    korean_chars = sum(1 for c in result if 0xAC00 <= ord(c) <= 0xD7A3)
    assert korean_chars >= 10, f"한국어 문자 부족: {korean_chars}개"

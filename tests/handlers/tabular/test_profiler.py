"""jh 단독 — tabular profiler 단위 테스트."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.handlers.tabular.profiler import profile

# ──────────────────────────────────────────────
# class_imbalance_ratio
# ──────────────────────────────────────────────


def test_class_imbalance_ratio_present(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    assert "class_imbalance_ratio" in extra
    assert extra["class_imbalance_ratio"] >= 1.0


def test_class_imbalance_ratio_balanced():
    """50:50 데이터 → imbalance ≈ 1.0."""
    from ada.core.state import PipelineState

    df = pd.DataFrame({"x": range(100), "y": [0] * 50 + [1] * 50})
    state = PipelineState(
        job_id="test-bal",
        file_id="test",
        category="tabular_ml",
        target_column="y",
    )
    extra = profile(df, state)
    assert extra["class_imbalance_ratio"] == pytest.approx(1.0, abs=0.01)


def test_class_imbalance_ratio_skewed():
    """90:10 데이터 → imbalance ≈ 9.0."""
    from ada.core.state import PipelineState

    df = pd.DataFrame({"x": range(100), "y": [0] * 90 + [1] * 10})
    state = PipelineState(
        job_id="test-skew",
        file_id="test",
        category="tabular_ml",
        target_column="y",
    )
    extra = profile(df, state)
    assert extra["class_imbalance_ratio"] == pytest.approx(9.0, abs=0.1)


# ──────────────────────────────────────────────
# vif_top  ← DoD 필수 컬럼
# ──────────────────────────────────────────────


def test_vif_top_present(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    assert "vif_top" in extra, "DoD: vif_top 컬럼 반드시 존재"


def test_vif_top_keys_are_numeric_cols(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    assert set(extra["vif_top"].keys()) == {"Pclass", "Age", "Fare"}


def test_vif_top_values_are_positive(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    for col, v in extra["vif_top"].items():
        assert v > 0, f"{col} VIF 은 양수여야 함"


# ──────────────────────────────────────────────
# correlation_clusters
# ──────────────────────────────────────────────


def test_correlation_clusters_key_present(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    assert "correlation_clusters" in extra


def test_correlation_clusters_detects_high_corr():
    """완전 상관 컬럼 쌍 → 클러스터 1개 이상."""
    from ada.core.state import PipelineState

    rng = np.random.default_rng(42)
    base = rng.standard_normal(200)
    df = pd.DataFrame(
        {
            "a": base,
            "b": base * 2 + 0.01 * rng.standard_normal(200),  # a 와 거의 완전 상관
            "c": rng.standard_normal(200),  # 독립
            "target": rng.integers(0, 2, 200),
        }
    )
    state = PipelineState(
        job_id="test-corr",
        file_id="test",
        category="tabular_ml",
        target_column="target",
    )
    extra = profile(df, state)
    clusters = extra["correlation_clusters"]
    assert len(clusters) >= 1
    all_members = [col for members in clusters.values() for col in members]
    assert "a" in all_members and "b" in all_members


def test_correlation_clusters_no_high_corr():
    """독립 컬럼만 있을 때 → 클러스터 0개."""
    from ada.core.state import PipelineState

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "x1": rng.standard_normal(100),
            "x2": rng.standard_normal(100),
            "x3": rng.standard_normal(100),
            "y": rng.integers(0, 2, 100),
        }
    )
    state = PipelineState(
        job_id="test-nocorr",
        file_id="test",
        category="tabular_ml",
        target_column="y",
    )
    extra = profile(df, state)
    assert extra["correlation_clusters"] == {}


# ──────────────────────────────────────────────
# cardinality_levels
# ──────────────────────────────────────────────


def test_cardinality_levels_present(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    assert "cardinality_levels" in extra


def test_cardinality_levels_values(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    levels = extra["cardinality_levels"]
    # Pclass: 3종 → low, Age: >10종 → medium or high, Sex: 2종 → binary
    assert levels["Sex"] == "binary"
    assert levels["Pclass"] == "low"


def test_cardinality_levels_excludes_target(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    assert "Survived" not in extra["cardinality_levels"]


# ──────────────────────────────────────────────
# 예외 내성
# ──────────────────────────────────────────────


def test_profile_empty_df_no_crash(tab_state):
    df = pd.DataFrame()
    extra = profile(df, tab_state)
    assert isinstance(extra, dict)


def test_profile_no_target_column():
    """target_column=None 이어도 크래시 없음."""
    from ada.core.state import PipelineState

    df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
    state = PipelineState(
        job_id="test-notarget",
        file_id="test",
        category="tabular_ml",
        target_column=None,
    )
    extra = profile(df, state)
    assert isinstance(extra, dict)
    assert "class_imbalance_ratio" not in extra

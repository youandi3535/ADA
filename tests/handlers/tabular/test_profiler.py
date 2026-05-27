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


# ──────────────────────────────────────────────
# preprocessing_thresholds_suggested
# ──────────────────────────────────────────────


def test_preprocessing_thresholds_key_exists(tab_state, tab_df):
    extra = profile(tab_df, tab_state)
    assert "preprocessing_thresholds_suggested" in extra


def test_threshold_target_encoding_min_card_scales_with_n():
    """n=400 → min_card=20(floor), n=10000 → min_card=100."""
    from ada.core.state import PipelineState

    rng = np.random.default_rng(0)

    df_small = pd.DataFrame({"x": rng.standard_normal(400), "y": rng.integers(0, 2, 400)})
    state = PipelineState(job_id="t-enc-s", file_id="t", category="tabular_ml", target_column="y")
    t_small = profile(df_small, state)["preprocessing_thresholds_suggested"]
    assert t_small["target_encoding_min_card"] == 20  # sqrt(400)=20, max(20,20)=20

    df_large = pd.DataFrame({"x": rng.standard_normal(10000), "y": rng.integers(0, 2, 10000)})
    state2 = PipelineState(job_id="t-enc-l", file_id="t", category="tabular_ml", target_column="y")
    t_large = profile(df_large, state2)["preprocessing_thresholds_suggested"]
    assert t_large["target_encoding_min_card"] == 100  # sqrt(10000)=100


def test_threshold_id_col_unique_ratio_in_range(tab_state, tab_df):
    t = profile(tab_df, tab_state)["preprocessing_thresholds_suggested"]
    ratio = t["id_col_unique_ratio"]
    assert 0.5 < ratio < 0.95


def test_threshold_missing_drop_clipped():
    """결측 없는 데이터 → clip 하한 0.3 적용."""
    from ada.core.state import PipelineState

    df = pd.DataFrame({"a": range(100), "b": range(100), "y": [0] * 50 + [1] * 50})
    state = PipelineState(job_id="t-miss", file_id="t", category="tabular_ml", target_column="y")
    t = profile(df, state)["preprocessing_thresholds_suggested"]
    assert 0.3 <= t["missing_drop_threshold"] <= 0.9


def test_threshold_smote_entropy_is_constant(tab_state, tab_df):
    t = profile(tab_df, tab_state)["preprocessing_thresholds_suggested"]
    assert t["smote_imbalance_entropy_threshold"] == 0.85


def test_threshold_smote_mem_mb_positive(tab_state, tab_df):
    t = profile(tab_df, tab_state)["preprocessing_thresholds_suggested"]
    assert t["smote_max_synthetic_mem_mb"] > 0


def test_threshold_vif_switches_on_condition_number():
    """독립 컬럼 → vif_threshold=10.0, 강한 공선성 → 5.0."""
    from ada.core.state import PipelineState

    rng = np.random.default_rng(1)

    # 독립 — condition number 낮음
    df_indep = pd.DataFrame(
        {
            "a": rng.standard_normal(200),
            "b": rng.standard_normal(200),
            "c": rng.standard_normal(200),
            "d": rng.standard_normal(200),
            "e": rng.standard_normal(200),
            "y": rng.integers(0, 2, 200),
        }
    )
    state = PipelineState(job_id="t-vif-i", file_id="t", category="tabular_ml", target_column="y")
    t_indep = profile(df_indep, state)["preprocessing_thresholds_suggested"]
    assert t_indep["vif_threshold"] == 10.0

    # 강한 공선성 — condition number 높음
    base = rng.standard_normal(200)
    df_collinear = pd.DataFrame(
        {
            "a": base,
            "b": base + 0.001 * rng.standard_normal(200),
            "c": base * 2 + 0.001 * rng.standard_normal(200),
            "d": rng.standard_normal(200),
            "y": rng.integers(0, 2, 200),
        }
    )
    state2 = PipelineState(job_id="t-vif-c", file_id="t", category="tabular_ml", target_column="y")
    t_col = profile(df_collinear, state2)["preprocessing_thresholds_suggested"]
    assert t_col["vif_threshold"] == 5.0


def test_threshold_vif_max_drop_ratio_in_range(tab_state, tab_df):
    t = profile(tab_df, tab_state)["preprocessing_thresholds_suggested"]
    ratio = t["vif_max_drop_ratio"]
    assert 0 < ratio <= 0.3


def test_threshold_computed_with_metadata(tab_state, tab_df):
    t = profile(tab_df, tab_state)["preprocessing_thresholds_suggested"]
    meta = t["_computed_with"]
    for key in ("n_rows", "n_features", "available_ram_gb", "corr_condition_number"):
        assert key in meta

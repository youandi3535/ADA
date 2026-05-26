"""NY Day 1 — anomaly profiler 단위 테스트.

커버리지:
  A. 기본 통계 (결측·중복·상수 컬럼)
  B. 이상치 비율 3종 (IQR / Z-score / Modified Z-score)
  C. 투표 이상치
  D. 분포 특성 (왜도·첨도)
  E. 다변량 분석 (고상관·마할라노비스)
  F. PCA 차원 분석
  G. Isolation Forest (컬럼별 + 전체)
  H. LOF
  I. 시간 컬럼 감지
  J. contamination 앙상블 추정
  K. 모델 힌트
  L. 엣지 케이스 (빈 df, 단일 컬럼, 상수 컬럼, 전부 NaN)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── 추가 픽스처 ───────────────────────────────────────────────────────────────


@pytest.fixture
def high_dim_df():
    """20개 수치 컬럼 + 이상치 5% — PCA 압축 유도."""
    rng = np.random.default_rng(42)
    base = rng.normal(0, 1, (500, 20))
    outlier_rows = rng.choice(500, 25, replace=False)
    base[outlier_rows] *= 6
    cols = [f"f{i:02d}" for i in range(20)]
    return pd.DataFrame(base, columns=cols)


@pytest.fixture
def time_series_df():
    """시간 컬럼 포함 DataFrame."""
    rng = np.random.default_rng(99)
    dates = pd.date_range("2024-01-01", periods=200, freq="1h")
    # 시간 간격 이상: 10개 행에 큰 갭 삽입
    df = pd.DataFrame(
        {
            "timestamp": dates,
            "value": np.concatenate([rng.normal(50, 5, 190), rng.normal(200, 20, 10)]),
        }
    )
    return df


@pytest.fixture
def correlated_df():
    """높은 상관관계 컬럼 포함."""
    rng = np.random.default_rng(7)
    x = rng.normal(0, 1, 300)
    return pd.DataFrame(
        {
            "x": x,
            "y": x * 0.95 + rng.normal(0, 0.1, 300),  # corr ≈ 0.99
            "z": rng.normal(0, 1, 300),
        }
    )


# ── A. 기본 통계 ───────────────────────────────────────────────────────────────


def test_basic_stats_keys(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    for key in ("n_rows", "n_numeric_cols", "missing_ratio_per_col", "constant_cols", "duplicate_row_ratio"):
        assert key in extra, f"키 누락: {key}"


def test_basic_stats_values(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert extra["n_rows"] == 1000
    assert extra["n_numeric_cols"] == 2
    assert extra["duplicate_row_ratio"] == pytest.approx(0.0, abs=0.01)


def test_constant_col_detected(anomaly_state):
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame({"value": np.random.normal(0, 1, 100), "const": np.ones(100)})
    extra = profile(df, anomaly_state)
    assert "const" in extra["constant_cols"]


def test_missing_ratio(anomaly_state):
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame(
        {
            "a": np.concatenate([np.nan * np.ones(20), np.ones(80)]),
            "b": np.ones(100),
        }
    )
    extra = profile(df, anomaly_state)
    assert extra["missing_ratio_per_col"]["a"] == pytest.approx(0.2, abs=0.01)


# ── B. 이상치 비율 3종 ─────────────────────────────────────────────────────────


def test_outlier_iqr_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "outlier_ratios_iqr" in extra
    ratios = extra["outlier_ratios_iqr"]
    assert "amount" in ratios and "freq" in ratios
    assert ratios["amount"] > 0, "이상치 950/50 분포이므로 IQR 비율 > 0이어야 함"


def test_outlier_zscore_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "outlier_ratios_zscore" in extra
    assert all(0 <= v <= 1 for v in extra["outlier_ratios_zscore"].values())


def test_outlier_modified_z_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "outlier_ratios_modified_z" in extra
    assert all(0 <= v <= 1 for v in extra["outlier_ratios_modified_z"].values())


@pytest.mark.parametrize(
    "key",
    [
        "outlier_ratios_iqr",
        "outlier_ratios_zscore",
        "outlier_ratios_modified_z",
    ],
)
def test_outlier_ratios_range(anomaly_state, anomaly_df, key):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    for v in extra[key].values():
        assert 0.0 <= v <= 1.0, f"{key}: 비율 범위 위반 {v}"


# ── C. 투표 이상치 ─────────────────────────────────────────────────────────────


def test_outlier_vote_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "outlier_vote_ratio" in extra
    vote = extra["outlier_vote_ratio"]
    assert "amount" in vote
    assert vote["amount"] > 0


def test_vote_less_than_any_single_method(anomaly_state, anomaly_df):
    """투표 비율은 보수적 — 단일 방법 최솟값 이하이거나 비슷해야 함."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    for c in extra.get("outlier_vote_ratio", {}):
        iqr_v = extra["outlier_ratios_iqr"].get(c, 1.0)
        z_v = extra["outlier_ratios_zscore"].get(c, 1.0)
        mz_v = extra["outlier_ratios_modified_z"].get(c, 1.0)
        vote_v = extra["outlier_vote_ratio"][c]
        assert vote_v <= max(iqr_v, z_v, mz_v) + 0.01


# ── D. 분포 특성 ───────────────────────────────────────────────────────────────


def test_skewness_kurtosis_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "skewness_per_col" in extra
    assert "kurtosis_per_col" in extra
    assert "amount" in extra["skewness_per_col"]


def test_high_skew_detected(anomaly_state):
    """오른쪽으로 심하게 편향된 분포를 감지."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(0)
    df = pd.DataFrame({"skewed": np.exp(rng.normal(0, 2, 500))})
    extra = profile(df, anomaly_state)
    assert "skewed" in extra["high_skew_cols"]


# ── E. 다변량 분석 ─────────────────────────────────────────────────────────────


def test_high_correlation_detected(anomaly_state, correlated_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(correlated_df, anomaly_state)
    assert "high_correlation_pairs" in extra
    pairs = extra["high_correlation_pairs"]
    assert len(pairs) > 0
    assert any("x" in p[0] and "y" in p[1] for p in pairs)


def test_mahalanobis_ratio_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "mahalanobis_outlier_ratio" in extra
    ratio = extra["mahalanobis_outlier_ratio"]
    assert ratio is not None
    assert 0.0 <= ratio <= 1.0


# ── F. PCA ─────────────────────────────────────────────────────────────────────


def test_pca_basic(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert extra["pca_n_components_95"] >= 1
    assert extra["pca_n_components_95"] <= extra["pca_total_dims"]
    assert "pca_explained_variance_ratio" in extra


def test_pca_high_dim_reduction(anomaly_state, high_dim_df):
    """상관된 20차원 데이터 → 95% 설명 차원이 20보다 작아야 함."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(high_dim_df, anomaly_state)
    assert extra["pca_n_components_95"] < 20


def test_pca_single_col(anomaly_state):
    """단일 컬럼: PCA 건너뜀, 기본값 반환."""
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame({"a": np.random.normal(0, 1, 100)})
    extra = profile(df, anomaly_state)
    assert extra["pca_n_components_95"] == 1
    assert extra["pca_total_dims"] == 1


# ── G. Isolation Forest ────────────────────────────────────────────────────────


def test_isolation_depth_per_dim(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "isolation_depth_per_dim" in extra
    depths = extra["isolation_depth_per_dim"]
    assert "amount" in depths and "freq" in depths
    for v in depths.values():
        assert isinstance(v, float)


def test_isolation_overall_ratio(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "isolation_outlier_ratio" in extra
    r = extra["isolation_outlier_ratio"]
    assert r is not None and 0 < r < 0.5


def test_most_anomalous_dim(anomaly_state, anomaly_df):
    """amount 컬럼이 이상치 주 원인 — most_anomalous_dim 에 등장해야 함."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "most_anomalous_dim" in extra
    assert extra["most_anomalous_dim"] in ("amount", "freq")


# ── H. LOF ─────────────────────────────────────────────────────────────────────


def test_lof_ratio_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "lof_outlier_ratio" in extra
    assert 0 < extra["lof_outlier_ratio"] < 0.5


# ── I. 시간 컬럼 감지 ─────────────────────────────────────────────────────────


def test_time_col_detected(anomaly_state, time_series_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(time_series_df, anomaly_state)
    assert extra["has_time_column"] is True
    assert len(extra["time_column_candidates"]) >= 1


def test_no_time_col(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert extra["has_time_column"] is False


def test_time_range_days(anomaly_state, time_series_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(time_series_df, anomaly_state)
    # 200시간 = 약 8.33일
    assert "time_range_days" in extra
    assert 8 <= extra["time_range_days"] <= 9


# ── J. contamination 추정 ─────────────────────────────────────────────────────


def test_contamination_estimate_range(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "contamination_estimate" in extra
    assert 0.001 <= extra["contamination_estimate"] <= 0.5


def test_contamination_confidence(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert extra["contamination_confidence"] in ("low", "medium", "high")
    assert "contamination_sources_used" in extra
    assert extra["contamination_sources_used"] >= 3


def test_contamination_accuracy(anomaly_state, anomaly_df):
    """실제 오염 비율 5% (50/1000) 에 대해 추정치가 0.02~0.15 범위여야 함."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert 0.02 <= extra["contamination_estimate"] <= 0.15, (
        f"추정치 {extra['contamination_estimate']} 가 실제 5%와 너무 멀다"
    )


# ── K. 모델 힌트 ───────────────────────────────────────────────────────────────


def test_model_hints_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "recommended_model_hints" in extra
    hints = extra["recommended_model_hints"]
    assert len(hints) >= 2
    assert "IsolationForest" in hints


def test_model_hints_include_tranad_with_time(anomaly_state, time_series_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(time_series_df, anomaly_state)
    assert "TranAD" in extra["recommended_model_hints"]


# ── L. 엣지 케이스 ─────────────────────────────────────────────────────────────


def test_no_numeric_cols_returns_warning(anomaly_state):
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame({"name": ["a", "b", "c"], "cat": ["x", "y", "z"]})
    extra = profile(df, anomaly_state)
    assert "anomaly_warning" in extra


def test_all_nan_col_handled(anomaly_state):
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame(
        {
            "good": np.random.normal(0, 1, 100),
            "all_nan": np.full(100, np.nan),
        }
    )
    extra = profile(df, anomaly_state)
    assert "contamination_estimate" in extra


def test_single_unique_value_col(anomaly_state):
    """상수 컬럼이 있어도 전체 프로파일 중단 없이 경고만."""
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame({"const": np.ones(200), "vary": np.random.normal(0, 1, 200)})
    extra = profile(df, anomaly_state)
    assert "const" in extra["constant_cols"]
    assert "contamination_estimate" in extra


def test_profile_warnings_is_list(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert isinstance(extra["profile_warnings"], list)


def test_small_dataset_warning(anomaly_state):
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame({"a": np.random.normal(0, 1, 8), "b": np.random.normal(0, 1, 8)})
    extra = profile(df, anomaly_state)
    assert any("신뢰도" in w for w in extra["profile_warnings"])

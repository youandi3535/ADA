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
            "y": x * 0.95 + rng.normal(0, 0.1, 300),
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
    assert ratios["amount"] > 0


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
        assert 0.0 <= v <= 1.0


# ── C. 투표 이상치 ─────────────────────────────────────────────────────────────


def test_outlier_vote_present(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "outlier_vote_ratio" in extra
    vote = extra["outlier_vote_ratio"]
    assert "amount" in vote
    assert vote["amount"] > 0


def test_vote_less_than_any_single_method(anomaly_state, anomaly_df):
    """투표 비율은 보수적 — 단일 방법 최댓값 이하."""
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
    from agents.handlers.anomaly.profiler import profile

    extra = profile(high_dim_df, anomaly_state)
    assert extra["pca_n_components_95"] < 20


def test_pca_single_col(anomaly_state):
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
    """실제 오염 5% (50/1000) → 추정치 0.02~0.15."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert 0.02 <= extra["contamination_estimate"] <= 0.15


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


# ── M. 재구현 회귀·견고함 보강 ────────────────────────────────────────────────


def test_reproducibility_same_seed(anomaly_state, anomaly_df):
    """같은 입력 두 번 → 같은 contamination_estimate."""
    from agents.handlers.anomaly.profiler import profile

    out1 = profile(anomaly_df.copy(), anomaly_state)
    out2 = profile(anomaly_df.copy(), anomaly_state)
    assert out1["contamination_estimate"] == out2["contamination_estimate"]
    assert out1["isolation_outlier_ratio"] == out2["isolation_outlier_ratio"]


def test_module_constants_present():
    """상수 외부 import 가능."""
    from agents.handlers.anomaly import profiler

    assert profiler.RANDOM_STATE == 42
    assert profiler.MAD_NORMAL_CONSTANT == 0.6745
    assert 0 < profiler.CONTAMINATION_MIN < profiler.CONTAMINATION_MAX <= 0.5


def test_no_numeric_returns_minimal_dict(anomaly_state):
    """수치 0 → anomaly_warning + 조기 종료."""
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame({"a": ["x", "y", "z"]})
    extra = profile(df, anomaly_state)
    assert "anomaly_warning" in extra
    assert extra["n_numeric_cols"] == 0
    assert "profile_warnings" in extra
    assert "contamination_estimate" not in extra


def test_rows_alias_equals_n_rows(anomaly_state, anomaly_df):
    """selector 호환 — rows == n_rows."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert extra["rows"] == extra["n_rows"]


def test_high_correlation_pairs_format(anomaly_state, correlated_df):
    """(col1, col2, float) tuple 형식."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(correlated_df, anomaly_state)
    pairs = extra["high_correlation_pairs"]
    for p in pairs:
        assert len(p) == 3
        assert isinstance(p[2], float)
        assert -1.0 <= p[2] <= 1.0


def test_isolation_depth_includes_all_numeric_cols(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    depths = extra["isolation_depth_per_dim"]
    assert set(depths.keys()) == {"amount", "freq"}


def test_pca_dim_reduction_flag_consistency(anomaly_state, high_dim_df):
    """n95 < total*0.8 일 때만 True."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(high_dim_df, anomaly_state)
    total = extra["pca_total_dims"]
    n95 = extra["pca_n_components_95"]
    expected = n95 < int(total * 0.8)
    assert extra["pca_dim_reduction_possible"] == expected


def test_model_hints_dedupe(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    hints = extra["recommended_model_hints"]
    assert len(hints) == len(set(hints))


def test_model_hints_iforest_first(anomaly_state, anomaly_df):
    """안전 디폴트 — IsolationForest 첫 번째."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert extra["recommended_model_hints"][0] == "IsolationForest"


def test_outlier_ratios_skip_constant_col(anomaly_state):
    """상수 컬럼 = outlier_ratios 안 들어감 (분산 0 스킵)."""
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame(
        {
            "const": np.ones(200),
            "vary": np.random.default_rng(0).normal(0, 1, 200),
        }
    )
    extra = profile(df, anomaly_state)
    assert "const" not in extra.get("outlier_ratios_iqr", {})
    assert "vary" in extra.get("outlier_ratios_iqr", {})


def test_mahalanobis_skipped_when_rows_lt_cols_plus_1(anomaly_state):
    """25행 × 30컬럼 → mahalanobis None."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 1, (25, 30)), columns=[f"c{i}" for i in range(30)])
    extra = profile(df, anomaly_state)
    assert extra.get("mahalanobis_outlier_ratio") is None


def test_time_column_via_object_dtype(anomaly_state):
    """object 날짜 문자열도 시간 컬럼 감지."""
    from agents.handlers.anomaly.profiler import profile

    dates = pd.date_range("2024-01-01", periods=100, freq="1h").strftime("%Y-%m-%d %H:%M:%S")
    df = pd.DataFrame(
        {
            "ts_str": dates.tolist(),
            "value": np.random.default_rng(1).normal(0, 1, 100),
        }
    )
    extra = profile(df, anomaly_state)
    assert extra["has_time_column"] is True
    assert "ts_str" in extra["time_column_candidates"]


def test_contamination_sources_used_increments_with_methods(anomaly_state, anomaly_df):
    """6 소스 모두 활성, sources_used ≥ 5."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert extra["contamination_sources_used"] >= 5


def test_pca_explained_variance_length_limited(anomaly_state, high_dim_df):
    """≤ 10 컴포넌트만 보관."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(high_dim_df, anomaly_state)
    assert len(extra["pca_explained_variance_ratio"]) <= 10


def test_returns_dict_type(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert isinstance(extra, dict)


def test_profile_warnings_strings(anomaly_state):
    """모든 원소 str."""
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame({"a": np.random.normal(0, 1, 8)})
    extra = profile(df, anomaly_state)
    for w in extra["profile_warnings"]:
        assert isinstance(w, str)


def test_no_pandas_deprecation_warning(anomaly_state, time_series_df, recwarn):
    """infer_datetime_format 미사용."""
    from agents.handlers.anomaly.profiler import profile

    profile(time_series_df, anomaly_state)
    bad = [w for w in recwarn.list if "infer_datetime_format" in str(w.message).lower()]
    assert not bad


# ── N. v2 패치 검증 (P1~P13) ──────────────────────────────────────────────────


def test_iqr_strict_key_present(anomaly_state, anomaly_df):
    """P1 — 3×IQR 키 + strict ≤ 1.5×IQR."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "outlier_ratios_iqr_strict" in extra
    strict = extra["outlier_ratios_iqr_strict"]
    iqr15 = extra["outlier_ratios_iqr"]
    for c in strict:
        assert strict[c] <= iqr15[c] + 1e-6


def test_zscore_unreliable_cols_detected(anomaly_state):
    """P2 — std » MAD 컬럼 감지."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "normal": rng.normal(0, 1, 1000),
            "spread": np.concatenate([rng.normal(0, 1, 800), rng.normal(0, 50, 200)]),
        }
    )
    extra = profile(df, anomaly_state)
    assert "zscore_unreliable_cols" in extra
    assert "spread" in extra["zscore_unreliable_cols"]


def test_modz_excludes_high_skew_in_contamination(anomaly_state):
    """P3 — high_skew → modz_unreliable 자동."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "skewed": np.exp(rng.normal(0, 2, 500)),
            "normal": rng.normal(0, 1, 500),
        }
    )
    extra = profile(df, anomaly_state)
    assert "skewed" in extra["high_skew_cols"]
    assert "skewed" in extra["modz_unreliable_cols"]


def test_mahalanobis_threshold_dynamic_present(anomaly_state, anomaly_df):
    """P4 — dynamic ≤ p975 (5% 오염)."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "mahalanobis_threshold_dynamic" in extra
    assert extra["mahalanobis_threshold_dynamic"] is not None
    assert extra["mahalanobis_threshold_dynamic"] <= extra["mahalanobis_threshold_p975"]


def test_pca_n_components_90_present(anomaly_state, high_dim_df):
    """P5 — n90 + last_pc_variance."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(high_dim_df, anomaly_state)
    assert "pca_n_components_90" in extra
    assert "last_pc_variance" in extra
    assert extra["pca_n_components_90"] <= extra["pca_n_components_95"]


def test_pca_reduction_stricter_v2(anomaly_state):
    """P5 — n90 ≤ n/2 AND last_pc < 0.05."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(0)
    df = pd.DataFrame(rng.normal(0, 1, (500, 5)), columns=[f"c{i}" for i in range(5)])
    extra = profile(df, anomaly_state)
    if extra.get("last_pc_variance", 0) >= 0.05:
        assert extra["pca_dim_reduction_possible"] is False


def test_contamination_method_field_present(anomaly_state, anomaly_df):
    """P7 → ★ V4 — 'consensus_weighted' (uni-median + IF/LOF 합의 게이트)."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "contamination_method" in extra
    if extra["contamination_sources_used"] >= 4:
        assert extra["contamination_method"] == "consensus_weighted"


def test_contamination_spread_present(anomaly_state, anomaly_df):
    """★ V4 — contamination_spread (소스 간 불일치 폭) ≥ 0."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "contamination_spread" in extra
    assert extra["contamination_spread"] >= 0.0


def test_contamination_breakdown_present(anomaly_state, anomaly_df):
    """P7 — 6 소스 breakdown dict."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    bd = extra["contamination_source_breakdown"]
    assert isinstance(bd, dict)
    expected_keys = {"iqr_mean", "zscore_mean", "modz_mean", "vote_mean", "if_ratio", "lof_ratio"}
    present = expected_keys & set(bd.keys())
    assert len(present) >= 4


def test_high_contamination_suspected_flag(anomaly_state):
    """P8 — bool 키 존재."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(pd.DataFrame({"a": np.random.default_rng(0).normal(0, 1, 200)}), anomaly_state)
    assert "high_contamination_suspected" in extra
    assert isinstance(extra["high_contamination_suspected"], bool)


def test_year_column_false_positive_risk(anomaly_state):
    """P9 — 연도-숫자 fp_risk 등록."""
    from agents.handlers.anomaly.profiler import profile

    df = pd.DataFrame(
        {
            "year_id": ["2020", "2021", "2022", "2023", "2024"] * 20,
            "value": np.random.default_rng(0).normal(0, 1, 100),
        }
    )
    extra = profile(df, anomaly_state)
    if "year_id" in extra["time_column_candidates"]:
        assert "year_id" in extra["time_column_false_positive_risk"]


def test_unix_epoch_int_detected(anomaly_state):
    """P11 — Unix epoch int 시간 감지."""
    from agents.handlers.anomaly.profiler import profile

    base = 1_704_067_200
    epochs = [base + i * 3600 for i in range(100)]
    df = pd.DataFrame(
        {
            "ts_int": epochs,
            "value": np.random.default_rng(0).normal(0, 1, 100),
        }
    )
    extra = profile(df, anomaly_state)
    assert extra["has_time_column"] is True
    assert "ts_int" in extra["time_column_candidates"]


def test_most_anomalous_dim_permutation_present(anomaly_state, anomaly_df):
    """P12 — permutation 키 + 정답 컬럼."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "most_anomalous_dim_permutation" in extra
    assert extra["most_anomalous_dim_permutation"] in ("amount", "freq")


def test_most_anomalous_dim_permutation_accuracy(anomaly_state):
    """P12 — A 컬럼만 이상 → A 정답."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(42)
    normal = rng.normal(0, 1, (950, 3))
    anom = rng.normal(0, 1, (50, 3))
    anom[:, 0] += 8
    df = pd.DataFrame(np.vstack([normal, anom]), columns=["A", "B", "C"])
    extra = profile(df, anomaly_state)
    assert extra["most_anomalous_dim_permutation"] == "A"


def test_most_anomalous_dim_confidence_field(anomaly_state, anomaly_df):
    """P13 — confidence 키 (high/medium/low)."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "most_anomalous_dim_confidence" in extra
    assert extra["most_anomalous_dim_confidence"] in ("high", "medium", "low")


def test_permutation_importance_per_dim_present(anomaly_state, anomaly_df):
    """P12 — 모든 수치 컬럼 importance."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "permutation_importance_per_dim" in extra
    perm = extra["permutation_importance_per_dim"]
    assert set(perm.keys()) == {"amount", "freq"}
    for v in perm.values():
        assert v >= 0


def test_contamination_accuracy_v2_improved(anomaly_state, anomaly_df):
    """v2 trimmed mean — 0.02~0.10."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert 0.02 <= extra["contamination_estimate"] <= 0.10


# === V3 보강 필드 (Day 1 설계 정합화) ============================


def test_v3_n_features_categorical_present(anomaly_state, anomaly_df):
    """V1 — int ≥ 0."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "n_features_categorical" in extra
    assert isinstance(extra["n_features_categorical"], int)
    assert extra["n_features_categorical"] >= 0


def test_v3_is_approximately_gaussian_present(anomaly_state, anomaly_df):
    """V2 — bool."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "is_approximately_gaussian" in extra
    assert isinstance(extra["is_approximately_gaussian"], bool)


def test_v3_intrinsic_dim_ratio_present(anomaly_state, anomaly_df):
    """V3 — [0,1]."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "intrinsic_dim_ratio" in extra
    assert 0.0 <= extra["intrinsic_dim_ratio"] <= 1.0


def test_v3_gaussian_flag_rejects_lognormal(anomaly_state):
    """V2 — LogNormal → False."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(42)
    df = pd.DataFrame({f"f{i}": rng.lognormal(0, 1, 500) for i in range(3)})
    extra = profile(df, anomaly_state)
    assert extra["is_approximately_gaussian"] is False


def test_v3_gaussian_flag_accepts_clean_gaussian(anomaly_state):
    """V2 — 정규 → True."""
    from agents.handlers.anomaly.profiler import profile

    rng = np.random.default_rng(42)
    df = pd.DataFrame({f"f{i}": rng.normal(0, 1, 500) for i in range(3)})
    extra = profile(df, anomaly_state)
    assert extra["is_approximately_gaussian"] is True


def test_v3_intrinsic_dim_ratio_correlated_data_compressible(anomaly_state, correlated_df):
    """V3 — 상관 데이터 → n95 < total."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(correlated_df, anomaly_state)
    assert extra["pca_n_components_95"] < extra["pca_total_dims"]
    assert extra["intrinsic_dim_ratio"] < 1.0


# === 서브카테고리 (판단기준 §부록 A, 2026-05-29) ===


def test_subcategory_fields_present(anomaly_state, anomaly_df):
    """eval_labels_available(bool) + anomaly_subcategory(C1~C4) 존재."""
    from agents.handlers.anomaly.profiler import profile

    extra = profile(anomaly_df, anomaly_state)
    assert "eval_labels_available" in extra
    assert "anomaly_subcategory" in extra
    assert isinstance(extra["eval_labels_available"], bool)
    assert extra["anomaly_subcategory"] in {"C1", "C2", "C3", "C4"}

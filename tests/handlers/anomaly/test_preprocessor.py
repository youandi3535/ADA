"""NY Day 2 — anomaly preprocessor 테스트 (13 케이스).

5 그룹 + 의심 신규 5:
  A 스키마 (#1·#2) — plan 메타 / 17 필드
  B 정확성 (#3·#4·#5) — scaler / limits / PCA 차원
  C 객체 보존 (#6) ★ DoD — RobustScaler + fit
  D Sanity (#7) — 행 수 보존
  E 엣지 (#8) — 상수 컬럼
  ★ 의심 신규 5 (#9·#10·#11 E-1·E-2·E-3 / #12 B-1 / #13 B-3)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── fixture 재정의 (pytest 파일별 격리 때문에) ────────────────────


@pytest.fixture
def high_dim_df():
    """20 차원 가우시안 — PCA 차원 축소 검증용."""
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        rng.normal(0, 1, (500, 20)),
        columns=[f"f{i:02d}" for i in range(20)],
    )


# === A. 스키마 검증 ===============================================

REQUIRED_KEYS = {
    "X_processed",
    "n_rows_in",
    "n_cols_in",
    "n_cols_out",
    "scaler",
    "winsor_limits",
    "pca",
    "feature_names_in",
    "dim_reduction_ratio",
    "pca_components_used",
    "applied_steps",
    "skipped_steps",
    "feature_names_out",
    "constant_cols_dropped",
    "nearly_constant_cols",
    "high_missing_cols_dropped",
    "inf_rows_dropped",
    "preprocessor_warnings",
}


def test_plan_returns_metadata(anomaly_state):
    """#1 — plan() 3 단계 메타 반환."""
    from agents.handlers.anomaly.preprocessor import plan

    steps = plan(anomaly_state)
    assert isinstance(steps, list)
    names = {s["name"] for s in steps}
    assert {"robust_scale", "winsorize", "pca"}.issubset(names)


def test_apply_returns_required_keys(anomaly_state, anomaly_df):
    """#2 — apply() 반환 17 필드 모두 존재."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    result = apply(anomaly_df, plan(anomaly_state), anomaly_state)
    assert REQUIRED_KEYS.issubset(result.keys())


# === B. 정확성 검증 ===============================================


def test_robust_scale_objects_persisted(anomaly_state, anomaly_df):
    """#3 — RobustScaler 가 fit 됨 (scale_ 속성)."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    result = apply(anomaly_df, plan(anomaly_state), anomaly_state)
    assert result["scaler"] is not None
    assert hasattr(result["scaler"], "scale_")


def test_winsorize_limits_applied(anomaly_state, anomaly_df):
    """#4 — winsor_limits 가 모든 컬럼에 (lo, hi) + lo<=hi."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    result = apply(anomaly_df, plan(anomaly_state), anomaly_state)
    assert len(result["winsor_limits"]) > 0
    for _col, (lo, hi) in result["winsor_limits"].items():
        assert lo <= hi


def test_pca_reduces_dimensions(anomaly_state, high_dim_df):
    """#5 — 20 차원 → PCA 후 n_cols_out ≤ 20."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    result = apply(high_dim_df, plan(anomaly_state), anomaly_state)
    assert result["n_cols_out"] <= result["n_cols_in"]
    assert 0.0 <= result["dim_reduction_ratio"] <= 1.0


# === C. 객체 보존 (DoD ★) ========================================


def test_scaler_object_persisted_and_fitted(anomaly_state, anomaly_df):
    """#6 ★ DoD — scaler 가 RobustScaler 인스턴스 + center_·scale_ 모두 존재."""
    from sklearn.preprocessing import RobustScaler

    from agents.handlers.anomaly.preprocessor import apply, plan

    result = apply(anomaly_df, plan(anomaly_state), anomaly_state)
    assert isinstance(result["scaler"], RobustScaler)
    assert hasattr(result["scaler"], "center_")
    assert hasattr(result["scaler"], "scale_")


# === D. Sanity ====================================================


def test_row_count_preserved(anomaly_state, anomaly_df):
    """#7 — Winsorize·PCA 모두 행 수 보존 (시계열 무결성)."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    result = apply(anomaly_df, plan(anomaly_state), anomaly_state)
    assert result["X_processed"].shape[0] == result["n_rows_in"]


# === E. 엣지 케이스 ===============================================


def test_constant_col_dropped(anomaly_state):
    """#8 — 상수 컬럼 (IQR=0) 자동 제외."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    df = pd.DataFrame(
        {
            "value": np.random.default_rng(0).normal(0, 1, 100),
            "const": np.ones(100),
        }
    )
    result = apply(df, plan(anomaly_state), anomaly_state)
    assert "const" in result["constant_cols_dropped"]


# === 의심 신규 5 ★ ================================================


def test_apply_transform_consistency(anomaly_state, anomaly_df):
    """#9 ★ E-1 — apply() = apply_transform() (학습/추론 일관성)."""
    from agents.handlers.anomaly.preprocessor import apply, apply_transform, plan

    result = apply(anomaly_df, plan(anomaly_state), anomaly_state)
    X_again = apply_transform(anomaly_df, result)
    np.testing.assert_allclose(result["X_processed"], X_again, rtol=1e-9)


def test_apply_transform_handles_column_reorder(anomaly_state, anomaly_df):
    """#10 ★ E-2 — 컬럼 순서 다른 새 데이터 처리."""
    from agents.handlers.anomaly.preprocessor import apply, apply_transform, plan

    result = apply(anomaly_df, plan(anomaly_state), anomaly_state)
    df_reordered = anomaly_df[anomaly_df.columns[::-1]]
    X = apply_transform(df_reordered, result)
    assert X.shape == result["X_processed"].shape


def test_apply_transform_with_pca_skip(anomaly_state):
    """#11 ★ E-3 — 단일 컬럼 시 PCA skip + None 가드."""
    from agents.handlers.anomaly.preprocessor import apply, apply_transform, plan

    rng = np.random.default_rng(0)
    df = pd.DataFrame({"only": rng.normal(0, 1, 100)})
    result = apply(df, plan(anomaly_state), anomaly_state)
    assert result["pca"] is None
    X = apply_transform(df, result)
    assert X.shape[0] > 0


def test_nearly_constant_col_warned(anomaly_state):
    """#12 ★ B-1 — 거의-상수 컬럼이 메타에 등장 (drop 안 됨)."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "normal": rng.normal(0, 1, 100),
            "nearly_const": [1.0] * 97 + [2.0, 3.0, 4.0],
        }
    )
    result = apply(df, plan(anomaly_state), anomaly_state)
    assert "nearly_const" in result["nearly_constant_cols"]
    assert "nearly_const" not in result["constant_cols_dropped"]


def test_apply_handles_inf_values(anomaly_state):
    """#13 ★ B-3 — inf 행 자동 제거 + 메타 기록."""
    from agents.handlers.anomaly.preprocessor import apply, plan

    rng = np.random.default_rng(0)
    df = pd.DataFrame(
        {
            "a": rng.normal(0, 1, 100),
            "b": rng.normal(0, 1, 100),
        }
    )
    df.iloc[5, 0] = np.inf
    df.iloc[10, 1] = -np.inf
    result = apply(df, plan(anomaly_state), anomaly_state)
    assert result["inf_rows_dropped"] >= 2

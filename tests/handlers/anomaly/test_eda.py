"""NY Day 3 — anomaly eda 단위 테스트 (9 케이스).

5 그룹:
  A 스키마 (#1·#2)
  B 정확성 (#3·#4·#5)
  D 분기 (#6·#7)
  E 엣지 (#8·#9)

mock 핵심: save_chart_to_minio 를 autouse fixture 로 자동 주입.
실제 MinIO 호출 X. plt.close(fig) 강제 (메모리 누수 방지).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── 모든 test 공통 mock ───────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_minio_upload(monkeypatch):
    """save_chart_to_minio 자동 mock — 실제 업로드 X."""

    def fake_upload(fig, kind, job_id):
        import matplotlib.pyplot as plt

        plt.close(fig)
        return f"minio://test/{kind}/{job_id}.png"

    monkeypatch.setattr(
        "agents.handlers.common.shared.save_chart_to_minio",
        fake_upload,
    )


# ── Day 3 전용 fixture ────────────────────────────────────────────


@pytest.fixture
def anomaly_state_with_time(anomaly_state):
    """시간 컬럼 있는 state — ③ 차트 검증용."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "has_time_column": True,
        # profiler 는 time_column_candidates(list) 를 내보낸다 (eda 가 읽는 정식 키)
        "time_column": "timestamp",
        "time_column_candidates": ["timestamp"],
        "isolation_depth_per_dim": {"amount": 0.5, "freq": 0.3},
    }
    return state


@pytest.fixture
def anomaly_df_with_time():
    """시간 컬럼 포함 df."""
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=200, freq="1h"),
            "amount": rng.normal(100, 10, 200),
            "freq": rng.normal(5, 1, 200),
        }
    )


@pytest.fixture
def anomaly_state_with_day2(anomaly_state, anomaly_df):
    """Day 2 mock 결과 포함 state — ② PCA 산점 검증용."""
    from copy import deepcopy

    from sklearn.decomposition import PCA
    from sklearn.preprocessing import RobustScaler

    state = deepcopy(anomaly_state)
    num = anomaly_df.select_dtypes(include=[np.number])
    X = RobustScaler().fit_transform(num.values)
    pca = PCA(n_components=2, random_state=42).fit(X)
    X_pca = pca.transform(X)

    state.category_extras = {
        "anomaly": {
            "preprocessing": {
                "X_processed": X_pca,
                "pca": pca,
                "scaler": RobustScaler().fit(num.values),
                "feature_names_in": num.columns.tolist(),
                "winsor_limits": {},
                "n_cols_out": 2,
                "n_cols_in": 2,
                "constant_cols_dropped": [],
                "high_missing_cols_dropped": [],
            }
        }
    }
    state.data_profile = {
        "isolation_depth_per_dim": {"amount": 0.5, "freq": 0.3},
    }
    return state


# === A. 스키마 ====================================================


def test_charts_returns_list_of_str(anomaly_state, anomaly_df):
    """#1 — list[str] 시그니처 보장."""
    from agents.handlers.anomaly.eda import charts

    result = charts(anomaly_df, anomaly_state)
    assert isinstance(result, list)
    assert all(isinstance(p, str) for p in result)


def test_charts_max_three_paths(anomaly_state, anomaly_df):
    """#2 — DoD '3 종' 상한."""
    from agents.handlers.anomaly.eda import charts

    result = charts(anomaly_df, anomaly_state)
    assert len(result) <= 3


# === B. 정확성 ====================================================


def test_feature_distribution_chart_created(anomaly_state, anomaly_df):
    """#3 — ① 차트 생성."""
    from agents.handlers.anomaly.eda import charts

    result = charts(anomaly_df, anomaly_state)
    assert any("feature_dist" in p for p in result)


def test_pca_scatter_chart_created(anomaly_state_with_day2, anomaly_df):
    """#4 — ② 차트 (Day 2 결과 사용)."""
    from agents.handlers.anomaly.eda import charts

    result = charts(anomaly_df, anomaly_state_with_day2)
    assert any("pca_scatter" in p for p in result)


def test_time_anomaly_chart_created(anomaly_state_with_time, anomaly_df_with_time):
    """#5 — ③ 시간축 anomaly (★ D2 미니 IForest)."""
    from agents.handlers.anomaly.eda import charts

    result = charts(anomaly_df_with_time, anomaly_state_with_time)
    assert any("time_anomaly" in p for p in result)


# === D. 분기 ======================================================


def test_pca_scatter_fallback_uses_top2_isolation_dims(anomaly_state, anomaly_df):
    """#6 ★ D6 — PCA skip 시 fallback 동작."""
    from copy import deepcopy

    from agents.handlers.anomaly.eda import charts

    state = deepcopy(anomaly_state)
    state.category_extras = {
        "anomaly": {
            "preprocessing": {
                "X_processed": None,
                "pca": None,
                "scaler": None,
                "winsor_limits": {},
            }
        }
    }
    state.data_profile = {
        "isolation_depth_per_dim": {"amount": 0.5, "freq": 0.3},
    }
    result = charts(anomaly_df, state)
    assert any("pca_scatter_fallback" in p for p in result)


def test_no_time_column_skips_third_chart(anomaly_state, anomaly_df):
    """#7 — 시간 컬럼 없으면 ③ skip."""
    from agents.handlers.anomaly.eda import charts

    result = charts(anomaly_df, anomaly_state)
    assert not any("time_anomaly" in p for p in result)


# === E. 엣지 ======================================================


def test_no_numeric_cols_returns_empty(anomaly_state):
    """#8 — 수치 0 컬럼 → 빈 list."""
    from agents.handlers.anomaly.eda import charts

    df = pd.DataFrame({"only_str": ["a", "b", "c", "d", "e"]})
    result = charts(df, anomaly_state)
    assert len(result) == 0


def test_chart_exception_does_not_break_pipeline(anomaly_state, anomaly_df, monkeypatch):
    """#9 — 한 차트 실패해도 나머지 진행."""
    from agents.handlers.anomaly import eda

    def broken_chart(*args, **kwargs):
        raise ValueError("simulated failure")

    monkeypatch.setattr(eda, "_chart_feature_distribution", broken_chart)

    # 에러 전파 안 됨
    result = eda.charts(anomaly_df, anomaly_state)
    assert isinstance(result, list)
    # ① 차트는 실패했지만 ② ③ skip (anomaly_state 에 Day 2 결과·시간 컬럼 없음)
    # → 결과 list 길이 0 또는 정상 진행 확인

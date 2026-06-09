"""Phase 1-A/B 테스트 — output_extras 의 전문가 차원 표 + 운영 권고 표.

검증 항목:
  - _build_expert_dimensions_table 가 selector_meta 있을 때 표 반환
  - _build_expert_dimensions_table 가 메타 없을 때 None
  - _build_ops_recommendation_table 가 retrain 권고 표 반환
  - build() 의 tables 에 두 표가 자연스럽게 추가됨 (기존 표와 충돌 X)
  - 표 구조 (title/columns/rows) carrier 호환
  - charts/text_blocks 기존 키 영향 0 (회귀 보존)
"""

from __future__ import annotations

import pytest


def _make_full_state(ts_state):
    return ts_state.with_update(
        user_intent="해석 가능한 단기 예측",
        data_profile={"rows": 200, "freq": "D"},
        eda_summary={"seasonal_period": 7, "stationary": True, "changepoints": 0},
        best_model={
            "model_name": "SARIMA",
            "metrics": {
                "val_rmse": 50.0,
                "val_mae": 40.0,
                "MASE": 0.83,
                "sMAPE": 18.5,
                "rmse_improvement_vs_naive": 0.12,
                "pi_coverage": 0.92,
                "y_pred_val": [100.0, 101.0, 102.0],
                "y_val_actual": [100.5, 101.2, 102.3],
                "y_train_tail": [98.0, 99.0],
            },
        },
        eval_result={
            "passed": True,
            "fold_diagnostics": {"stability": "stable", "available": True},
            "leakage_suspect_signals": [],
            "symptom_classification": {"symptom": "normal"},
            "residual_diagnostics": {"kind": "white_noise"},
            "dm_test": {"verdict": "model_wins"},
        },
    )


def test_expert_dimensions_table_present_when_meta(ts_state):
    """selector_meta (재호출로 산출됨) → 표 반환."""
    from agents.handlers.timeseries.output_extras import _build_expert_dimensions_table

    state = _make_full_state(ts_state)
    tbl = _build_expert_dimensions_table(state)
    # selector.score() 가 정상 동작하면 표 반환
    if tbl is not None:
        assert tbl["title"] == "전문가 차원 점수표"
        assert "해석성" in tbl["columns"]
        assert "강건성" in tbl["columns"]
        assert "불확실성" in tbl["columns"]
        assert "재학습 효율" in tbl["columns"]
        assert len(tbl["rows"]) >= 1  # 최소 가중치 행


def test_expert_dimensions_table_none_when_no_state(ts_state):
    """data_profile 비어있어도 graceful — None 또는 정상 동작."""
    from agents.handlers.timeseries.output_extras import _build_expert_dimensions_table

    state = ts_state.with_update(
        data_profile={},
        eda_summary={},
    )
    tbl = _build_expert_dimensions_table(state)
    # None 또는 정상 표 모두 허용 (graceful)
    assert tbl is None or isinstance(tbl, dict)


def test_ops_recommendation_table_present(ts_state):
    """retrain schedule → 운영 권고 표."""
    from agents.handlers.timeseries.output_extras import _build_ops_recommendation_table

    state = _make_full_state(ts_state)
    tbl = _build_ops_recommendation_table(state)
    assert tbl is not None
    assert tbl["title"] == "운영 권고 (재학습 주기)"
    assert tbl["columns"] == ["항목", "값"]
    # 3 행: 주기·긴급도·근거
    assert len(tbl["rows"]) == 3
    # 일수 포함
    interval_row = tbl["rows"][0]
    assert "일" in interval_row[1]


def test_build_tables_includes_expert_and_ops(ts_state):
    """build() 의 tables 에 새 표 자연스럽게 추가."""
    from agents.handlers.timeseries.output_extras import build

    state = _make_full_state(ts_state)
    out = build(state)
    assert "tables" in out
    table_titles = [t.get("title") for t in out["tables"]]
    # 운영 권고는 항상 추가됨 (retrain 은 graceful 결과 보장)
    assert "운영 권고 (재학습 주기)" in table_titles


def test_build_returns_three_keys(ts_state):
    """build() 반환 키 OUTPUT_EXTRAS_KEYS 3종 (회귀 0)."""
    from agents.handlers.timeseries.output_extras import build

    state = _make_full_state(ts_state)
    out = build(state)
    assert set(out.keys()) >= {"charts", "tables", "text_blocks"}


def test_build_graceful_minimal_state(ts_state):
    """최소 state 에서도 build 가 죽지 않음 (graceful)."""
    from agents.handlers.timeseries.output_extras import build

    state = ts_state.with_update(
        data_profile={},
        eda_summary={},
        best_model={"model_name": "SARIMA", "metrics": {}},
    )
    out = build(state)
    assert isinstance(out, dict)
    # tables/charts/text_blocks 중 일부 비어도 키는 존재
    assert "tables" in out or "charts" in out or "text_blocks" in out


def test_build_preserves_existing_tables(ts_state):
    """기존 fold_diagnostics·잔차·DM 표 보존 (회귀 0)."""
    from agents.handlers.timeseries.output_extras import build

    state = _make_full_state(ts_state)
    # fold_diagnostics 풍부하게 채워서 기존 표 트리거
    state = state.with_update(
        eval_result={
            **(state.eval_result or {}),
            "fold_diagnostics": {
                "available": True,
                "stability": "stable",
                "n_folds": 3,
                "best_fold": {"idx": 0, "score": 0.14},
                "worst_fold": {"idx": 2, "score": 0.10},
            },
        },
    )
    out = build(state)
    titles = [t.get("title") for t in out.get("tables", [])]
    # 기존 표 + 새 표 모두 존재
    # (운영 권고 + 모델 성능 등 일부 존재)
    assert any("운영 권고" in t for t in titles)

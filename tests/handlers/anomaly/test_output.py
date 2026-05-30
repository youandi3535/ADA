"""NY Day 9 — anomaly output_extras 단위 테스트 (12 케이스).

5 그룹:
  A 스키마 (#1·#2·#3) ★ #2·#3 시그니처 양쪽 호환 (E-1)
  B 정확성 (#4·#5·#6) ★ #4 top_n_table · #5 σ
  D 분기 (#7·#8)
  E 엣지 (#9·#10)
  F 회귀 (#11·#12)

LLM·matplotlib 호출 없음 (NY handler R-004 + 차트 재사용).
Day 1·6·7 mock + eda_charts. Day 8 insight 헬퍼 재사용.
"""

from __future__ import annotations

import re
from copy import deepcopy

import numpy as np
import pytest

# ── Day 9 전용 fixture ────────────────────────────────────────────


@pytest.fixture
def state_full(anomaly_state):
    """Day 1·6·7 결과 + eda_charts + threshold_curve_path mock."""
    state = deepcopy(anomaly_state)
    rng = np.random.default_rng(42)
    n, n_anom = 1000, 50
    scores = np.concatenate([rng.normal(0.3, 0.1, n - n_anom), rng.normal(0.85, 0.05, n_anom)])
    predicted = (scores > 0.7).astype(bool)
    state.category_extras = {
        "anomaly": {
            "pipeline": {
                "ensemble_scores": scores,
                "predicted_anomalies": predicted,
                "threshold": 0.7,
            },
            "evaluation": {
                "auc": 0.92,
                "pr_at_10": 0.85,
                "threshold_curve_path": "s3://ada/outputs/OUT-EVAL/job/threshold_curve.png",
            },
        }
    }
    state.data_profile = {
        "contamination_estimate": 0.05,
        "permutation_importance_per_dim": {"amount": 0.65, "freq": 0.42, "elapsed": 0.28},
    }
    state.eda_charts = ["s3://ada/outputs/EDA/job/box.png"]
    return state


@pytest.fixture
def state_no_pipeline(anomaly_state):
    """Day 6 결과 없음."""
    state = deepcopy(anomaly_state)
    state.eval_result = {}
    state.data_profile = {"contamination_estimate": 0.05}
    return state


@pytest.fixture
def state_no_pred(anomaly_state):
    """predicted_anomalies 모두 False."""
    state = deepcopy(anomaly_state)
    state.category_extras = {
        "anomaly": {
            "pipeline": {
                "ensemble_scores": np.zeros(500),
                "predicted_anomalies": np.zeros(500).astype(bool),
                "threshold": 0.5,
            }
        }
    }
    state.data_profile = {
        "contamination_estimate": 0.05,
        "permutation_importance_per_dim": {"amount": 0.5},
    }
    return state


# === A. 스키마 ====================================================


def test_assets_returns_three_keys(state_full):
    """#1 — 반환 dict = {charts, tables, text_blocks} 모두 list."""
    from agents.handlers.anomaly.output_extras import assets

    out = assets(state_full)
    assert set(out.keys()) == {"charts", "tables", "text_blocks"}
    assert all(isinstance(out[k], list) for k in out)


def test_assets_two_arg_call(state_full):
    """#2 ★ E-1 — base._call_extras 의 2-arg 호출 (state, ctx)."""
    from agents.handlers.anomaly.output_extras import assets

    out = assets(state_full, {"output_code": "OUT-01", "category": "anomaly_detection"})
    assert isinstance(out, dict)
    assert set(out.keys()) == {"charts", "tables", "text_blocks"}


def test_assets_one_arg_call(state_full):
    """#3 ★ E-1 — report_composer 의 1-arg 호출 (state)."""
    from agents.handlers.anomaly.output_extras import assets

    out = assets(state_full)
    assert isinstance(out, dict)
    assert set(out.keys()) == {"charts", "tables", "text_blocks"}


# === B. 정확성 ====================================================


def test_top_n_table_structure(state_full):
    """#4 ★ DoD top_n_table — title/columns/rows + rows≤5 + 키 일치."""
    from agents.handlers.anomaly.output_extras import assets

    tables = assets(state_full)["tables"]
    assert len(tables) == 1
    tbl = tables[0]
    assert "title" in tbl and "columns" in tbl and "rows" in tbl
    assert 1 <= len(tbl["rows"]) <= 5
    for row in tbl["rows"]:
        assert set(row.keys()) == set(tbl["columns"])


def test_table_contains_sigma(state_full):
    """#5 ★ DoD — 편차(σ) 셀이 'N.Nσ' 형식."""
    from agents.handlers.anomaly.output_extras import assets

    rows = assets(state_full)["tables"][0]["rows"]
    assert any(re.search(r"[\d.]+σ", str(r["편차(σ)"])) for r in rows)


def test_charts_no_dup_with_eda(state_full):
    """#6 — charts list[str] + eda_charts 와 비중복 (E-5)."""
    from agents.handlers.anomaly.output_extras import assets

    charts = assets(state_full)["charts"]
    assert isinstance(charts, list)
    assert all(isinstance(c, str) for c in charts)
    assert set(charts).isdisjoint(set(state_full.eda_charts))
    assert charts and "threshold_curve.png" in charts[0]


# === D. 분기 ======================================================


def test_no_pipeline_empty_table(state_no_pipeline):
    """#7 — Day 6 결과 없음 → tables=[]."""
    from agents.handlers.anomaly.output_extras import assets

    out = assets(state_no_pipeline)
    assert out["tables"] == []


def test_no_predictions_empty(state_no_pred):
    """#8 — predicted 모두 False → tables=[]·text_blocks=[]."""
    from agents.handlers.anomaly.output_extras import assets

    out = assets(state_no_pred)
    assert out["tables"] == []
    assert out["text_blocks"] == []


# === E. 엣지 ======================================================


def test_empty_state_handled(anomaly_state):
    """#9 — 빈 state → 예외 X + 3 키."""
    state = deepcopy(anomaly_state)
    state.category_extras = {}
    state.data_profile = None
    from agents.handlers.anomaly.output_extras import assets

    out = assets(state)
    assert set(out.keys()) == {"charts", "tables", "text_blocks"}


def test_only_output_extras_keys(state_full):
    """#10 — 반환 키가 정확히 3 개 (옛 extra_charts/category_label 없음)."""
    from agents.handlers.anomaly.output_extras import assets

    out = assets(state_full)
    assert set(out.keys()) == {"charts", "tables", "text_blocks"}
    assert "extra_charts" not in out and "category_label" not in out


# === F. 회귀 ======================================================


def test_assets_registered():
    """#11 — dispatcher 자동 등록 (assets capability, E-2)."""
    import agents.handlers.anomaly  # noqa: F401
    from agents.handlers import HANDLER_REGISTRY

    fn = HANDLER_REGISTRY["anomaly_detection"].get("assets")
    assert callable(fn)


def test_text_block_korean(state_full):
    """#12 — text_blocks 한국어 (있으면)."""
    from agents.handlers.anomaly.output_extras import assets

    blocks = assets(state_full)["text_blocks"]
    if blocks:
        joined = " ".join(blocks)
        assert any(0xAC00 <= ord(c) <= 0xD7A3 for c in joined)

"""NY Day 7 — anomaly evaluator 단위 테스트 (11 케이스).

5 그룹:
  A 스키마 (#1·#2)
  B 정확성 (#3·#4·#5) ★ #3 DoD pr_at_10 > 0.7
  D 분기 (#6·#7)
  E 엣지 (#8·#9)
  F 회귀 (#10·#11)

mock 핵심: save_chart_to_minio autouse (Day 3 eda 패턴).
"""

from __future__ import annotations

import numpy as np
import pytest

# ── autouse fixture: MinIO mock ───────────────────────────────────


@pytest.fixture(autouse=True)
def mock_minio_upload(monkeypatch):
    """save_chart_to_minio 자동 mock — 실제 MinIO 호출 X."""

    def fake_upload(fig, kind, job_id):
        import matplotlib.pyplot as plt

        plt.close(fig)
        return f"minio://test/{kind}/{job_id}.png"

    monkeypatch.setattr(
        "agents.handlers.common.shared.save_chart_to_minio",
        fake_upload,
    )


# ── Day 7 전용 fixture ────────────────────────────────────────────


@pytest.fixture
def state_with_day6_result(anomaly_state, monkeypatch):
    """★ X-3/X-6 ①: best_model state + `_generate_scores` → 합성 (labels) 튜플 patch (AUC 측정 가능)."""
    from copy import deepcopy

    from agents.handlers.anomaly import evaluator

    state = deepcopy(anomaly_state)
    state.best_model = {"model_name": "IsolationForest", "params_used": {}}
    state.job_id = "test_job_42"

    rng = np.random.default_rng(42)
    n, n_anom = 1000, 50
    scores = np.concatenate([rng.normal(0.3, 0.1, n - n_anom), rng.normal(0.8, 0.1, n_anom)])
    y_true = np.concatenate([np.zeros(n - n_anom), np.ones(n_anom)]).astype(int)
    idx = rng.permutation(n)
    scores, y_true = scores[idx], y_true[idx]
    predicted = (scores > 0.5).astype(int)

    monkeypatch.setattr(evaluator, "_generate_scores", lambda s: (scores, predicted, 0.5, y_true))
    return state


@pytest.fixture
def state_without_y_true(anomaly_state, monkeypatch):
    """y_true 없는 비지도(C2/C4) — `_generate_scores` → (scores, predicted, thr, None)."""
    from copy import deepcopy

    from agents.handlers.anomaly import evaluator

    state = deepcopy(anomaly_state)
    state.best_model = {"model_name": "IsolationForest", "params_used": {}}
    state.job_id = "test_job_no_y"

    rng = np.random.default_rng(0)
    scores = rng.normal(0.5, 0.2, 500)
    predicted = (scores > 0.7).astype(int)

    monkeypatch.setattr(evaluator, "_generate_scores", lambda s: (scores, predicted, 0.7, None))
    return state


@pytest.fixture
def state_no_ensemble(anomaly_state, monkeypatch):
    """점수 생성 불가 — `_generate_scores` → None (skip dict)."""
    from copy import deepcopy

    from agents.handlers.anomaly import evaluator

    state = deepcopy(anomaly_state)
    state.job_id = "test_job_empty"
    monkeypatch.setattr(evaluator, "_generate_scores", lambda s: None)
    return state


# === A. 스키마 ====================================================


def test_evaluate_returns_rich_dict(state_with_day6_result):
    """#1 ★ X-3/X-6 — evaluate 반환 dict (eval_agent 가 state.eval_result 에 저장)."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    assert isinstance(result, dict)
    for key in ("ensemble_scores", "predicted_anomalies", "threshold", "passed"):
        assert key in result


def test_evaluation_keys_present(state_with_day6_result):
    """#2 — 필수 키 4 + extra."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    for key in ("pr_at_10", "auc", "f1", "threshold_curve_path", "y_true_available"):
        assert key in result


# === B. 정확성 ====================================================


def test_pr_at_10_above_07(state_with_day6_result):
    """#3 ★ DoD — 합성 데이터 → pr_at_10 > 0.7."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    assert result["pr_at_10"] is not None
    assert result["pr_at_10"] > 0.7, f"DoD 위반: pr_at_10={result['pr_at_10']}"


def test_auc_f1_present_with_y_true(state_with_day6_result):
    """#4 — y_true 제공 → auc·f1 not None."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    assert result["auc"] is not None
    assert result["f1"] is not None
    assert 0 <= result["auc"] <= 1
    assert 0 <= result["f1"] <= 1


def test_threshold_curve_path_present(state_with_day6_result):
    """#5 — threshold_curve_path minio:// 형식."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    assert result["threshold_curve_path"] is not None
    assert result["threshold_curve_path"].startswith("minio://")


# === D. 분기 ======================================================


def test_y_true_none_returns_none_metrics(state_without_y_true):
    """#6 — y_true 없으면 metrics = None (Day 6 B-1 일관)."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_without_y_true)
    assert result["pr_at_10"] is None
    assert result["auc"] is None
    assert result["f1"] is None
    assert result["y_true_available"] is False


def test_no_ensemble_scores_returns_warning(state_no_ensemble):
    """#7 — Day 6 결과 없으면 warning."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_no_ensemble)
    assert result.get("warning") is not None
    assert result["pr_at_10"] is None


# === E. 엣지 ======================================================


def test_generate_scores_none_skip(anomaly_state, monkeypatch):
    """#8 ★ — _generate_scores None(best_model/데이터 없음) → skip dict (passed=True, 필드 None)."""
    from copy import deepcopy

    from agents.handlers.anomaly import evaluator

    state = deepcopy(anomaly_state)
    state.job_id = "test_empty"
    monkeypatch.setattr(evaluator, "_generate_scores", lambda s: None)
    result = evaluator.evaluate(state)
    assert result["passed"] is True
    assert result["pr_at_10"] is None and result["ensemble_scores"] is None
    assert result.get("warning") is not None


def test_minio_save_failure_returns_none_path(state_with_day6_result, monkeypatch):
    """#9 — MinIO 실패 시 path=None. 메인 metrics 는 정상."""

    def fake_upload_fail(fig, kind, job_id):
        raise RuntimeError("MinIO 연결 실패")

    monkeypatch.setattr(
        "agents.handlers.common.shared.save_chart_to_minio",
        fake_upload_fail,
    )
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    assert result["threshold_curve_path"] is None
    assert result["pr_at_10"] is not None
    assert result["auc"] is not None


# === F. 회귀 ======================================================


def test_precision_at_k_helper():
    """#10 — 헬퍼 단위 정밀도."""
    from agents.handlers.anomaly.evaluator import _precision_at_k

    scores = np.array([0.1, 0.2, 0.9, 0.8, 0.3])
    y_true = np.array([0, 0, 1, 1, 0])

    pr = _precision_at_k(scores, y_true, k=2)
    assert pr == 1.0


def test_threshold_sweep_table_format(state_with_day6_result):
    """#11 — sweep table 형식 (list of dict, 4 키)."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    sweep = result["threshold_sweep_table"]
    assert isinstance(sweep, list)
    if sweep:
        for d in sweep:
            assert set(d.keys()) == {"threshold", "precision", "recall", "f1"}
            for v in d.values():
                assert isinstance(v, float)


# === ★ C-2 결정 후 추가 (A-2·A-3·B-1 검증) =========================


def test_pr_auc_present_with_y_true(state_with_day6_result):
    """#12 ★ A-2 — PR-AUC 산출 (imbalanced 도메인 본질)."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_with_day6_result)
    assert result["pr_auc"] is not None
    assert 0 <= result["pr_auc"] <= 1
    # ROC-AUC 와 PR-AUC 둘 다 존재
    assert result["auc"] is not None


def test_threshold_sweep_50_thresholds():
    """#13 ★ A-3 — n_thresholds=50 (10→50 정밀화)."""
    import numpy as np

    from agents.handlers.anomaly.evaluator import THRESHOLD_SWEEP_N, _threshold_sweep

    # 상수 검증
    assert THRESHOLD_SWEEP_N == 50

    # 실제 호출 시 최대 50 thresholds
    rng = np.random.default_rng(0)
    scores = rng.normal(0.5, 0.2, 1000)
    y_true = (scores > 0.7).astype(int)
    sweep = _threshold_sweep(scores, y_true, n_thresholds=50)

    # predicted.sum()==0 인 threshold 는 skip 되므로 ≤ 50
    assert len(sweep) <= 50
    assert len(sweep) > 0


def test_warning_when_y_true_none(state_without_y_true):
    """#B-1 — y_true 없으면 label metrics None + y_true_available False."""
    from agents.handlers.anomaly.evaluator import evaluate

    result = evaluate(state_without_y_true)
    assert result["y_true_available"] is False
    assert result["pr_at_10"] is None
    assert result["auc"] is None
    assert result["f1"] is None

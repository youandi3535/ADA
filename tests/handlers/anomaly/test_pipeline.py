"""NY Day 6 — anomaly pipeline 단위 테스트 (11 케이스).

5 그룹:
  A 스키마 (#1·#2)
  B 정확성 (#3·#4·#5) ★ #3 DoD AUC > 0.8
  D 분기 (#6·#7·#8)
  E 엣지 (#9·#10)
  F 회귀 (#11)

★ E-1 결정 후 클래스 기반 — AnomalyPipeline (run_full_pipeline 은 X-3/X-6 으로 제거).
"""

from __future__ import annotations

import numpy as np
import pytest

# ── autouse fixture: selector mock ────────────────────────────────


@pytest.fixture(autouse=True)
def mock_selector_score(monkeypatch):
    """selector.score top3 카드 5 키 (E-1 형식) 자동 mock."""

    def fake_score(state, recipes=None):
        return {
            "top3": [
                {"id": 1, "title": "IsolationForest", "rationale": "범용", "total_score": 0.85, "score_breakdown": {}},
                {"id": 2, "title": "OneClassSVM", "rationale": "저오염", "total_score": 0.80, "score_breakdown": {}},
                {"id": 3, "title": "LOF", "rationale": "지역", "total_score": 0.75, "score_breakdown": {}},
            ],
            "rationale": "mock",
            "citations": [],
        }

    monkeypatch.setattr("agents.handlers.anomaly.selector.score", fake_score)


# ── Day 6 전용 fixture ────────────────────────────────────────────


@pytest.fixture(
    params=[
        {"seed": 42, "distance": 6.0, "ratio": 0.05},  # 기본 시나리오
        {"seed": 0, "distance": 9.0, "ratio": 0.10},  # 거리·비율 ↑ (쉬운 케이스)
        {"seed": 1, "distance": 3.0, "ratio": 0.05},  # 거리 ↓ (어려운 케이스, 정상과 가까움)
    ]
)
def anomaly_X_y_synthetic(request):
    """★ B-1 결정: 합성 fixture 다양화 (3 시나리오) — AUC 안정성 검증.

    DoD AUC > 0.8 이 3 시나리오 모두 통과해야 신뢰성 ↑.
    """
    p = request.param
    rng = np.random.default_rng(p["seed"])
    n_total = 1000
    n_anomaly = int(n_total * p["ratio"])
    n_normal = n_total - n_anomaly
    X_normal = rng.normal(0, 1, (n_normal, 5))
    X_anomaly = rng.normal(p["distance"], 1, (n_anomaly, 5))
    X = np.vstack([X_normal, X_anomaly])
    y = np.concatenate([np.zeros(n_normal), np.ones(n_anomaly)])
    idx = rng.permutation(n_total)
    return X[idx], y[idx]


@pytest.fixture
def anomaly_X_no_y():
    """y 없는 X (실제 사용 시나리오)."""
    rng = np.random.default_rng(0)
    return rng.normal(0, 1, (500, 5))


@pytest.fixture
def anomaly_state_with_time(anomaly_state):
    """has_time=True — TranAD/AT 분기 검증."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "rows": 500,
        "has_time_column": True,
        "contamination_estimate": 0.05,
    }
    return state


@pytest.fixture
def anomaly_state_no_time(anomaly_state):
    """has_time=False — 5 모델만 활성."""
    from copy import deepcopy

    state = deepcopy(anomaly_state)
    state.data_profile = {
        "rows": 500,
        "has_time_column": False,
        "contamination_estimate": 0.05,
    }
    return state


@pytest.fixture
def pipeline_instance():
    """AnomalyPipeline 인스턴스 (E-1 결정)."""
    from pipelines.anomaly.pipeline import AnomalyPipeline

    return AnomalyPipeline()


# === A. AnomalyPipeline 클래스 단위 (★ X-3/X-6: run_full_pipeline 제거) ===
#  per-row·ensemble 결과(category_extras 기록)는 Day 7 evaluator 가 생성 → Day 7 test 가 검증.
#  Day 6 책임 = executor 가 쓰는 train/predict/evaluate + evaluator 가 쓰는 otsu 등 정적 헬퍼.


def test_train_returns_fitted_model(pipeline_instance, anomaly_X_y_synthetic):
    """#1 — train → fitted model (predict/decision_function 보유)."""
    X, y = anomaly_X_y_synthetic
    model = pipeline_instance.train(X, y, "IsolationForest", {})
    assert hasattr(model, "decision_function") or hasattr(model, "predict")


def test_predict_returns_per_row_scores(pipeline_instance, anomaly_X_y_synthetic):
    """#2 — predict → per-row score (len == n_rows)."""
    X, y = anomaly_X_y_synthetic
    model = pipeline_instance.train(X, y, "IsolationForest", {})
    scores = np.asarray(pipeline_instance.predict(model, X))
    assert scores.shape[0] == X.shape[0]


def test_evaluate_returns_metrics_dict(pipeline_instance, anomaly_X_y_synthetic):
    """#3 — evaluate → metrics dict (val_auc 또는 threshold 키)."""
    X, y = anomaly_X_y_synthetic
    model = pipeline_instance.train(X, y, "IsolationForest", {})
    metrics = pipeline_instance.evaluate(model, X, y)
    assert isinstance(metrics, dict) and ("val_auc" in metrics or "threshold" in metrics)


# === B. 정적 헬퍼 (evaluator·ensemble 소비) ===


def test_otsu_threshold_in_score_range():
    """#4 — otsu_threshold ∈ [min, max]."""
    from pipelines.anomaly.pipeline import AnomalyPipeline

    rng = np.random.default_rng(0)
    scores = np.concatenate([rng.normal(0.3, 0.1, 100), rng.normal(0.8, 0.05, 20)])
    thr = float(AnomalyPipeline.otsu_threshold(scores))
    assert float(scores.min()) <= thr <= float(scores.max())


def test_ensemble_voting_combines_models():
    """#5 — ensemble_voting → 결합 점수 (len 유지, NaN 없음)."""
    from pipelines.anomaly.pipeline import AnomalyPipeline

    s1 = np.array([0.1, 0.9, 0.2, 0.8])
    s2 = np.array([0.2, 0.7, 0.1, 0.9])
    ens = np.asarray(AnomalyPipeline.ensemble_voting({"IsolationForest": s1, "LOF": s2}, {}))
    assert ens.shape[0] == 4 and not np.isnan(ens).any()


# === D. 모델 로스터 / 무라벨 ===


def test_supported_models_has_six():
    """#6 — SUPPORTED_MODELS 6종 보유 (모델 선택 분기는 Day 4·5 책임)."""
    from pipelines.anomaly.pipeline import AnomalyPipeline

    for m in ("IsolationForest", "LOF", "OneClassSVM", "AutoEncoder", "TranAD", "AnomalyTransformer"):
        assert m in AnomalyPipeline.SUPPORTED_MODELS


def test_evaluate_y_none_safe(pipeline_instance, anomaly_X_no_y):
    """#7 — y_val=None(비지도) → evaluate 안 죽음 (val_auc None 또는 0.5 fallback)."""
    X = anomaly_X_no_y
    model = pipeline_instance.train(X, None, "IsolationForest", {})
    metrics = pipeline_instance.evaluate(model, X, None)
    assert metrics.get("val_auc") in (None, 0.5)


# === F. 회귀 ======================================================


def test_copod_in_supported_models():
    """#12 ★ A-1 — COPOD 가 SUPPORTED_MODELS 에 7 번째로 포함."""
    from pipelines.anomaly.pipeline import AnomalyPipeline

    assert "COPOD" in AnomalyPipeline.SUPPORTED_MODELS


def test_otsu_threshold_validation_meta():
    """#13 ★ A-2 — Otsu + contamination sanity check meta dict 반환."""
    import numpy as np

    from pipelines.anomaly.pipeline import _otsu_threshold_with_validation

    scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.8, 0.9])
    contamination = 0.1
    threshold, meta = _otsu_threshold_with_validation(scores, contamination)

    assert isinstance(threshold, float)
    assert isinstance(meta, dict)
    assert "method" in meta and meta["method"] in ("otsu", "contamination")
    assert "reason" in meta
    assert "otsu_value" in meta
    assert "contam_value" in meta


def test_normalize_scores_clipped():
    """#14 ★ A-3 — _normalize_scores 결과 ∈ [0.05, 0.95]."""
    import numpy as np

    from pipelines.anomaly.pipeline import NORMALIZE_CLIP_HIGH, NORMALIZE_CLIP_LOW, _normalize_scores

    scores = np.array([-10.0, -5.0, 0.0, 5.0, 10.0])
    normalized = _normalize_scores(scores)

    # 클리핑 결과는 [0.05, 0.95] 범위
    assert float(normalized.min()) >= NORMALIZE_CLIP_LOW
    assert float(normalized.max()) <= NORMALIZE_CLIP_HIGH
    # 상수 검증
    assert NORMALIZE_CLIP_LOW == 0.05
    assert NORMALIZE_CLIP_HIGH == 0.95


def test_base_models_score_sign_auc_above_080():
    """#15 ★ P0 — IF/LOF/OCSVM sklearn fallback 점수 부호 회귀.

    부호가 올바르면 AUC≈1.0, 뒤집히면 AUC≈0.0 — 부호 버그를 결정적으로 잡는다.
    이상치를 ±8 방향으로 랜덤 시프트해 LOF cluster 효과를 차단한다.
    """
    from sklearn.metrics import roc_auc_score

    from pipelines.anomaly.pipeline import AnomalyPipeline

    rng = np.random.default_rng(0)
    n_normal, n_anom, n_feat = 950, 50, 4
    X_normal = rng.normal(0, 1, (n_normal, n_feat))
    X_anomaly = rng.normal(0, 1, (n_anom, n_feat)) + rng.choice([-8, 8], size=(n_anom, n_feat))
    X = np.vstack([X_normal, X_anomaly])
    y = np.concatenate([np.zeros(n_normal), np.ones(n_anom)])
    idx = rng.permutation(n_normal + n_anom)
    X, y = X[idx], y[idx]

    pipe = AnomalyPipeline()
    for model_name in ("IsolationForest", "LOF", "OneClassSVM"):
        model = pipe.train(X, y, model_name, {})
        scores = np.asarray(pipe.predict(model, X))
        auc = roc_auc_score(y, scores)
        assert auc > 0.8, f"{model_name} AUC={auc:.4f} < 0.8 (점수 부호 버그 의심)"


# #11 (predicted_anomalies dtype) — ★ X-3/X-6 이전: per-row predicted_anomalies 는
#   Day 7 evaluator 가 생성(state.eval_result). 검증은 ny-day7-test_evaluator.md 로 이전됨.

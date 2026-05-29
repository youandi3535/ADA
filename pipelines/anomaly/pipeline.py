"""pipelines.anomaly.pipeline — 이상탐지 본격화 (NY 담당, Day 6 v2).

PyOD 7종 (IF·LOF·OCSVM·AE·COPOD·TranAD·AnomalyTransformer) 학습 →
Otsu threshold 자동 → Ensemble voting (top3 가중) → AUC 측정 (DoD>0.8).

진입 (★ E-1 결정 — BasePipeline 표준):
  - class AnomalyPipeline(BasePipeline)
      - .train(X_train, y_train, model_name, params) -> fitted_model
      - .predict(model, X) -> anomaly_scores
      - .evaluate(model, X_val, y_val, task) -> metrics dict
  - run_full_pipeline(state, X_train, y_train=None) -> state (편의 함수)

DoD: 합성 이상치 데이터 → AUC > 0.8
"""

from __future__ import annotations

from typing import Any

import numpy as np

from pipelines.base import BasePipeline

# ── 헬퍼 (모듈 함수) ──────────────────────────────────────────────


def _train_one_model(model_name: str, X_train: np.ndarray, params: dict[str, Any]) -> Any:
    """단일 모델 학습 — PyOD 우선, sklearn fallback."""
    if model_name == "IsolationForest":
        try:
            from pyod.models.iforest import IForest

            m = IForest(**params)
        except ImportError:
            from sklearn.ensemble import IsolationForest

            sk_params = {k: v for k, v in params.items() if k != "contamination" or v != "auto"}
            m = IsolationForest(**sk_params)
        m.fit(X_train)
        return m

    if model_name == "LOF":
        try:
            from pyod.models.lof import LOF

            m = LOF(**params)
            m.fit(X_train)
            return m
        except ImportError:
            from sklearn.neighbors import LocalOutlierFactor

            sk_params = {k: v for k, v in params.items() if k != "contamination"}
            m = LocalOutlierFactor(novelty=True, **sk_params)
            m.fit(X_train)
            return m

    if model_name == "OneClassSVM":
        try:
            from pyod.models.ocsvm import OCSVM

            m = OCSVM(**params)
        except ImportError:
            from sklearn.svm import OneClassSVM

            sk_params = {k: v for k, v in params.items() if k != "contamination"}
            m = OneClassSVM(**sk_params)
        m.fit(X_train)
        return m

    if model_name == "AutoEncoder":
        from pyod.models.auto_encoder import AutoEncoder

        m = AutoEncoder(**params)
        m.fit(X_train)
        return m

    if model_name == "COPOD":
        from pyod.models.copod import COPOD

        m = COPOD(**params)
        m.fit(X_train)
        return m

    if model_name in ("TranAD", "AnomalyTransformer"):
        # 시계열 모델 - PyOD 가상, 미구현 시 ImportError
        raise ImportError(f"{model_name} 미구현 (Day 7+ 본격화 예정)")

    raise ValueError(f"Unknown model: {model_name}")


def _get_anomaly_scores(model: Any, X: np.ndarray, model_name: str) -> np.ndarray:
    """모델별 anomaly score 추출 (높을수록 이상)."""
    # PyOD: decision_function (높을수록 이상)
    if hasattr(model, "decision_function") and model_name not in ("IsolationForest_sklearn",):
        try:
            return np.asarray(model.decision_function(X), dtype=float)
        except Exception:
            pass

    # sklearn IsolationForest: score_samples (낮을수록 이상) → 반전
    if hasattr(model, "score_samples"):
        return -np.asarray(model.score_samples(X), dtype=float)

    # sklearn LOF / OCSVM: decision_function (낮을수록 이상) → 반전
    if hasattr(model, "decision_function"):
        return -np.asarray(model.decision_function(X), dtype=float)

    # fallback
    return np.asarray(model.predict(X), dtype=float)


NORMALIZE_CLIP_LOW = 0.05  # ★ A-3 (옵션 B)
NORMALIZE_CLIP_HIGH = 0.95  # ★ A-3 (옵션 B)


def _normalize_scores(scores: np.ndarray) -> np.ndarray:
    """min-max 정규화 [0, 1] + outlier 클리핑 [0.05, 0.95] (★ A-3).

    클리핑 이유: outlier model 극단 점수 (0/1) ensemble 왜곡 → 강건성 보완.
    """
    if len(scores) == 0:
        return scores
    s_min = float(scores.min())
    s_max = float(scores.max())
    if s_max - s_min < 1e-9:
        return np.zeros_like(scores)
    normalized = (scores - s_min) / (s_max - s_min)
    return np.clip(normalized, NORMALIZE_CLIP_LOW, NORMALIZE_CLIP_HIGH)


def _ensemble_voting(
    scores_dict: dict[str, np.ndarray],
    top3_weights: dict[str, float] | None = None,
) -> np.ndarray:
    """가중 평균 ensemble (top3 모델 가중치 ↑)."""
    if not scores_dict:
        return np.array([])

    weights: list[float] = []
    matrices: list[np.ndarray] = []
    for name, s in scores_dict.items():
        w = top3_weights.get(name, 0.5) if top3_weights else 1.0
        weights.append(w)
        matrices.append(s)

    weights_arr = np.array(weights, dtype=float)
    if weights_arr.sum() == 0:
        weights_arr = np.ones_like(weights_arr)

    score_matrix = np.stack(matrices, axis=1)  # (n_samples, n_models)
    return np.average(score_matrix, axis=1, weights=weights_arr)


def _otsu_threshold(scores: np.ndarray, n_bins: int = 256) -> float:
    """Otsu method — 분산 가중치 최소화 자동 임계."""
    if len(scores) < 2:
        return 0.5

    hist, bin_edges = np.histogram(scores, bins=n_bins)
    if hist.sum() == 0:
        return 0.5

    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    p = hist / hist.sum()

    w0 = np.cumsum(p)
    w1 = 1 - w0
    mu0 = np.cumsum(p * bin_centers) / np.maximum(w0, 1e-9)
    mu_total = np.sum(p * bin_centers)
    mu1 = (mu_total - np.cumsum(p * bin_centers)) / np.maximum(w1, 1e-9)

    sigma_b2 = w0 * w1 * (mu0 - mu1) ** 2
    idx = int(np.argmax(sigma_b2))
    return float(bin_centers[idx])


def _compute_auc(y_true: np.ndarray | None, scores: np.ndarray) -> float | None:
    """sklearn roc_auc_score. y_true 없으면 None."""
    if y_true is None or len(scores) == 0:
        return None
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y_true, scores))
    except Exception:
        return None


# ── ★ E-1: AnomalyPipeline 클래스 (BasePipeline 표준) ────────────


class AnomalyPipeline(BasePipeline):
    """이상탐지 pipeline — BasePipeline 추상 구현.

    ★ E-1 결정: dispatcher capability 가 아닌 클래스 패턴.
    HJ orchestrator 가 인스턴스화 후 메서드 호출.
    """

    experiment_name = "ada-anomaly"
    SUPPORTED_MODELS = (
        "IsolationForest",
        "LOF",
        "OneClassSVM",
        "AutoEncoder",
        "COPOD",
        "TranAD",
        "AnomalyTransformer",
    )

    def train(
        self,
        X_train: Any,
        y_train: Any,
        model_name: str,
        params: dict[str, Any],
    ) -> Any:
        """단일 모델 학습 (PyOD 우선, sklearn fallback). MLflow 로깅."""
        with self._start_mlflow_run(tags={"model": model_name}):
            try:
                import mlflow  # noqa: WPS433

                mlflow.log_params({**params, "model_name": model_name})
            except Exception:
                pass
            return _train_one_model(model_name, X_train, params)

    def predict(self, model: Any, X: Any) -> np.ndarray:
        """anomaly_score 반환 (높을수록 이상)."""
        return _get_anomaly_scores(model, X, model_name="")

    def evaluate(
        self,
        model: Any,
        X_val: Any,
        y_val: Any,
        task: str = "anomaly",
    ) -> dict[str, float]:
        """AUC + Otsu + predicted_anomalies. ★ DoD: AUC > 0.8."""
        scores = _get_anomaly_scores(model, X_val, "")
        threshold = self.otsu_threshold(scores)
        predicted = (scores > threshold).astype(bool)
        metrics: dict[str, Any] = {
            "threshold": threshold,
            "predicted_anomalies_count": int(predicted.sum()),
            "predicted_anomalies_ratio": float(predicted.mean()),
            "score_min": float(scores.min()) if len(scores) else 0.0,
            "score_max": float(scores.max()) if len(scores) else 0.0,
            "score_mean": float(scores.mean()) if len(scores) else 0.0,
        }
        if y_val is not None:
            try:
                from sklearn.metrics import roc_auc_score

                metrics["auc"] = float(roc_auc_score(y_val, scores))
            except Exception:
                metrics["auc"] = None
        else:
            metrics["auc"] = None
        return metrics

    # static 헬퍼 (public — Day 7·9 도 사용)
    @staticmethod
    def normalize_scores(scores: np.ndarray) -> np.ndarray:
        return _normalize_scores(scores)

    @staticmethod
    def ensemble_voting(
        scores_dict: dict[str, np.ndarray],
        top3_weights: dict[str, float] | None = None,
    ) -> np.ndarray:
        return _ensemble_voting(scores_dict, top3_weights)

    @staticmethod
    def otsu_threshold(scores: np.ndarray, n_bins: int = 256) -> float:
        return _otsu_threshold(scores, n_bins)


# ── ★ X-3/X-6 ① (2026-05-29): run_full_pipeline·_update_state 제거 ──
#
# 제거 이유:
#  - orphan: ADA orchestrator 는 본 함수를 호출 안 함 (model_selection→tuner→
#    training_executor 의 per-model 경로만). → category_extras["anomaly"]["pipeline"] 미생성.
#  - R-005 위반: _update_state 가 state.category_extras 를 직접 수정 (with_update 미사용).
#  - 데이터 버스 오해(X-6): per-row 결과는 category_extras 가 아니라 top-level state 에 실려야.
#
# per-row anomaly score 생성 책임 → Day 7 evaluator(`_generate_scores`)로 이전:
#   best_model(orchestrator 선정)을 데이터에 재적용 → otsu → predicted → state.eval_result 반환.
# Day 6 잔존 책임:
#   AnomalyPipeline.train/predict/evaluate  (training_executor 가 모델별 호출)
#   AnomalyPipeline.otsu_threshold          (Day 7 evaluator 가 소비)
#   normalize_scores/ensemble_voting        (단일 best_model 경로에선 미사용 — 추후 ensemble 재도입 대비 보존)


def _otsu_threshold_with_validation(scores: np.ndarray, contamination: float = 0.1) -> tuple[float, dict[str, Any]]:
    """★ A-2 (Day 6, 2026-05-29) — Otsu 와 contamination 임계 비교 후 sanity check.

    반환: (선택 임계, meta 딕셔너리). meta = {method, reason, otsu_value, contam_value}
    method ∈ {"otsu", "contamination"} — Otsu 이상치 비율이 contamination 의 5 배 초과 시 contamination 폴백.
    """
    scores = np.asarray(scores, dtype=float).ravel()
    if scores.size == 0:
        return 0.0, {"method": "otsu", "reason": "empty", "otsu_value": 0.0, "contam_value": 0.0}
    otsu_v = float(_otsu_threshold(scores))
    contam_v = float(np.quantile(scores, 1.0 - float(contamination))) if 0 < contamination < 1 else otsu_v
    otsu_ratio = float((scores >= otsu_v).mean())
    if otsu_ratio > 5.0 * max(contamination, 1e-6):
        return contam_v, {
            "method": "contamination",
            "reason": f"otsu_ratio {otsu_ratio:.3f} > 5×contam {contamination:.3f}",
            "otsu_value": otsu_v,
            "contam_value": contam_v,
        }
    return otsu_v, {
        "method": "otsu",
        "reason": "within sanity range",
        "otsu_value": otsu_v,
        "contam_value": contam_v,
    }

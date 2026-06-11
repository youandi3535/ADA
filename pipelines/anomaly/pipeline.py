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
            m.fit(X_train)
            try:
                m._ada_backend = "pyod"
            except Exception:
                pass
            return m
        except ImportError:
            from sklearn.ensemble import IsolationForest

            sk_params = {k: v for k, v in params.items() if k != "contamination" or v != "auto"}
            m = IsolationForest(**sk_params)
            m.fit(X_train)
            try:
                m._ada_backend = "sklearn"
            except Exception:
                pass
            return m

    if model_name == "LOF":
        try:
            from pyod.models.lof import LOF

            m = LOF(**params)
            m.fit(X_train)
            try:
                m._ada_backend = "pyod"
            except Exception:
                pass
            return m
        except ImportError:
            from sklearn.neighbors import LocalOutlierFactor

            sk_params = {k: v for k, v in params.items() if k != "contamination"}
            m = LocalOutlierFactor(novelty=True, **sk_params)
            m.fit(X_train)
            try:
                m._ada_backend = "sklearn"
            except Exception:
                pass
            return m

    if model_name == "OneClassSVM":
        try:
            from pyod.models.ocsvm import OCSVM

            m = OCSVM(**params)
            m.fit(X_train)
            try:
                m._ada_backend = "pyod"
            except Exception:
                pass
            return m
        except ImportError:
            from sklearn.svm import OneClassSVM

            sk_params = {k: v for k, v in params.items() if k != "contamination"}
            m = OneClassSVM(**sk_params)
            m.fit(X_train)
            try:
                m._ada_backend = "sklearn"
            except Exception:
                pass
            return m

    if model_name == "AutoEncoder":
        from pyod.models.auto_encoder import AutoEncoder

        _ae_key_map = {"epochs": "epoch_num", "hidden_neurons": "hidden_neuron_list"}
        ae_params = {_ae_key_map.get(k, k): v for k, v in params.items()}
        m = AutoEncoder(**ae_params)
        m.fit(X_train)
        try:
            m._ada_backend = "pyod"
        except Exception:
            pass
        return m

    if model_name == "COPOD":
        from pyod.models.copod import COPOD

        m = COPOD(**params)
        m.fit(X_train)
        try:
            m._ada_backend = "pyod"
        except Exception:
            pass
        return m

    if model_name == "ECOD":
        # ★ V4: ECOD (Li et al., 2022, IEEE TKDE) — 차원별 경험적 CDF 꼬리확률.
        #   파라미터-프리·O(n·d)·해석 가능. ADBench(Han et al., NeurIPS 2022) 평균 상위권.
        from pyod.models.ecod import ECOD

        m = ECOD(**params)
        m.fit(X_train)
        try:
            m._ada_backend = "pyod"
        except Exception:
            pass
        return m

    if model_name == "HBOS":
        # ★ V4: HBOS (Goldstein & Dengel, 2012, KI) — 차원별 히스토그램 밀도.
        #   선형 시간 — 대용량(n≥10k) 1차 스크리닝에 최적.
        from pyod.models.hbos import HBOS

        m = HBOS(**params)
        m.fit(X_train)
        try:
            m._ada_backend = "pyod"
        except Exception:
            pass
        return m

    if model_name in ("TranAD", "AnomalyTransformer"):
        return _train_torch_ts_model(model_name, X_train, params)

    raise ValueError(f"Unknown anomaly model: {model_name}")


# ── PyTorch 기반 간략화 시계열 이상탐지 (TranAD / AnomalyTransformer) ─────
#
# 설계 원칙 (간략화 사항 명시):
#   1. 원논문의 복잡한 이중 분기(TranAD)/Association Discrepancy(AnomalyTransformer) 대신
#      동일한 "Transformer Encoder → Linear 재구성" 구조를 공유.
#      TranAD는 input/output 모두 window이지만 여기선 단일 타임스텝 재구성으로 단순화.
#      AnomalyTransformer의 Association Discrepancy(Prior/Series) 손실은 미구현 — MSE 단독.
#   2. 슬라이딩 윈도우 배치로 시계열 패턴 학습 (window_size=16, stride=1).
#      데이터가 window_size 미만이면 전체를 하나의 윈도우로 처리.
#   3. Deterministic (torch.manual_seed 고정, CPU 전용).
#   4. 에폭 수·모델 크기는 CPU에서 수 초 이내 완료 수준으로 제한.
#   5. 반환 객체: _TorchTSAnomalyModel (decision_function/fit 미포함) —
#      _get_anomaly_scores 가 score_samples 없는 경우를 처리하므로
#      custom predict(X) → anomaly score ndarray 를 노출.
#
# 인터페이스: model.anomaly_scores(X: ndarray) -> ndarray (높을수록 이상)
#             _get_anomaly_scores 가 model_name 별 분기 없이 사용 가능하도록
#             decision_function 을 구현.


class _TorchTSAnomalyModel:
    """경량 Transformer 재구성 이상탐지 모델 (TranAD/AnomalyTransformer 공용).

    ★ 간략화 — 원 논문 대비 단순화 항목:
      - TranAD: 이중-분기 역전파(phase1/phase2) 미구현, 단일 MSE 재구성으로 대체.
      - AnomalyTransformer: Association Discrepancy(Prior/Series Association) 미구현.
      - 두 모델 모두 동일한 TransformerEncoder + Linear 재구성 아키텍처 사용.
      - 슬라이딩 윈도우 = 16 타임스텝, 배치 = 64, 에폭 = 10 (CPU 친화).
    """

    def __init__(self, model_name: str, n_features: int, window_size: int = 16) -> None:
        self.model_name = model_name
        self.n_features = n_features
        self.window_size = window_size
        self._net: Any = None
        self._train_scores: Any = None  # 학습 데이터 재구성 오류 분포 (임계 결정용)
        self._ada_backend = "torch"

    def fit(self, X: np.ndarray) -> "_TorchTSAnomalyModel":
        """학습: X (n_samples, n_features) → 슬라이딩 윈도우 재구성 학습."""
        try:
            import torch
            import torch.nn as nn
        except ImportError as exc:
            raise ImportError(
                f"{self.model_name} 학습에는 PyTorch가 필요합니다. "
                "requirements/handlers-anomaly.txt 에 torch>=2.0 추가 후 재설치하세요."
            ) from exc

        torch.manual_seed(42)
        n_feat = self.n_features
        ws = self.window_size

        # ── 모델 정의 ──────────────────────────────────────────────
        class _TSAnomalyNet(nn.Module):
            def __init__(self, n_feat: int, ws: int) -> None:
                super().__init__()
                d_model = max(16, min(64, n_feat * 2))
                self.input_proj = nn.Linear(n_feat, d_model)
                encoder_layer = nn.TransformerEncoderLayer(
                    d_model=d_model,
                    nhead=max(1, d_model // 8),
                    dim_feedforward=d_model * 2,
                    batch_first=True,
                    dropout=0.0,
                )
                self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=1)
                self.output_proj = nn.Linear(d_model, n_feat)

            def forward(self, x: Any) -> Any:
                # x: (batch, window, n_feat)
                z = self.input_proj(x)
                z = self.encoder(z)
                return self.output_proj(z)

        net = _TSAnomalyNet(n_feat, ws)
        optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)
        criterion = nn.MSELoss()

        # ── 슬라이딩 윈도우 배치 구성 ──────────────────────────────
        X_t = torch.tensor(X, dtype=torch.float32)
        n = len(X_t)
        if n < ws:
            windows = X_t.unsqueeze(0)  # (1, n, feat)
        else:
            windows = X_t.unfold(0, ws, 1).permute(0, 2, 1)  # (n-ws+1, ws, feat)

        batch_size = 64
        n_epochs = 10
        net.train()
        for _ in range(n_epochs):
            perm = torch.randperm(len(windows))
            for start in range(0, len(windows), batch_size):
                batch = windows[perm[start : start + batch_size]]
                pred = net(batch)
                loss = criterion(pred, batch)
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

        self._net = net

        # ── 학습 데이터 점수 저장 (임계 결정용) ──────────────────
        self._train_scores = self._compute_scores(X)
        return self

    def _compute_scores(self, X: np.ndarray) -> np.ndarray:
        """MSE 재구성 오류 → per-sample anomaly score."""
        try:
            import torch
        except ImportError as exc:
            raise ImportError(
                f"{self.model_name} 추론에는 PyTorch가 필요합니다. "
                "requirements/handlers-anomaly.txt 에 torch>=2.0 추가 후 재설치하세요."
            ) from exc

        net = self._net
        if net is None:
            raise RuntimeError(f"{self.model_name}: fit() 을 먼저 호출하세요.")

        ws = self.window_size
        X_t = torch.tensor(X, dtype=torch.float32)
        n = len(X_t)
        net.eval()

        sample_errors = np.zeros(n, dtype=float)
        sample_counts = np.zeros(n, dtype=int)

        with torch.no_grad():
            if n < ws:
                w = X_t.unsqueeze(0)  # (1, n, feat)
                pred = net(w).squeeze(0)  # (n, feat)
                err = float(((X_t - pred) ** 2).mean().item())
                sample_errors[:] += err
                sample_counts[:] += 1
            else:
                for i in range(n - ws + 1):
                    w = X_t[i : i + ws].unsqueeze(0)  # (1, ws, feat)
                    pred = net(w).squeeze(0)  # (ws, feat)
                    errors = ((X_t[i : i + ws] - pred) ** 2).mean(dim=1).numpy()
                    for j in range(ws):
                        sample_errors[i + j] += errors[j]
                        sample_counts[i + j] += 1

        mask = sample_counts > 0
        sample_errors[mask] /= sample_counts[mask]
        return sample_errors

    def decision_function(self, X: np.ndarray) -> np.ndarray:
        """PyOD 규약: 높을수록 이상 (MSE 재구성 오류 직접 반환)."""
        return self._compute_scores(X)


def _train_torch_ts_model(model_name: str, X_train: np.ndarray, params: dict[str, Any]) -> "_TorchTSAnomalyModel":
    """TranAD / AnomalyTransformer 학습 진입점."""
    window_size = int(params.get("window_size", 16))
    n_features = X_train.shape[1] if X_train.ndim == 2 else 1
    m = _TorchTSAnomalyModel(model_name=model_name, n_features=n_features, window_size=window_size)
    m.fit(X_train)
    return m


def _get_anomaly_scores(model: Any, X: np.ndarray) -> np.ndarray:
    """모델별 anomaly score 추출 (높을수록 이상). backend-aware.

    우선순위:
      1) _ada_backend == "pyod"    → decision_function 그대로 (높을수록 이상)
      2) _ada_backend == "torch"   → decision_function 그대로 (재구성 오류, 높을수록 이상)
      3) _ada_backend == "sklearn" → score_samples 있으면 -score_samples,
                                     없으면 -decision_function, 그것도 없으면 predict
      4) 태그 없는 경우(안전망)     → __module__ 로 pyod 여부 판별 후 동일 규약 적용
    """
    backend = getattr(model, "_ada_backend", None)

    if backend == "pyod":
        return np.asarray(model.decision_function(X), dtype=float)

    if backend == "torch":
        return np.asarray(model.decision_function(X), dtype=float)

    if backend == "sklearn":
        if hasattr(model, "score_samples"):
            return -np.asarray(model.score_samples(X), dtype=float)
        if hasattr(model, "decision_function"):
            return -np.asarray(model.decision_function(X), dtype=float)
        return np.asarray(model.predict(X), dtype=float)

    # 안전망: _ada_backend 없는 경우 모듈명으로 판별
    module = type(model).__module__ or ""
    if module.startswith("pyod"):
        return np.asarray(model.decision_function(X), dtype=float)
    # sklearn 규약 (높을수록 정상 → 반전)
    if hasattr(model, "score_samples"):
        return -np.asarray(model.score_samples(X), dtype=float)
    if hasattr(model, "decision_function"):
        return -np.asarray(model.decision_function(X), dtype=float)
    return np.asarray(model.predict(X), dtype=float)


NORMALIZE_CLIP_LOW = 0.05  # ★ A-3 (옵션 B)
NORMALIZE_CLIP_HIGH = 0.95  # ★ A-3 (옵션 B)


def _normalize_scores_rank(scores: np.ndarray) -> np.ndarray:
    """★ V4: rank 기반 정규화 [0, 1] — 이종 detector 점수 결합용.

    근거: 스케일이 다른 detector 점수의 min-max 결합은 극단값 1개가
    전체 분포를 압축해 ensemble 을 왜곡 (Kriegel et al., SDM 2011
    "Interpreting and Unifying Outlier Scores"; Aggarwal & Sathe, 2015
    "Theoretical Foundations and Algorithms for Outlier Ensembles").
    rank 는 단조변환에 불변 → detector 간 스케일 차이를 구조적으로 제거.
    동점은 평균 rank (scipy 없이 구현, 결정적).
    """
    n = len(scores)
    if n == 0:
        return np.asarray(scores, dtype=float)
    if n == 1:
        return np.array([0.5])
    order = np.argsort(scores, kind="stable")
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(n, dtype=float)
    # 동점 평균 rank
    sorted_vals = np.asarray(scores, dtype=float)[order]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and sorted_vals[j + 1] == sorted_vals[i]:
            j += 1
        if j > i:
            avg = (i + j) / 2.0
            ranks[order[i : j + 1]] = avg
        i = j + 1
    return ranks / (n - 1)


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
        "ECOD",  # ★ V4 (Li et al., 2022 TKDE)
        "HBOS",  # ★ V4 (Goldstein & Dengel, 2012)
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
        """단일 모델 학습 (PyOD 우선, sklearn fallback). MLflow 로깅.

        학습된 model 에 ``_ada_model_name`` 속성을 부착해 predict/evaluate 가
        모델 종류별 분기(_get_anomaly_scores 의 IsolationForest_sklearn 등)를
        정확히 수행할 수 있게 한다.
        """
        from contextlib import nullcontext

        try:
            mlflow_ctx: Any = self._start_mlflow_run(tags={"model": model_name})
        except Exception:
            mlflow_ctx = nullcontext()

        with mlflow_ctx:
            try:
                import mlflow  # noqa: WPS433

                mlflow.log_params({**params, "model_name": model_name})
            except Exception:
                pass
            model = _train_one_model(model_name, X_train, params)
            try:
                model._ada_model_name = model_name  # noqa: SLF001
            except Exception:  # noqa: BLE001  — 일부 C 확장 모델은 동적 속성 불가
                pass
            return model

    @staticmethod
    def _resolve_model_name(model: Any) -> str:
        """train 에서 부착한 _ada_model_name 우선, 없으면 클래스명 fallback."""
        nm = getattr(model, "_ada_model_name", None)
        if isinstance(nm, str) and nm:
            return nm
        return type(model).__name__

    def predict(self, model: Any, X: Any) -> np.ndarray:
        """anomaly_score 반환 (높을수록 이상)."""
        return _get_anomaly_scores(model, X)

    def evaluate(
        self,
        model: Any,
        X_val: Any,
        y_val: Any,
        task: str = "anomaly",
    ) -> dict[str, float]:
        """AUC + Otsu + predicted_anomalies. ★ DoD: AUC > 0.8."""
        scores = _get_anomaly_scores(model, X_val)
        # static method 이므로 클래스 경유 호출이 스타일상 명확
        threshold = AnomalyPipeline.otsu_threshold(scores)
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

                auc_val = float(roc_auc_score(y_val, scores))
                metrics["auc"] = auc_val
                metrics["val_auc"] = auc_val
            except Exception:
                metrics["auc"] = None
                metrics["val_auc"] = None
        else:
            metrics["auc"] = None
            metrics["val_auc"] = None
        return metrics

    # static 헬퍼 (public — Day 7·9 도 사용)
    @staticmethod
    def normalize_scores(scores: np.ndarray) -> np.ndarray:
        return _normalize_scores(scores)

    @staticmethod
    def normalize_scores_rank(scores: np.ndarray) -> np.ndarray:
        """★ V4: 이종 detector 결합용 rank 정규화 (Day 7 ensemble 이 소비)."""
        return _normalize_scores_rank(scores)

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
    """A-2 (Day 6, 2026-05-29) — Otsu vs contamination sanity."""
    scores = np.asarray(scores, dtype=float).ravel()
    if scores.size == 0:
        return 0.0, {"method": "otsu", "reason": "empty", "otsu_value": 0.0, "contam_value": 0.0}
    otsu_v = float(_otsu_threshold(scores))
    contam_v = float(np.quantile(scores, 1.0 - float(contamination))) if 0 < contamination < 1 else otsu_v
    otsu_ratio = float((scores >= otsu_v).mean())
    if otsu_ratio > 5.0 * max(contamination, 1e-6):
        return contam_v, {
            "method": "contamination",
            "reason": f"otsu_ratio {otsu_ratio:.3f} > 5x",
            "otsu_value": otsu_v,
            "contam_value": contam_v,
        }
    return otsu_v, {"method": "otsu", "reason": "within range", "otsu_value": otsu_v, "contam_value": contam_v}

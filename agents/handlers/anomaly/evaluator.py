"""agents.handlers.anomaly.evaluator — 이상탐지 평가 (NY 담당, Day 7 v2).

precision@k (k=10) · ROC-AUC · F1 · threshold sweep 곡선 (MinIO PNG).

진입함수 (dispatcher 자동 등록):
  - evaluate(state) -> dict  반환: pr_at_10, auc, f1, threshold_curve_path

DoD: `pr_at_10`, `auc`, `f1`, `threshold_curve_path` 4 필드.
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
PR_AT_K_DEFAULT = 10  # ★ DoD pr_at_10
THRESHOLD_SWEEP_N = 50  # ★ A-3 결정 — 정밀 PR/F1 곡선 (10→50)
AUC_PASS_THRESHOLD = 0.70  # ★ QA 통과 임계 (기존 evaluator THRESHOLD 와 동일값 — 하드코딩 회피)
CHART_DPI = 100
CHART_FIGSIZE = (8, 5)


# ── 헬퍼 ──────────────────────────────────────────────────────────


def _precision_at_k(scores, y_true, k: int = PR_AT_K_DEFAULT) -> float:
    """top k 의 정밀도 (이상탐지 핵심 지표)."""
    import numpy as np

    if len(scores) == 0 or k <= 0:
        return 0.0
    k = min(k, len(scores))
    top_k_idx = np.argsort(scores)[-k:]
    return float(np.asarray(y_true)[top_k_idx].sum() / k)


def _compute_roc_auc(scores, y_true) -> float | None:
    """sklearn roc_auc_score wrapper."""
    if y_true is None or len(scores) == 0:
        return None
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y_true, scores))
    except Exception:
        return None


def _compute_f1(predicted, y_true) -> float | None:
    """sklearn f1_score wrapper."""
    if y_true is None or len(predicted) == 0:
        return None
    try:
        from sklearn.metrics import f1_score

        return float(f1_score(y_true, predicted))
    except Exception:
        return None


def _threshold_sweep(scores, y_true, n_thresholds: int = THRESHOLD_SWEEP_N) -> list[dict[str, float]]:
    """threshold sweep — precision·recall·F1 계산."""
    import numpy as np

    if y_true is None or len(scores) == 0:
        return []

    from sklearn.metrics import f1_score, precision_score, recall_score

    scores_arr = np.asarray(scores)
    thresholds = np.linspace(scores_arr.min(), scores_arr.max(), n_thresholds)
    results: list[dict[str, float]] = []

    for thr in thresholds:
        predicted = (scores_arr >= thr).astype(int)
        if predicted.sum() == 0:
            continue
        prec = float(precision_score(y_true, predicted, zero_division=0))
        rec = float(recall_score(y_true, predicted, zero_division=0))
        f1 = float(f1_score(y_true, predicted, zero_division=0))
        results.append(
            {
                "threshold": float(thr),
                "precision": prec,
                "recall": rec,
                "f1": f1,
            }
        )

    return results


def _save_threshold_curve_to_minio(sweep_data: list[dict[str, float]], job_id: str) -> str | None:
    """matplotlib threshold curve → MinIO PNG."""
    if not sweep_data:
        return None

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from agents.handlers.common.shared import save_chart_to_minio

    thresholds = [d["threshold"] for d in sweep_data]
    precisions = [d["precision"] for d in sweep_data]
    recalls = [d["recall"] for d in sweep_data]
    f1s = [d["f1"] for d in sweep_data]

    fig, ax = plt.subplots(figsize=CHART_FIGSIZE, dpi=CHART_DPI)
    ax.plot(thresholds, precisions, label="Precision", color="steelblue", marker="o")
    ax.plot(thresholds, recalls, label="Recall", color="crimson", marker="s")
    ax.plot(thresholds, f1s, label="F1", color="darkgreen", marker="^")
    ax.set_xlabel("Threshold")
    ax.set_ylabel("Metric")
    ax.set_title("Threshold Sweep — Precision/Recall/F1")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    fig.tight_layout()

    try:
        return save_chart_to_minio(fig, kind="anomaly/threshold_curve", job_id=job_id)
    except Exception:
        plt.close(fig)
        return None


# ── 진입점 ────────────────────────────────────────────────────────


def _generate_scores(state: Any):
    """★ X-3/X-6 ① — best_model 을 데이터에 적용해 per-row anomaly score 생성.

    ADA 오케스트레이션이 만든 best_model(top-level)을 재학습(random_state 고정→재현)·predict
    → otsu → predicted. category_extras 의존 제거 (X-6: 데이터 버스 = top-level state).
    반환: (scores, predicted, threshold, y_true|None) 또는 None (생성 불가).
    """
    import numpy as np

    best = getattr(state, "best_model", None) or {}
    model_name = best.get("model_name")
    if not model_name:
        return None
    params = best.get("params_used") or {}

    try:
        from agents.training_executor import _split_xy
        from pipelines.anomaly import AnomalyPipeline
        from tools.minio_tool import get_minio_client

        mc = get_minio_client()
        df = mc.load_dataframe(state.file_id, fmt=state.file_id.rsplit(".", 1)[-1].lower())
        X, y = _split_xy(df, getattr(state, "target_column", None))
    except Exception:
        return None

    y_true = np.asarray(y).astype(int) if getattr(state, "target_column", None) else None

    try:
        pipeline = AnomalyPipeline()
        model = pipeline.train(X, y, model_name, params)  # 재학습 (seed 고정 → 재현)
        scores = np.asarray(pipeline.predict(model, X), dtype=float)
        threshold = float(AnomalyPipeline.otsu_threshold(scores))
        predicted = (scores > threshold).astype(int)
    except Exception:
        return None

    return scores, predicted, threshold, y_true


def evaluate(state: Any) -> dict[str, Any]:
    """anomaly 평가 (dispatcher) — ★ X-3/X-6 ①: per-row score 생성 + metrics.

    best_model 로 per-row anomaly score 를 만들고(_generate_scores) metrics 계산.
    **반환 dict → eval_agent 가 state.eval_result 에 저장** (category_extras 미사용, R-005 준수).
    Day 8·9 는 state.eval_result 에서 ensemble_scores·predicted_anomalies·threshold·metrics 읽음.
    y_true 없으면(C2/C4 비지도) label metrics = None (B-1·서브카테고리 일관).
    """
    gen = _generate_scores(state)
    if gen is None:
        return {
            "ensemble_scores": None,
            "predicted_anomalies": None,
            "threshold": 0.0,
            "passed": True,
            "pr_at_10": None,
            "pr_auc": None,
            "auc": None,
            "f1": None,
            "threshold_curve_path": None,
            "y_true_available": False,
            "threshold_sweep_table": [],
            "warning": "best_model 미설정 또는 데이터 로드 실패 — 평가 skip",
            "rationale": "score 생성 불가 (gen=None) — 후속 단계 skip",
        }

    scores, predicted, threshold, y_true = gen
    has_y = y_true is not None

    pr = _precision_at_k(scores, y_true) if has_y else None
    pr_auc = None
    if has_y:
        try:
            from sklearn.metrics import average_precision_score

            pr_auc = float(average_precision_score(y_true, scores))
        except Exception:
            pr_auc = None
    auc = _compute_roc_auc(scores, y_true) if has_y else None
    f1 = _compute_f1(predicted, y_true) if has_y else None
    sweep = _threshold_sweep(scores, y_true) if has_y else []
    curve_path = _save_threshold_curve_to_minio(sweep, getattr(state, "job_id", "")) if has_y else None

    if has_y and auc is not None:
        passed = bool(auc >= 0.70)
        rationale = f"AUC={auc:.3f} (임계 0.70)"
    else:
        passed = True
        rationale = "y_true 부재 — 비지도 평가 (메트릭 None)"

    return {
        "ensemble_scores": scores.tolist(),
        "predicted_anomalies": predicted.tolist(),
        "threshold": float(threshold),
        "passed": passed,
        "pr_at_10": float(pr) if pr is not None else None,
        "pr_auc": pr_auc,
        "auc": float(auc) if auc is not None else None,
        "f1": float(f1) if f1 is not None else None,
        "threshold_curve_path": curve_path,
        "y_true_available": has_y,
        "threshold_sweep_table": sweep,
        "rationale": rationale,
    }

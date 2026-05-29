"""agents.handlers.tabular.evaluator — 정형 평가 (jh 담당).

Day 6 기준: ``best_model.metrics`` 임계치 판정.
Day 7 보강: 예측값(y_true / y_pred / y_prob)으로부터
  - accuracy / f1 / precision / recall
  - ROC-AUC (binary 1d, multiclass OvR macro)
  - calibration (Brier score + ECE)  ->  ``calibration_brier`` 필드 (DoD)
  - 다중 임계치 sweep (binary)        ->  ``best_threshold``
를 계산해 ``eval_result`` 에 병합한다.

예측 데이터 소스 (우선순위):
  1. ``state.category_extras["tabular"]["predictions"]`` = {"y_true","y_pred","y_prob"}
  2. ``state.category_extras["tabular"]`` 최상위 동일 키
  3. ``state.best_model`` 동일 키
모두 없으면 ``calibration_brier=None`` / ``threshold_sweep=[]`` 로 graceful degrade.

기본 임계: tabular_ml val_f1>=0.65, val_accuracy>=0.70. tabular_dl val_f1>=0.70.

R-005: state 직접 수정 금지 — dict 만 반환. dispatcher(eval_agent) 가 with_update 처리.
"""

from __future__ import annotations

from typing import Any

THRESHOLDS_BY_CAT = {
    "tabular_ml": {"val_f1": 0.65, "val_accuracy": 0.70},
    "tabular_dl": {"val_f1": 0.70},
}

# 다중 임계치 sweep 구간 (binary 분류 전용) — 0.05 .. 0.95
_SWEEP_THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]


# 입력 추출 ────────────────────────────────────────────────────────────────


def _as_array(x: Any):
    if x is None:
        return None
    try:
        import numpy as np  # noqa: WPS433

        arr = np.asarray(x)
        return arr if arr.size > 0 else None
    except Exception:
        return None


def _extract_eval_data(state: Any):
    """(y_true, y_pred, y_prob) 추출. 누락 허용 -> None."""
    ce = getattr(state, "category_extras", {}) or {}
    tab = ce.get("tabular", {}) or {}
    preds = tab.get("predictions", {}) or {}
    bm = getattr(state, "best_model", None) or {}

    def _pick(key: str):
        for src in (preds, tab, bm):
            if isinstance(src, dict) and src.get(key) is not None:
                return src[key]
        return None

    return _as_array(_pick("y_true")), _as_array(_pick("y_pred")), _as_array(_pick("y_prob"))


def _resolve_task_type(state: Any, y_true) -> str | None:
    """task_type 결정: best_model.task_type -> state.task -> y_true 추론."""
    bm = getattr(state, "best_model", None) or {}
    tt = bm.get("task_type")
    if tt in ("binary", "multiclass", "regression"):
        return tt

    task = (getattr(state, "task", "auto") or "auto").lower()
    if task == "regression":
        return "regression"

    n_unique = None
    if y_true is not None:
        try:
            import numpy as np  # noqa: WPS433

            yt = np.asarray(y_true)
            n_unique = int(np.unique(yt).size)
            if task != "classification" and yt.dtype.kind in "fc":
                # 실수형: 정수값 + 소수 클래스만 분류로 간주, 그 외 회귀
                if not (np.allclose(yt, np.round(yt)) and n_unique <= 20):
                    return "regression"
        except Exception:
            n_unique = None

    if task == "classification" or n_unique is not None:
        if n_unique == 2:
            return "binary"
        if n_unique is not None and n_unique <= 50:
            return "multiclass"
        if task == "classification":
            return "binary"
        return "regression"
    return None


def _binary_prob(y_prob):
    """양성 클래스 확률 1d 벡터 추출."""
    if y_prob is None:
        return None
    try:
        import numpy as np  # noqa: WPS433

        p = np.asarray(y_prob, dtype=float)
        if p.ndim == 1:
            return p
        if p.ndim == 2:
            if p.shape[1] == 2:
                return p[:, 1]
            if p.shape[1] == 1:
                return p.ravel()
        return None
    except Exception:
        return None


# 계산 ─────────────────────────────────────────────────────────────────────


def _compute_calibration(y_true, prob1):
    """(brier, ece) 반환. ECE 는 10-bin count-weighted."""
    import numpy as np  # noqa: WPS433
    from sklearn.metrics import brier_score_loss  # noqa: WPS433

    yt = np.asarray(y_true).astype(float)
    p = np.asarray(prob1, dtype=float)
    try:
        brier = float(brier_score_loss(yt, p))
    except Exception:
        brier = float(np.mean((p - yt) ** 2))

    bins = np.linspace(0.0, 1.0, 11)
    bin_ids = np.clip(np.digitize(p, bins) - 1, 0, 9)
    n = len(yt)
    ece = 0.0
    for b in range(10):
        mask = bin_ids == b
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        conf = float(p[mask].mean())
        acc = float(yt[mask].mean())
        ece += (cnt / n) * abs(acc - conf)
    return brier, float(ece)


def _threshold_sweep(y_true, prob1):
    """binary 임계치 sweep -> (sweep_list, best_threshold, best_f1)."""
    import numpy as np  # noqa: WPS433
    from sklearn.metrics import f1_score, precision_score, recall_score  # noqa: WPS433

    yt = np.asarray(y_true).astype(int)
    p = np.asarray(prob1, dtype=float)
    sweep = []
    for t in _SWEEP_THRESHOLDS:
        y_hat = (p >= t).astype(int)
        sweep.append(
            {
                "threshold": t,
                "f1": round(float(f1_score(yt, y_hat, zero_division=0)), 4),
                "precision": round(float(precision_score(yt, y_hat, zero_division=0)), 4),
                "recall": round(float(recall_score(yt, y_hat, zero_division=0)), 4),
            }
        )
    best = max(sweep, key=lambda d: d["f1"]) if sweep else None
    return sweep, (best["threshold"] if best else None), (best["f1"] if best else None)


def _multiclass_brier(y_true, y_prob):
    import numpy as np  # noqa: WPS433

    try:
        yp = np.asarray(y_prob, dtype=float)
        yt = np.asarray(y_true)
        classes = np.unique(yt)
        if yp.ndim != 2 or yp.shape[1] < len(classes):
            return None
        idx = {c: i for i, c in enumerate(classes)}
        oh = np.zeros_like(yp)
        for i, c in enumerate(yt):
            j = idx.get(c)
            if j is not None and j < yp.shape[1]:
                oh[i, j] = 1.0
        return float(np.mean(np.sum((yp - oh) ** 2, axis=1)))
    except Exception:
        return None


def _compute_classification(y_true, y_pred, y_prob, task_type: str) -> dict[str, Any]:
    import numpy as np  # noqa: WPS433
    from sklearn.metrics import (  # noqa: WPS433
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    out: dict[str, Any] = {
        "metrics": {
            "val_accuracy": float(accuracy_score(y_true, y_pred)),
            "val_f1": float(f1_score(y_true, y_pred, average="weighted")),
            "val_precision": float(precision_score(y_true, y_pred, average="weighted", zero_division=0)),
            "val_recall": float(recall_score(y_true, y_pred, average="weighted", zero_division=0)),
        },
        "roc_auc": None,
        "calibration_brier": None,
        "calibration_ece": None,
        "threshold_sweep": [],
        "best_threshold": None,
    }

    if task_type == "binary":
        prob1 = _binary_prob(y_prob)
        if prob1 is not None:
            try:
                out["roc_auc"] = float(roc_auc_score(y_true, prob1))
            except Exception:
                pass
            try:
                out["calibration_brier"], out["calibration_ece"] = _compute_calibration(y_true, prob1)
            except Exception:
                pass
            try:
                sweep, best_t, _ = _threshold_sweep(y_true, prob1)
                out["threshold_sweep"] = sweep
                out["best_threshold"] = best_t
            except Exception:
                pass
    elif task_type == "multiclass":
        yp = np.asarray(y_prob, dtype=float) if y_prob is not None else None
        if yp is not None and yp.ndim == 2:
            try:
                out["roc_auc"] = float(roc_auc_score(y_true, yp, multi_class="ovr", average="macro"))
            except Exception:
                pass
            out["calibration_brier"] = _multiclass_brier(y_true, yp)
    return out


def _compute_regression(y_true, y_pred) -> dict[str, float]:
    import numpy as np  # noqa: WPS433
    from sklearn.metrics import (  # noqa: WPS433
        mean_absolute_error,
        mean_squared_error,
        r2_score,
    )

    return {
        "val_rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "val_r2": float(r2_score(y_true, y_pred)),
        "val_mae": float(mean_absolute_error(y_true, y_pred)),
    }


# 진입점 ───────────────────────────────────────────────────────────────────


def evaluate(state: Any) -> dict[str, Any]:
    best = getattr(state, "best_model", None) or {}
    base_metrics = dict(best.get("metrics") or {})

    y_true, y_pred, y_prob = _extract_eval_data(state)
    task_type = _resolve_task_type(state, y_true)

    computed: dict[str, Any] = {}
    calibration_brier = base_metrics.get("calibration_brier")
    calibration_ece = None
    roc_auc = base_metrics.get("val_roc_auc")
    threshold_sweep: list[dict[str, Any]] = []
    best_threshold = None

    if y_true is not None and y_pred is not None:
        try:
            if task_type in ("binary", "multiclass"):
                cls = _compute_classification(y_true, y_pred, y_prob, task_type)
                computed.update(cls["metrics"])
                calibration_brier = cls["calibration_brier"] if cls["calibration_brier"] is not None else calibration_brier
                calibration_ece = cls["calibration_ece"]
                roc_auc = cls["roc_auc"] if cls["roc_auc"] is not None else roc_auc
                threshold_sweep = cls["threshold_sweep"]
                best_threshold = cls["best_threshold"]
            elif task_type == "regression":
                computed.update(_compute_regression(y_true, y_pred))
        except Exception:  # 평가 보강 실패가 게이트를 깨지 않도록
            pass

    # best_model.metrics 가 권위 — 계산값은 빈 키만 보충
    metrics = {**computed, **base_metrics}
    if calibration_brier is not None:
        metrics.setdefault("calibration_brier", calibration_brier)
    if roc_auc is not None:
        metrics.setdefault("val_roc_auc", roc_auc)

    # Day 6 임계치 판정 (병합된 metrics 기준)
    thr = THRESHOLDS_BY_CAT.get(state.category, {})
    violations: list[str] = []
    for k, t in thr.items():
        v = metrics.get(k)
        if v is not None and float(v) < t:
            violations.append(f"{k}<{t} (got {float(v):.3f})")
    passed = len(violations) == 0

    return {
        "passed": passed,
        "rationale": "임계치 통과" if passed else "; ".join(violations),
        "threshold_violations": violations,
        "metrics": metrics,
        "task_type": task_type,
        "calibration_brier": calibration_brier,
        "calibration_ece": calibration_ece,
        "roc_auc": roc_auc,
        "threshold_sweep": threshold_sweep,
        "best_threshold": best_threshold,
    }

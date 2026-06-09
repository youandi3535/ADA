"""agents.handlers.tabular.threshold_optimizer — cost-sensitive 임계치 (jh, Day 11++).

문제 정의
========
이진 분류에서 기본 임계치 0.5 는 "비용 대칭 가정" 위에서만 옳다. 실무에선
FN/FP 비용이 크게 비대칭:
  - 사기탐지     : FN 280k (사기 통과) vs FP 2k (정상 거래 차단)
  - 이탈 방지    : FN 180k (이탈 놓침) vs FP 5k (불필요 캠페인)
  - 의료 진단    : FN 사람 목숨 vs FP 추가 검사

비대칭 비용에서 0.5 임계치를 쓰면 expected_cost 가 최소가 아님. 사용자가
산출물 받아도 "어떤 임계치를 쓰라"는 정량 답이 빠져 있던 상태.

본 모듈은 4 전략을 동일 데이터에서 비교 + 자동 권고:
  - F1-max     : F1 점수 최대화 (기본, 비용 대칭 가정)
  - cost-min   : expected_cost 최소화 (cost_matrix 입력 시)
  - Youden J   : TPR - FPR 최대화 (민감도·특이도 균형)
  - recall-min : recall ≥ 목표(0.9)에서 precision 최대 (FN 절대 회피)

Calibration 본구현 후에야 의미가 있음 — 보정된 확률 위에서 expected_cost
계산이 정직해짐. category_extras["tabular"]["calibration"] 의 method 가
있으면 보정된 확률을 자동 사용.

저장 위치
=========
state.category_extras["tabular"]["threshold_strategies"] = {
    "strategies": {
        "f1_max":     {"threshold": float, "f1": float, "precision": float,
                       "recall": float, "expected_cost": float | None},
        "cost_min":   {...} | None,   # cost_matrix 없으면 None
        "youden_j":   {"threshold": float, "tpr": float, "fpr": float,
                       "j_statistic": float, "expected_cost": float | None},
        "recall_min": {"threshold": float, "recall": float, "precision": float,
                       "expected_cost": float | None} | None,  # 달성 불가 시 None
    },
    "recommended": "cost_min" | "f1_max",
    "cost_matrix": {"fp": float, "fn": float, "tp": float, "tn": float},
    "calibrated": bool,
    "target_recall": float,
    "chart_path": str | None,
    "n_samples_used": int,
    "skipped_reason": str | None,
}
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib  # noqa: WPS433

matplotlib.use("Agg")

logger = logging.getLogger(__name__)


# 상수
_THRESHOLD_GRID = 99  # 0.01 ~ 0.99 단위 0.01
_DEFAULT_TARGET_RECALL = 0.9
_DEFAULT_COST_MATRIX = {"tp": 0.0, "tn": 0.0, "fp": 1.0, "fn": 1.0}  # 비용 대칭
_MIN_VAL_SAMPLES = 50


# ──────────────────────────────────────────────────────────────────────────────
# 내부 — confusion matrix + expected cost
# ──────────────────────────────────────────────────────────────────────────────


def _confusion(y_true: Any, y_pred: Any) -> tuple[int, int, int, int]:
    """confusion matrix → (tn, fp, fn, tp). 결정론."""
    import numpy as np

    y_true = np.asarray(y_true).astype(int)
    y_pred = np.asarray(y_pred).astype(int)
    tn = int(((y_true == 0) & (y_pred == 0)).sum())
    fp = int(((y_true == 0) & (y_pred == 1)).sum())
    fn = int(((y_true == 1) & (y_pred == 0)).sum())
    tp = int(((y_true == 1) & (y_pred == 1)).sum())
    return tn, fp, fn, tp


def compute_expected_cost(
    y_true: Any, y_proba: Any, threshold: float, cost_matrix: dict[str, float]
) -> float:
    """주어진 임계치에서 expected_cost = TN·c_tn + FP·c_fp + FN·c_fn + TP·c_tp."""
    import numpy as np

    y_pred = (np.asarray(y_proba) >= threshold).astype(int)
    tn, fp, fn, tp = _confusion(y_true, y_pred)
    cost = (
        tn * float(cost_matrix.get("tn", 0.0))
        + fp * float(cost_matrix.get("fp", 1.0))
        + fn * float(cost_matrix.get("fn", 1.0))
        + tp * float(cost_matrix.get("tp", 0.0))
    )
    return float(cost)


def _metrics_at(y_true: Any, y_proba: Any, threshold: float) -> dict[str, float]:
    """주어진 임계치에서 F1/precision/recall/TPR/FPR 계산."""
    import numpy as np

    y_pred = (np.asarray(y_proba) >= threshold).astype(int)
    tn, fp, fn, tp = _confusion(y_true, y_pred)
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    f1 = 2 * precision * recall / max(precision + recall, 1e-9)
    tpr = recall
    fpr = fp / max(fp + tn, 1)
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "tpr": float(tpr),
        "fpr": float(fpr),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 4 전략 grid search
# ──────────────────────────────────────────────────────────────────────────────


def _grid() -> Any:
    """0.01 ~ 0.99 임계치 그리드."""
    import numpy as np

    return np.linspace(0.01, 0.99, _THRESHOLD_GRID)


def find_f1_max(y_true: Any, y_proba: Any, cost_matrix: dict[str, float] | None = None) -> dict[str, Any]:
    """F1-max 임계치 — F1 점수 최대화. 비용 대칭 가정."""
    import numpy as np

    grid = _grid()
    f1s = np.array([_metrics_at(y_true, y_proba, t)["f1"] for t in grid])
    best_idx = int(np.argmax(f1s))
    t = float(grid[best_idx])
    m = _metrics_at(y_true, y_proba, t)
    return {
        "threshold": round(t, 3),
        "f1": round(m["f1"], 4),
        "precision": round(m["precision"], 4),
        "recall": round(m["recall"], 4),
        "expected_cost": (
            round(compute_expected_cost(y_true, y_proba, t, cost_matrix), 2)
            if cost_matrix else None
        ),
    }


def find_cost_min(y_true: Any, y_proba: Any, cost_matrix: dict[str, float]) -> dict[str, Any]:
    """cost-min 임계치 — expected_cost 최소화. cost_matrix 필수."""
    import numpy as np

    grid = _grid()
    costs = np.array([
        compute_expected_cost(y_true, y_proba, t, cost_matrix) for t in grid
    ])
    best_idx = int(np.argmin(costs))
    t = float(grid[best_idx])
    m = _metrics_at(y_true, y_proba, t)
    return {
        "threshold": round(t, 3),
        "f1": round(m["f1"], 4),
        "precision": round(m["precision"], 4),
        "recall": round(m["recall"], 4),
        "expected_cost": round(float(costs[best_idx]), 2),
    }


def find_youden_j(y_true: Any, y_proba: Any, cost_matrix: dict[str, float] | None = None) -> dict[str, Any]:
    """Youden J — TPR - FPR 최대화. 민감도·특이도 균형."""
    import numpy as np

    grid = _grid()
    js = []
    for t in grid:
        m = _metrics_at(y_true, y_proba, t)
        js.append(m["tpr"] - m["fpr"])
    js_arr = np.array(js)
    best_idx = int(np.argmax(js_arr))
    t = float(grid[best_idx])
    m = _metrics_at(y_true, y_proba, t)
    return {
        "threshold": round(t, 3),
        "tpr": round(m["tpr"], 4),
        "fpr": round(m["fpr"], 4),
        "j_statistic": round(float(js_arr[best_idx]), 4),
        "f1": round(m["f1"], 4),
        "expected_cost": (
            round(compute_expected_cost(y_true, y_proba, t, cost_matrix), 2)
            if cost_matrix else None
        ),
    }


def find_recall_min(
    y_true: Any,
    y_proba: Any,
    target_recall: float = _DEFAULT_TARGET_RECALL,
    cost_matrix: dict[str, float] | None = None,
) -> dict[str, Any] | None:
    """recall-min — recall ≥ target 조건에서 precision 최대. 달성 불가면 None."""
    import numpy as np

    grid = _grid()
    feasible: list[tuple[float, dict[str, float]]] = []
    for t in grid:
        m = _metrics_at(y_true, y_proba, t)
        if m["recall"] >= target_recall:
            feasible.append((float(t), m))

    if not feasible:
        return None

    # precision 최대 (동률 시 가장 큰 임계치 = recall 가까운 쪽)
    feasible.sort(key=lambda x: (-x[1]["precision"], -x[0]))
    t, m = feasible[0]
    return {
        "threshold": round(t, 3),
        "recall": round(m["recall"], 4),
        "precision": round(m["precision"], 4),
        "f1": round(m["f1"], 4),
        "target_recall": round(target_recall, 3),
        "expected_cost": (
            round(compute_expected_cost(y_true, y_proba, t, cost_matrix), 2)
            if cost_matrix else None
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# 진입점 — calibrate 결과 활용
# ──────────────────────────────────────────────────────────────────────────────


def _get_calibrated_proba(model_obj: Any, X_val: Any, y_val: Any, state: Any) -> Any:
    """category_extras 의 calibration.method 가 있으면 보정된 확률 반환.

    calibration.py 의 fit_platt/fit_isotonic 으로 보정함수 재구성 → 적용.
    """
    import numpy as np

    raw_proba = model_obj.predict_proba(X_val)
    if raw_proba.ndim != 2 or raw_proba.shape[1] != 2:
        return raw_proba[:, 1] if raw_proba.ndim == 2 else raw_proba
    proba = raw_proba[:, 1]

    cal_info = (
        (getattr(state, "category_extras", None) or {})
        .get("tabular", {})
        .get("calibration") or {}
    )
    method = cal_info.get("method")
    if not method:
        return proba

    try:
        from agents.handlers.tabular import calibration as _cal_mod

        y_arr = np.asarray(y_val).astype(float)
        if method == "platt":
            calibrator = _cal_mod.fit_platt(y_arr, proba)
        elif method == "isotonic":
            calibrator = _cal_mod.fit_isotonic(y_arr, proba)
        else:
            return proba
        return calibrator(proba)
    except Exception as exc:
        logger.debug("calibrator_reapply_failed: %s — raw proba 사용", exc)
        return proba


def _skipped_result(reason: str) -> dict[str, Any]:
    """가드 통과 못 했을 때 표준 빈 결과."""
    return {
        "strategies": {},
        "recommended": None,
        "cost_matrix": None,
        "calibrated": False,
        "target_recall": _DEFAULT_TARGET_RECALL,
        "chart_path": None,
        "n_samples_used": 0,
        "skipped_reason": reason,
    }


def optimize_thresholds(
    state: Any,
    cost_matrix: dict[str, float] | None = None,
    target_recall: float = _DEFAULT_TARGET_RECALL,
) -> dict[str, Any]:
    """state 기반 4 전략 임계치 자동 산출.

    cost_matrix:
        명시 입력 또는 state.category_extras["tabular"]["cost_matrix"] 에서 자동.
        없으면 cost-min 전략 skip.
    target_recall: recall-min 전략의 목표 recall (기본 0.9).
    """
    from pipelines.tabular_ml.pipeline import is_baseline_model

    bm = getattr(state, "best_model", None) or {}
    model_name = bm.get("model_name")

    # 가드
    if not model_name:
        return _skipped_result("no_best_model")
    if is_baseline_model(model_name):
        return _skipped_result("baseline_skip")
    metrics = bm.get("metrics") or {}
    if "val_r2" in metrics and "val_f1" not in metrics:
        return _skipped_result("regression_not_supported")

    # 모델 + 데이터 재로드
    from agents.handlers.tabular.output_extras import _try_reload_model_and_data

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return _skipped_result("model_reload_failed")

    model_obj, X_val, y_val = reload
    if not hasattr(model_obj, "predict_proba"):
        return _skipped_result("no_predict_proba")

    try:
        import numpy as np

        y_proba = _get_calibrated_proba(model_obj, X_val, y_val, state)
        y_arr = np.asarray(y_val).astype(int)

        # 이진분류 확인
        if y_proba.ndim != 1 and y_proba.shape[1] != 1:
            return _skipped_result("multiclass_not_supported")
        if len(y_arr) < _MIN_VAL_SAMPLES:
            return _skipped_result(f"too_few_samples_lt_{_MIN_VAL_SAMPLES}")
        if len(np.unique(y_arr)) < 2:
            return _skipped_result("single_class_only")

        # cost_matrix 자동 입력
        cat_extras = (getattr(state, "category_extras", None) or {}).get("tabular", {})
        if cost_matrix is None:
            cost_matrix = cat_extras.get("cost_matrix")

        # 4 전략 산출
        strategies: dict[str, Any] = {}
        strategies["f1_max"] = find_f1_max(y_arr, y_proba, cost_matrix)

        if cost_matrix and (
            cost_matrix.get("fp", 0) > 0 or cost_matrix.get("fn", 0) > 0
        ):
            strategies["cost_min"] = find_cost_min(y_arr, y_proba, cost_matrix)
        else:
            strategies["cost_min"] = None

        strategies["youden_j"] = find_youden_j(y_arr, y_proba, cost_matrix)
        strategies["recall_min"] = find_recall_min(y_arr, y_proba, target_recall, cost_matrix)

        # 권고: cost_matrix 있고 cost_min 산출됐으면 cost_min, 아니면 f1_max
        if cost_matrix and strategies.get("cost_min"):
            recommended = "cost_min"
        else:
            recommended = "f1_max"

        # 차트
        chart_path = _build_strategy_chart(y_arr, y_proba, strategies, state)

        calibrated = bool(
            (cat_extras.get("calibration") or {}).get("method")
        )

        return {
            "strategies": strategies,
            "recommended": recommended,
            "cost_matrix": cost_matrix,
            "calibrated": calibrated,
            "target_recall": target_recall,
            "chart_path": chart_path,
            "n_samples_used": int(len(y_arr)),
            "skipped_reason": None,
        }

    except Exception as exc:
        logger.warning("threshold_optimize_failed: %s", exc)
        return _skipped_result(f"threshold_error: {type(exc).__name__}")


# ──────────────────────────────────────────────────────────────────────────────
# 차트 — Precision-Recall curve + 4 전략 위치 표시
# ──────────────────────────────────────────────────────────────────────────────


def _build_strategy_chart(
    y_true: Any, y_proba: Any, strategies: dict[str, Any], state: Any
) -> str | None:
    """PR curve 위에 4 전략 임계치 위치 마킹."""
    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from sklearn.metrics import precision_recall_curve

        from agents.handlers.common.shared import save_chart_to_minio

        prec, rec, thr = precision_recall_curve(y_true, y_proba)
        # precision_recall_curve 는 thr 가 prec/rec 보다 1 짧음 — 마지막 점 보정
        prec = prec[:-1]
        rec = rec[:-1]

        fig, ax = plt.subplots(figsize=(8, 6), dpi=100)
        ax.plot(rec, prec, color="#94a3b8", lw=1.5, label="PR curve")

        # 4 전략 점 표시
        strategy_colors = {
            "f1_max": "#2563eb",
            "cost_min": "#dc2626",
            "youden_j": "#16a34a",
            "recall_min": "#9333ea",
        }
        strategy_labels = {
            "f1_max": "F1-max",
            "cost_min": "Cost-min",
            "youden_j": "Youden J",
            "recall_min": "Recall-min",
        }
        for key, color in strategy_colors.items():
            s = strategies.get(key)
            if not s:
                continue
            t = float(s["threshold"])
            # 해당 임계치에서 precision/recall
            m = _metrics_at(y_true, y_proba, t)
            label = f"{strategy_labels[key]} (t={t:.2f})"
            if s.get("expected_cost") is not None:
                label += f", cost={s['expected_cost']:.0f}"
            ax.scatter(m["recall"], m["precision"], color=color, s=120, zorder=5, label=label)

        ax.set_xlabel("Recall")
        ax.set_ylabel("Precision")
        ax.set_title("Threshold Strategies — Precision/Recall 평면")
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="lower left", fontsize=9)
        fig.tight_layout()

        return save_chart_to_minio(
            fig, kind="tabular/threshold_strategies", job_id=getattr(state, "job_id", "")
        )
    except Exception as exc:
        logger.warning("threshold_chart_failed: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 편의 함수
# ──────────────────────────────────────────────────────────────────────────────


def threshold_strategies_chart(state: Any) -> str | None:
    """output_extras 가 호출. category_extras 캐시 우선."""
    cached = (
        (getattr(state, "category_extras", None) or {})
        .get("tabular", {})
        .get("threshold_strategies")
    )
    if isinstance(cached, dict) and cached.get("chart_path"):
        return cached["chart_path"]
    result = optimize_thresholds(state)
    return result.get("chart_path")

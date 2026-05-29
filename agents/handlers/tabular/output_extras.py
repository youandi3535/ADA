"""agents.handlers.tabular.output_extras — 정형 산출물 추가 (jh 담당).

Day 9: OUT-04(HTML Dashboard) 등 carrier 에 임베드할 차트/테이블/텍스트 생성.
``build(state, ctx)`` 가 task_type 분기로 4 차트를 matplotlib 으로 생성 → MinIO 저장:
  - binary     : ROC / Calibration / Confusion Matrix / Feature Importance
  - multiclass : ROC(OvR) / PR(OvR) / Confusion Matrix(normalized) / Feature Importance
  - regression : Residual / Predicted-vs-Actual / Q-Q(or Histogram) / Feature Importance

추가로 Day6 assets() 의 부가 산출물(미리 만든 eval_charts·OUT-02 EDA차트·메트릭
테이블·selector 근거)도 통합한다. assets() 는 build() 로 위임 (하위 호환).

입력 소스 (Day7/Day8 과 동일):
  - 예측값: state.category_extras["tabular"]["predictions"] {y_true,y_pred,y_prob}
  - 피처중요도: best_model["feature_importances"]/["feature_names"] → explanations → eval_result
입력 누락 시 해당 차트만 silent skip (carrier 가 죽지 않음).

base._call_extras 가 'build' 를 'assets' 보다 우선 호출 + OUTPUT_EXTRAS_KEYS 화이트리스트.
"""

from __future__ import annotations

from typing import Any

THEME_COLOR = {"tabular_ml": "#2563eb", "tabular_dl": "#0891b2"}
_GRID = "#94a3b8"
_TOP_FI = 15


# matplotlib / 저장 헬퍼 ───────────────────────────────────────────────────────


def _plt():
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    return plt


def _save(fig, kind: str, job_id: str) -> str | None:
    """fig → MinIO 저장. 실패 시 fig close 후 None."""
    try:
        from agents.handlers.common import shared  # noqa: WPS433

        return shared.save_chart_to_minio(fig, kind=f"tabular/{kind}", job_id=job_id)
    except Exception:
        try:
            _plt().close(fig)
        except Exception:
            pass
        return None


# 차트 — 분류 공통 ──────────────────────────────────────────────────────────────


def _chart_roc_binary(y_true, prob1, color, job_id):
    if y_true is None or prob1 is None:
        return None
    try:
        from sklearn.metrics import auc, roc_curve  # noqa: WPS433

        fpr, tpr, _ = roc_curve(y_true, prob1)
        a = auc(fpr, tpr)
        fig, ax = _plt().subplots(figsize=(6, 5))
        ax.plot(fpr, tpr, color=color, lw=2, label=f"AUC={a:.3f}")
        ax.plot([0, 1], [0, 1], "--", color=_GRID)
        ax.set_xlabel("False Positive Rate")
        ax.set_ylabel("True Positive Rate")
        ax.set_title("ROC Curve")
        ax.legend(loc="lower right")
        return _save(fig, "roc", job_id)
    except Exception:
        return None


def _chart_calibration(y_true, prob1, color, job_id):
    if y_true is None or prob1 is None:
        return None
    try:
        from sklearn.calibration import calibration_curve  # noqa: WPS433

        prob_true, prob_pred = calibration_curve(y_true, prob1, n_bins=10, strategy="uniform")
        fig, ax = _plt().subplots(figsize=(6, 5))
        ax.plot([0, 1], [0, 1], "--", color=_GRID, label="Perfect")
        ax.plot(prob_pred, prob_true, "o-", color=color, label="Model")
        ax.set_xlabel("Predicted probability")
        ax.set_ylabel("Observed frequency")
        ax.set_title("Calibration Curve")
        ax.legend(loc="upper left")
        return _save(fig, "calibration", job_id)
    except Exception:
        return None


def _chart_confusion(y_true, y_pred, color, job_id, *, normalize=False, title="Confusion Matrix"):
    if y_true is None or y_pred is None:
        return None
    try:
        import numpy as np  # noqa: WPS433
        from sklearn.metrics import confusion_matrix  # noqa: WPS433

        labels = np.unique(np.concatenate([np.asarray(y_true), np.asarray(y_pred)]))
        cm = confusion_matrix(y_true, y_pred, labels=labels, normalize="true" if normalize else None)
        fig, ax = _plt().subplots(figsize=(5.5, 4.5))
        im = ax.imshow(cm, cmap="Blues")
        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels([str(v) for v in labels])
        ax.set_yticklabels([str(v) for v in labels])
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title(title)
        fmt = "{:.2f}" if normalize else "{:.0f}"
        thresh = (cm.max() / 2.0) if cm.size else 0
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(
                    j, i, fmt.format(cm[i, j]), ha="center", va="center",
                    color="white" if cm[i, j] > thresh else "black", fontsize=8,
                )
        fig.colorbar(im, ax=ax, fraction=0.046)
        return _save(fig, "cm_norm" if normalize else "cm", job_id)
    except Exception:
        return None


def _chart_feature_importance(fi_pairs, color, job_id):
    if not fi_pairs:
        return None
    try:
        ranked = sorted(fi_pairs, key=lambda p: p[1], reverse=True)[:_TOP_FI]
        names = [p[0] for p in ranked]
        vals = [p[1] for p in ranked]
        fig, ax = _plt().subplots(figsize=(8, max(3.5, len(vals) * 0.32)))
        ypos = list(range(len(vals)))
        ax.barh(ypos[::-1], vals[::-1], color=color)
        ax.set_yticks(ypos[::-1])
        ax.set_yticklabels(names[::-1], fontsize=8)
        ax.set_xlabel("Importance")
        ax.set_title(f"Top-{len(vals)} Feature Importance")
        return _save(fig, "fi", job_id)
    except Exception:
        return None


# 차트 — 다중분류 전용 ────────────────────────────────────────────────────────


def _chart_roc_ovr(y_true, y_prob, color, job_id):
    if y_true is None or y_prob is None:
        return None
    try:
        import numpy as np  # noqa: WPS433
        from sklearn.metrics import auc, roc_curve  # noqa: WPS433
        from sklearn.preprocessing import label_binarize  # noqa: WPS433

        yp = np.asarray(y_prob, dtype=float)
        if yp.ndim != 2:
            return None
        classes = np.unique(y_true)
        yb = label_binarize(y_true, classes=classes)
        if yb.shape[1] == 1:
            return None
        fig, ax = _plt().subplots(figsize=(6, 5))
        aucs = []
        for k in range(min(yb.shape[1], yp.shape[1])):
            fpr, tpr, _ = roc_curve(yb[:, k], yp[:, k])
            a = auc(fpr, tpr)
            aucs.append(a)
            ax.plot(fpr, tpr, lw=1.5, label=f"{classes[k]} (AUC={a:.2f})")
        ax.plot([0, 1], [0, 1], "--", color=_GRID)
        ax.set_xlabel("False Positive Rate")
        ax.set_ylabel("True Positive Rate")
        ax.set_title(f"ROC OvR (macro AUC={float(np.mean(aucs)):.3f})")
        ax.legend(loc="lower right", fontsize=7)
        return _save(fig, "roc_ovr", job_id)
    except Exception:
        return None


def _chart_pr_ovr(y_true, y_prob, color, job_id):
    if y_true is None or y_prob is None:
        return None
    try:
        import numpy as np  # noqa: WPS433
        from sklearn.metrics import average_precision_score, precision_recall_curve  # noqa: WPS433
        from sklearn.preprocessing import label_binarize  # noqa: WPS433

        yp = np.asarray(y_prob, dtype=float)
        if yp.ndim != 2:
            return None
        classes = np.unique(y_true)
        yb = label_binarize(y_true, classes=classes)
        if yb.shape[1] == 1:
            return None
        fig, ax = _plt().subplots(figsize=(6, 5))
        for k in range(min(yb.shape[1], yp.shape[1])):
            prec, rec, _ = precision_recall_curve(yb[:, k], yp[:, k])
            ap = average_precision_score(yb[:, k], yp[:, k])
            ax.plot(rec, prec, lw=1.5, label=f"{classes[k]} (AP={ap:.2f})")
        ax.set_xlabel("Recall")
        ax.set_ylabel("Precision")
        ax.set_title("Precision-Recall (OvR)")
        ax.legend(loc="lower left", fontsize=7)
        return _save(fig, "pr_ovr", job_id)
    except Exception:
        return None


# 차트 — 회귀 전용 ────────────────────────────────────────────────────────────


def _chart_residuals(y_true, y_pred, color, job_id):
    if y_true is None or y_pred is None:
        return None
    try:
        import numpy as np  # noqa: WPS433

        yt = np.asarray(y_true, dtype=float)
        yp = np.asarray(y_pred, dtype=float)
        res = yp - yt
        fig, ax = _plt().subplots(figsize=(6, 5))
        ax.scatter(yp, res, alpha=0.5, color=color, s=15)
        ax.axhline(0, ls="--", color=_GRID)
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Residual")
        ax.set_title("Residual Plot")
        return _save(fig, "residuals", job_id)
    except Exception:
        return None


def _chart_pred_vs_actual(y_true, y_pred, color, job_id):
    if y_true is None or y_pred is None:
        return None
    try:
        import numpy as np  # noqa: WPS433
        from sklearn.metrics import r2_score  # noqa: WPS433

        yt = np.asarray(y_true, dtype=float)
        yp = np.asarray(y_pred, dtype=float)
        fig, ax = _plt().subplots(figsize=(6, 5))
        ax.scatter(yt, yp, alpha=0.5, color=color, s=15)
        lim = [min(yt.min(), yp.min()), max(yt.max(), yp.max())]
        ax.plot(lim, lim, "--", color=_GRID)
        ax.set_xlabel("Actual")
        ax.set_ylabel("Predicted")
        ax.set_title(f"Predicted vs Actual (R2={float(r2_score(yt, yp)):.3f})")
        return _save(fig, "pva", job_id)
    except Exception:
        return None


def _chart_qq_or_hist(y_true, y_pred, color, job_id):
    if y_true is None or y_pred is None:
        return None
    try:
        import numpy as np  # noqa: WPS433

        yt = np.asarray(y_true, dtype=float)
        yp = np.asarray(y_pred, dtype=float)
        res = yp - yt
        fig, ax = _plt().subplots(figsize=(6, 5))
        try:
            from scipy import stats  # noqa: WPS433

            stats.probplot(res, plot=ax)
            ax.set_title("Residual Q-Q Plot")
        except Exception:
            ax.hist(res, bins=30, color=color)
            ax.axvline(0, ls="--", color=_GRID)
            ax.set_xlabel("Residual")
            ax.set_ylabel("Count")
            ax.set_title("Residual Distribution")
        return _save(fig, "qq", job_id)
    except Exception:
        return None


# 테이블 / 텍스트 ─────────────────────────────────────────────────────────────


def _table_top_features(fi_pairs, k: int = 10) -> dict[str, Any]:
    ranked = sorted(fi_pairs, key=lambda p: p[1], reverse=True)[:k]
    total = sum(v for _, v in fi_pairs) or 0.0
    rows = [
        [n, f"{v:.4f}", f"{(v / total * 100 if total > 0 else 0):.1f}%"]
        for n, v in ranked
    ]
    return {"title": "Top-10 피처 중요도", "columns": ["피처", "중요도", "기여도"], "rows": rows}


def _compose_text_blocks(state: Any, task_type: str | None) -> list[str]:
    bm = getattr(state, "best_model", None) or {}
    m = bm.get("metrics") or {}
    er = getattr(state, "eval_result", None) or {}
    out: list[str] = []
    if task_type in ("binary", "multiclass"):
        bits = []
        if m.get("val_f1") is not None:
            bits.append(f"F1 {float(m['val_f1']):.3f}")
        auc = er.get("roc_auc") if er.get("roc_auc") is not None else m.get("val_roc_auc")
        if auc is not None:
            bits.append(f"ROC AUC {float(auc):.3f}")
        brier = er.get("calibration_brier")
        if brier is not None:
            bits.append(f"Brier {float(brier):.3f}")
        if bits:
            out.append("주요 지표: " + ", ".join(bits) + ".")
    elif task_type == "regression":
        bits = []
        for key, lab in (("val_r2", "R2"), ("val_rmse", "RMSE"), ("val_mae", "MAE")):
            if m.get(key) is not None:
                bits.append(f"{lab} {float(m[key]):.3f}")
        if bits:
            out.append("주요 지표: " + ", ".join(bits) + ".")
    return out


def _passive_extras(state: Any, ctx: dict[str, Any]):
    """Day6 assets() 부가 산출물 (미리 만든 차트·메트릭 테이블·근거)."""
    output_code = ctx.get("output_code", "")
    category = ctx.get("category", getattr(state, "category", ""))
    label = "정형 ML" if category == "tabular_ml" else "정형 DL"
    extras = getattr(state, "category_extras", {}) or {}
    tabular = extras.get("tabular", {})

    charts: list[Any] = list(tabular.get("eval_charts") or [])
    if output_code == "OUT-02":
        charts.extend(getattr(state, "eda_charts", None) or [])

    tables: list[dict] = []
    metrics = tabular.get("metrics") or {}
    if metrics:
        rows = [[k, f"{v:.4f}" if isinstance(v, float) else str(v)] for k, v in metrics.items()]
        tables.append({"title": f"{label} 평가 지표", "columns": ["지표", "값"], "rows": rows})

    text: list[str] = []
    sr = tabular.get("selector_rationale")
    if sr:
        text.append(sr)
    return charts, tables, text


# 진입점 ───────────────────────────────────────────────────────────────────────


def build(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = ctx or {}
    category = getattr(state, "category", "")
    color = THEME_COLOR.get(category, "#4b5563")
    job_id = getattr(state, "job_id", "unknown")

    from agents.handlers.tabular.evaluator import (  # noqa: WPS433
        _binary_prob,
        _extract_eval_data,
        _resolve_task_type,
    )
    from agents.handlers.tabular.insight import _feature_importance_pairs  # noqa: WPS433

    y_true, y_pred, y_prob = _extract_eval_data(state)
    task_type = _resolve_task_type(state, y_true)
    fi_pairs = _feature_importance_pairs(state)
    prob1 = _binary_prob(y_prob)

    if task_type == "binary":
        candidates = [
            _chart_roc_binary(y_true, prob1, color, job_id),
            _chart_calibration(y_true, prob1, color, job_id),
            _chart_confusion(y_true, y_pred, color, job_id),
            _chart_feature_importance(fi_pairs, color, job_id),
        ]
    elif task_type == "multiclass":
        candidates = [
            _chart_roc_ovr(y_true, y_prob, color, job_id),
            _chart_pr_ovr(y_true, y_prob, color, job_id),
            _chart_confusion(y_true, y_pred, color, job_id, normalize=True, title="Confusion Matrix (normalized)"),
            _chart_feature_importance(fi_pairs, color, job_id),
        ]
    elif task_type == "regression":
        candidates = [
            _chart_residuals(y_true, y_pred, color, job_id),
            _chart_pred_vs_actual(y_true, y_pred, color, job_id),
            _chart_qq_or_hist(y_true, y_pred, color, job_id),
            _chart_feature_importance(fi_pairs, color, job_id),
        ]
    else:
        candidates = [_chart_feature_importance(fi_pairs, color, job_id)]

    charts = [p for p in candidates if p]

    p_charts, p_tables, p_text = _passive_extras(state, ctx)
    charts.extend(p_charts)

    tables = list(p_tables)
    if fi_pairs:
        tables.append(_table_top_features(fi_pairs))

    text_blocks = list(p_text)
    text_blocks.extend(_compose_text_blocks(state, task_type))

    return {"charts": charts, "tables": tables, "text_blocks": text_blocks}


def assets(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """하위 호환 — build() 로 위임."""
    return build(state, ctx)

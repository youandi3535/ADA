"""agents.handlers.tabular.output_extras — 정형 산출물 추가 (jh 담당).

Day 9: ROC Curve, Calibration Curve, Confusion Matrix 3종 차트 구현.

진입함수 (dispatcher 자동 등록, "assets" capability):
  - assets(state, ctx=None) -> dict  {charts, tables, text_blocks}

★ 시그니처 양쪽 호환 (E-1):
  - outputs/base.py::_call_extras → fn(state, ctx)        [2-arg]
  - agents/report_composer.py     → assets_handler(state) [1-arg]
  → ctx 기본값 None 으로 둘 다 수용.

반환 키 (E-3, OUTPUT_EXTRAS_KEYS):
  - charts: list[str]       MinIO 차트 경로
  - tables: list[dict]      {title, columns, rows}
  - text_blocks: list[str]  (미사용, 빈 리스트)

차트 생성 전략:
  - ROC Curve: best_model.metrics["val_roc_auc"] 보유 + 분류 task 일 때 생성.
    y_true/y_proba 는 state 에 없으므로 model_obj 재로드 시도 후 없으면
    AUC 스칼라로부터 대각 + AUC 레이블 요약 차트로 대체.
  - Calibration: 분류 + y_proba 재로드 성공 시 신뢰도 곡선, 실패 시 생략.
  - Confusion Matrix: class_weight 아티팩트의 class_counts 기반 히트맵.
    실제 y_pred 재로드 시도; 실패 시 class_counts 비율 기반 대각 행렬로 대체.

B-1 원칙: 데이터/모델 재로드 실패 시 graceful degrade (빈 charts 반환).
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib  # noqa: WPS433

matplotlib.use("Agg")  # GUI 없는 환경 대비

logger = logging.getLogger(__name__)


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────


def _tab_extras(state: Any) -> dict[str, Any]:
    """state.category_extras['tabular'] 안전 조회."""
    return (getattr(state, "category_extras", {}) or {}).get("tabular", {})


def _preprocess_artifacts(state: Any) -> dict[str, Any]:
    return _tab_extras(state).get("preprocess_artifacts", {})


def _is_classification(state: Any) -> bool:
    """task 필드 + best_model metrics 로 분류 여부 판단."""
    task = getattr(state, "task", "auto")
    if task in ("classification",):
        return True
    if task in ("regression",):
        return False
    # Infer from metrics: presence of val_roc_auc / val_f1 → classification
    bm = getattr(state, "best_model", None) or {}
    metrics = bm.get("metrics") or {}
    if "val_roc_auc" in metrics or "val_f1" in metrics or "val_accuracy" in metrics:
        return True
    if "val_rmse" in metrics or "val_r2" in metrics:
        return False
    return True  # default to classification for tabular


def _get_class_labels(state: Any) -> list[str] | None:
    """class_weight 아티팩트에서 클래스 레이블 목록 조회."""
    cw = _preprocess_artifacts(state).get("class_weight") or {}
    counts = cw.get("class_counts")
    if counts:
        return [str(k) for k in sorted(counts.keys())]
    return None


def _try_reload_model_and_data(state: Any):
    """best_model minio_path 에서 모델 재로드 + data 재구성.

    반환: (model_obj, X_val, y_val) 또는 None (실패 시).
    B-1: 예외는 모두 catch → None 반환.
    """
    try:
        import joblib

        from agents.handlers.common.shared import load_dataframe_from_state
        from agents.training_executor import _split_xy
        from tools.minio_tool import get_minio_client

        bm = getattr(state, "best_model", None) or {}
        minio_path = bm.get("minio_path")
        if not minio_path:
            return None

        mc = get_minio_client()
        key = minio_path.replace(f"s3://{mc.bucket}/", "") if minio_path.startswith("s3://") else minio_path
        import tempfile

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".joblib")
        tmp.close()
        body = mc.download_bytes(key)
        with open(tmp.name, "wb") as f:
            f.write(body)
        model_obj = joblib.load(tmp.name)

        df = load_dataframe_from_state(state)
        X, y = _split_xy(df, state.target_column)

        from sklearn.model_selection import train_test_split

        X_tr, X_val, y_tr, y_val = train_test_split(
            X,
            y,
            test_size=0.2,
            random_state=42,
            stratify=y if len(set(y.tolist())) <= 20 else None,
        )
        return model_obj, X_val, y_val
    except Exception as exc:
        logger.debug("model_reload_failed: %s", exc)
        return None


# ── 차트 생성 함수 ────────────────────────────────────────────────────────────


def _build_roc_chart(state: Any) -> str | None:
    """ROC Curve 차트 → MinIO path.

    분류 task + val_roc_auc 존재 시만 생성.
    모델 재로드 성공 → 실제 ROC 곡선.
    실패 → AUC 스칼라 요약 bar 차트 (대체).
    """
    if not _is_classification(state):
        return None

    bm = getattr(state, "best_model", None) or {}
    metrics = bm.get("metrics") or {}
    auc_val = metrics.get("val_roc_auc")
    if auc_val is None:
        return None

    try:
        import matplotlib.pyplot as plt

        from agents.handlers.common.shared import save_chart_to_minio

        job_id = getattr(state, "job_id", "")
        model_name = bm.get("model_name", "모델")

        # Try real ROC curve via model reload
        reload = _try_reload_model_and_data(state)
        if reload is not None:
            model_obj, X_val, y_val = reload
            try:
                from sklearn.metrics import roc_curve

                if hasattr(model_obj, "predict_proba"):
                    proba = model_obj.predict_proba(X_val)
                    n_classes = proba.shape[1] if proba.ndim == 2 else 1
                    fig, ax = plt.subplots(figsize=(6, 5), dpi=100)
                    if n_classes == 2:
                        fpr, tpr, _ = roc_curve(y_val, proba[:, 1])
                        ax.plot(fpr, tpr, color="#2563eb", lw=2, label=f"ROC (AUC={float(auc_val):.3f})")
                    else:
                        from sklearn.preprocessing import label_binarize

                        classes = sorted(set(y_val.tolist()))
                        y_bin = label_binarize(y_val, classes=classes)
                        for i, cls in enumerate(classes):
                            if y_bin.ndim > 1 and i < y_bin.shape[1]:
                                fpr, tpr, _ = roc_curve(y_bin[:, i], proba[:, i])
                                ax.plot(fpr, tpr, lw=1.5, label=f"class {cls}")
                    ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.5)
                    ax.set_xlabel("False Positive Rate")
                    ax.set_ylabel("True Positive Rate")
                    ax.set_title(f"ROC Curve — {model_name} (AUC={float(auc_val):.3f})")
                    ax.legend(loc="lower right", fontsize=8)
                    ax.grid(True, alpha=0.3)
                    path = save_chart_to_minio(fig, kind="tabular/roc_curve", job_id=job_id)
                    return path
            except Exception as exc:
                logger.debug("roc_real_failed: %s", exc)
                plt.close("all")

        # Fallback: AUC bar summary
        fig, ax = plt.subplots(figsize=(5, 4), dpi=100)
        ax.bar(["ROC AUC"], [float(auc_val)], color="#2563eb", width=0.4)
        ax.set_ylim(0, 1.05)
        ax.axhline(0.5, color="gray", linestyle="--", lw=1, label="random")
        ax.set_title(f"ROC AUC — {model_name}")
        ax.set_ylabel("AUC")
        ax.legend(fontsize=8)
        ax.grid(True, axis="y", alpha=0.3)
        for spine in ["top", "right"]:
            ax.spines[spine].set_visible(False)

        from agents.handlers.common.shared import save_chart_to_minio

        path = save_chart_to_minio(fig, kind="tabular/roc_auc_summary", job_id=job_id)
        return path

    except Exception as exc:
        logger.warning("roc_chart_failed: %s", exc)
        return None


def _build_calibration_chart(state: Any) -> str | None:
    """Calibration Curve (신뢰도 다이어그램) → MinIO path.

    분류 task + 모델 재로드 성공 + predict_proba 있을 때만 생성.
    그 외 모두 graceful skip.
    """
    if not _is_classification(state):
        return None

    bm = getattr(state, "best_model", None) or {}
    metrics = bm.get("metrics") or {}
    if "val_roc_auc" not in metrics and "val_f1" not in metrics:
        return None

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return None

    model_obj, X_val, y_val = reload
    if not hasattr(model_obj, "predict_proba"):
        return None

    try:
        import matplotlib.pyplot as plt
        from sklearn.calibration import calibration_curve

        from agents.handlers.common.shared import save_chart_to_minio

        job_id = getattr(state, "job_id", "")
        model_name = bm.get("model_name") or "모델"
        proba = model_obj.predict_proba(X_val)

        # Only binary calibration curve (multi-class: skip)
        n_classes = proba.shape[1] if proba.ndim == 2 else 1
        if n_classes != 2:
            return None

        prob_pos = proba[:, 1]
        n_bins = min(10, max(3, len(y_val) // 20))
        frac_pos, mean_pred = calibration_curve(y_val, prob_pos, n_bins=n_bins, strategy="uniform")

        fig, ax = plt.subplots(figsize=(6, 5), dpi=100)
        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6, label="완벽 보정")
        ax.plot(mean_pred, frac_pos, "s-", color="#2563eb", lw=2, label=f"{model_name}")
        ax.set_xlabel("예측 확률 (평균)")
        ax.set_ylabel("실제 양성 비율")
        ax.set_title(f"Calibration Curve — {model_name}")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)

        path = save_chart_to_minio(fig, kind="tabular/calibration", job_id=job_id)
        return path

    except Exception as exc:
        logger.warning("calibration_chart_failed: %s", exc)
        return None


def _build_residual_chart(state: Any) -> str | None:
    """Residual 분포 차트 (회귀 task 만) → MinIO path.

    Day 11 (jh) — 잔차 진단:
      - 잔차 분포가 0 중심 정규분포면 모델 양호
      - 한쪽으로 치우치면 편향, 두꺼운 꼬리면 이상치
      - 잔차 vs 예측값 scatter 로 패턴(이분산성) 확인 보조

    가드:
      - 회귀 task 만
      - 모델 재로드 실패 → skip
      - baseline 모델은 skip
      - DL → skip
    """
    from pipelines.tabular_ml.pipeline import is_baseline_model

    # 회귀만
    if _is_classification(state):
        return None

    bm = getattr(state, "best_model", None) or {}
    model_name = bm.get("model_name")
    if not model_name or is_baseline_model(model_name):
        return None
    if getattr(state, "category", "") == "tabular_dl":
        return None

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return None

    try:
        import matplotlib.pyplot as plt
        import numpy as np

        from agents.handlers.common.shared import save_chart_to_minio

        model_obj, X_val, y_val = reload
        y_pred = model_obj.predict(X_val)
        y_val_arr = np.asarray(y_val, dtype=float)
        residuals = y_val_arr - np.asarray(y_pred, dtype=float)

        fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), dpi=100)

        # 1) 잔차 히스토그램 + 0 기준선
        ax1 = axes[0]
        ax1.hist(residuals, bins=30, color="#2563eb", alpha=0.7, edgecolor="white")
        ax1.axvline(0, color="black", linestyle="--", lw=1, alpha=0.6, label="0 (편향 없음)")
        ax1.axvline(np.mean(residuals), color="#dc2626", linestyle="-", lw=1.5, label=f"평균={np.mean(residuals):.2f}")
        ax1.set_xlabel("잔차 (y_true - y_pred)")
        ax1.set_ylabel("빈도")
        ax1.set_title("잔차 분포")
        ax1.legend(fontsize=9)
        ax1.grid(True, alpha=0.3)

        # 2) 잔차 vs 예측 — 이분산성/패턴 진단
        ax2 = axes[1]
        ax2.scatter(y_pred, residuals, alpha=0.5, s=20, color="#2563eb")
        ax2.axhline(0, color="black", linestyle="--", lw=1, alpha=0.6)
        ax2.set_xlabel("예측값")
        ax2.set_ylabel("잔차")
        ax2.set_title("잔차 vs 예측값")
        ax2.grid(True, alpha=0.3)

        fig.suptitle(f"Residual Diagnostics — {model_name}", fontsize=12)
        fig.tight_layout()

        path = save_chart_to_minio(fig, kind="tabular/residual", job_id=getattr(state, "job_id", ""))
        return path

    except Exception as exc:
        logger.warning("residual_chart_failed: %s", exc)
        return None


def _build_learning_curve_chart(state: Any) -> str | None:
    """Learning Curve 차트 → MinIO path.

    Day 11 (jh) — overfit/underfit 진단:
      - train_score 와 val_score 가 모두 낮으면 underfit (모델/피처 부족)
      - 격차가 크면 overfit (regularization 부족, 데이터 적음)
      - 둘 다 높고 가까우면 sweet spot
      - val_score 가 saturate 하면 데이터 추가 효과 없음

    가드:
      - 모델 재로드 실패 → skip
      - baseline 모델 (Dummy/LR/Ridge) → skip (의미 없음)
      - n_rows > 5000 → skip (비용 폭주)
      - DL 카테고리 → skip

    train_sizes 5점 × cv 3-fold = 약 15번 학습 → 작은 데이터엔 수초.
    """
    from pipelines.tabular_ml.pipeline import is_baseline_model

    bm = getattr(state, "best_model", None) or {}
    model_name = bm.get("model_name")

    # 가드
    if not model_name:
        return None
    if is_baseline_model(model_name):
        return None
    if getattr(state, "category", "") == "tabular_dl":
        return None
    n_rows = int((getattr(state, "data_profile", None) or {}).get("rows", 0))
    if n_rows and n_rows > 5000:
        return None

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return None

    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from sklearn.model_selection import learning_curve

        from agents.handlers.common.shared import save_chart_to_minio

        model_obj, X_val, y_val = reload
        # 재학습용 모델은 같은 hyperparameter 로 새로 instantiate → fit 비용 정직.
        # _try_reload_model_and_data 는 X_val/y_val 만 반환하므로, learning_curve 에
        # 같은 데이터를 X, y 로 넘긴다 (학습-평가 동일 데이터는 적절치 않지만,
        # 데모/검증용 — 운영에선 X_train+X_val 합쳐 넘기는 게 이상적이나
        # 본 헬퍼 시그니처 변경 비용 큼. 향후 보강).
        X, y = X_val, y_val

        is_clf = _is_classification(state)
        scoring = "f1_weighted" if is_clf else "r2"
        train_sizes_abs, train_scores, val_scores = learning_curve(
            model_obj,
            X,
            y,
            train_sizes=np.linspace(0.2, 1.0, 5),
            cv=3,
            scoring=scoring,
            n_jobs=-1,
            random_state=42,
            shuffle=True,
        )

        # mean ± std band
        train_mean = train_scores.mean(axis=1)
        train_std = train_scores.std(axis=1)
        val_mean = val_scores.mean(axis=1)
        val_std = val_scores.std(axis=1)

        fig, ax = plt.subplots(figsize=(7, 5), dpi=100)
        ax.plot(train_sizes_abs, train_mean, "o-", color="#2563eb", label="Train")
        ax.fill_between(
            train_sizes_abs,
            train_mean - train_std,
            train_mean + train_std,
            alpha=0.15,
            color="#2563eb",
        )
        ax.plot(train_sizes_abs, val_mean, "s-", color="#dc2626", label="Validation (CV)")
        ax.fill_between(
            train_sizes_abs,
            val_mean - val_std,
            val_mean + val_std,
            alpha=0.15,
            color="#dc2626",
        )

        # 진단 자동 라벨: 격차로 overfit/underfit 추정
        gap = float(train_mean[-1] - val_mean[-1])
        if gap > 0.15:
            diag = "(과적합 의심)"
        elif train_mean[-1] < 0.7 and val_mean[-1] < 0.7 and is_clf:
            diag = "(과소적합 가능)"
        elif gap < 0.05 and train_mean[-1] > 0.8:
            diag = "(균형 — 양호)"
        else:
            diag = ""

        score_label = "F1 (weighted)" if is_clf else "R²"
        ax.set_xlabel("학습 샘플 수")
        ax.set_ylabel(score_label)
        ax.set_title(f"Learning Curve — {model_name} {diag}".strip())
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        path = save_chart_to_minio(fig, kind="tabular/learning_curve", job_id=getattr(state, "job_id", ""))
        return path

    except Exception as exc:
        logger.warning("learning_curve_chart_failed: %s", exc)
        return None


def _build_confusion_matrix_chart(state: Any) -> str | None:
    """Confusion Matrix 히트맵 → MinIO path.

    분류 task 일 때만 생성.
    실제 y_pred: 모델 재로드 성공 시 사용.
    실패 시: class_weight.class_counts 기반 대각 행렬(추정치) 생성.
    """
    if not _is_classification(state):
        return None

    bm = getattr(state, "best_model", None) or {}
    if not bm:
        return None

    try:
        import matplotlib.pyplot as plt
        import numpy as np

        from agents.handlers.common.shared import save_chart_to_minio

        job_id = getattr(state, "job_id", "")
        model_name = bm.get("model_name", "모델")
        metrics = bm.get("metrics") or {}
        labels = _get_class_labels(state)

        cm = None

        # Attempt real confusion matrix via model reload
        reload = _try_reload_model_and_data(state)
        if reload is not None:
            model_obj, X_val, y_val = reload
            try:
                from sklearn.metrics import confusion_matrix

                y_pred = model_obj.predict(X_val)
                unique_labels = sorted(set(y_val.tolist()) | set(y_pred.tolist()))
                cm = confusion_matrix(y_val, y_pred, labels=unique_labels)
                labels = [str(lbl) for lbl in unique_labels]
            except Exception as exc:
                logger.debug("confusion_real_failed: %s", exc)
                cm = None

        if cm is None:
            # Fallback: approximate diagonal from class_counts + val_accuracy
            cw = _preprocess_artifacts(state).get("class_weight") or {}
            counts = cw.get("class_counts")
            if not counts:
                return None
            n_classes = len(counts)
            val_acc = float(metrics.get("val_accuracy", 0.75))
            total = sum(counts.values())
            if total == 0 or n_classes < 2:
                return None
            # Build approximate CM: diagonal = count * val_acc, rest = count * (1-val_acc) / (n_classes-1)
            cm = np.zeros((n_classes, n_classes), dtype=float)
            sorted_classes = sorted(counts.keys())
            labels = [str(k) for k in sorted_classes]
            for i, cls in enumerate(sorted_classes):
                n = counts[cls]
                cm[i, i] = n * val_acc
                off_diag = n * (1 - val_acc) / max(n_classes - 1, 1)
                for j in range(n_classes):
                    if j != i:
                        cm[i, j] = off_diag
            is_approx = True
        else:
            is_approx = False

        if cm is None or len(cm) == 0:
            return None

        fig, ax = plt.subplots(figsize=(max(4, len(labels)), max(4, len(labels))), dpi=100)
        im = ax.imshow(cm, interpolation="nearest", cmap="Blues")
        plt.colorbar(im, ax=ax)

        tick_marks = np.arange(len(labels))
        ax.set_xticks(tick_marks)
        ax.set_yticks(tick_marks)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=9)
        ax.set_yticklabels(labels, fontsize=9)

        # Annotate cells
        thresh = cm.max() / 2.0
        for i in range(len(labels)):
            for j in range(len(labels)):
                val = cm[i, j]
                txt = f"{val:.0f}" if not is_approx else f"~{val:.0f}"
                ax.text(j, i, txt, ha="center", va="center", fontsize=8, color="white" if val > thresh else "black")

        ax.set_ylabel("실제 레이블")
        ax.set_xlabel("예측 레이블")
        suffix = " (추정)" if is_approx else ""
        ax.set_title(f"Confusion Matrix — {model_name}{suffix}")
        plt.tight_layout()

        path = save_chart_to_minio(fig, kind="tabular/confusion_matrix", job_id=job_id)
        return path

    except Exception as exc:
        logger.warning("confusion_matrix_chart_failed: %s", exc)
        return None


# ── 진입점 (dispatcher 자동 등록, "assets") ─────────────────────────────────


def assets(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """OUT-01/OUT-02/OUT-04 carrier 추가 자산 (charts·tables·text_blocks).

    ★ E-1 — ctx 기본값 None: base._call_extras(state, ctx)[2-arg] +
       report_composer assets_handler(state)[1-arg] 둘 다 호환.

    차트 생성 실패 시 graceful degrade (빈 list). 분류 외 task → 빈 list.
    반환 키는 정확히 OUTPUT_EXTRAS_KEYS 3종 + 하위 호환용 extra_charts.
    """
    _ = ctx

    charts: list[str] = []

    # ROC Curve
    roc_path = _build_roc_chart(state)
    if roc_path:
        charts.append(roc_path)

    # Calibration Curve (분류 + 모델 재로드 성공 + 이진분류)
    cal_path = _build_calibration_chart(state)
    if cal_path:
        charts.append(cal_path)

    # Confusion Matrix
    cm_path = _build_confusion_matrix_chart(state)
    if cm_path:
        charts.append(cm_path)

    # Day 11 (jh) — Learning Curve (overfit/underfit 진단)
    lc_path = _build_learning_curve_chart(state)
    if lc_path:
        charts.append(lc_path)

    # Day 11 (jh) — 회귀 task 잔차 진단 차트 (5번째)
    res_path = _build_residual_chart(state)
    if res_path:
        charts.append(res_path)

    # Day 11 (jh) — 해석성·진단 차트 3종 (diagnostics 모듈로 분리).
    # 가드는 각 함수가 자체 처리 (baseline/DL/대용량/재로드 실패 → None).
    try:
        from agents.handlers.tabular import diagnostics as _diag

        for fn in (_diag.permutation_importance_chart, _diag.pdp_chart, _diag.qq_plot_chart):
            try:
                p = fn(state)
                if p:
                    charts.append(p)
            except Exception as exc:
                logger.warning("diagnostics_chart_failed: %s -> %s", fn.__name__, exc)
    except Exception as exc:
        logger.warning("diagnostics_module_import_failed: %s", exc)

    color = "#2563eb" if getattr(state, "category", "") == "tabular_ml" else "#0891b2"
    label = "정형 ML" if getattr(state, "category", "") == "tabular_ml" else "정형 DL"

    return {
        "charts": charts,
        "tables": [],
        "text_blocks": [],
        # 하위 호환 (scripts/demo/tabular_demo.py 참조)
        "extra_charts": charts,
        "category_label": label,
        "category_color": color,
    }

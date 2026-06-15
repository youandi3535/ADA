"""agents.handlers.tabular.output_extras — 정형 산출물 추가 (jh 담당).

Day 9: ROC Curve, Calibration Curve, Confusion Matrix 3종 차트 구현.
Day 11: Learning Curve · Residual + diagnostics (Permutation/PDP/QQ).
Day 11+ (jh, decision-aware): archetype 기반 운영 권고 표 4 종 (tables 키).

진입함수 (dispatcher 자동 등록, "assets" capability):
  - assets(state, ctx=None) -> dict  {charts, tables, text_blocks}

★ 시그니처 양쪽 호환 (E-1):
  - outputs/base.py::_call_extras → fn(state, ctx)        [2-arg]
  - agents/report_composer.py     → assets_handler(state) [1-arg]
  → ctx 기본값 None 으로 둘 다 수용.

반환 키 (E-3, OUTPUT_EXTRAS_KEYS):
  - charts: list[str]       MinIO 차트 경로
  - tables: list[dict]      {title, columns, rows} — 운영 권고 표 4 종
  - text_blocks: list[str]  (미사용, 빈 리스트)

운영 권고 표 4 종 (tables, Day 11+ jh):
  1. 배포 체크리스트       — SHA256 / MLflow / 임계치 / 캘리브레이션 / A/B 권고비율
  2. 모니터링 KPI 표        — 데이터 드리프트 / 성능 / 캘리브레이션 / 레이턴시
  3. 임계치 전략 비교       — F1-max / cost-min / Youden J / recall-min (분류만)
  4. 재학습 권고            — archetype × 메트릭 기반 강도/범위/트리거/롤백

차트 생성 전략:
  - ROC Curve: best_model.metrics["val_roc_auc"] 보유 + 분류 task 일 때 생성.
  - Calibration: 분류 + y_proba 재로드 성공 시 신뢰도 곡선, 실패 시 생략.
  - Confusion Matrix: 실제 y_pred 재로드 시도; 실패 시 class_counts 폴백.

B-1 원칙: 차트/표 생성 실패 시 graceful degrade (해당 항목만 skip, 다른 건 반환).
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


def _cache_in_state(state: Any, key: str, value: Any) -> None:
    """SHAP·calibration 결과를 state.category_extras["tabular"][key] 에 저장.

    PipelineState 가 immutable 이지만, category_extras 는 mutable dict 인스턴스.
    같은 호출 사이클 내에서 다른 모듈(insight)이 캐시 읽을 수 있도록 in-place.
    (정식 dispatcher 가 with_update 로 머지하기 전까지의 임시 캐시)
    """
    cat_extras = getattr(state, "category_extras", None)
    if not isinstance(cat_extras, dict):
        return
    tab = cat_extras.get("tabular")
    if not isinstance(tab, dict):
        tab = {}
        cat_extras["tabular"] = tab
    tab[key] = value


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
        key = mc.object_key(minio_path)  # 버킷명 무관 s3:// 접두 제거 (단일 진입점)
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


# ── 운영 권고 표 4 종 (Day 11+ jh, decision-aware) ──────────────────────────


def _build_deployment_checklist(state: Any) -> dict[str, Any] | None:
    """배포 체크리스트 표 — SHA256/MLflow/임계치/캘리브레이션/A/B 권고비율."""
    bm = getattr(state, "best_model", None) or {}
    if not bm:
        return None

    metrics = bm.get("metrics") or {}
    sha256 = bm.get("model_sha256") or "—"
    mlflow_run = bm.get("mlflow_run_id") or "—"
    opt_thr = metrics.get("val_optimal_threshold")
    threshold_basis = f"F1-max 자동 탐색 (opt={float(opt_thr):.2f})" if opt_thr is not None else "기본 0.5"

    # archetype 기반 A/B 권고비율 + 매칭 근거
    profile = getattr(state, "data_profile", None) or {}
    archetype_info = profile.get("archetype") or {}
    archetype = archetype_info.get("primary")
    archetype_conf = float(archetype_info.get("primary_confidence", 0) or 0)
    archetype_signals = archetype_info.get("signals") or {}

    ab_ratio = {
        "extreme_imbalance": "5% (위험도 큼)",
        "target_leakage_suspected": "0% (롤아웃 보류 — 누수 확인 우선)",
        "low_signal": "5% (신호 약함 — 보수적)",
        "p_gg_n": "10%",
        "imbalanced_moderate": "10%",
    }.get(archetype, "20% (표준)")

    # Day 11++ — 캘리브레이션 실측치 인용 (calibrate() 가 채웠으면)
    cat_extras_local = _tab_extras(state)
    cal = cat_extras_local.get("calibration") or {}
    if cal.get("method") and cal.get("ece_before") is not None and cal.get("ece_after") is not None:
        cal_str = f"{cal['method']} 적용 — ECE {float(cal['ece_before']):.3f} → {float(cal['ece_after']):.3f}"
    elif cal.get("skipped_reason"):
        cal_str = f"보정 skip ({cal['skipped_reason']}) — 기본 확률 사용"
    else:
        cal_str = "ECE > 0.05 면 Platt 또는 Isotonic 권고"

    rows = [
        ["모델 SHA256", str(sha256)[:16] + "..." if len(str(sha256)) > 16 else str(sha256)],
        ["MLflow run", str(mlflow_run)],
        ["임계치 산출", threshold_basis],
        ["캘리브레이션", cal_str],
        ["A/B 트래픽 비율", ab_ratio],
        ["데이터 누수 가드", "leakage_safe_split=True 확인 (preprocessor)"],
    ]

    # Day 11++ — archetype 매칭 근거를 표에 명시 (투명성).
    # confidence < 0.5 면 노출 생략, ≥ 0.5 면 신호값 + confidence 표시.
    if archetype and archetype != "clean_balanced" and archetype_conf >= 0.5:
        signal_summary = _format_archetype_signals(archetype, archetype_signals)
        conf_str = f"{archetype_conf:.0%}"
        rows.append(
            [
                "데이터 archetype",
                f"{archetype} (신뢰도 {conf_str}) — {signal_summary}",
            ]
        )

    return {
        "title": "배포 체크리스트",
        "columns": ["항목", "값/권고"],
        "rows": rows,
    }


def _format_archetype_signals(archetype: str, signals: dict[str, Any]) -> str:
    """archetype 매칭 근거를 한 줄 텍스트로 요약 (운영 표에 노출)."""
    if archetype == "target_leakage_suspected":
        cols = signals.get("leakage_columns") or []
        if cols:
            return f"누수 의심 컬럼: {', '.join(str(c) for c in cols[:3])}"
        return "누수 의심 컬럼 감지"
    if archetype == "extreme_imbalance":
        r = signals.get("imbalance_ratio")
        return f"클래스 비율 1:{int(r):,}" if r else "1:1000 이상"
    if archetype == "p_gg_n":
        r = signals.get("feature_to_row_ratio")
        return f"피처/행 비율 {float(r):.2f}" if r is not None else "p≫n"
    if archetype == "high_cardinality_heavy":
        n = signals.get("high_cardinality_count")
        return f"고카디 컬럼 {int(n)}개" if n is not None else "고카디 다수"
    if archetype == "multicollinear_heavy":
        c = signals.get("corr_clusters")
        cn = signals.get("corr_condition_number")
        parts = []
        if c:
            parts.append(f"상관 클러스터 {int(c)}개")
        if cn:
            parts.append(f"cond.number {float(cn):.0f}")
        return ", ".join(parts) or "다중공선성 감지"
    if archetype == "id_overload":
        r = signals.get("id_like_ratio")
        return f"id-like 컬럼 비율 {float(r):.0%}" if r is not None else "id-like 다수"
    if archetype == "imbalanced_moderate":
        r = signals.get("imbalance_ratio")
        return f"클래스 비율 1:{int(r):,}" if r else "중간 불균형"
    if archetype == "low_signal":
        mi = signals.get("max_mutual_info")
        return f"MI 최댓값 {float(mi):.3f}" if mi is not None else "신호 약함"
    if archetype == "regression_heteroscedastic":
        cv = signals.get("max_coefficient_of_variation")
        return f"변동계수 {float(cv):.1f}" if cv is not None else "이분산 의심"
    return "매칭됨"


def _build_monitoring_kpi_table(state: Any) -> dict[str, Any] | None:
    """모니터링 KPI 표 — 데이터 드리프트 / 성능 / 캘리브레이션 / 레이턴시."""
    profile = getattr(state, "data_profile", None) or {}
    archetype = (profile.get("archetype") or {}).get("primary")
    bm = getattr(state, "best_model", None) or {}
    metrics = bm.get("metrics") or {}
    primary_metric_name = "F1" if _is_classification(state) else "R²"
    primary_value = metrics.get("val_f1") if _is_classification(state) else metrics.get("val_r2")
    primary_str = f"{float(primary_value):.3f}" if primary_value is not None else "—"

    # archetype 별로 점검 주기 조정
    drift_cadence = "주 1회" if archetype == "extreme_imbalance" else "월 1회"
    perf_cadence = "일 1회" if archetype in ("extreme_imbalance", "target_leakage_suspected") else "주 1회"

    # Day 11++ — 캘리브레이션 초기값을 실측치로 채움 (calibrate() 결과)
    cal = _tab_extras(state).get("calibration") or {}
    ece_after = cal.get("ece_after")
    ece_init_str = f"{float(ece_after):.3f} ({cal.get('method')})" if ece_after is not None else "최초 측정 필요"

    return {
        "title": "모니터링 KPI",
        "columns": ["지표", "임계치", "점검 주기", "초기값"],
        "rows": [
            ["데이터 드리프트 (top-5 feature PSI)", "0.25", drift_cadence, "기준선 측정 필요"],
            [f"성능 ({primary_metric_name}) 롤링 평균", "-3%p 알람", perf_cadence, primary_str],
            ["캘리브레이션 (ECE)", "0.05", "월 1회", ece_init_str],
            ["추론 레이턴시 p95", "200ms", "실시간", "serving 측정"],
            ["오류율 (503/5xx)", "0.1%", "실시간", "—"],
        ],
    }


def _build_threshold_strategy_table(state: Any) -> dict[str, Any] | None:
    """임계치 전략 비교 표 — F1-max / cost-min / Youden J / recall-min.

    Day 11++ (jh) — 기존 simple 추정 자리를 threshold_optimizer 실측치로 교체.
    category_extras["tabular"]["threshold_strategies"] 가 있으면 사용, 없으면
    재계산 시도 (보정된 확률 위에서 honest expected_cost).
    """
    if not _is_classification(state):
        return None

    # threshold_optimizer 결과 (output_extras assets() 가 사전에 캐시했어야 함)
    cat_extras = _tab_extras(state)
    ts = cat_extras.get("threshold_strategies") or {}
    strategies = ts.get("strategies") or {}

    # 캐시 미존재 시 직접 호출 (graceful)
    if not strategies:
        try:
            from agents.handlers.tabular import threshold_optimizer as _ts_mod

            ts = _ts_mod.optimize_thresholds(state)
            strategies = ts.get("strategies") or {}
        except Exception as exc:
            logger.warning("threshold_table_compute_failed: %s", exc)

    if not strategies:
        # 폴백: best_model.metrics 의 optimal_threshold 만 활용한 최소 표
        bm = getattr(state, "best_model", None) or {}
        metrics = bm.get("metrics") or {}
        opt_thr = metrics.get("val_optimal_threshold")
        if opt_thr is None:
            return None
        f1_at_opt = metrics.get("val_f1_at_optimal_threshold")
        return {
            "title": "임계치 전략 비교 (간이)",
            "columns": ["전략", "임계치", "비고"],
            "rows": [
                ["기본 0.5", "0.50", "확률 보정 완료된 경우"],
                ["F1-max", f"{float(opt_thr):.2f}", f"F1={float(f1_at_opt):.2f}" if f1_at_opt else "F1 최대"],
                ["cost-min / Youden J / recall-min", "—", "threshold_optimizer 미실행"],
            ],
        }

    cost_matrix = ts.get("cost_matrix") or {}
    cost_str_suffix = (
        f" (FP={cost_matrix.get('fp')}, FN={cost_matrix.get('fn')})" if cost_matrix else " — cost_matrix 입력 시 활성화"
    )
    recommended = ts.get("recommended") or "f1_max"

    def _fmt_strategy(name: str, s: dict | None, fields: list[str]) -> list[str]:
        if not s:
            return [name, "—", "산출 불가"]
        cells = [name, f"{float(s.get('threshold', 0)):.2f}"]
        details: list[str] = []
        for f in fields:
            v = s.get(f)
            if v is None:
                continue
            if f == "expected_cost":
                details.append(f"cost={float(v):.0f}")
            elif f in ("f1", "precision", "recall", "tpr", "fpr", "j_statistic"):
                details.append(f"{f}={float(v):.2f}")
        if recommended == name.split()[0].lower().replace("-", "_"):
            details.append("⭐ 권고")
        cells.append(", ".join(details) if details else "—")
        return cells

    rows = [
        ["기본 0.5", "0.50", "확률 보정 완료된 경우만 권장"],
        _fmt_strategy("F1-max", strategies.get("f1_max"), ["f1", "precision", "recall", "expected_cost"]),
        _fmt_strategy("Cost-min", strategies.get("cost_min"), ["expected_cost", "f1", "precision", "recall"]),
        _fmt_strategy("Youden J", strategies.get("youden_j"), ["j_statistic", "tpr", "fpr"]),
        _fmt_strategy(
            f"Recall-min (≥{ts.get('target_recall', 0.9):.1f})",
            strategies.get("recall_min"),
            ["recall", "precision", "expected_cost"],
        ),
    ]

    title = f"임계치 전략 비교{cost_str_suffix}"
    if ts.get("calibrated"):
        title += " · 보정된 확률 사용"

    return {
        "title": title,
        "columns": ["전략", "임계치", "주요 지표"],
        "rows": rows,
    }


def _build_retrain_policy_table(state: Any) -> dict[str, Any] | None:
    """재학습 권고 표 — archetype + 메트릭 기반 강도/범위/트리거/롤백."""
    profile = getattr(state, "data_profile", None) or {}
    archetype = (profile.get("archetype") or {}).get("primary")
    n_rows = int(profile.get("rows", 0) or 0)

    # 재학습 강도 — archetype 별
    intensity_map = {
        "extreme_imbalance": ("주기적 (월)", "medium (HPO warm-start 재실행)"),
        "target_leakage_suspected": ("즉시", "heavy (전처리·피처 재설계)"),
        "low_signal": ("보류", "피처 엔지니어링 우선 — 모델만 재학습 무의미"),
        "p_gg_n": ("주기적 (분기)", "light (기존 모델 + 새 데이터로 fit)"),
        "high_cardinality_heavy": ("주기적 (월)", "light (새 카테고리 등장 모니터링)"),
    }
    intensity, scope = intensity_map.get(archetype, ("주기적 (분기)", "light"))

    # 필요 데이터량 — n_rows × 0.2 (rule-of-thumb)
    data_req = f"≥ {int(n_rows * 0.2):,} 건 누적" if n_rows else "기준 미정"

    return {
        "title": "재학습 권고",
        "columns": ["항목", "권고"],
        "rows": [
            ["재학습 강도", intensity],
            ["재학습 범위", scope],
            ["트리거 — 성능", "primary metric -3%p (롤링 1000건)"],
            ["트리거 — 드리프트", "top-5 feature PSI > 0.25"],
            ["트리거 — 캘리브레이션", "ECE > 0.05"],
            ["필요 데이터량", data_req],
            ["롤백 조건", "신규 모델 primary metric < 기존 - 2%p 시 자동 폐기"],
        ],
    }


def _build_operational_tables(state: Any) -> list[dict[str, Any]]:
    """4 종 운영 권고 표 일괄 생성. 각 표 생성 실패 시 해당 표만 skip."""
    tables: list[dict[str, Any]] = []
    for fn in (
        _build_deployment_checklist,
        _build_monitoring_kpi_table,
        _build_threshold_strategy_table,
        _build_retrain_policy_table,
    ):
        try:
            t = fn(state)
            if t:
                tables.append(t)
        except Exception as exc:
            logger.warning("operational_table_failed: %s -> %s", fn.__name__, exc)
    return tables


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

    # Day 11++ (jh) — 분석 모듈 3종 fan-out 병렬 실행.
    # 이전: SHAP → Calibration → Threshold sequential (≈ 50s)
    # 이후: SHAP + Calibration 병렬, Threshold 는 Calibration 직후 (≈ 28s)
    # threshold 가 calibration calibrator 를 활용하므로 의존성 보존.
    from concurrent.futures import ThreadPoolExecutor

    try:
        from agents.handlers.tabular import calibration as _cal_mod, explainability as _shap_mod

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_shap = executor.submit(_shap_mod.explain, state)
            future_cal = executor.submit(_cal_mod.calibrate, state)

            # SHAP 결과 회수
            try:
                shap_result = future_shap.result()
                if shap_result.get("shap_summary_path"):
                    charts.append(shap_result["shap_summary_path"])
                for dep_path in shap_result.get("shap_dependence_paths") or []:
                    charts.append(dep_path)
                _cache_in_state(state, "shap", shap_result)
            except Exception as exc:
                logger.warning("shap_integration_failed: %s", exc)

            # Calibration 결과 회수 (Threshold 가 이걸 의존하므로 먼저 캐시)
            try:
                cal_result = future_cal.result()
                if cal_result.get("reliability_chart_path"):
                    charts.append(cal_result["reliability_chart_path"])
                _cache_in_state(state, "calibration", cal_result)
            except Exception as exc:
                logger.warning("calibration_integration_failed: %s", exc)
    except Exception as exc:
        logger.warning("analysis_fanout_failed: %s", exc)

    # Threshold 는 calibration calibrator 활용 — sequential 로 cal 직후 실행.
    try:
        from agents.handlers.tabular import threshold_optimizer as _ts_mod

        ts_result = _ts_mod.optimize_thresholds(state)
        if ts_result.get("chart_path"):
            charts.append(ts_result["chart_path"])
        _cache_in_state(state, "threshold_strategies", ts_result)
    except Exception as exc:
        logger.warning("threshold_integration_failed: %s", exc)

    color = "#2563eb" if getattr(state, "category", "") == "tabular_ml" else "#0891b2"
    label = "정형 ML" if getattr(state, "category", "") == "tabular_ml" else "정형 DL"

    # Day 11+ (jh, decision-aware) — 운영 권고 표 4 종.
    # 차트만 있던 것에서 carrier 가 표 슬롯(PPT slide 19 모니터링 KPI 등) 을 채울 수 있게 함.
    tables = _build_operational_tables(state)

    # jh 2026-06-12 — ctx 배달용 분석 수치 (S14·S15·S16 '미적립' 해소).
    # 차트만 만들고 버리던 y_val/y_pred 를 CM 수치·세그먼트·개별 사례로 재활용.
    try:
        analysis = _analysis_payload(state)
    except Exception as exc:
        logger.warning("analysis_payload_failed: %s", exc)
        analysis = {}

    return {
        "charts": charts,
        "tables": tables,
        "text_blocks": [],
        "analysis": analysis,
        # 하위 호환 (scripts/demo/tabular_demo.py 참조)
        "extra_charts": charts,
        "category_label": label,
        "category_color": color,
    }


def _analysis_payload(state: Any) -> dict[str, Any]:
    """CM 수치 + 세그먼트별 정확도 + 개별 예측 사례 3건 — ReportContext 배달용.

    jh 2026-06-12 — builder._augment_from_assets 가 ctx 로 매핑:
        confusion_matrix → ctx.evaluation.confusion_matrix (tn/fp/fn/tp)
        per_segment      → ctx.evaluation.per_segment
        local_examples   → ctx.interpretation.local_examples (S14 가 직접 소비)
    """
    out: dict[str, Any] = {}
    if not _is_classification(state):
        return out
    reload = _try_reload_model_and_data(state)
    if reload is None:
        return out
    model_obj, X_val, y_val = reload

    import numpy as np

    # jh 2026-06-12 — _split_xy 가 .values(numpy) 를 반환해 X_val.columns 가
    # 항상 없었음 → per_segment·사례별 SHAP 피처명이 통째로 스킵되던 결함.
    # 동일 seed/stratify 로 원본 df 의 val 행을 복원해 컬럼 정보를 되살린다.
    raw_val = None
    feat_cols = None  # 학습 피처명 — 반드시 전처리본(df_raw) 기준 (SHAP 벡터 정합)
    try:
        from sklearn.model_selection import train_test_split

        from agents.handlers.common.shared import load_dataframe_from_state

        df_raw = load_dataframe_from_state(state)
        tgt = state.target_column
        if tgt and tgt in df_raw.columns:
            y_full = df_raw[tgt].values
            # jh 2026-06-12 — state df 는 전처리본(스케일링)이라 세그먼트 라벨이
            # "Pclass=-1.0" 처럼 나옴 (운영 S16 실측). 원본 파일을 받아 행 순서·
            # 타깃이 일치할 때만 라벨 소스로 교체.
            df_label = df_raw
            try:
                from tools.minio_tool import get_minio_client

                _mc = get_minio_client()
                # file_id 에 확장자가 없는 경우(uuid) fmt 파싱이 uuid 전체가 되어
                # 로드가 조용히 실패 → 라벨이 전처리본(Pclass=-2.0)으로 남던 결함
                _fid = str(state.file_id)
                _fmt = _fid.rsplit(".", 1)[-1].lower() if "." in _fid else "csv"
                _df0 = _mc.load_dataframe(_fid, fmt=_fmt)
                if (
                    len(_df0) == len(df_raw)
                    and tgt in _df0.columns
                    and np.array_equal(np.asarray(_df0[tgt].values).ravel(), np.asarray(y_full).ravel())
                ):
                    df_label = _df0
            except Exception as _exc:  # noqa: BLE001
                # warning 승격 — S16 라벨이 인코딩 값으로 남는 원인 추적용 (운영 로그 노출)
                logger.warning("analysis_raw_file_fallback: %s: %s", type(_exc).__name__, _exc)
            if df_label is df_raw:
                logger.warning(
                    "analysis_segment_label_source=preprocessed (원본 로드 실패 또는 행 불일치) file_id=%s",
                    str(getattr(state, "file_id", "?"))[:60],
                )
            idx = np.arange(len(df_raw))
            _, idx_val = train_test_split(
                idx,
                test_size=0.2,
                random_state=42,
                stratify=y_full if len(set(y_full.tolist())) <= 20 else None,
            )
            cand_val = df_label.drop(columns=[tgt]).iloc[idx_val].reset_index(drop=True)
            # 안전망: 복원한 행의 타깃이 reload 한 y_val 과 일치할 때만 사용
            if np.array_equal(np.asarray(y_full[idx_val]).ravel(), np.asarray(y_val).ravel()):
                raw_val = cand_val
                feat_cols = list(df_raw.drop(columns=[tgt]).select_dtypes(include=[np.number, "bool"]).columns)
            else:
                logger.warning("analysis_raw_val_mismatch: split 불일치 — 세그먼트 스킵")
    except Exception as exc:
        logger.debug("analysis_raw_val_failed: %s", exc)

    try:
        y_pred = model_obj.predict(X_val)
    except Exception:
        return out
    yv = np.asarray(y_val).ravel()
    yp = np.asarray(y_pred).ravel()

    # 1) Confusion Matrix 수치 (이진)
    try:
        from sklearn.metrics import confusion_matrix

        uniq = sorted(set(yv.tolist()) | set(yp.tolist()))
        cm = confusion_matrix(yv, yp, labels=uniq)
        if len(uniq) == 2:
            out["confusion_matrix"] = {
                "tn": int(cm[0, 0]),
                "fp": int(cm[0, 1]),
                "fn": int(cm[1, 0]),
                "tp": int(cm[1, 1]),
                "labels": [str(u) for u in uniq],
            }
    except Exception:
        pass

    # 2) 세그먼트별 정확도 — 카디널리티 2~6 의 *범주형* 컬럼 상위 3개
    # jh 2026-06-12 — numpy X_val 대신 복원한 raw_val(원본 컬럼) 사용.
    seg_df = raw_val if raw_val is not None else (X_val if hasattr(X_val, "columns") else None)

    def _seg_ok(s) -> bool:
        # jh 2026-06-14 — 의미 있는 범주형만 세그먼트로 사용. 식별자/연속·인코딩 float
        # (예: target-encode 된 'Name' 의 0.0112 같은 값)이 'Name=0.0112' 무의미
        # 세그먼트로 잡혀 취약 세그먼트·차트를 오염시키던 버그 차단.
        try:
            nun = int(s.nunique(dropna=True))
        except Exception:
            return False
        if not (2 <= nun <= 6):
            return False
        if str(s.dtype).startswith("float"):
            # 1.0/2.0/3.0 처럼 정수에 해당하는 float 만 허용, 연속 인코딩은 제외
            try:
                return all(float(v).is_integer() for v in s.dropna().unique())
            except Exception:
                return False
        return True

    def _seg_label(col, v) -> str:
        # 1.0 → 1 처럼 정수형 float 는 깔끔하게 표기
        try:
            if isinstance(v, float) and float(v).is_integer():
                v = int(v)
        except Exception:
            pass
        return f"{col}={v}"

    try:
        if seg_df is not None:
            correct = yv == yp
            segs: list[dict[str, Any]] = []
            cand = [c for c in seg_df.columns if _seg_ok(seg_df[c])][:3]
            for col in cand:
                for v in seg_df[col].dropna().unique():
                    mask = (seg_df[col] == v).to_numpy()
                    n = int(mask.sum())
                    if n >= 10:
                        segs.append(
                            {
                                "segment": _seg_label(col, v),
                                "metric": "accuracy",
                                "value": round(float(correct[mask].mean()), 3),
                                "n": n,
                            }
                        )
            if segs:
                segs.sort(key=lambda s: s["value"])
                out["per_segment"] = segs[:8]
    except Exception:
        pass

    # 3) 개별 예측 사례 3건 — 정분류/미탐(FN)/오탐(FP) 대표 + SHAP 지역 기여 top3
    try:
        cases: list[dict[str, Any]] = []
        picks: list[tuple[str, Any]] = []
        for kind, mask in (
            ("정분류", (yv == yp)),
            ("미탐 (FN)", (yv > yp) if len(set(yv.tolist())) == 2 else (yv != yp)),
            ("오탐 (FP)", (yv < yp) if len(set(yv.tolist())) == 2 else (yv != yp)),
        ):
            idxs = np.where(mask)[0]
            if len(idxs):
                picks.append((kind, int(idxs[0])))

        shap_vals = None
        _explainer = None
        try:
            import shap  # type: ignore

            _explainer = shap.TreeExplainer(model_obj)
            rows = X_val.iloc[[i for _, i in picks]] if hasattr(X_val, "iloc") else X_val[[i for _, i in picks]]
            sv = _explainer.shap_values(rows)
            shap_vals = sv[1] if isinstance(sv, list) and len(sv) == 2 else sv
        except Exception:
            shap_vals = None

        # jh 2026-06-12 — X_val 은 numpy 라 columns 없음. 학습 피처 순서는
        # _split_xy 의 select_dtypes(number·bool) 와 동일 — 전처리본 기준 feat_cols 사용.
        if hasattr(X_val, "columns"):
            feat_names = list(X_val.columns)
        elif feat_cols:
            feat_names = list(feat_cols)
        else:
            feat_names = []
        for j, (kind, i) in enumerate(picks):
            case: dict[str, Any] = {
                "case": kind,
                "actual": str(yv[i]),
                "predicted": str(yp[i]),
            }
            if shap_vals is not None and feat_names:
                try:
                    contrib = np.asarray(shap_vals)[j].ravel()
                    top = np.argsort(-np.abs(contrib))[:3]
                    case["top_features"] = [
                        {"feature": feat_names[k], "shap": round(float(contrib[k]), 3)} for k in top
                    ]
                except Exception:
                    pass
            cases.append(case)
        if cases:
            out["local_examples"] = cases

        # 4) 전역 SHAP Top — ExplainabilityAgent 실패 시에도 S13 이 채워지는 2중 안전망
        # (jh 2026-06-12 — 운영 덱에서 전역 SHAP 미적립 재발, explainer 재활용으로 직접 적립)
        try:
            if _explainer is not None and feat_names:
                sample = X_val[:200] if not hasattr(X_val, "iloc") else X_val.iloc[:200]
                sv_g = _explainer.shap_values(sample)
                sv_g = sv_g[1] if isinstance(sv_g, list) and len(sv_g) == 2 else sv_g
                arr = np.abs(np.asarray(sv_g))
                imp = arr.mean(axis=0) if arr.ndim == 2 else arr.mean(axis=(0, 2))
                imp = np.asarray(imp).ravel()
                if len(imp) == len(feat_names):
                    order = np.argsort(-imp)[:10]
                    out["global_importance"] = [
                        {"name": feat_names[k], "importance": round(float(imp[k]), 4)} for k in order
                    ]
                    logger.info("analysis_global_shap_ok: %d features", len(out["global_importance"]))
                else:
                    logger.warning("analysis_global_shap_len_mismatch: imp=%d feat=%d", len(imp), len(feat_names))
            else:
                logger.warning(
                    "analysis_global_shap_skipped: explainer=%s feat_names=%d",
                    _explainer is not None,
                    len(feat_names),
                )
        except Exception as _exc:  # noqa: BLE001
            logger.warning("analysis_global_shap_failed: %s", _exc)
    except Exception:
        pass

    return out

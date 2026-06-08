"""agents.handlers.tabular.diagnostics — 정형 진단 차트 (jh 담당, Day 11).

해석성·설명가능성 보강을 위한 진단 차트 3종을 한 모듈에 모음.
output_extras 가 점점 비대해지는 걸 막고, 진단 코드만 분리 테스트 가능하게 함.

차트:
  1. permutation_importance_chart : 학습된 모델에 대해 feature permutation 후
     예측 성능 하락 = 그 피처의 진짜 중요도. 트리 model.feature_importances_
     (split 빈도 기반) 와 다른 관점을 보완.
  2. pdp_chart                    : Partial Dependence Plot. top 4 피처에 대해
     "X 변화가 모델 예측에 어떤 영향을 미치는가" 시각화.
  3. qq_plot_chart                : 회귀 한정. 잔차의 정규성을 QQ plot 으로
     검증. 직선이면 정규분포(모델 가정 OK), 휘면 비정규(비선형 모델 필요).

전부 jh 영역. output_extras 가 직접 import 해서 assets() 진입점에서 호출.
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib  # noqa: WPS433

matplotlib.use("Agg")

logger = logging.getLogger(__name__)


# 비용 가드 상수
_PERMUTATION_MAX_ROWS = 5000  # permutation 은 n_repeats * n_features 학습 비용
_PERMUTATION_N_REPEATS = 5
_PDP_TOP_K = 4  # PDP 는 top 4 피처만


def _is_classification_from_state(state: Any) -> bool:
    """state.task + best_model.metrics 로 분류 여부 판단 (output_extras 와 동일 룰)."""
    task = getattr(state, "task", "auto")
    if task == "classification":
        return True
    if task == "regression":
        return False
    bm = getattr(state, "best_model", None) or {}
    metrics = bm.get("metrics") or {}
    if "val_f1" in metrics or "val_accuracy" in metrics or "val_roc_auc" in metrics:
        return True
    if "val_r2" in metrics or "val_rmse" in metrics:
        return False
    return True


def _common_guards(state: Any) -> bool:
    """모든 diagnostics 차트가 공유하는 가드. True 면 차트 생성 진행."""
    from pipelines.tabular_ml.pipeline import is_baseline_model

    bm = getattr(state, "best_model", None) or {}
    model_name = bm.get("model_name")
    if not model_name or is_baseline_model(model_name):
        return False
    if getattr(state, "category", "") == "tabular_dl":
        return False
    return True


def permutation_importance_chart(state: Any) -> str | None:
    """Permutation Importance 차트 → MinIO path.

    가드:
      - 공통 가드 (baseline/DL/no_model) 실패 → skip
      - n_rows > 5000 → skip (n_repeats * n_features 학습 비용 폭주)
      - 모델 재로드 실패 → skip
    """
    if not _common_guards(state):
        return None
    n_rows = int((getattr(state, "data_profile", None) or {}).get("rows", 0))
    if n_rows and n_rows > _PERMUTATION_MAX_ROWS:
        return None

    from agents.handlers.tabular.output_extras import _try_reload_model_and_data

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return None

    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from sklearn.inspection import permutation_importance

        from agents.handlers.common.shared import save_chart_to_minio

        model_obj, X_val, y_val = reload
        is_clf = _is_classification_from_state(state)
        scoring = "f1_weighted" if is_clf else "r2"
        result = permutation_importance(
            model_obj,
            X_val,
            y_val,
            n_repeats=_PERMUTATION_N_REPEATS,
            random_state=42,
            scoring=scoring,
            n_jobs=-1,
        )

        # top 10 정렬
        importances_mean = result.importances_mean
        importances_std = result.importances_std
        n_features = len(importances_mean)
        top_n = min(10, n_features)
        # 양수 importance 가 큰 순
        sorted_idx = np.argsort(importances_mean)[-top_n:]

        # 피처명: X_val 이 DataFrame 이면 columns, 아니면 index
        try:
            feature_names = list(getattr(X_val, "columns", []))
            if not feature_names or len(feature_names) != n_features:
                feature_names = [f"feature_{i}" for i in range(n_features)]
        except Exception:
            feature_names = [f"feature_{i}" for i in range(n_features)]

        labels = [feature_names[i] for i in sorted_idx]
        means = importances_mean[sorted_idx]
        stds = importances_std[sorted_idx]

        fig, ax = plt.subplots(figsize=(7, max(4, top_n * 0.4)), dpi=100)
        y_pos = np.arange(len(labels))
        ax.barh(y_pos, means, xerr=stds, color="#2563eb", alpha=0.8, capsize=3)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(labels)
        ax.set_xlabel(f"Permutation importance ({scoring} 하락)")
        model_name = (getattr(state, "best_model", None) or {}).get("model_name", "모델")
        ax.set_title(f"Permutation Importance — {model_name} (top {top_n})")
        ax.grid(True, axis="x", alpha=0.3)
        fig.tight_layout()

        return save_chart_to_minio(
            fig, kind="tabular/permutation_importance", job_id=getattr(state, "job_id", "")
        )

    except Exception as exc:
        logger.warning("permutation_importance_chart_failed: %s", exc)
        return None


def pdp_chart(state: Any) -> str | None:
    """Partial Dependence Plot → MinIO path.

    top 4 피처에 대해 PDP 를 grid 로 그림. 각 피처값 변화가 예측에 미치는
    평균적 효과를 시각화.

    가드:
      - 공통 가드 실패 → skip
      - 모델 재로드 실패 → skip
      - 피처가 너무 적으면 (< 2) → skip
    """
    if not _common_guards(state):
        return None

    from agents.handlers.tabular.output_extras import _try_reload_model_and_data

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return None

    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from sklearn.inspection import PartialDependenceDisplay

        from agents.handlers.common.shared import save_chart_to_minio

        model_obj, X_val, y_val = reload

        # 피처 개수
        n_features = X_val.shape[1] if hasattr(X_val, "shape") else len(X_val[0])
        if n_features < 2:
            return None

        top_k = min(_PDP_TOP_K, n_features)
        # 피처명
        try:
            feature_names = list(getattr(X_val, "columns", []))
            if not feature_names or len(feature_names) != n_features:
                feature_names = [f"feature_{i}" for i in range(n_features)]
        except Exception:
            feature_names = [f"feature_{i}" for i in range(n_features)]

        # 분산이 가장 큰 numeric 피처 top K 선택 (PDP 효과 잘 보임)
        try:
            X_arr = np.asarray(X_val)
            variances = np.nanvar(X_arr, axis=0)
            top_idx = list(np.argsort(variances)[-top_k:][::-1])
        except Exception:
            top_idx = list(range(top_k))

        # PDP 그리기 — 2x2 grid (top_k=4 기준)
        n_cols = 2
        n_rows = (top_k + n_cols - 1) // n_cols
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(10, n_rows * 3.5), dpi=100)
        axes_flat = axes.ravel() if top_k > 1 else [axes]

        is_clf = _is_classification_from_state(state)
        # multi-class 면 target=class 1 사용
        target_class = None
        if is_clf:
            try:
                if hasattr(model_obj, "classes_") and len(model_obj.classes_) > 2:
                    target_class = model_obj.classes_[1]
            except Exception:
                pass

        try:
            disp = PartialDependenceDisplay.from_estimator(
                model_obj,
                X_val,
                features=top_idx,
                feature_names=feature_names,
                ax=axes_flat[:top_k],
                kind="average",
                grid_resolution=20,
                target=target_class,
            )
            _ = disp  # noqa: F841 (ax 에 직접 그려짐)
        except Exception as exc:
            logger.warning("pdp_from_estimator_failed: %s", exc)
            plt.close(fig)
            return None

        # 사용 안 한 axes 숨김
        for i in range(top_k, len(axes_flat)):
            axes_flat[i].set_visible(False)

        model_name = (getattr(state, "best_model", None) or {}).get("model_name", "모델")
        fig.suptitle(f"Partial Dependence Plot — {model_name} (top {top_k})", fontsize=12)
        fig.tight_layout()

        return save_chart_to_minio(fig, kind="tabular/pdp", job_id=getattr(state, "job_id", ""))

    except Exception as exc:
        logger.warning("pdp_chart_failed: %s", exc)
        return None


def qq_plot_chart(state: Any) -> str | None:
    """QQ Plot 차트 (회귀 한정) → MinIO path.

    잔차를 정규분포 quantile 과 비교. 직선에 가까우면 잔차가 정규분포 →
    선형 회귀 모델 가정 OK. 휘면 비정규 → 비선형 변환 또는 다른 모델 필요.

    가드:
      - 회귀 task 만
      - 공통 가드 실패 → skip
      - 모델 재로드 실패 → skip
    """
    if _is_classification_from_state(state):
        return None
    if not _common_guards(state):
        return None

    from agents.handlers.tabular.output_extras import _try_reload_model_and_data

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return None

    try:
        import matplotlib.pyplot as plt
        import numpy as np

        from agents.handlers.common.shared import save_chart_to_minio

        model_obj, X_val, y_val = reload
        y_pred = model_obj.predict(X_val)
        residuals = np.asarray(y_val, dtype=float) - np.asarray(y_pred, dtype=float)

        # 정규성 검증: scipy.stats.probplot 사용 (scipy 는 test.txt 의존성)
        try:
            from scipy import stats as _stats

            fig, ax = plt.subplots(figsize=(6.5, 5), dpi=100)
            _stats.probplot(residuals, dist="norm", plot=ax)
            # probplot 의 기본 색을 본 프로젝트 톤으로 살짝 조정
            ax.get_lines()[0].set_markersize(4)
            ax.get_lines()[0].set_color("#2563eb")
            ax.get_lines()[1].set_color("#dc2626")
            ax.set_title("")
        except Exception:
            # scipy 미존재 시 수동 구현 — 단순 표본 quantile vs 정규 quantile
            fig, ax = plt.subplots(figsize=(6.5, 5), dpi=100)
            sorted_res = np.sort(residuals)
            n = len(sorted_res)
            # 정규분포 quantile (Filliben 추정)
            probs = (np.arange(1, n + 1) - 0.375) / (n + 0.25)
            # 표준 정규 inverse CDF 근사 — math.erfinv 활용 (Beasley-Springer)
            import math

            theo = np.array([math.sqrt(2) * math.erf(2 * p - 1) for p in probs])
            ax.scatter(theo, sorted_res, color="#2563eb", s=15, alpha=0.7)
            # 회귀선
            slope, intercept = np.polyfit(theo, sorted_res, 1)
            line_x = np.linspace(theo.min(), theo.max(), 100)
            ax.plot(line_x, slope * line_x + intercept, color="#dc2626", lw=1.5)
            ax.set_xlabel("Theoretical Quantiles")
            ax.set_ylabel("Sample Quantiles (잔차)")

        model_name = (getattr(state, "best_model", None) or {}).get("model_name", "모델")
        ax.set_title(f"QQ Plot — {model_name} 잔차 정규성")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()

        return save_chart_to_minio(fig, kind="tabular/qq_plot", job_id=getattr(state, "job_id", ""))

    except Exception as exc:
        logger.warning("qq_plot_chart_failed: %s", exc)
        return None

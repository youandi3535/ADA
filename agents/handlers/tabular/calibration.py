"""agents.handlers.tabular.calibration — 확률 보정 (jh 담당, Day 11++).

문제 정의
========
RF / XGBoost / LightGBM / CatBoost 의 predict_proba() 출력은 진짜 확률이 아님.
모델이 "80% 확률" 이라고 해도 실제로 80% 가 맞을 보장이 없음 → 사용자가 받는
산출물의 확률 숫자가 거짓말이 됨. 비즈니스 의사결정(cost-sensitive threshold,
expected loss, prioritization)이 다 깨짐.

본 모듈은:
  1. ECE (Expected Calibration Error) 측정으로 보정 상태 진단
  2. Platt scaling / Isotonic regression 두 보정 방법을 K-fold CV 로 정직하게 평가
  3. 더 낮은 ECE 를 내는 방법 자동 선택
  4. reliability diagram 차트 생성
  5. category_extras 에 저장 → insight·output_extras 가 인용

대상
====
  - 이진 분류만 (현재 구현). 다중분류는 향후 per-class ECE 로 확장.
  - 회귀 → skip (확률 개념 없음)
  - baseline 모델 → skip (Dummy/Ridge/LR predict_proba 보정 의미 약함)
  - val 샘플 < 50 → skip (ECE 신뢰 불가)
  - 모델 재로드 실패 → skip

저장 위치 (jh 영역)
==================
state.category_extras["tabular"]["calibration"] = {
    "ece_before"            : float — 보정 전 ECE
    "ece_after"             : float — 보정 후 ECE (CV 평균)
    "method"                : "platt" | "isotonic" | None
    "methods_tried"         : dict{name: ece} — 시도한 모든 방법
    "improvement_ratio"     : float — ece_after / ece_before (0~1, 낮을수록 개선)
    "reliability_chart_path": str | None — MinIO 차트 경로
    "n_samples_used"        : int
    "skipped_reason"        : str | None
}
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import matplotlib  # noqa: WPS433

matplotlib.use("Agg")

logger = logging.getLogger(__name__)


# 가드 상수
_MIN_VAL_SAMPLES = 50
_N_BINS = 10
_N_CV_SPLITS = 3  # 5 → 3: K-fold CV 시간 40% 단축 (honest 평가 충분)
_BASELINE_MODELS = {"Dummy", "LogisticRegression", "Ridge", "Lasso"}


# ──────────────────────────────────────────────────────────────────────────────
# Public — ECE 계산
# ──────────────────────────────────────────────────────────────────────────────


def compute_ece(y_true: Any, y_proba: Any, n_bins: int = _N_BINS) -> float:
    """Expected Calibration Error.

    예측 확률을 n_bins 균등 구간으로 나누고, 각 bin 의
        |bin 평균 예측 확률 - bin 실제 정답률| × (bin 비율)
    의 합. 0 = 완벽 보정, 0.5 = 최악.

    일반 기준:
      - ≤ 0.02 잘 보정됨
      - 0.02~0.05 보통
      - ≥ 0.05 보정 필요
      - ≥ 0.10 심각
    """
    import numpy as np

    y_true = np.asarray(y_true).astype(float)
    y_proba = np.asarray(y_proba).astype(float)
    n = len(y_true)
    if n == 0:
        return 0.0

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            in_bin = (y_proba >= lo) & (y_proba <= hi)
        else:
            in_bin = (y_proba >= lo) & (y_proba < hi)
        n_in = int(in_bin.sum())
        if n_in == 0:
            continue
        avg_proba = float(y_proba[in_bin].mean())
        actual = float(y_true[in_bin].mean())
        ece += abs(avg_proba - actual) * (n_in / n)
    return float(ece)


def reliability_diagram_data(y_true: Any, y_proba: Any, n_bins: int = _N_BINS) -> dict[str, list[float]]:
    """reliability diagram 시각화용 데이터.

    Returns:
        {
          "bin_mean_proba": list[float] — bin 별 평균 예측 확률
          "bin_actual"   : list[float] — bin 별 실제 정답률
          "bin_count"    : list[int]   — bin 별 샘플 수
          "bin_centers"  : list[float] — bin 중심점 (시각화 X 축용)
        }
    """
    import numpy as np

    y_true = np.asarray(y_true).astype(float)
    y_proba = np.asarray(y_proba).astype(float)

    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2.0

    bin_mean_proba: list[float] = []
    bin_actual: list[float] = []
    bin_count: list[int] = []

    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        if i == n_bins - 1:
            in_bin = (y_proba >= lo) & (y_proba <= hi)
        else:
            in_bin = (y_proba >= lo) & (y_proba < hi)
        n_in = int(in_bin.sum())
        if n_in == 0:
            bin_mean_proba.append(float("nan"))
            bin_actual.append(float("nan"))
        else:
            bin_mean_proba.append(float(y_proba[in_bin].mean()))
            bin_actual.append(float(y_true[in_bin].mean()))
        bin_count.append(n_in)

    return {
        "bin_mean_proba": bin_mean_proba,
        "bin_actual": bin_actual,
        "bin_count": bin_count,
        "bin_centers": [float(x) for x in bin_centers],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Public — 보정 방법
# ──────────────────────────────────────────────────────────────────────────────


class _PlattCalibrator:
    """joblib-picklable Platt scaling 보정기 (closure 대신 class)."""

    def __init__(self, lr: Any) -> None:
        self._lr = lr

    def __call__(self, new_proba: Any) -> Any:
        import numpy as np

        arr = np.asarray(new_proba).astype(float).reshape(-1, 1)
        return self._lr.predict_proba(arr)[:, 1]


class _IsotonicCalibrator:
    """joblib-picklable Isotonic 보정기 (closure 대신 class)."""

    def __init__(self, ir: Any) -> None:
        self._ir = ir

    def __call__(self, new_proba: Any) -> Any:
        import numpy as np

        return self._ir.predict(np.asarray(new_proba).astype(float))


def fit_platt(y_true: Any, y_proba: Any) -> Callable[[Any], Any]:
    """Platt scaling — predict_proba 출력 위에 LogisticRegression fit.

    데이터 적을 때 (≤ 1000) 또는 보정 곡선이 부드러울 때 잘 동작.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    y_true = np.asarray(y_true).astype(int)
    y_proba = np.asarray(y_proba).astype(float).reshape(-1, 1)

    lr = LogisticRegression(solver="lbfgs", max_iter=1000)
    lr.fit(y_proba, y_true)
    return _PlattCalibrator(lr)


def fit_isotonic(y_true: Any, y_proba: Any) -> Callable[[Any], Any]:
    """Isotonic regression — 단조 증가 비모수 보정.

    데이터 많을 때 (≥ 1000) 유연성 강함. Platt 보다 표현력 크지만 과적합 위험.
    """
    import numpy as np
    from sklearn.isotonic import IsotonicRegression

    y_true = np.asarray(y_true).astype(float)
    y_proba = np.asarray(y_proba).astype(float)

    ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    ir.fit(y_proba, y_true)
    return _IsotonicCalibrator(ir)


# ──────────────────────────────────────────────────────────────────────────────
# Internal — K-fold CV 로 honest ECE 평가
# ──────────────────────────────────────────────────────────────────────────────


def _evaluate_calibrator_cv(
    fit_fn: Callable[[Any, Any], Callable[[Any], Any]],
    y_true: Any,
    y_proba: Any,
    n_splits: int = _N_CV_SPLITS,
) -> float:
    """fit_fn 으로 보정기 만든 후 K-fold CV 로 ECE 평가.

    각 fold:
      - train 부분으로 보정기 fit
      - test 부분에서 보정된 확률의 ECE 계산
    평균 ECE 반환.

    이는 "보정 후 ECE 가 진짜로 낮은가" 를 정직하게 측정.
    (보정기 train/eval 데이터 분리 안 하면 과적합 — ECE 인위적으로 0 됨)
    """
    import numpy as np
    from sklearn.model_selection import KFold

    y_true = np.asarray(y_true).astype(float)
    y_proba = np.asarray(y_proba).astype(float)
    n = len(y_true)
    n_splits = min(n_splits, max(2, n // 20))  # 너무 작은 fold 방지

    kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    eces: list[float] = []
    for tr_idx, te_idx in kf.split(y_proba):
        # 양쪽 클래스 모두 train 에 있어야 LogisticRegression 동작
        if len(np.unique(y_true[tr_idx])) < 2:
            continue
        try:
            calibrator = fit_fn(y_true[tr_idx], y_proba[tr_idx])
            cal_proba = calibrator(y_proba[te_idx])
            eces.append(compute_ece(y_true[te_idx], cal_proba))
        except Exception as exc:
            logger.debug("calibrator_cv_fold_failed: %s", exc)
            continue
    if not eces:
        return float("nan")
    return float(sum(eces) / len(eces))


# ──────────────────────────────────────────────────────────────────────────────
# Internal — 결과 표준 형식
# ──────────────────────────────────────────────────────────────────────────────


def _skipped_result(reason: str) -> dict[str, Any]:
    """가드 통과 못 했을 때 표준 빈 결과."""
    return {
        "ece_before": None,
        "ece_after": None,
        "method": None,
        "methods_tried": {},
        "improvement_ratio": None,
        "reliability_chart_path": None,
        "calibrator_minio_path": None,
        "n_samples_used": 0,
        "skipped_reason": reason,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Honest gap closure — calibrator 직렬화 + 적용 (Day 11++ 후속)
# ──────────────────────────────────────────────────────────────────────────────


def _serialize_calibrator(calibrator: Any, method: str, state: Any) -> str | None:
    """학습된 calibrator 를 joblib 로 직렬화 → MinIO 업로드 → 경로 반환.

    실패 시 None (graceful — calibrate() 가 skipped_reason 안 채움. 산출물 표
    + insight 는 측정값만 그대로 표시. serving 적용은 calibrator 없으면 skip).
    """
    try:
        import io

        import joblib

        from tools.minio_tool import get_minio_client

        buf = io.BytesIO()
        joblib.dump({"calibrator": calibrator, "method": method}, buf)
        buf.seek(0)

        mc = get_minio_client()
        job_id = getattr(state, "job_id", "no-job")
        key = f"calibrators/tabular/{job_id}/{method}.joblib"
        mc.upload_bytes(buf.read(), key)
        return f"s3://{mc.bucket}/{key}"
    except Exception as exc:
        logger.warning("calibrator_serialize_failed: %s", exc)
        return None


def apply_calibration(state: Any, raw_proba: Any) -> Any:
    """raw predict_proba 출력에 보정 적용해 honest 확률 반환.

    serving·후처리 단에서 호출. 호출 우선순위:
      1. category_extras["tabular"]["calibration"]["calibrator_minio_path"]
         → joblib 다운로드 + 적용 (정식 경로)
      2. category_extras["tabular"]["calibration"]["method"]
         → val 데이터로 재학습 (fallback — calibrator 직렬화 실패한 경우)
      3. 둘 다 없음 → raw_proba 그대로 반환 (정상 — calibration skip 상태)

    Args:
        state    : PipelineState
        raw_proba: model.predict_proba(X) 의 양성 클래스 컬럼 (1-D array)

    Returns:
        보정된 확률 (1-D array) 또는 raw_proba 그대로.
    """
    import numpy as np

    raw = np.asarray(raw_proba).astype(float)

    cal_info = (getattr(state, "category_extras", None) or {}).get("tabular", {}).get("calibration") or {}
    method = cal_info.get("method")
    if not method:
        return raw

    # 경로 1: MinIO 에서 calibrator joblib 다운로드
    path = cal_info.get("calibrator_minio_path")
    if path:
        try:
            import io

            import joblib

            from tools.minio_tool import get_minio_client

            mc = get_minio_client()
            key = mc.object_key(path)
            blob = mc.download_bytes(key)
            payload = joblib.load(io.BytesIO(blob))
            calibrator = payload.get("calibrator")
            if callable(calibrator):
                return calibrator(raw)
            # IsotonicRegression 처럼 객체 자체에 predict 가 있는 경우
            if hasattr(calibrator, "predict"):
                return calibrator.predict(raw)
        except Exception as exc:
            logger.debug("calibrator_download_failed: %s → fallback 재학습 시도", exc)

    # 경로 2: val 데이터로 재학습 (output_extras._try_reload_model_and_data 활용)
    try:
        from agents.handlers.tabular.output_extras import _try_reload_model_and_data

        reload = _try_reload_model_and_data(state)
        if reload is None:
            return raw
        model_obj, X_val, y_val = reload
        if not hasattr(model_obj, "predict_proba"):
            return raw
        val_proba = model_obj.predict_proba(X_val)[:, 1]

        if method == "platt":
            calibrator = fit_platt(np.asarray(y_val).astype(float), val_proba)
        elif method == "isotonic":
            calibrator = fit_isotonic(np.asarray(y_val).astype(float), val_proba)
        else:
            return raw
        return calibrator(raw)
    except Exception as exc:
        logger.debug("calibrator_refit_failed: %s → raw 반환", exc)
        return raw


# ──────────────────────────────────────────────────────────────────────────────
# 핵심 진입점
# ──────────────────────────────────────────────────────────────────────────────


def calibrate(state: Any) -> dict[str, Any]:
    """state.best_model + val 데이터 → 보정 자동 시도 + 평가 + 차트.

    output 형식은 모듈 docstring 참조.
    """
    from pipelines.tabular_ml.pipeline import is_baseline_model

    bm = getattr(state, "best_model", None) or {}
    model_name = bm.get("model_name")

    # 가드 1: 분류만
    metrics = bm.get("metrics") or {}
    if "val_r2" in metrics and "val_f1" not in metrics:
        return _skipped_result("regression_not_supported")

    # 가드 2: 모델 존재
    if not model_name:
        return _skipped_result("no_best_model")

    # 가드 3: baseline skip (예측 곡선이 평탄해서 의미 없음)
    if is_baseline_model(model_name) or model_name in _BASELINE_MODELS:
        return _skipped_result("baseline_skip")

    # 가드 4: 모델 + 데이터 재로드
    from agents.handlers.tabular.output_extras import _try_reload_model_and_data

    reload = _try_reload_model_and_data(state)
    if reload is None:
        return _skipped_result("model_reload_failed")

    model_obj, X_val, y_val = reload

    # 가드 5: 이진분류만 (현재 구현)
    if not hasattr(model_obj, "predict_proba"):
        return _skipped_result("no_predict_proba")

    try:
        import numpy as np

        proba_full = model_obj.predict_proba(X_val)
        if proba_full.ndim != 2 or proba_full.shape[1] != 2:
            return _skipped_result("multiclass_not_supported")
        y_proba = proba_full[:, 1]
        y_true = np.asarray(y_val).astype(float)

        if len(y_true) < _MIN_VAL_SAMPLES:
            return _skipped_result(f"too_few_samples_lt_{_MIN_VAL_SAMPLES}")

        # 양쪽 클래스 모두 있어야 의미
        if len(np.unique(y_true)) < 2:
            return _skipped_result("single_class_only")

        # ECE before
        ece_before = compute_ece(y_true, y_proba)

        # 두 보정 방법 시도 + K-fold CV ECE
        methods_tried: dict[str, float] = {}
        try:
            ece_platt = _evaluate_calibrator_cv(fit_platt, y_true, y_proba)
            if not _is_nan(ece_platt):
                methods_tried["platt"] = float(ece_platt)
        except Exception as exc:
            logger.debug("platt_failed: %s", exc)

        try:
            ece_iso = _evaluate_calibrator_cv(fit_isotonic, y_true, y_proba)
            if not _is_nan(ece_iso):
                methods_tried["isotonic"] = float(ece_iso)
        except Exception as exc:
            logger.debug("isotonic_failed: %s", exc)

        if not methods_tried:
            return _skipped_result("all_calibrators_failed")

        # 최저 ECE 방법 선택
        best_method = min(methods_tried.keys(), key=lambda m: methods_tried[m])
        ece_after = methods_tried[best_method]
        improvement_ratio = ece_after / ece_before if ece_before > 0 else 0.0

        # reliability diagram 차트
        chart_path = _build_reliability_chart(y_true, y_proba, methods_tried, best_method, ece_before, state)

        # honest gap closure — best method 로 전체 val 에 fit 한 calibrator 직렬화
        # → MinIO 업로드. apply_calibration() 이 이걸 읽어 serving 시점에 적용.
        if best_method == "platt":
            best_calibrator = fit_platt(y_true, y_proba)
        elif best_method == "isotonic":
            best_calibrator = fit_isotonic(y_true, y_proba)
        else:
            best_calibrator = None
        calibrator_path = (
            _serialize_calibrator(best_calibrator, best_method, state) if best_calibrator is not None else None
        )

        return {
            "ece_before": round(float(ece_before), 4),
            "ece_after": round(float(ece_after), 4),
            "method": best_method,
            "methods_tried": {k: round(float(v), 4) for k, v in methods_tried.items()},
            "improvement_ratio": round(float(improvement_ratio), 3),
            "reliability_chart_path": chart_path,
            "calibrator_minio_path": calibrator_path,
            "n_samples_used": int(len(y_true)),
            "skipped_reason": None,
        }

    except Exception as exc:
        logger.warning("calibration_compute_failed: %s", exc)
        return _skipped_result(f"calibration_error: {type(exc).__name__}")


def _is_nan(x: float) -> bool:
    return x != x  # noqa: PLR0124


# ──────────────────────────────────────────────────────────────────────────────
# Internal — reliability diagram 차트
# ──────────────────────────────────────────────────────────────────────────────


def _build_reliability_chart(
    y_true: Any,
    y_proba: Any,
    methods_tried: dict[str, float],
    best_method: str,
    ece_before: float,
    state: Any,
) -> str | None:
    """raw + 보정 후 reliability diagram 을 한 차트에 표시."""
    try:
        import matplotlib.pyplot as plt
        import numpy as np

        from agents.handlers.common.shared import save_chart_to_minio

        model_name = (getattr(state, "best_model", None) or {}).get("model_name", "모델")

        # raw 곡선
        raw_data = reliability_diagram_data(y_true, y_proba, n_bins=_N_BINS)

        # 보정 후 곡선 (best_method 로 전체 데이터 fit 후 그 자체 평가 — 시각용)
        if best_method == "platt":
            calibrator = fit_platt(y_true, y_proba)
        else:
            calibrator = fit_isotonic(y_true, y_proba)
        y_proba_cal = calibrator(y_proba)
        cal_data = reliability_diagram_data(y_true, y_proba_cal, n_bins=_N_BINS)

        fig, axes = plt.subplots(1, 2, figsize=(12, 5), dpi=100)

        # (1) reliability diagram
        ax = axes[0]
        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6, label="완벽 보정")

        # raw
        raw_x = [x for x, c in zip(raw_data["bin_centers"], raw_data["bin_count"]) if c > 0]
        raw_y = [y for y, c in zip(raw_data["bin_actual"], raw_data["bin_count"]) if c > 0]
        ax.plot(raw_x, raw_y, "o-", color="#dc2626", lw=2, label=f"보정 전 (ECE={ece_before:.3f})")

        # calibrated
        cal_x = [x for x, c in zip(cal_data["bin_centers"], cal_data["bin_count"]) if c > 0]
        cal_y = [y for y, c in zip(cal_data["bin_actual"], cal_data["bin_count"]) if c > 0]
        ax.plot(
            cal_x,
            cal_y,
            "s-",
            color="#2563eb",
            lw=2,
            label=f"보정 후 — {best_method} (ECE={methods_tried[best_method]:.3f})",
        )

        ax.set_xlabel("평균 예측 확률")
        ax.set_ylabel("실제 양성 비율")
        ax.set_title(f"Reliability Diagram — {model_name}")
        ax.legend(loc="upper left", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)

        # (2) 예측 확률 히스토그램 — 분포 진단
        ax2 = axes[1]
        ax2.hist(y_proba, bins=20, color="#dc2626", alpha=0.5, label="보정 전")
        ax2.hist(np.asarray(y_proba_cal), bins=20, color="#2563eb", alpha=0.5, label="보정 후")
        ax2.set_xlabel("예측 확률")
        ax2.set_ylabel("샘플 수")
        ax2.set_title("예측 확률 분포")
        ax2.legend(fontsize=9)
        ax2.grid(True, alpha=0.3)

        fig.tight_layout()

        return save_chart_to_minio(fig, kind="tabular/reliability_diagram", job_id=getattr(state, "job_id", ""))
    except Exception as exc:
        logger.warning("reliability_chart_failed: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 편의 함수 — caller (output_extras) 가 호출
# ──────────────────────────────────────────────────────────────────────────────


def reliability_diagram_chart(state: Any) -> str | None:
    """output_extras 가 charts 리스트에 추가하기 위해 호출.

    category_extras 캐시 우선. 없으면 calibrate() 한 번 실행.
    """
    cached = (getattr(state, "category_extras", None) or {}).get("tabular", {}).get("calibration")
    if isinstance(cached, dict) and cached.get("reliability_chart_path"):
        return cached["reliability_chart_path"]
    result = calibrate(state)
    return result.get("reliability_chart_path")

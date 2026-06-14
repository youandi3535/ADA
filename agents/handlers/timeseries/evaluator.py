"""agents.handlers.timeseries.evaluator — 시계열 평가 (CS 담당, cs-day7 v3 디벨롭).

cs-day6 의 pipeline.evaluate 가 MASE/sMAPE/naïve/PI coverage 까지 모두 계산하여
metrics dict 에 포함. 본 evaluator 는 자매 카테고리 (anomaly · tabular) 와 동일 패턴
— 단순 임계치 판정 + cs-day7 v3 디벨롭 (walk-forward 진단 + 누수 사후 진단 + 증상 분류).

진입함수 (dispatcher 자동 등록):
  - evaluate(state) -> dict   반환: passed / rationale / threshold_violations / metrics
                                    + fold_diagnostics / leakage_suspect_signals / symptom_classification

DoD (불변):
  - eval_result["metrics"]["rmse_improvement_vs_naive"] 필드 (cs-day6 가 채움 → cs-day7 전달)
  - 기존 4 키 (passed, rationale, threshold_violations, metrics) 그대로

cs-day7 v3 디벨롭 (신규 — 헌장 갭 해소):
  H1 fold_diagnostics — 롤백 원칙 5 (fold 분산 판정)
     · cv (변동계수) 기반 안정성 분류 (stable / unstable / very_unstable)
     · best_model["fold_scores"] 또는 best_model.metrics["fold_scores"] 둘 다 지원
     · 없으면 {"available": False} — 기존 동작 그대로 (회귀 0)
  H2 leakage_suspect_signals — 누수 1-6 사후 진단
     · (a) too_good_vs_naive: improvement > 0.95 비현실적
     · (b) mase_too_low:      MASE < 0.01 거의 완벽 예측 = 타겟 누수 의심
     · (c) single_fold_outlier_good: 특정 fold 만 mean+2σ 초과
  H3 symptom_classification — 헌장 7단계 증상 A~E 자동 분류
     · 우선순위: 누수 의심(C) > fold 출렁임(D) > naïve 못 이김(E) > 과소적합(B) > 정상

핵심 설계 원칙:
  - 자매 카테고리와 동일 시그니처/구조 + 추가 키 노출 (anomaly 패턴)
  - 데이터 재로드 X — cs-day6 가 모든 메트릭 계산
  - 상대 임계치 — 절대 RMSE X · improvement + MASE 핵심
  - violations 누적 — 단일 violation 으로도 passed=False
  - None 안전 — MASE/sMAPE/cov/fold_scores 가 None 이면 임계치 skip
  - 회귀 0 — 기존 4 키 불변, 신규 3 키만 추가
"""

from __future__ import annotations

import math
from typing import Any, Optional

# ── 임계치 (시계열 특수성 — 상대값 위주) ──────────────────────────
THRESHOLDS = {
    "rmse_improvement_vs_naive_min": 0.0,  # > 0 통과 (naïve 보다 우수)
    "MASE_max": 1.0,  # < 1.0 통과 (in-sample naïve 보다 우수)
    "sMAPE_max": 30.0,  # < 30% 통과 (있을 때만)
    "pi_coverage_min": 0.90,  # ≥ 0.90 통과 (있을 때만)
}

# 누수 1-6 사후 진단 임계
LEAKAGE_IMPROVEMENT_SUSPECT = 0.95  # naïve 대비 95%+ 개선 = 비현실적
LEAKAGE_MASE_SUSPECT = 0.01  # MASE 거의 0 = 타겟 누수 의심
LEAKAGE_SMAPE_SUSPECT = 0.5  # sMAPE 0.5% 미만 = 거의 완벽 예측 (누수 의심)
LEAKAGE_PI_COV_TOO_HIGH = 0.999  # PI coverage 0.999+ = 구간이 비현실적으로 넓음 (PI 무의미)
FOLD_OUTLIER_SIGMA = 2.0  # 특정 fold > mean+2σ → 누수 의심

# 롤백 5 fold 분산 안정성 임계 (변동계수 = std/|mean|)
FOLD_CV_STABLE = 0.5  # cv < 0.5 = 안정
FOLD_CV_UNSTABLE = 1.0  # 0.5 ≤ cv < 1.0 = 불안정 / ≥ 1.0 = 매우 불안정

# OF5 (2026-06-05) — 과적합/과소적합 진단 임계
OVERFIT_GAP_WARN = 0.30  # val_rmse 가 train_rmse 의 +30% = 과적합 의심
OVERFIT_GAP_SEVERE = 0.60  # +60% = 심각한 과적합
UNDERFIT_MASE_MIN = 1.0  # MASE >= 1.0 + improvement <= 0 = 과소적합 (naive 못 이김)


# X3 (2026-06-05) — 적응형 임계 (데이터 길이 따라 동적 조정)
def _adaptive_thresholds(state: Any) -> dict[str, float]:
    """데이터 특성에 맞춰 THRESHOLDS 동적 조정.

    - n_rows < 100 (짧은 시계열): MASE_max 1.0 → 1.2 (완화), pi_coverage_min 0.90 → 0.85
    - n_rows >= 1000 (긴 시계열): MASE_max 1.0 → 0.85 (강화), sMAPE_max 30 → 25
    - 기타: 기본값 유지

    헌장 5단계 "임계는 데이터 통계로 결정" 의 일관.
    """
    out = dict(THRESHOLDS)
    try:
        profile = getattr(state, "data_profile", None) or {}
        n_rows = int(profile.get("rows") or profile.get("n_rows") or 0)
        if n_rows == 0:
            return out
        if n_rows < 100:
            out["MASE_max"] = 1.2
            out["pi_coverage_min"] = 0.85
        elif n_rows >= 1000:
            out["MASE_max"] = 0.85
            out["sMAPE_max"] = 25.0
    except Exception:
        pass
    return out


# ════════════════════════════════════════════════════════════════
# §H4 (2026-06-05) — overfit / underfit 진단 (OF5)
# ════════════════════════════════════════════════════════════════
def _diagnose_fit_quality(metrics: dict) -> dict[str, Any]:
    """train_rmse vs val_rmse 격차 + MASE + improvement 종합 진단.

    반환:
      kind     : "overfit" | "underfit" | "ok" | "unknown"
      severity : "none" | "warn" | "severe"
      train_rmse / val_rmse / overfit_gap : 인용용
      hint     : 한국어 권장 조치
    """
    if not isinstance(metrics, dict):
        return {"kind": "unknown", "severity": "none"}

    train_rmse = metrics.get("train_rmse")
    val_rmse = metrics.get("val_rmse")
    overfit_gap = metrics.get("overfit_gap")
    mase = metrics.get("MASE")
    improvement = metrics.get("rmse_improvement_vs_naive")

    # 과소적합 우선 판정
    try:
        imp_f = float(improvement) if improvement is not None else None
        mase_f = float(mase) if mase is not None else None
        if imp_f is not None and imp_f <= 0 and mase_f is not None and mase_f >= UNDERFIT_MASE_MIN:
            return {
                "kind": "underfit",
                "severity": "severe",
                "train_rmse": train_rmse,
                "val_rmse": val_rmse,
                "overfit_gap": overfit_gap,
                "hint": (
                    "naïve 기준선조차 못 이겼습니다 — 피처 부족 또는 모델 용량 부족. "
                    "lag/달력/푸리에 피처 추가 또는 더 표현력 있는 모델 (TFT/Prophet) 시도 권장."
                ),
            }
    except (TypeError, ValueError):
        pass

    # 과적합 판정
    if isinstance(overfit_gap, (int, float)):
        gap = float(overfit_gap)
        if gap >= OVERFIT_GAP_SEVERE:
            return {
                "kind": "overfit",
                "severity": "severe",
                "train_rmse": train_rmse,
                "val_rmse": val_rmse,
                "overfit_gap": round(gap, 3),
                "hint": (
                    f"심각한 과적합 (val_rmse 가 train_rmse 의 +{gap:.0%}). "
                    "정규화 강화 (ARIMA 차수 축소 / DL dropout↑ / Prophet changepoint_prior_scale↓) 권장."
                ),
            }
        if gap >= OVERFIT_GAP_WARN:
            return {
                "kind": "overfit",
                "severity": "warn",
                "train_rmse": train_rmse,
                "val_rmse": val_rmse,
                "overfit_gap": round(gap, 3),
                "hint": (f"과적합 의심 (val_rmse 가 train_rmse 의 +{gap:.0%}). fold 수 증가 또는 모델 용량 축소 검토."),
            }
        return {
            "kind": "ok",
            "severity": "none",
            "train_rmse": train_rmse,
            "val_rmse": val_rmse,
            "overfit_gap": round(gap, 3),
            "hint": "train/val 격차 정상.",
        }

    return {"kind": "unknown", "severity": "none"}


# ════════════════════════════════════════════════════════════════
# §H5 (2026-06-05) — 학습 사후 잔차 진단 (G15)
# ════════════════════════════════════════════════════════════════
def _diagnose_residuals(metrics: dict) -> dict[str, Any]:
    """잔차 자기상관·정규성·평균 검정 — 표준 시계열 분석 15단계.

    pipeline.evaluate 가 metrics 에 y_pred_val·y_val_actual 을 저장하므로 검증 잔차로 진단.

    반환:
      kind     : "white_noise" | "autocorrelated" | "biased" | "unknown"
      ljung_box_p : float | None
      mean_pct  : 잔차 평균 / 타깃 평균 (편향 진단)
      hint     : 한국어 권장 조치
    """
    if not isinstance(metrics, dict):
        return {"kind": "unknown"}

    y_pred = metrics.get("y_pred_val")
    y_true = metrics.get("y_val_actual")
    if not (isinstance(y_pred, list) and isinstance(y_true, list) and len(y_pred) >= 10):
        return {"kind": "unknown", "reason": "insufficient_residuals"}

    try:
        import numpy as _np

        y_pred_arr = _np.asarray(y_pred, dtype=float).flatten()
        y_true_arr = _np.asarray(y_true, dtype=float).flatten()
        L = min(len(y_pred_arr), len(y_true_arr))
        residuals = y_true_arr[:L] - y_pred_arr[:L]
        mask = ~_np.isnan(residuals)
        residuals = residuals[mask]
        if len(residuals) < 10:
            return {"kind": "unknown", "reason": "too_few_after_nan"}

        # (1) Ljung-Box 검정 — 잔차 자기상관 (p > 0.05 = white noise)
        ljung_p: Any = None
        try:
            from statsmodels.stats.diagnostic import acorr_ljungbox  # noqa: WPS433

            lb_lag = min(10, len(residuals) // 5)
            lb = acorr_ljungbox(residuals, lags=[max(1, lb_lag)], return_df=True)
            ljung_p = float(lb["lb_pvalue"].iloc[0])
        except Exception:
            pass

        # (2) 평균 편향 — |mean(resid)| / mean(|y_true|)
        y_abs_mean = float(_np.mean(_np.abs(y_true_arr[mask])))
        mean_pct = float(abs(_np.mean(residuals)) / y_abs_mean) if y_abs_mean > 1e-9 else 0.0

        # (2.5) Shapiro-Wilk 정규성 검정 (2026-06-14, Phase Ⅳ — P5)
        # 잔차가 정규분포에 가까운지 → PI(예측구간)의 가정 충족 여부.
        # p>0.05 → 정규성 통과. n>5000 시 skip(통계적 위양성 회피).
        shapiro_p: Any = None
        skew_v: Any = None
        kurt_v: Any = None
        try:
            from scipy.stats import kurtosis, shapiro, skew  # noqa: WPS433

            if 3 <= len(residuals) <= 5000:
                _stat, _p = shapiro(residuals)
                shapiro_p = float(_p)
            skew_v = float(skew(residuals)) if len(residuals) >= 3 else None
            kurt_v = float(kurtosis(residuals)) if len(residuals) >= 3 else None
        except Exception:
            pass

        # 등급 1 #6 (2026-06-14) — noise 확률 산출
        # Hurst exponent (랜덤워크 판정) + Spectral entropy (균등 분포 판정)
        # 둘 다 noise 지표 → 0~1 noise_probability 통합 점수.
        hurst_v: Any = None
        spec_ent: Any = None
        noise_prob: Any = None
        try:
            if len(residuals) >= 50:
                # Hurst: R/S 분석 — H≈0.5 = 랜덤워크 (예측 불가)
                lags = _np.arange(2, min(20, len(residuals) // 5))
                tau = [_np.std(_np.subtract(residuals[lag:], residuals[:-lag])) for lag in lags]
                tau_valid = [(lag_v, t) for lag_v, t in zip(lags, tau) if t > 1e-12]
                if len(tau_valid) >= 3:
                    log_lag = _np.log([lag_v for lag_v, _ in tau_valid])
                    log_tau = _np.log([t for _, t in tau_valid])
                    hurst_v = float(_np.polyfit(log_lag, log_tau, 1)[0])
            if len(residuals) >= 32:
                # Spectral entropy: 균등 분포 = 1.0 (완전 noise), 집중 = 0.0
                fft = _np.abs(_np.fft.rfft(residuals - _np.mean(residuals)))
                psd = fft**2
                psd_sum = psd.sum()
                if psd_sum > 1e-12:
                    psd_norm = psd / psd_sum
                    ent = -_np.sum(psd_norm * _np.log(psd_norm + 1e-12))
                    spec_ent = float(ent / _np.log(len(psd_norm)))  # 정규화 0~1
            # noise_probability — Hurst≈0.5 + Spectral entropy 높음 → noise 확률 ↑
            if hurst_v is not None and spec_ent is not None:
                hurst_noise = max(0.0, 1.0 - 2.0 * abs(hurst_v - 0.5))  # H=0.5 → 1, H=0/1 → 0
                noise_prob = float(0.5 * hurst_noise + 0.5 * spec_ent)
        except Exception:
            pass

        # 판정
        bias_warn = mean_pct > 0.10
        # 정규성 메타 (공통 키)
        _norm_meta = {
            "shapiro_p": round(shapiro_p, 4) if shapiro_p is not None else None,
            "normal_ok": (shapiro_p is not None and shapiro_p > 0.05),
            "skew": round(skew_v, 3) if skew_v is not None else None,
            "kurtosis": round(kurt_v, 3) if kurt_v is not None else None,
            # 등급 1 #6 — noise 확률 진단
            "hurst_exponent": round(hurst_v, 3) if hurst_v is not None else None,
            "spectral_entropy": round(spec_ent, 3) if spec_ent is not None else None,
            "noise_probability": round(noise_prob, 3) if noise_prob is not None else None,
        }
        if ljung_p is not None and ljung_p > 0.05 and not bias_warn:
            return {
                "kind": "white_noise",
                "ljung_box_p": round(ljung_p, 4),
                "mean_pct": round(mean_pct, 4),
                "hint": "잔차가 백색잡음에 가까워 모델이 신호를 충분히 추출했습니다.",
                **_norm_meta,
            }
        if ljung_p is not None and ljung_p <= 0.05:
            return {
                "kind": "autocorrelated",
                "ljung_box_p": round(ljung_p, 4),
                "mean_pct": round(mean_pct, 4),
                "hint": (
                    f"잔차 자기상관 잔존 (Ljung-Box p={ljung_p:.3f} ≤ 0.05) — 모델이 잡지 못한 시간 의존성. "
                    "lag 추가 / 차분 차수 증가 / 더 큰 ARIMA 차수 검토."
                ),
                **_norm_meta,
            }
        if bias_warn:
            return {
                "kind": "biased",
                "ljung_box_p": round(ljung_p, 4) if ljung_p is not None else None,
                "mean_pct": round(mean_pct, 4),
                "hint": f"잔차 평균 편향 +{mean_pct:.1%} — 추세 보정 / 상수항 추가 검토.",
                **_norm_meta,
            }
        return {"kind": "unknown", "ljung_box_p": ljung_p, "mean_pct": round(mean_pct, 4), **_norm_meta}
    except Exception as exc:  # noqa: BLE001
        return {"kind": "unknown", "reason": f"diagnose_failed: {exc}"}


# ════════════════════════════════════════════════════════════════
# §H6 (2026-06-05) — Diebold-Mariano 검정 (G13)
# ════════════════════════════════════════════════════════════════
def _dm_test(metrics: dict) -> dict[str, Any]:
    """Diebold-Mariano 검정 — top1 모델 vs naïve 예측력 통계 비교.

    pipeline.evaluate 의 y_pred_val · y_val_actual + naive_kind/naive_s 활용해
    naïve 예측 재구성 → 두 시리즈의 손실 차이 검정.

    반환:
      available  : bool
      dm_stat    : float | None
      p_value    : float | None
      verdict    : "model_wins" | "naive_wins" | "tie"
      hint       : 한국어 안내
    """
    if not isinstance(metrics, dict):
        return {"available": False, "reason": "no_metrics"}

    y_pred = metrics.get("y_pred_val")
    y_true = metrics.get("y_val_actual")
    y_train_tail = metrics.get("y_train_tail")
    if not (isinstance(y_pred, list) and isinstance(y_true, list)):
        return {"available": False, "reason": "no_pred_or_actual"}
    if len(y_pred) < 5 or len(y_true) < 5:
        return {"available": False, "reason": "too_few"}

    try:
        import numpy as _np

        y_pred_arr = _np.asarray(y_pred, dtype=float).flatten()
        y_true_arr = _np.asarray(y_true, dtype=float).flatten()
        L = min(len(y_pred_arr), len(y_true_arr))
        y_pred_arr = y_pred_arr[:L]
        y_true_arr = y_true_arr[:L]

        # naïve 예측 재구성 — y_train_tail 마지막 값 반복 (simple naïve)
        if isinstance(y_train_tail, list) and len(y_train_tail) > 0:
            naive_val = float(y_train_tail[-1])
        else:
            naive_val = float(y_true_arr[0])
        y_naive = _np.full(L, naive_val)

        # 손실 차이 (squared error)
        d = (y_true_arr - y_pred_arr) ** 2 - (y_true_arr - y_naive) ** 2
        d = d[~_np.isnan(d)]
        if len(d) < 5:
            return {"available": False, "reason": "nan_after_filter"}

        d_mean = float(_np.mean(d))
        d_var = float(_np.var(d, ddof=1))
        if d_var <= 0:
            return {"available": True, "dm_stat": 0.0, "p_value": 1.0, "verdict": "tie", "hint": "두 모델 차이 없음."}

        dm_stat = d_mean / _np.sqrt(d_var / len(d))

        # 양측 p-value (정규근사)
        from scipy import stats as _st  # noqa: WPS433

        p_value = float(2.0 * (1.0 - _st.norm.cdf(abs(dm_stat))))

        if p_value < 0.05:
            if d_mean < 0:
                return {
                    "available": True,
                    "dm_stat": round(float(dm_stat), 3),
                    "p_value": round(p_value, 4),
                    "verdict": "model_wins",
                    "hint": f"DM 검정 p={p_value:.3f} — 모델이 naïve 대비 통계적으로 우수.",
                }
            return {
                "available": True,
                "dm_stat": round(float(dm_stat), 3),
                "p_value": round(p_value, 4),
                "verdict": "naive_wins",
                "hint": f"DM 검정 p={p_value:.3f} — 모델이 naïve 보다 통계적으로 못함. 모델 재검토.",
            }
        return {
            "available": True,
            "dm_stat": round(float(dm_stat), 3),
            "p_value": round(p_value, 4),
            "verdict": "tie",
            "hint": f"DM 검정 p={p_value:.3f} — 모델과 naïve 간 통계적 차이 미확인.",
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"dm_failed: {exc}"}


# ════════════════════════════════════════════════════════════════
# §0. 헬퍼
# ════════════════════════════════════════════════════════════════
def _safe_mean(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    return float(sum(xs) / len(xs))


def _safe_std(xs: list[float]) -> Optional[float]:
    n = len(xs)
    if n < 2:
        return 0.0 if n == 1 else None
    m = _safe_mean(xs)
    if m is None:
        return None
    var = sum((x - m) ** 2 for x in xs) / n  # population std (분산 = E[(X-μ)²])
    return float(math.sqrt(var))


def _extract_fold_scores(best: dict) -> Optional[list[float]]:
    """best_model 어디에 fold_scores 가 있어도 안전 추출.

    탐색 순서 (호환성 — HJ HyperparameterTuner/TrainingExecutor 가
    어디에 넣어도 잡힘):
      1. best_model["fold_scores"]
      2. best_model.get("metrics", {}).get("fold_scores")
      3. best_model.get("cv_result", {}).get("fold_scores")
    """
    if not isinstance(best, dict):
        return None
    candidates = [
        best.get("fold_scores"),
        (best.get("metrics") or {}).get("fold_scores") if isinstance(best.get("metrics"), dict) else None,
        (best.get("cv_result") or {}).get("fold_scores") if isinstance(best.get("cv_result"), dict) else None,
    ]
    for c in candidates:
        if isinstance(c, list) and c:
            try:
                return [float(x) for x in c if x is not None]
            except (TypeError, ValueError):
                continue
    return None


def _extract_fold_metrics(best: dict) -> Optional[list[dict[str, Any]]]:
    """L5 — fold 별 상세 metrics (val_rmse/val_mae/MASE/improvement) 안전 추출.

    pipeline.train_with_cv 가 반환하는 fold_metrics list[dict] 가 best_model 에
    도달했을 때만 활성. 없으면 None.
    """
    if not isinstance(best, dict):
        return None
    candidates = [
        best.get("fold_metrics"),
        (best.get("metrics") or {}).get("fold_metrics") if isinstance(best.get("metrics"), dict) else None,
        (best.get("cv_result") or {}).get("fold_metrics") if isinstance(best.get("cv_result"), dict) else None,
    ]
    for c in candidates:
        if isinstance(c, list) and c and all(isinstance(x, dict) for x in c):
            return list(c)
    return None


# ════════════════════════════════════════════════════════════════
# §H1. fold_diagnostics — 롤백 원칙 5 (fold 분산 판정)
# ════════════════════════════════════════════════════════════════
def _diagnose_fold_variance(fold_scores: Optional[list[float]]) -> dict[str, Any]:
    """walk-forward fold 분산 진단 (방법론 4-1·롤백 5).

    반환 키:
      available    : bool (fold_scores 있어야 True)
      n_folds      : int
      mean / std   : float
      cv           : 변동계수 = std / max(|mean|, eps) — 부호 무관 절대 변동
      range_ratio  : (max - min) / max(|mean|, eps)
      stability    : "stable" / "unstable" / "very_unstable"
      best_fold    : (idx, score) 가장 좋은 fold
      worst_fold   : (idx, score) 가장 나쁜 fold
    """
    if not fold_scores or len(fold_scores) < 2:
        return {
            "available": False,
            "reason": "no_folds_or_single_fold",
            "n_folds": len(fold_scores) if fold_scores else 0,
        }
    mean = _safe_mean(fold_scores)
    std = _safe_std(fold_scores)
    if mean is None or std is None:
        return {"available": False, "reason": "stats_failed"}
    eps = 1e-9
    abs_mean = max(abs(mean), eps)
    cv = float(std / abs_mean)
    range_ratio = float((max(fold_scores) - min(fold_scores)) / abs_mean)

    if cv < FOLD_CV_STABLE:
        stability = "stable"
    elif cv < FOLD_CV_UNSTABLE:
        stability = "unstable"
    else:
        stability = "very_unstable"

    best_idx = int(max(range(len(fold_scores)), key=lambda i: fold_scores[i]))
    worst_idx = int(min(range(len(fold_scores)), key=lambda i: fold_scores[i]))

    return {
        "available": True,
        "n_folds": int(len(fold_scores)),
        "mean": round(mean, 6),
        "std": round(std, 6),
        "cv": round(cv, 4),
        "range_ratio": round(range_ratio, 4),
        "stability": stability,
        "best_fold": {"idx": best_idx, "score": round(float(fold_scores[best_idx]), 6)},
        "worst_fold": {"idx": worst_idx, "score": round(float(fold_scores[worst_idx]), 6)},
    }


def _diagnose_fold_metrics(fold_metrics: Optional[list[dict[str, Any]]]) -> dict[str, Any]:
    """L5 — fold 별 val_rmse 분산 진단 (per-metric).

    pipeline.train_with_cv 의 fold_metrics 가 있을 때만 활성. fold_scores
    (improvement) 가 안정해도 val_rmse 분산이 크면 fold 별 어려움 차이가 큼.
    """
    if not fold_metrics or len(fold_metrics) < 2:
        return {"available": False, "reason": "no_fold_metrics_or_single"}
    out: dict[str, Any] = {"available": True, "n_folds": len(fold_metrics), "per_metric": {}}
    for key in ("val_rmse", "val_mae", "MASE"):
        vals = [m.get(key) for m in fold_metrics if isinstance(m, dict) and m.get(key) is not None]
        if len(vals) < 2:
            continue
        try:
            vals_f = [float(v) for v in vals]
        except (TypeError, ValueError):
            continue
        m = _safe_mean(vals_f)
        s = _safe_std(vals_f)
        if m is None or s is None:
            continue
        out["per_metric"][key] = {
            "n": len(vals_f),
            "mean": round(m, 6),
            "std": round(s, 6),
            "cv": round(s / max(abs(m), 1e-9), 4),
            "min": round(min(vals_f), 6),
            "max": round(max(vals_f), 6),
        }
    return out


# ════════════════════════════════════════════════════════════════
# §H2. leakage_suspect_signals — 누수 1-6 사후 진단
# ════════════════════════════════════════════════════════════════
def _detect_leakage_signals(metrics: dict, fold_scores: Optional[list[float]]) -> list[dict[str, Any]]:
    """누수 1-6 사후 진단 — 비현실적 좋은 성능 / 특정 fold 폭발 등.

    헌장 누수 1-6 (사후 진단):
      (a) 검증 성능이 비현실적으로 좋다 → 1순위 누수 의심
      (b) MASE 가 거의 0 → 타겟 누수 (피처가 타겟 자체)
      (c) 특정 fold 만 비정상 좋음 → 그 fold 경계 누수

    반환: list[dict] — 각 dict 는 {kind, value, threshold, hint}
    """
    signals: list[dict[str, Any]] = []
    if not isinstance(metrics, dict):
        return signals

    imp = metrics.get("rmse_improvement_vs_naive")
    mase = metrics.get("MASE")

    # (a) too_good_vs_naive — improvement 도메인 상식 초과
    if imp is not None:
        try:
            imp_f = float(imp)
            if imp_f > LEAKAGE_IMPROVEMENT_SUSPECT:
                signals.append(
                    {
                        "kind": "too_good_vs_naive",
                        "value": round(imp_f, 4),
                        "threshold": LEAKAGE_IMPROVEMENT_SUSPECT,
                        "hint": (
                            "검증 improvement 가 비현실적으로 좋습니다. "
                            "방법론 누수 1-6 (a): 1순위 누수 의심 — 타겟/시간정렬/전처리 점검 권장."
                        ),
                    }
                )
        except (TypeError, ValueError):
            pass

    # (b) MASE 비정상 낮음 — 타겟 누수
    if mase is not None:
        try:
            mase_f = float(mase)
            if 0.0 <= mase_f < LEAKAGE_MASE_SUSPECT:
                signals.append(
                    {
                        "kind": "mase_too_low",
                        "value": round(mase_f, 6),
                        "threshold": LEAKAGE_MASE_SUSPECT,
                        "hint": (
                            "MASE 가 거의 0 — 모델이 in-sample naïve 보다 100x 우수합니다. "
                            "타겟 누수 의심 (피처에 타겟 정보가 새고 있을 수 있음)."
                        ),
                    }
                )
        except (TypeError, ValueError):
            pass

    # L7 — (d) sMAPE 비정상 낮음 — 타겟 누수
    smape = metrics.get("sMAPE")
    if smape is not None:
        try:
            smape_f = float(smape)
            if 0.0 <= smape_f < LEAKAGE_SMAPE_SUSPECT:
                signals.append(
                    {
                        "kind": "smape_too_low",
                        "value": round(smape_f, 4),
                        "threshold": LEAKAGE_SMAPE_SUSPECT,
                        "hint": (f"sMAPE 가 {smape_f:.3f}% — 거의 완벽 예측입니다. 타겟 누수 또는 데이터 일치 의심."),
                    }
                )
        except (TypeError, ValueError):
            pass

    # L7 — (e) PI coverage 너무 높음 — 구간이 비현실적으로 넓음 (PI 무의미)
    pi_cov = metrics.get("pi_coverage")
    if pi_cov is not None:
        try:
            pi_f = float(pi_cov)
            if pi_f >= LEAKAGE_PI_COV_TOO_HIGH:
                signals.append(
                    {
                        "kind": "pi_coverage_too_high",
                        "value": round(pi_f, 4),
                        "threshold": LEAKAGE_PI_COV_TOO_HIGH,
                        "hint": (
                            f"PI coverage 가 {pi_f:.3f} — 95% 구간이 거의 모든 점을 포함합니다. "
                            "구간이 너무 넓어 의사결정 가치가 낮음. 잔차 변동성 점검 권장."
                        ),
                    }
                )
        except (TypeError, ValueError):
            pass

    # 등급 1 #5 (2026-06-14) — 자각 신호 3 종 추가
    # (d) residual_autocorr_strong — 잔차에 강한 시계열성 남음 = 타깃 잘못 정함
    residual_diag = metrics.get("residual_diagnostics") or {}
    if isinstance(residual_diag, dict):
        lb_p = residual_diag.get("ljung_box_p")
        if lb_p is not None:
            try:
                lb_pf = float(lb_p)
                if lb_pf < 0.01:
                    signals.append(
                        {
                            "kind": "residual_autocorr_strong",
                            "ljung_box_p": round(lb_pf, 4),
                            "hint": (
                                f"잔차에 강한 자기상관 잔존 (Ljung-Box p={lb_pf:.4f} < 0.01). "
                                "타깃이 잘못 정의됐을 가능성 — 잔차 자체가 진짜 타깃일 수 있음. "
                                "차분·로그 변환 후 재학습 권장."
                            ),
                        }
                    )
            except (TypeError, ValueError):
                pass

    # (e) naive_beats_all — naïve 가 모델보다 우수 = 학습 가치 없음
    improvement = metrics.get("rmse_improvement_vs_naive")  # 등급 1 #5 — 로컬 추출
    if improvement is not None:
        try:
            imp_f2 = float(improvement)
            if imp_f2 <= -0.05:  # naïve 가 5%+ 우수
                signals.append(
                    {
                        "kind": "naive_beats_all",
                        "improvement": round(imp_f2, 4),
                        "hint": (
                            f"naïve 기준선이 모델보다 {abs(imp_f2):.1%} 우수합니다. "
                            "이 타깃은 시계열 학습 가치가 낮음 — 타깃 재정의 또는 분석 불가 보고 권장."
                        ),
                    }
                )
        except (TypeError, ValueError):
            pass

    # (f) mase_zero_suspect — MASE 가 정확히 0 = trivial 타깃
    mase = metrics.get("MASE")  # 등급 1 #5 — 로컬 추출
    if mase is not None:
        try:
            mase_f2 = float(mase)
            if mase_f2 == 0.0:
                signals.append(
                    {
                        "kind": "mase_zero_suspect",
                        "MASE": 0.0,
                        "hint": (
                            "MASE=0.0 — 타깃 변동이 0 이거나 완벽 누수. "
                            "타깃 컬럼이 상수에 가깝거나 피처에 타깃 포함 의심."
                        ),
                    }
                )
        except (TypeError, ValueError):
            pass

    # (c) 특정 fold 만 비정상 좋음 — fold 경계 누수
    if fold_scores and len(fold_scores) >= 3:
        m = _safe_mean(fold_scores)
        s = _safe_std(fold_scores)
        if m is not None and s is not None and s > 0:
            threshold = m + FOLD_OUTLIER_SIGMA * s
            max_score = max(fold_scores)
            if max_score > threshold:
                best_idx = int(max(range(len(fold_scores)), key=lambda i: fold_scores[i]))
                signals.append(
                    {
                        "kind": "single_fold_outlier_good",
                        "max_score": round(float(max_score), 6),
                        "mean": round(m, 6),
                        "std": round(s, 6),
                        "threshold": round(float(threshold), 6),
                        "best_fold_idx": best_idx,
                        "hint": (
                            f"fold {best_idx} 만 mean+2σ 초과로 좋습니다 ({max_score:.3f} > {threshold:.3f}). "
                            "그 fold 경계에서 누수 발생 의심 — walk-forward 분할 점검 권장."
                        ),
                    }
                )

    return signals


# ════════════════════════════════════════════════════════════════
# §H3. symptom_classification — 헌장 7단계 증상 A~E 자동 분류
# ════════════════════════════════════════════════════════════════
def _classify_symptom(
    metrics: dict,
    fold_diag: dict,
    leakage_signals: list[dict],
) -> dict[str, Any]:
    """헌장 7단계 증상 분류 — 우선순위 결정.

    증상:
      A 과적합           (학습 좋고 검증 나쁨 — 현재 우리는 train 메트릭 없어 미감지)
      B 과소적합/신호부족 (improvement≤0 + MASE 큼)
      C 누수 의심         (improvement 비현실적 좋음 또는 누수 signal)
      D fold 편차 큼      (fold cv unstable+)
      E naïve 못 이김     (improvement≤0 + fold 안정)
      normal              (정상 통과)

    rollback_priority: 헌장 7단계 비용 대비 우선순위 (5→3→4→2→0).
    """
    imp = metrics.get("rmse_improvement_vs_naive")
    mase = metrics.get("MASE")

    # 1순위 — 누수 의심 (증상 C)
    if leakage_signals:
        return {
            "symptom": "C",
            "label": "검증 성능 비현실적 좋음 (누수 의심)",
            "rollback_priority": ["3단계 horizon-aware lag", "1·3단계 보간·스케일러", "0단계 타겟 정의", "4단계 분할"],
            "reason": f"leakage_signals={[s['kind'] for s in leakage_signals]}",
        }

    # 2순위 — fold 편차 큼 (증상 D, fold_diag 있을 때만)
    if fold_diag.get("available") and fold_diag.get("stability") in ("unstable", "very_unstable"):
        return {
            "symptom": "D",
            "label": "fold 편차 큼 (특정 fold 만 나쁨 또는 전반 출렁임)",
            "rollback_priority": ["4단계 rolling 검증", "3단계 레짐/이벤트 피처", "4단계 fold 수 증가"],
            "reason": f"cv={fold_diag.get('cv')}, stability={fold_diag.get('stability')}",
        }

    # 3순위 — naïve 못 이김 (증상 E)
    try:
        imp_f = float(imp) if imp is not None else None
    except (TypeError, ValueError):
        imp_f = None
    try:
        mase_f = float(mase) if mase is not None else None
    except (TypeError, ValueError):
        mase_f = None

    if imp_f is not None and imp_f <= 0:
        if mase_f is not None and mase_f >= 1.0:
            return {
                "symptom": "E",
                "label": "naïve 기준선 못 이김",
                "rollback_priority": [
                    "3단계 차분/변화율 타겟",
                    "3단계 외생변수 강화",
                    "2단계 신호 존재 확인 (CCF)",
                    "0단계 타겟 재정의",
                ],
                "reason": f"improvement={imp_f}, MASE={mase_f} — 신호 부족 또는 랜덤워크",
            }
        # improvement≤0 + MASE 없거나 < 1.0 — 부분 신호 → 증상 B 로 분류
        return {
            "symptom": "B",
            "label": "학습/검증 둘 다 나쁨 (과소적합/신호 부족)",
            "rollback_priority": ["3단계 피처 추가 (lag/달력/푸리에)", "3단계 타겟 표현 (차분)", "2단계 EDA 재검"],
            "reason": f"improvement={imp_f}",
        }

    return {
        "symptom": "normal",
        "label": "정상 통과",
        "rollback_priority": [],
        "reason": "improvement>0 + (MASE 정상 or 미제공) + fold 안정",
    }


# ════════════════════════════════════════════════════════════════
# §A~§C. evaluate (진입점)
# ════════════════════════════════════════════════════════════════
def evaluate(state: Any) -> dict[str, Any]:
    """시계열 평가 — metrics 임계치 판정 + fold 진단 + 누수 사후 + 증상 분류.

    회귀 0: 기존 4 키 (passed / rationale / threshold_violations / metrics) 불변.
    신규 3 키 (fold_diagnostics / leakage_suspect_signals / symptom_classification) 추가.
    """
    # ── A-1 : best_model 존재 ──
    best = getattr(state, "best_model", None) or {}
    if not best or not isinstance(best, dict):
        return {
            "passed": False,
            "rationale": "no_best_model — cs-day6 모든 후보 실패",
            "threshold_violations": ["no_best_model"],
            "metrics": {},
            "fold_diagnostics": {"available": False, "reason": "no_best_model"},
            "leakage_suspect_signals": [],
            "symptom_classification": {
                "symptom": "no_model",
                "label": "모델 학습 실패 — 진단 불가",
                "rollback_priority": ["6단계 모델 후보 교체 (R2)", "4단계 검증 재설계"],
                "reason": "best_model None or 빈 dict",
            },
            "task_kind_hint": None,
        }

    # ── A-2 : metrics 추출 (빈 dict 여도 통과 — 임계치 판정 시 None 처리) ──
    metrics = best.get("metrics") or {}

    # ── B-1 : 메트릭 추출 ──
    violations: list[str] = []
    improvement = metrics.get("rmse_improvement_vs_naive")
    mase = metrics.get("MASE")
    smape = metrics.get("sMAPE")
    cov = metrics.get("pi_coverage")

    # ── B-2 : violations 누적 (X3 — 적응형 임계 적용) ──
    th = _adaptive_thresholds(state)
    if improvement is None:
        violations.append("rmse_improvement_vs_naive missing")
    elif improvement <= th["rmse_improvement_vs_naive_min"]:
        violations.append(f"rmse_improvement_vs_naive<={th['rmse_improvement_vs_naive_min']} (got {improvement:.3f})")

    if mase is not None and mase >= th["MASE_max"]:
        violations.append(f"MASE>={th['MASE_max']} (got {mase:.3f})")

    if smape is not None and smape > th["sMAPE_max"]:
        violations.append(f"sMAPE>{th['sMAPE_max']} (got {smape:.1f})")

        violations.append(f"pi_coverage<{th['pi_coverage_min']} (got {cov:.3f})")

    # ── B-3 (신규) : fold_scores + fold_metrics 추출 ──
    fold_scores = _extract_fold_scores(best)
    fold_metrics_list = _extract_fold_metrics(best)

    # ── B-4 (신규 H1) : fold 분산 진단 (scores + per-metric) ──
    fold_diag = _diagnose_fold_variance(fold_scores)
    fold_metric_diag = _diagnose_fold_metrics(fold_metrics_list)
    # L5 — fold_diag 에 per-metric 진단 병합 (호환 — fold_diag.available 의 의미는 fold_scores 기반 유지)
    if fold_metric_diag.get("available"):
        fold_diag["per_metric"] = fold_metric_diag.get("per_metric", {})

    # ── B-5 (신규 H2) : 누수 사후 진단 ──
    leakage_signals = _detect_leakage_signals(metrics, fold_scores)

    # ── B-6 (신규 H3) : 증상 분류 ──
    symptom = _classify_symptom(metrics, fold_diag, leakage_signals)

    # ── B-7 (L4) : task_kind 분류형 안내 — chosen_recipe.meta.task_kind 안전 추출 ──
    # 시계열의 이상 시점 recipe (proposer §F meta.task_kind="classification") 인 경우
    # 회귀 메트릭만으로는 모자라 결정 임계 (precision/recall + 비용) 보강 필요.
    # state.chosen_recipe.meta.task_kind 가 있을 때만 안내 메시지 (rollback 강제 X).
    chosen = getattr(state, "chosen_recipe", None) or {}
    task_kind_meta = None
    if isinstance(chosen, dict):
        meta = chosen.get("meta") if isinstance(chosen.get("meta"), dict) else {}
        task_kind_meta = meta.get("task_kind")
    classification_hint: Optional[str] = None
    if task_kind_meta == "classification":
        classification_hint = (
            "task_kind='classification' (이상 시점 recipe). 회귀 임계 외에 결정 임계 "
            "(precision/recall · 비즈니스 오탐/미탐 비용) 검토 필요. 헌장 5-1."
        )

    # ── B-7 (신규) : 누수 의심 시 violations 에도 명시 (passed=False 강제) ──
    # 헌장 1-6: 누수 신호가 있으면 임계치 통과여도 실패 처리 — "정직한 실패가 가짜 성공보다 낫다"
    if leakage_signals:
        violations.append(
            f"leakage_suspect ({len(leakage_signals)}건): " + ", ".join(s["kind"] for s in leakage_signals)
        )

    # ── B-8 (HJ 2026-06-13) : DM 검정 유의성 게이트 — model 이 naïve 를 통계적으로
    #   "못" 이기면(verdict=naive_wins) passed=False. 상대·유의성 표준(common.gates 의
    #   시계열판). dm_test unavailable / tie / model_wins 면 무영향(기존 동작 보존).
    dm = _dm_test(metrics)
    if dm.get("verdict") == "naive_wins":
        violations.append("DM 검정: naïve 대비 통계적 열세 (model_loses)")

    # ── C-1 : 최종 반환 ──
    # L6 — rationale 한국어 가독성 + 수치 인용 강화 (InsightAgent fallback 활용성 ↑)
    passed = len(violations) == 0
    rationale_parts: list[str] = []
    if passed:
        # 정상 통과 — 핵심 수치 인용 (한국어)
        imp_txt = f"{improvement:+.1%}" if improvement is not None else "N/A"
        mase_txt = f"{mase:.3f}" if mase is not None else "N/A"
        cov_txt = f"{cov:.3f}" if cov is not None else "N/A"
        rationale_parts.append(
            f"임계치 통과 — naïve 대비 개선 {imp_txt} (>0), MASE {mase_txt} (<1.0), PI 커버리지 {cov_txt} (≥0.90)"
        )
    else:
        # 위반 — 한국어 안내 + 수치 인용
        # violations 항목은 영문 코드 형태라 그대로 + 한국어 헤더
        rationale_parts.append(f"임계치 미달 ({len(violations)}건): " + "; ".join(violations))
    # 증상 분류 보강 (정상이 아닐 때만)
    if symptom.get("symptom") not in (None, "normal"):
        sympt_label = symptom.get("label") or symptom.get("symptom")
        rationale_parts.append(f"증상={sympt_label}")
        rb = symptom.get("rollback_priority") or []
        if rb:
            rationale_parts.append(f"롤백 우선순위: {' > '.join(rb[:3])}")
    if classification_hint:
        rationale_parts.append(classification_hint)
    rationale = " | ".join(rationale_parts)

    return {
        "passed": passed,
        "rationale": rationale,
        "threshold_violations": violations,
        "metrics": metrics,
        "fold_diagnostics": fold_diag,
        "leakage_suspect_signals": leakage_signals,
        "symptom_classification": symptom,
        "fit_quality": _diagnose_fit_quality(metrics),
        "residual_diagnostics": _diagnose_residuals(metrics),
        "dm_test": dm,
        "task_kind_hint": classification_hint,
    }

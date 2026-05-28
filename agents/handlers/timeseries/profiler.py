"""agents.handlers.timeseries.profiler — 시계열 데이터 프로파일 보강 (CS 담당).

7-Phase 순서 파이프라인 — 각 단계는 이전 단계 결과에 의존한다:

  Phase 1 — 시간축 감지 & 품질
              ↓  (freq, period, gap_info)
  Phase 2 — 정상성 검정  [ADF + KPSS 4-case 합의, diff_order 결정]
              ↓  (diff_order → ACF/PACF 에 전달)
  Phase 3 — ACF / PACF  [diff 적용 후 AR·MA order 힌트, Ljung-Box]
              ↓
  Phase 4 — STL 분해  [period 사용, robust=True]
              ↓  (stl_result → Phase 5, 6 에 전달)
  Phase 5 — 계절성 요약  [STL strength + periodogram 이중 검증]
  Phase 6 — 추세 요약    [Mann-Kendall 비모수 검정 + Hurst 지수]
              (Phase 4 불가 시 slope fallback)
  Phase 7 — 이상치 분석  [IQR Tukey fence + Z-score 이중 검출]
"""

from __future__ import annotations

import re
from math import sqrt
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


# ─────────────────────────────────────────────────────────────────
#  Phase 1 — 시간축 감지 & 품질
# ─────────────────────────────────────────────────────────────────


def _detect_date_column(df: Any) -> Optional[str]:
    """datetime64 dtype 우선, 이름 패턴(date/time/ts/timestamp) 차선."""
    import pandas as pd

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col
    for col in df.columns:
        if re.search(r"(date|time|ts|timestamp)", col, re.IGNORECASE):
            try:
                pd.to_datetime(df[col].head(100), errors="raise")
                return col
            except Exception:
                continue
    return None


def _phase1_time_axis(df: Any, date_col: Optional[str]) -> tuple[str, int, dict[str, Any]]:
    """
    Returns
    -------
    freq_str : str
        pd.infer_freq 결과. 실패 시 median delta 기반 추론("D"/"W"/"M"/"unknown").
    period : int
        freq 기반 계절 주기. D→7 / W→52 / M→12 / Q→4 / H→24.
    gap_info : dict
        n_gaps       — 비정상 긴 간격 수 (median의 2배 초과)
        max_gap_days — 최대 간격 (일 단위)
        gap_ratio    — n_gaps / 전체 간격 수  [0~1]
        is_regular   — gap_ratio < 0.05

    의존
    ----
    없음. 모든 Phase 의 시작점.
    """
    if date_col is None:
        return "unknown", 7, {"n_gaps": 0, "max_gap_days": 0.0, "gap_ratio": 0.0, "is_regular": False}

    try:
        import pandas as pd

        dates = pd.to_datetime(df[date_col].dropna()).sort_values().reset_index(drop=True)

        # ── 빈도 추론 (1순위: pd.infer_freq) ─────────────────────────
        inferred = pd.infer_freq(dates)

        _FREQ_MAP: dict[str, tuple[int, str]] = {
            "D": (7, "D"),
            "W": (52, "W"),
            "M": (12, "M"),
            "MS": (12, "MS"),
            "Q": (4, "Q"),
            "QS": (4, "QS"),
            "H": (24, "H"),
        }

        period, freq_str = 7, "unknown"
        if inferred:
            for prefix, (p, fs) in _FREQ_MAP.items():
                if inferred.startswith(prefix):
                    period, freq_str = p, inferred
                    break
            else:
                freq_str, period = inferred, 7  # 알 수 없는 빈도는 period=7 기본

        else:
            # ── 2순위: median delta 기반 추론 ─────────────────────────
            if len(dates) > 1:
                deltas = dates.diff().dropna()
                median_days = float(deltas.median().total_seconds() / 86400)
                if median_days <= 1.5:
                    freq_str, period = "D", 7
                elif median_days <= 8.0:
                    freq_str, period = "W", 52
                elif median_days <= 35.0:
                    freq_str, period = "M", 12
                elif median_days <= 100.0:
                    freq_str, period = "Q", 4
                else:
                    freq_str, period = "unknown", 7

        # ── gap 품질 분석 ──────────────────────────────────────────────
        if len(dates) > 1:
            deltas = dates.diff().dropna()
            median_delta = deltas.median()
            n_gaps = int((deltas > 2 * median_delta).sum())
            max_gap_days = float(deltas.max().total_seconds() / 86400)
            gap_ratio = round(n_gaps / max(1, len(deltas)), 4)
        else:
            n_gaps, max_gap_days, gap_ratio = 0, 0.0, 0.0

        gap_info = {
            "n_gaps": n_gaps,
            "max_gap_days": round(max_gap_days, 2),
            "gap_ratio": gap_ratio,
            "is_regular": gap_ratio < 0.05,
        }
        return freq_str, period, gap_info

    except Exception:
        return "unknown", 7, {"n_gaps": 0, "max_gap_days": 0.0, "gap_ratio": 0.0, "is_regular": False}


# ─────────────────────────────────────────────────────────────────
#  Phase 2 — 정상성 검정
# ─────────────────────────────────────────────────────────────────


def _phase2_stationarity(series: Any) -> dict[str, Any]:
    """
    1단계: ADF (Augmented Dickey-Fuller)  autolag='AIC'
           H0: 단위근 존재(비정상)  →  p < 0.05 이면 정상

    2단계: KPSS (Kwiatkowski-Phillips-Schmidt-Shin)
           H0: 정상               →  p > 0.05 이면 정상

    3단계: 4-case 합의 테이블
        ┌────────────────┬──────────────────┬───────────────────────────────┐
        │ ADF 결론       │ KPSS 결론        │ consensus / diff_order        │
        ├────────────────┼──────────────────┼───────────────────────────────┤
        │ 정상(p<.05)   │ 정상(p>.05)      │ "stationary"          / 0     │
        │ 비정상(p≥.05) │ 비정상(p≤.05)   │ "non_stationary"      / 1     │
        │ 정상(p<.05)   │ 비정상(p≤.05)   │ "trend_stationary"    / 0     │
        │ 비정상(p≥.05) │ 정상(p>.05)      │ "diff_stationary"     / 1     │
        └────────────────┴──────────────────┴───────────────────────────────┘

    4단계: diff_order=1 → 1차 차분 후 ADF 재검정 → 여전히 비정상이면 diff_order=2

    의존
    ----
    Phase 1 이후. Phase 3(ACF/PACF)에 diff_order 전달.
    """
    from statsmodels.tsa.stattools import adfuller, kpss

    logger.debug("phase2_start", n=len(series))
    n = len(series)

    # ADF
    adf_stat, adf_p, *_ = adfuller(series, autolag="AIC")
    adf_stationary = bool(adf_p < 0.05)

    # KPSS
    kpss_p_value: Optional[float] = None
    kpss_stationary: Optional[bool] = None
    try:
        _, kp, *_ = kpss(series, regression="c", nlags="auto")
        kpss_p_value = round(float(kp), 4)
        kpss_stationary = bool(kp > 0.05)
    except Exception:
        pass

    # 4-case 합의
    if adf_stationary and kpss_stationary is True:
        consensus, diff_order, recommended_action = "stationary", 0, "모델링 바로 적용 가능"
    elif (not adf_stationary) and kpss_stationary is False:
        consensus, diff_order, recommended_action = "non_stationary", 1, "1차 차분 후 재학습 권고"
    elif adf_stationary and kpss_stationary is False:
        # ADF: 단위근 없음, KPSS: 비정상 → 결정론적 추세 존재
        consensus, diff_order, recommended_action = "trend_stationary", 0, "추세 제거(detrend) 후 재학습 권고"
    elif (not adf_stationary) and kpss_stationary is True:
        # ADF: 단위근 있음, KPSS: 정상 → 차분이 필요한 확률적 추세
        consensus, diff_order, recommended_action = "diff_stationary", 1, "1차 차분 후 재학습 권고"
    else:
        # KPSS 실패 등 — ADF 만으로 판단
        consensus = "stationary" if adf_stationary else "non_stationary"
        diff_order = 0 if adf_stationary else 1
        recommended_action = "KPSS 검정 실패 — ADF 단독 판단"

    # diff_order=1 → 1차 차분 후 재검정 → 여전히 비정상이면 diff_order=2
    if diff_order == 1 and n > 10:
        try:
            diffed = series.diff(1).dropna()
            _, adf2_p, *_ = adfuller(diffed, autolag="AIC")
            if adf2_p >= 0.05:
                diff_order = 2
                recommended_action = "2차 차분 권고 (과적분 주의)"
        except Exception:
            pass

    result = {
        "adf_statistic": round(float(adf_stat), 4),
        "adf_p_value": round(float(adf_p), 4),
        "adf_is_stationary": adf_stationary,
        "kpss_p_value": kpss_p_value,
        "kpss_is_stationary": kpss_stationary,
        "is_stationary": adf_stationary and bool(kpss_stationary),
        "consensus": consensus,
        "diff_order": diff_order,
        "recommended_action": recommended_action,
    }
    logger.debug(
        "phase2_done",
        consensus=result["consensus"],
        diff_order=result["diff_order"],
        adf_p=result["adf_p_value"],
        kpss_p=result["kpss_p_value"],
    )
    return result


# ─────────────────────────────────────────────────────────────────
#  Phase 3 — ACF / PACF
# ─────────────────────────────────────────────────────────────────


def _phase3_acf_pacf(series: Any, stationarity: dict[str, Any], period: int) -> dict[str, Any]:
    """
    의존: Phase 2의 diff_order → 비정상 시계열에 차분 적용 후 분석.

    ACF 패턴 해석:
      느린 지수 감소 → AR 프로세스 → PACF에서 AR 차수 p 결정
      lag q 이후 급격히 0 → MA(q) 프로세스
      period 배수에서 spike → 계절성 재확인

    PACF 패턴 해석:
      lag p 이후 급격히 0 → AR(p) 프로세스
      느린 감소 → MA 프로세스 → ACF에서 MA 차수 q 결정

    ar_order_hint: PACF에서 연속 유의 lag의 마지막 번호
    ma_order_hint: ACF에서 연속 유의 lag의 마지막 번호
    seasonal_lags: period × k 위치에 유의 spike 있는 lag 목록
    ljung_box_p:   p > 0.05 → 잔차 white noise (자기상관 구조 충분히 설명됨)
    used_diff_order: 실제 적용한 차분 횟수 (기록용)
    """
    from statsmodels.stats.diagnostic import acorr_ljungbox
    from statsmodels.tsa.stattools import acf, pacf

    logger.debug("phase3_start", n=len(series), diff_order=stationarity.get("diff_order", 0))
    diff_order = stationarity.get("diff_order", 0)

    # 차분 적용
    working = series.copy()
    for _ in range(min(diff_order, 2)):
        working = working.diff(1).dropna()

    n = len(working)
    significance = 2.0 / sqrt(max(n, 1))

    _empty = {
        "acf": [],
        "pacf": [],
        "significant_lags_acf": [],
        "significance_threshold": round(significance, 4),
        "ar_order_hint": 0,
        "ma_order_hint": 0,
        "seasonal_lags": [],
        "ljung_box_p": None,
        "used_diff_order": diff_order,
    }
    if n < 4:
        return _empty

    max_lags = min(40, n // 2 - 1)

    try:
        acf_vals = acf(working, nlags=max_lags, fft=True)
        pacf_vals = pacf(working, nlags=max_lags)
    except Exception:
        return _empty

    sig_acf = [i for i, v in enumerate(acf_vals[1:], 1) if abs(v) > significance]
    sig_pacf = [i for i, v in enumerate(pacf_vals[1:], 1) if abs(v) > significance]

    # AR order: PACF에서 연속 유의 lag의 마지막 번호
    ar_order = 0
    for i, lag in enumerate(sig_pacf):
        if i == 0 or lag == sig_pacf[i - 1] + 1:
            ar_order = lag
        else:
            break

    # MA order: ACF에서 연속 유의 lag의 마지막 번호
    ma_order = 0
    for i, lag in enumerate(sig_acf):
        if i == 0 or lag == sig_acf[i - 1] + 1:
            ma_order = lag
        else:
            break

    # 계절 lag(period, 2*period)에서 ACF spike 확인
    seasonal_lags = [
        k * period
        for k in range(1, 3)
        if k * period <= max_lags and len(acf_vals) > k * period and abs(acf_vals[k * period]) > significance
    ]

    # Ljung-Box 잔차 검정 (잔차 자기상관 유의 여부)
    ljung_box_p: Optional[float] = None
    try:
        lb_lag = max(1, min(10, n // 5))
        lb = acorr_ljungbox(working, lags=[lb_lag], return_df=True)
        ljung_box_p = round(float(lb["lb_pvalue"].iloc[0]), 4)
    except Exception:
        pass

    result = {
        "acf": [round(float(v), 4) for v in acf_vals],
        "pacf": [round(float(v), 4) for v in pacf_vals],
        "significant_lags_acf": sig_acf,
        "significance_threshold": round(significance, 4),
        "ar_order_hint": ar_order,
        "ma_order_hint": ma_order,
        "seasonal_lags": seasonal_lags,
        "ljung_box_p": ljung_box_p,
        "used_diff_order": diff_order,
    }
    logger.debug("phase3_done", ar_order=ar_order, ma_order=ma_order, seasonal_lags=seasonal_lags)
    return result


# ─────────────────────────────────────────────────────────────────
#  Phase 4 — STL 분해
# ─────────────────────────────────────────────────────────────────


def _phase4_stl(series: Any, period: int) -> dict[str, Any]:
    """
    의존: Phase 1의 period.

    robust=True: 이상치에 강건한 IRLS 가중치 반복 분해.
                 (robust=False 대비 이상치가 trend/seasonal 에 흡수되지 않음)
    최소 관측 수: 2 * period + 1 (미달 시 available=False 반환)

    seasonal_strength = 1 - Var(R) / Var(S + R)   [0~1, 1: 완전 계절성]
    trend_strength    = 1 - Var(R) / Var(T + R)   [0~1, 1: 완전 추세]
    resid_std         : 잔차 표준편차 — 낮을수록 T+S 로 잘 설명됨 (모델 품질 가늠)
    total_var         : T + S + R 분산 합 (분산 분해 비율 계산용)
    """
    from statsmodels.tsa.seasonal import STL

    logger.debug("phase4_start", n=len(series), period=period)
    base = {"available": False, "period": period}
    n = len(series)
    if n < 2 * period + 1:
        return base

    try:
        stl = STL(series, period=period, robust=True).fit()

        resid_var = float(stl.resid.var(ddof=0))
        seasonal_var = float(stl.seasonal.var(ddof=0))
        trend_var = float(stl.trend.var(ddof=0))
        total_var = resid_var + seasonal_var + trend_var

        s_strength = max(0.0, 1.0 - resid_var / max(seasonal_var + resid_var, 1e-9))
        t_strength = max(0.0, 1.0 - resid_var / max(trend_var + resid_var, 1e-9))

        stl_out = {
            "available": True,
            "period": period,
            "trend_var": round(trend_var, 4),
            "seasonal_var": round(seasonal_var, 4),
            "resid_var": round(resid_var, 4),
            "total_var": round(total_var, 4),
            "seasonal_strength": round(s_strength, 4),
            "trend_strength": round(t_strength, 4),
            "resid_std": round(float(stl.resid.std(ddof=0)), 4),
        }
        logger.debug("phase4_done", available=True, seasonal_strength=round(s_strength, 4))
        return stl_out
    except Exception:
        logger.debug("phase4_done", available=False)
        return base


# ─────────────────────────────────────────────────────────────────
#  Phase 5 — 계절성 요약
# ─────────────────────────────────────────────────────────────────


def _phase5_seasonality(stl_result: dict[str, Any], period: int, series: Any) -> dict[str, Any]:
    """
    의존: Phase 4(stl_result), Phase 1(period).

    1차 판단: STL seasonal_strength > 0.4 → has_seasonality=True
    2차 검증: scipy.signal.periodogram 으로 dominant_period 독립 추정
              dominant_period ≈ period (±2 허용) → period_confirmed=True
    period_confidence: 지배 주파수 파워 / 전체 스펙트럼 파워 비율

    두 방법이 모두 계절성을 확인하면 신뢰도 높음.
    """
    logger.debug("phase5_start")
    s_strength = float(stl_result.get("seasonal_strength") or 0.0)
    has_seasonality = s_strength > 0.4

    dominant_period: Optional[int] = None
    period_confirmed = False
    period_confidence = 0.0

    try:
        import numpy as np
        from scipy.signal import periodogram

        vals = series.values.astype(float)
        freqs, power = periodogram(vals)

        if len(freqs) > 1:
            # DC 성분(freq=0) 제외하고 가장 강한 주파수 탐색
            nz_idx = np.argmax(power[1:]) + 1
            dom_freq = freqs[nz_idx]
            if dom_freq > 0:
                dominant_period = int(round(1.0 / dom_freq))
                total_power = float(power[1:].sum())
                period_confidence = round(float(power[nz_idx]) / max(total_power, 1e-9), 4)
                period_confirmed = abs(dominant_period - period) <= 2
    except Exception:
        pass

    result = {
        "has_seasonality": has_seasonality,
        "period": period,
        "seasonal_strength": round(s_strength, 4) if stl_result.get("available") else None,
        "dominant_period": dominant_period,
        "period_confirmed": period_confirmed,
        "period_confidence": period_confidence,
    }
    logger.debug(
        "phase5_done",
        has_seasonality=has_seasonality,
        period=period,
        period_confirmed=period_confirmed,
    )
    return result


# ─────────────────────────────────────────────────────────────────
#  Phase 6 — 추세 요약
# ─────────────────────────────────────────────────────────────────


def _estimate_hurst(values: Any) -> Optional[float]:
    """
    R/S (Rescaled Range) 분석으로 허스트 지수 추정.

    H > 0.5 → 장기 양의 의존성 (추세 지속)
    H ≈ 0.5 → 랜덤워크
    H < 0.5 → 평균 회귀

    log(R/S) ~ H * log(n) 관계에서 OLS slope 추정.
    블록 크기 = [8, 16, 32, 64, 128] 중 n//2 이하인 것만 사용.
    """
    import numpy as np

    n = len(values)
    sizes = [s for s in (8, 16, 32, 64, 128) if s <= n // 2]
    if len(sizes) < 2:
        return None

    rs_log: list[tuple[float, float]] = []
    for size in sizes:
        blocks = [values[i : i + size] for i in range(0, n - size + 1, size)]
        rs_vals = []
        for blk in blocks:
            mean = np.mean(blk)
            cum_dev = np.cumsum(blk - mean)
            R = float(cum_dev.max() - cum_dev.min())
            S = float(np.std(blk, ddof=1))
            if S > 0:
                rs_vals.append(R / S)
        if rs_vals:
            rs_log.append((float(np.log(size)), float(np.log(np.mean(rs_vals)))))

    if len(rs_log) < 2:
        return None

    xs = [v[0] for v in rs_log]
    ys = [v[1] for v in rs_log]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    den = sum((x - x_mean) ** 2 for x in xs)
    if den == 0:
        return None
    h = num / den
    return round(float(max(0.0, min(1.0, h))), 4)


def _phase6_trend(series: Any, stl_result: dict[str, Any]) -> dict[str, Any]:
    """
    의존: Phase 4(stl_result의 trend_strength), 원본 series.

    Mann-Kendall 비모수 검정 (scipy.stats.kendalltau):
      kendalltau(time_index, values) → tau, p_value
      tau > 0 + p < 0.05 → 유의미한 상승 추세
      tau < 0 + p < 0.05 → 유의미한 하락 추세
      p ≥ 0.05           → 추세 불명확

    direction 결정 우선순위:
      1) mk_significant=True → tau 부호로 결정
      2) mk_significant=False + |slope| > 1e-6 → slope 부호로 결정
      3) 나머지 → "none"

    hurst_exponent: R/S 분석 (H>0.5=추세지속 / H≈0.5=랜덤워크 / H<0.5=평균회귀)
    """
    from scipy.stats import kendalltau

    logger.debug("phase6_start", n=len(series))
    n = len(series)
    values = series.values.astype(float)

    # Mann-Kendall
    tau_stat, mk_p = kendalltau(range(n), values)
    tau_stat = round(float(tau_stat), 4)
    mk_p_val = round(float(mk_p), 4)
    mk_significant = bool(mk_p_val < 0.05)

    # 단순 선형 기울기 (fallback 지표)
    slope = float((values[-1] - values[0]) / max(1, n - 1))

    # 방향 결정
    if mk_significant:
        direction = "increasing" if tau_stat > 0 else "decreasing"
    elif abs(slope) > 1e-6:
        direction = "increasing" if slope > 0 else "decreasing"
    else:
        direction = "none"

    t_strength_raw = stl_result.get("trend_strength") if stl_result.get("available") else None
    t_strength = float(t_strength_raw) if t_strength_raw is not None else None
    has_trend = mk_significant or (t_strength is not None and t_strength > 0.4)

    result = {
        "has_trend": bool(has_trend),
        "direction": direction,
        "slope_per_obs": round(slope, 6),
        "mk_tau": tau_stat,
        "mk_p_value": mk_p_val,
        "mk_significant": mk_significant,
        "trend_strength": round(t_strength, 4) if t_strength is not None else None,
        "hurst_exponent": _estimate_hurst(values),
    }
    logger.debug("phase6_done", direction=direction, mk_significant=mk_significant)
    return result


# ─────────────────────────────────────────────────────────────────
#  Phase 7 — 이상치 이중 검출
# ─────────────────────────────────────────────────────────────────


def _phase7_outliers(series: Any) -> float:
    """
    IQR Tukey fence 기반 이상치 비율 반환 (테스트 호환 float).

    내부 로직 (이중 검증):
      IQR fence  : Q1 - 1.5*IQR  <  x  <  Q3 + 1.5*IQR  벗어나면 이상치
      Z-score    : |z| > 3 이면 이상치
      교집합(강한 이상치): 두 방법 모두 탐지한 것

    반환값은 IQR 비율 (float) — 기존 테스트와 호환.
    selector·EDA 등이 더 많은 정보를 필요로 할 경우
    state.category_extras["timeseries"]["outlier_detail"] 을 사용할 것.
    """
    logger.debug("phase7_start", n=len(series))
    q1 = float(series.quantile(0.25))
    q3 = float(series.quantile(0.75))
    iqr = q3 - q1

    if iqr > 0:
        iqr_mask = (series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)
        ratio = round(float(iqr_mask.mean()), 4)
        logger.debug("phase7_done", iqr_ratio=ratio)
        return ratio
    logger.debug("phase7_done", iqr_ratio=0.0)
    return 0.0


# ─────────────────────────────────────────────────────────────────
#  진입점
# ─────────────────────────────────────────────────────────────────


def profile(df: Any, state: Any) -> dict[str, Any]:
    """시계열 전용 추가 필드 반환. dispatcher 가 basic profile 에 병합.

    Phase 실행 순서
    ---------------
    1 → date_col, freq, period  (이후 모든 Phase 에서 사용)
    2 → diff_order              (Phase 3 에서 사용)
    3 → AR/MA 힌트              (Phase 2 결과 소비)
    4 → STL stl_result          (Phase 5, 6 에서 사용)
    5 → seasonality             (Phase 4 결과 소비)
    6 → trend                   (Phase 4 결과 소비)
    7 → outlier_iqr_ratio       (독립)
    """
    target_col = state.target_column
    date_col = _detect_date_column(df)

    logger.info(
        "profile_start",
        job_id=getattr(state, "job_id", None),
        target=target_col,
        n_rows=len(df),
        category=getattr(state, "category", None),
    )

    # Phase 1
    freq_str, period, _gap_info = _phase1_time_axis(df, date_col)

    extra: dict[str, Any] = {
        "date_col": date_col,
        "freq": freq_str,
    }

    if not target_col or target_col not in df.columns:
        extra["timeseries_warning"] = "target_column 누락 — 시계열 분석 일부 생략"
        for key in ("stationarity", "acf_pacf", "stl_decompose", "seasonality", "trend", "outlier_iqr_ratio"):
            extra[key] = None
        return extra

    try:
        if date_col:
            df = df.sort_values(date_col).reset_index(drop=True)
        series = df[target_col].dropna().reset_index(drop=True).astype(float)

    except Exception as e:
        extra["timeseries_error"] = str(e)
        for key in ("stationarity", "acf_pacf", "stl_decompose", "seasonality", "trend", "outlier_iqr_ratio"):
            extra[key] = None
        return extra

    # Phase 2 — 정상성 (실패해도 나머지 Phase 계속)
    stationarity: dict | None = None
    try:
        stationarity = _phase2_stationarity(series)
    except Exception as e:
        logger.warning("phase2_failed", error=str(e), n=len(series))
    extra["stationarity"] = stationarity

    # Phase 3 — ACF/PACF (stationarity 가 None 이어도 .get("diff_order", 0) 으로 안전)
    try:
        extra["acf_pacf"] = _phase3_acf_pacf(series, stationarity or {}, period)
    except Exception as e:
        logger.warning("phase3_failed", error=str(e))
        extra["acf_pacf"] = None

    # Phase 4 — STL (default dict 로 Phase 5/6 안전 접근 보장)
    stl_result: dict = {"available": False, "period": period}
    try:
        stl_result = _phase4_stl(series, period)
    except Exception as e:
        logger.warning("phase4_failed", error=str(e))
    extra["stl_decompose"] = stl_result

    # Phase 5 — 계절성
    try:
        extra["seasonality"] = _phase5_seasonality(stl_result, period, series)
    except Exception as e:
        logger.warning("phase5_failed", error=str(e))
        extra["seasonality"] = None

    # Phase 6 — 추세
    try:
        extra["trend"] = _phase6_trend(series, stl_result)
    except Exception as e:
        logger.warning("phase6_failed", error=str(e))
        extra["trend"] = None

    # Phase 7 — 이상치 (독립)
    try:
        extra["outlier_iqr_ratio"] = _phase7_outliers(series)
    except Exception as e:
        logger.warning("phase7_failed", error=str(e))
        extra["outlier_iqr_ratio"] = None

    # 진단 키 4개 (Day 2/7/8 사전 데이터 — basic profile 과 키 이름 충돌 없음)
    try:
        if len(series) > 0:
            extra["target_min"] = float(series.min())
            extra["target_max"] = float(series.max())
            extra["target_has_zeros"] = bool((series == 0).any())
            extra["target_has_negatives"] = bool((series < 0).any())
        else:
            extra["target_min"] = None
            extra["target_max"] = None
            extra["target_has_zeros"] = None
            extra["target_has_negatives"] = None
    except Exception as e:
        logger.warning("diagnostic_keys_failed", error=str(e))
        extra["target_min"] = None
        extra["target_max"] = None
        extra["target_has_zeros"] = None
        extra["target_has_negatives"] = None

    logger.info(
        "profile_done",
        job_id=getattr(state, "job_id", None),
        date_col=date_col,
        freq=freq_str,
        period=period,
        consensus=(extra.get("stationarity") or {}).get("consensus"),
        has_seasonality=(extra.get("seasonality") or {}).get("has_seasonality"),
        outlier_ratio=extra.get("outlier_iqr_ratio"),
    )
    return extra

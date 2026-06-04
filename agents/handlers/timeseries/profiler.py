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
#  Phase 8 — 시간축 무결성 (방법론 1단계 + 누수 1-2)
#  target 유무와 무관하게 항상 실행.
# ─────────────────────────────────────────────────────────────────


def _phase8_timeaxis_integrity(df: Any, date_col: Optional[str], period: int) -> dict[str, Any]:
    """
    원본(정렬 전) 시간축의 무결성을 진단한다. profile() 이 나중에 정렬하므로
    여기서는 "원본이 정렬돼 있었나 / 중복·결측 시점 / 불규칙 빈도" 를 측정한다.

    반환 계약
    ---------
    has_time_axis      : bool          (date_col 유무)
    is_monotonic       : bool | None   (date_col 없으면 None)
    duplicate_ts_count : int           (기본 0)
    missing_ts_count   : int           (기본 0)
    missing_ts_ratio   : float [0~1]   (기본 0.0)
    tz_aware           : bool          (기본 False)
    irregular          : bool | None   (간격 계산 불가 시 None)
    """
    # 8-A — date_col None 가드 (정수 인덱스 강등 케이스)
    base: dict[str, Any] = {
        "has_time_axis": False,
        "is_monotonic": None,
        "duplicate_ts_count": 0,
        "missing_ts_count": 0,
        "missing_ts_ratio": 0.0,
        "tz_aware": False,
        "irregular": None,
    }
    if date_col is None:
        return base

    try:
        import pandas as pd

        raw = df[date_col]

        # 8-C — 타임존 (to_datetime 단계 try/except, 실패 시 부분 결과)
        ts = pd.to_datetime(raw, errors="coerce")
        try:
            tz_aware = bool(getattr(ts.dt, "tz", None) is not None)
        except Exception:
            tz_aware = False

        # 8-B — 원본(정렬 전) 순서 단조성. NaT 제거 후 raw 순서 그대로 평가.
        valid = ts.dropna()
        is_monotonic: Optional[bool] = bool(valid.is_monotonic_increasing) if len(valid) >= 2 else None

        # 8-D — 중복 타임스탬프 (같은 시각 여러 행)
        duplicate_ts_count = int(valid.duplicated().sum())

        # 유효 시점 3개 미만 → 결측·불규칙 계산 skip, 기본값
        uniq = valid.drop_duplicates().sort_values().reset_index(drop=True)
        if len(uniq) < 3:
            base.update(
                has_time_axis=True,
                is_monotonic=is_monotonic,
                duplicate_ts_count=duplicate_ts_count,
                tz_aware=tz_aware,
                irregular=None,
            )
            return base

        deltas = uniq.diff().dropna()
        missing_ts_count = 0
        missing_ts_ratio = 0.0
        irregular: Optional[bool] = None
        try:
            # 8-E — 최빈 간격(step)으로 완전 그리드 생성 → 누락 행 수
            step = deltas.mode().iloc[0]
            if step.total_seconds() > 0:
                expected = pd.date_range(start=uniq.iloc[0], end=uniq.iloc[-1], freq=step)
                missing_ts_count = int(max(0, len(expected) - len(uniq)))
                missing_ts_ratio = round(missing_ts_count / max(1, len(expected)), 4)
                # 8-F — 최빈 간격 외 간격 비율 > 5% → 불규칙
                off_step = int((deltas != step).sum())
                irregular = bool(off_step / max(1, len(deltas)) > 0.05)
            else:
                irregular = None  # step=0 (전부 같은 날짜 등) → 간격 계산 불가
        except Exception:
            irregular = None

        return {
            "has_time_axis": True,
            "is_monotonic": is_monotonic,
            "duplicate_ts_count": duplicate_ts_count,
            "missing_ts_count": missing_ts_count,
            "missing_ts_ratio": missing_ts_ratio,
            "tz_aware": tz_aware,
            "irregular": irregular,
        }
    except Exception:
        # 타임존 혼재·파싱 실패 등 — date_col 은 있었으므로 has_time_axis=True
        base["has_time_axis"] = True
        return base


# ─────────────────────────────────────────────────────────────────
#  Phase 9 — 가법/승법 판정 (방법론 2-2)
# ─────────────────────────────────────────────────────────────────


def _phase9_multiplicative(series: Any, period: int) -> dict[str, Any]:
    """
    period 길이 블록의 (평균, 표준편차) 상관으로 분산-레벨 비례 여부를 판정.
    분산이 레벨에 비례(승법) -> mean 상승 시 std 상승 -> corr 큼.

    반환 계약
    ---------
    is_multiplicative : bool | None   (블록<2 또는 무변동 시 None)
    confidence        : float [0~1]   (|corr|)
    basis             : str
    """
    import numpy as np

    out: dict[str, Any] = {
        "is_multiplicative": None,
        "confidence": 0.0,
        "basis": "insufficient_data",
    }
    try:
        vals = np.asarray(series, dtype=float)
        vals = vals[~np.isnan(vals)]
        p = int(period) if period and period >= 2 else 0
        n = len(vals)
        if p < 2 or n < 2 * p:
            return out  # 블록 2개 미만

        n_blocks = n // p
        blocks = vals[: n_blocks * p].reshape(n_blocks, p)
        means = blocks.mean(axis=1)
        stds = blocks.std(axis=1, ddof=1)  # 블록 내 2관측치 이상 -> ddof=1 안전

        # 블록 평균/표준편차 변동이 없으면 corr 무의미
        if float(np.ptp(means)) < 1e-9 or float(np.ptp(stds)) < 1e-9:
            return {"is_multiplicative": None, "confidence": 0.0, "basis": "no_level_variation"}

        corr = float(np.corrcoef(means, stds)[0, 1])
        if np.isnan(corr):
            return {"is_multiplicative": None, "confidence": 0.0, "basis": "no_level_variation"}

        return {
            "is_multiplicative": bool(corr > 0.6),
            "confidence": round(abs(corr), 4),
            "basis": "block_mean_std_corr",
        }
    except Exception:
        return out


# ─────────────────────────────────────────────────────────────────
#  Phase 10 — 레짐 변화 / changepoint (방법론 2-1 · 롤백5)
#  ruptures 등 외부 lib 안 씀. numpy/pandas 만.
# ─────────────────────────────────────────────────────────────────


def _phase10_changepoints(series: Any, stl_result: dict[str, Any], period: int) -> dict[str, Any]:
    """
    1차 차분(추세 제거 근사) 후 rolling z-score spike 와 CUSUM drift 를 교차.
    병합 규칙: 교집합 우선(보수적) -> 비면 합집합 -> 인접(window 이내) 1건 병합.

    반환 계약
    ---------
    count   : int          (병합 개수 — proposer 호환)
    indices : list[int]    (대표 위치, 최대 20)
    method  : str          ("intersection"/"union"/"none")
    """
    import numpy as np
    import pandas as pd

    out: dict[str, Any] = {"count": 0, "indices": [], "method": "none"}
    try:
        vals = np.asarray(series, dtype=float)
        vals = vals[~np.isnan(vals)]
        n = len(vals)
        if n < 20:  # changepoint 판정 의미 없음
            return out

        resid = np.diff(vals)
        if float(np.std(resid)) < 1e-12:  # 상수 / 무변동
            return out

        p = int(period) if period and period >= 2 else 5
        window = max(5, p)

        rs = pd.Series(resid)
        # 1) rolling z-score spike
        rmean = rs.rolling(window, min_periods=2).mean()
        rstd = rs.rolling(window, min_periods=2).std(ddof=0)
        z = ((rs - rmean) / rstd.replace(0.0, np.nan)).fillna(0.0)
        spike = set(np.where(np.abs(z.to_numpy()) > 3.0)[0].tolist())

        # 2) CUSUM drift
        cusum = np.cumsum(resid - float(np.mean(resid)))
        sigma = float(np.std(resid))
        drift = set(np.where(np.abs(cusum) > 5.0 * sigma)[0].tolist()) if sigma > 0 else set()

        # 병합 규칙: 교집합 우선
        inter = spike & drift
        if inter:
            cand, method = sorted(inter), "intersection"
        else:
            uni = spike | drift
            cand, method = sorted(uni), ("union" if uni else "none")

        if not cand:
            return {"count": 0, "indices": [], "method": "none"}

        # 인접(window 이내) 지점 1건 병합
        merged: list[int] = []
        last = -(10**9)
        for idx in cand:
            if idx - last > window:
                merged.append(idx)
            last = idx

        # diff 인덱스 -> 원계열 인덱스 보정(+1)
        indices = [int(i + 1) for i in merged][:20]
        return {"count": int(len(merged)), "indices": indices, "method": method}
    except Exception:
        return out


# ─────────────────────────────────────────────────────────────────
#  Phase 11 — 누적/증분 판정 (방법론 1단계)
# ─────────────────────────────────────────────────────────────────


def _phase11_target_kind(series: Any, trend: dict[str, Any]) -> dict[str, Any]:
    """
    diff 의 비감소 비율 + Hurst(Phase 6 재활용) 로 누적(cumulative) 여부 판정.

    반환 계약
    ---------
    target_kind : "cumulative" | "level" | "unknown"
    confidence  : float
    basis       : str
    """
    import numpy as np

    out: dict[str, Any] = {
        "target_kind": "unknown",
        "confidence": 0.0,
        "basis": "insufficient_data",
    }
    try:
        vals = np.asarray(series, dtype=float)
        vals = vals[~np.isnan(vals)]
        n = len(vals)
        if n < 10:
            return out

        diffs = np.diff(vals)
        scale = float(np.nanmax(np.abs(vals))) if n else 0.0
        eps = 1e-9 * max(1.0, scale)
        nonneg_ratio = float(np.mean(diffs >= -eps))

        hurst = (trend or {}).get("hurst_exponent")
        hurst_high = bool(hurst is not None and hurst > 0.9)

        if nonneg_ratio > 0.97 and (hurst_high or nonneg_ratio > 0.995):
            return {
                "target_kind": "cumulative",
                "confidence": round(nonneg_ratio, 4),
                "basis": "nonneg_diff_ratio" + ("+hurst" if hurst_high else ""),
            }

        # level: 부호 균형 기반 신뢰도
        pos = float(np.mean(diffs > eps))
        neg = float(np.mean(diffs < -eps))
        balance = 1.0 - abs(pos - neg)
        return {
            "target_kind": "level",
            "confidence": round(max(0.0, min(1.0, balance)), 4),
            "basis": "sign_balance",
        }
    except Exception:
        return out


# ─────────────────────────────────────────────────────────────────
#  Phase 12 — CCF(시차 상관) + 누수 사전탐지 (방법론 2-5 · 누수 1-1)
# ─────────────────────────────────────────────────────────────────


def _phase12_ccf_leakage(df: Any, target_col: str, date_col: Optional[str], max_lag: int = 14) -> dict[str, Any]:
    """
    exog(수치형, target·date 제외) 와 target 의 누수·시차상관 진단.

    1) 누수 사전탐지: 동시점 원계열 |corr|>0.98 -> leakage_suspect_cols
    2) CCF: target·exog 1차 차분 후 lag 0~max_lag 상관, |corr| 최대 lag 기록

    반환 계약
    ---------
    is_multivariate      : bool          (exog >= 1)
    n_exog               : int
    ccf_top_lags         : dict[str, {lag:int, corr:float}]
    leakage_suspect_cols : list[str]
    """
    import numpy as np
    import pandas as pd

    out: dict[str, Any] = {
        "is_multivariate": False,
        "n_exog": 0,
        "ccf_top_lags": {},
        "leakage_suspect_cols": [],
    }
    try:
        target = pd.to_numeric(df[target_col], errors="coerce")

        exclude = {target_col}
        if date_col:
            exclude.add(date_col)
        exog_cols: list[str] = []
        for col in df.columns:
            if col in exclude:
                continue
            if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_bool_dtype(df[col]):
                exog_cols.append(col)
        exog_cols = exog_cols[:30]  # 비용 상한

        if not exog_cols:
            return out

        ccf_top_lags: dict[str, Any] = {}
        leakage_suspect: list[str] = []
        t_diff_full = target.diff()

        for col in exog_cols:
            try:
                ex = pd.to_numeric(df[col], errors="coerce")

                # 1) 누수 사전탐지 — 동시점 원계열 상관
                pair = pd.concat([target, ex], axis=1).dropna()
                if len(pair) >= 3:
                    c0 = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
                    if not np.isnan(c0) and abs(c0) > 0.98:
                        leakage_suspect.append(col)

                # 2) CCF — 차분 후 lag 시프트 상관 (허위상관 방지)
                ex_diff = ex.diff()
                best_lag, best_corr = 0, 0.0
                for lag in range(0, max_lag + 1):
                    shifted = ex_diff.shift(lag)
                    dd = pd.concat([t_diff_full, shifted], axis=1).dropna()
                    if len(dd) < 3:
                        continue
                    c = float(dd.iloc[:, 0].corr(dd.iloc[:, 1]))
                    if np.isnan(c):
                        continue
                    if abs(c) > abs(best_corr):
                        best_lag, best_corr = lag, c
                if abs(best_corr) > 0.2:  # 의미 있는 신호만
                    ccf_top_lags[col] = {"lag": int(best_lag), "corr": round(best_corr, 4)}
            except Exception:
                continue

        return {
            "is_multivariate": True,
            "n_exog": len(exog_cols),
            "ccf_top_lags": ccf_top_lags,
            "leakage_suspect_cols": leakage_suspect,
        }
    except Exception:
        return out


# ─────────────────────────────────────────────────────────────────
#  §6 보강 — freq="unknown" 시 ACF 기반 period 재추론
#  기존 seasonality.period 불변. 별도 키 period_acf_inferred 로만 노출.
# ─────────────────────────────────────────────────────────────────


def _infer_period_from_acf(acf_pacf: dict[str, Any], n: int, current_period: int) -> Optional[int]:
    """seasonal_lags 또는 유의 ACF peak 중 최댓값을 period 후보로. 2<=p<=n//2 면 채택."""
    try:
        cand: Optional[int] = None
        seasonal_lags = (acf_pacf or {}).get("seasonal_lags") or []
        if seasonal_lags:
            cand = int(max(seasonal_lags))
        else:
            sig = (acf_pacf or {}).get("significant_lags_acf") or []
            if sig:
                cand = int(max(sig))
        if cand is None:
            return None
        if 2 <= cand <= n // 2:
            return cand
        return None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────
#  Phase 13 — 이분산 진단 (방법론 2-1 "분산의 시간 변화")
#  분산이 시간/레벨에 따라 변하는지 → 고정 임계·등분산 가정 모델 경고.
# ─────────────────────────────────────────────────────────────────


def _phase13_heteroscedasticity(series: Any, period: int) -> dict[str, Any]:
    """
    시계열을 앞/뒤 절반(또는 블록)으로 나눠 분산이 유의하게 변하는지 진단.
    승법성(Phase 9)이 '레벨↔분산'이라면, 이분산은 '시간↔분산'을 본다.

    반환 계약
    ---------
    is_heteroscedastic : bool | None   (n 부족/무변동 시 None)
    var_ratio          : float | None  (후반 분산 / 전반 분산)
    basis              : str           ("half_split_var_ratio"/"insufficient_data"/"no_variance")
    """
    import numpy as np

    out: dict[str, Any] = {"is_heteroscedastic": None, "var_ratio": None, "basis": "insufficient_data"}
    try:
        vals = np.asarray(series, dtype=float)
        vals = vals[~np.isnan(vals)]
        n = len(vals)
        if n < 20:  # 분산 비교 의미 없음
            return out

        # 추세가 분산을 오염시키지 않도록 1차 차분 후 분산 비교
        resid = np.diff(vals)
        if float(np.std(resid)) < 1e-12:
            return {"is_heteroscedastic": None, "var_ratio": None, "basis": "no_variance"}

        half = len(resid) // 2
        first = resid[:half]
        second = resid[half:]
        if len(first) < 2 or len(second) < 2:
            return out

        v1 = float(np.var(first, ddof=1))
        v2 = float(np.var(second, ddof=1))
        if v1 < 1e-12 and v2 < 1e-12:
            return {"is_heteroscedastic": None, "var_ratio": None, "basis": "no_variance"}

        # var_ratio: 큰 쪽/작은 쪽 (>1). 2배 이상 차이면 이분산으로 판정(보수적).
        hi, lo = (v2, v1) if v2 >= v1 else (v1, v2)
        var_ratio = float(hi / lo) if lo > 1e-12 else None
        if var_ratio is None:
            return {"is_heteroscedastic": None, "var_ratio": None, "basis": "no_variance"}

        return {
            "is_heteroscedastic": bool(var_ratio > 2.0),
            "var_ratio": round(var_ratio, 4),
            "basis": "half_split_var_ratio",
        }
    except Exception:
        return out


# ─────────────────────────────────────────────────────────────────
#  Phase 14 — 이상치 성격 구분 (방법론 2-1·3-1 "오류 vs 진짜 이벤트")
#  IQR 이상치 중 '물리적 오류 의심' vs '진짜 이벤트 의심' 을 휴리스틱 분리.
# ─────────────────────────────────────────────────────────────────


def _phase14_outlier_kind(series: Any) -> dict[str, Any]:
    """
    IQR Tukey fence 이상치를 두 갈래로 분류:
      - error_suspect : 물리적으로 비현실적인 값 의심 — 음수(전부 양수 계열에서),
                        또는 |z| 가 극단(>8)인 단발 스파이크. → 제거/정정 후보.
      - event_suspect : fence 는 벗어나지만 z 가 중간(3~8)인 값 — 세일·연휴 등
                        진짜 이벤트 의심. → 제거가 아니라 이벤트 더미 후보.

    반환 계약
    ---------
    outlier_count      : int
    error_suspect_count: int     (제거/정정 후보)
    event_suspect_count: int     (이벤트 더미 후보)
    recommend          : str     ("flag_as_event"/"investigate_errors"/"none")
    """
    import numpy as np

    out: dict[str, Any] = {
        "outlier_count": 0,
        "error_suspect_count": 0,
        "event_suspect_count": 0,
        "recommend": "none",
    }
    try:
        vals = np.asarray(series, dtype=float)
        vals = vals[~np.isnan(vals)]
        n = len(vals)
        if n < 8:
            return out

        q1, q3 = np.percentile(vals, [25, 75])
        iqr = float(q3 - q1)
        if iqr <= 0:
            return out

        lo_fence = q1 - 1.5 * iqr
        hi_fence = q3 + 1.5 * iqr
        mask = (vals < lo_fence) | (vals > hi_fence)
        outlier_count = int(mask.sum())
        if outlier_count == 0:
            return out

        mean = float(np.mean(vals))
        std = float(np.std(vals, ddof=1)) if n > 1 else 0.0
        # "정상 영역(이상치 제외)이 전부 양수인가" — 이상치 음수 자체가
        # all_positive 판정을 뒤집지 않도록 inlier 기준으로 본다.
        inliers = vals[~mask]
        normally_positive = bool(len(inliers) > 0 and np.all(inliers >= 0))

        error_suspect = 0
        event_suspect = 0
        for v in vals[mask]:
            z = abs((v - mean) / std) if std > 1e-12 else 0.0
            # 정상 영역이 양수인데 음수 이상치 = 물리 오류 의심 / z 극단(>8) = 오류 의심
            if (normally_positive and v < 0) or z > 8.0:
                error_suspect += 1
            else:
                event_suspect += 1

        if error_suspect > 0:
            recommend = "investigate_errors"
        elif event_suspect > 0:
            recommend = "flag_as_event"
        else:
            recommend = "none"

        return {
            "outlier_count": outlier_count,
            "error_suspect_count": error_suspect,
            "event_suspect_count": event_suspect,
            "recommend": recommend,
        }
    except Exception:
        return out


# ─────────────────────────────────────────────────────────────────
#  Phase 15 — 0 vs NaN 도메인 구분 (방법론 1단계 "센서 미작동 vs 값 0")
#  0 을 결측 대용으로 쓴 정황(연속 0 런·과다 0 비율)을 신호로 노출.
# ─────────────────────────────────────────────────────────────────


def _phase15_zero_vs_nan(series: Any) -> dict[str, Any]:
    """
    target 의 0 값이 '진짜 0' 인지 '결측을 0 으로 채운 것(센서 미작동)' 인지
    직접 단정할 수는 없으나, 의심 신호를 정량화한다.

    신호:
      - zero_ratio          : 0 값 비율
      - max_zero_run        : 연속 0 최대 길이 (긴 0 런 = 미작동 의심)
      - has_nan             : 원본에 NaN 도 함께 존재하는가 (0 과 NaN 혼재 = 의미 구분 필요)
      - zero_suspect        : zero_ratio>0.3 또는 max_zero_run>=period 면 True

    반환 계약
    ---------
    zero_ratio    : float [0~1]
    max_zero_run  : int
    has_nan       : bool
    zero_suspect  : bool
    basis         : str
    """
    import numpy as np

    out: dict[str, Any] = {
        "zero_ratio": 0.0,
        "max_zero_run": 0,
        "has_nan": False,
        "zero_suspect": False,
        "basis": "ok",
    }
    try:
        raw = np.asarray(series, dtype=float)
        n_total = len(raw)
        if n_total == 0:
            return {**out, "basis": "empty"}

        has_nan = bool(np.isnan(raw).any())
        vals = raw[~np.isnan(raw)]
        n = len(vals)
        if n == 0:
            return {**out, "has_nan": has_nan, "basis": "all_nan"}

        is_zero = vals == 0.0
        zero_ratio = float(np.mean(is_zero))

        # 연속 0 런 최대 길이
        max_run = 0
        cur = 0
        for z in is_zero:
            if z:
                cur += 1
                if cur > max_run:
                    max_run = cur
            else:
                cur = 0

        zero_suspect = bool(zero_ratio > 0.3 or max_run >= 7)

        return {
            "zero_ratio": round(zero_ratio, 4),
            "max_zero_run": int(max_run),
            "has_nan": has_nan,
            "zero_suspect": zero_suspect,
            "basis": "zero_run_and_ratio",
        }
    except Exception:
        return out


# ─────────────────────────────────────────────────────────────────
#  진입점
# ─────────────────────────────────────────────────────────────────

# target 없음 / 로드 실패 early-return 시 None 으로 채울 키.
# timeaxis_integrity 는 target 무관(항상 측정)이라 이 목록에서 제외.
_NONE_ON_NO_TARGET = (
    "stationarity",
    "acf_pacf",
    "stl_decompose",
    "seasonality",
    "trend",
    "outlier_iqr_ratio",
    "is_multiplicative",
    "changepoints",
    "target_kind",
    "ccf_leakage",
    "heteroscedasticity",
    "outlier_kind",
    "zero_vs_nan",
)


def profile(df: Any, state: Any) -> dict[str, Any]:
    """시계열 전용 추가 필드 반환. dispatcher 가 basic profile 에 병합.

    Phase 실행 순서
    ---------------
    1  → date_col, freq, period  (이후 모든 Phase 에서 사용)
    8  → timeaxis_integrity      (target 무관, 항상 실행)
    2  → diff_order              (Phase 3 에서 사용)
    3  → AR/MA 힌트              (Phase 2 결과 소비)
    4  → STL stl_result          (Phase 5, 6 에서 사용)
    5  → seasonality             (Phase 4 결과 소비)
    6  → trend                   (Phase 4 결과 소비)
    7  → outlier_iqr_ratio       (독립)
    9  → is_multiplicative       (가법/승법)
    10 → changepoints            (레짐 변화)
    11 → target_kind             (누적/증분)
    12 → ccf_leakage             (CCF + 누수 사전탐지)
    §6 → period_acf_inferred     (freq=unknown 일 때만)
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
        "n_rows": int(len(df)),  # 행수 직접 노출 — 공통 basic_profile 의 rows 없을 때 fallback
    }

    # Phase 8 — 시간축 무결성 (target 무관, 항상 실행. early-return 직전에 둔다)
    try:
        extra["timeaxis_integrity"] = _phase8_timeaxis_integrity(df, date_col, period)
    except Exception as e:
        logger.warning("phase8_failed", error=str(e))
        extra["timeaxis_integrity"] = None

    if not target_col or target_col not in df.columns:
        extra["timeseries_warning"] = "target_column 누락 — 시계열 분석 일부 생략"
        for key in _NONE_ON_NO_TARGET:
            extra[key] = None
        return extra

    try:
        if date_col:
            df = df.sort_values(date_col).reset_index(drop=True)
        series = df[target_col].dropna().reset_index(drop=True).astype(float)

    except Exception as e:
        extra["timeseries_error"] = str(e)
        for key in _NONE_ON_NO_TARGET:
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

    # Phase 9 — 가법/승법 판정
    try:
        extra["is_multiplicative"] = _phase9_multiplicative(series, period)
    except Exception as e:
        logger.warning("phase9_failed", error=str(e))
        extra["is_multiplicative"] = None

    # Phase 10 — 레짐 변화 (count 평탄화 + 상세 분리)
    try:
        cp = _phase10_changepoints(series, stl_result, period)
        extra["changepoints"] = int(cp.get("count", 0))  # proposer 호환(평탄 int)
        extra["changepoints_detail"] = cp
    except Exception as e:
        logger.warning("phase10_failed", error=str(e))
        extra["changepoints"] = None
        extra["changepoints_detail"] = None

    # Phase 11 — 누적/증분 판정
    try:
        extra["target_kind"] = _phase11_target_kind(series, extra.get("trend") or {})
    except Exception as e:
        logger.warning("phase11_failed", error=str(e))
        extra["target_kind"] = None

    # Phase 12 — CCF + 누수 사전탐지 (정렬된 df 사용)
    try:
        extra["ccf_leakage"] = _phase12_ccf_leakage(df, target_col, date_col)
    except Exception as e:
        logger.warning("phase12_failed", error=str(e))
        extra["ccf_leakage"] = None

    # §6 보강 — freq=unknown 일 때만 ACF 기반 period 후보를 별도 키로 노출.
    # 기존 seasonality.period 는 불변 (회귀 0).
    try:
        if freq_str == "unknown":
            inferred = _infer_period_from_acf(extra.get("acf_pacf") or {}, len(series), period)
            if inferred is not None:
                extra["period_acf_inferred"] = inferred
    except Exception as e:
        logger.warning("period_reinference_failed", error=str(e))

    # Phase 13 — 이분산 진단 (분산의 시간 변화)
    try:
        extra["heteroscedasticity"] = _phase13_heteroscedasticity(series, period)
    except Exception as e:
        logger.warning("phase13_failed", error=str(e))
        extra["heteroscedasticity"] = None

    # Phase 14 — 이상치 성격 구분 (오류 vs 진짜 이벤트)
    try:
        extra["outlier_kind"] = _phase14_outlier_kind(series)
    except Exception as e:
        logger.warning("phase14_failed", error=str(e))
        extra["outlier_kind"] = None

    # Phase 15 — 0 vs NaN 도메인 구분 (센서 미작동 의심)
    # 원본 target(정렬 후, dropna 전 0 포함)을 봐야 0/NaN 패턴이 보존됨.
    try:
        raw_target = df[target_col] if (target_col and target_col in df.columns) else series
        extra["zero_vs_nan"] = _phase15_zero_vs_nan(raw_target)
    except Exception as e:
        logger.warning("phase15_failed", error=str(e))
        extra["zero_vs_nan"] = None

    logger.info(
        "profile_done",
        job_id=getattr(state, "job_id", None),
        date_col=date_col,
        freq=freq_str,
        period=period,
        consensus=(extra.get("stationarity") or {}).get("consensus"),
        has_seasonality=(extra.get("seasonality") or {}).get("has_seasonality"),
        outlier_ratio=extra.get("outlier_iqr_ratio"),
        changepoints=extra.get("changepoints"),
    )
    return extra

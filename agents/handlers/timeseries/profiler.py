"""agents.handlers.timeseries.profiler — 시계열 데이터 프로파일 보강 (CS 담당).

기본 stat 은 common.basic_dataframe_profile 이 처리. 본 함수는 시계열 전용 추가:
  - date_col          : 날짜 컬럼 자동 감지
  - freq              : 날짜 빈도 추론 (D/W/M/...)
  - stationarity      : ADF + KPSS 정상성 검정
  - acf_pacf          : ACF/PACF 자기상관 분석
  - stl_decompose     : STL 분해 (추세/계절/잔차 분산 비율)
  - seasonality       : 계절성 강도 + 주기
  - trend             : 추세 방향 + 강도
  - outlier_iqr_ratio : IQR 기반 이상치 비율
"""

from __future__ import annotations

import re
from math import sqrt
from typing import Any, Optional


def _detect_date_column(df: Any) -> Optional[str]:
    import pandas as pd  # noqa: WPS433

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col
        if re.search(r"(date|time|ts|timestamp)", col, re.IGNORECASE):
            try:
                pd.to_datetime(df[col].head(100), errors="raise")
                return col
            except Exception:
                continue
    return None


def _detect_period_and_freq(df: Any, date_col: Optional[str]) -> tuple[int, str]:
    """날짜 컬럼 빈도 추론 → 계절 주기 반환.

    일별(D) → period=7 (주간 계절성)
    월별(M) → period=12 (연간 계절성)
    """
    if date_col is None:
        return 7, "unknown"
    try:
        import pandas as pd  # noqa: WPS433

        dates = pd.to_datetime(df[date_col].dropna())
        inferred = pd.infer_freq(dates)
        if inferred:
            if inferred.startswith("D"):
                return 7, inferred
            if inferred.startswith("W"):
                return 52, inferred
            if inferred.startswith(("M", "MS")):
                return 12, inferred
            if inferred.startswith("Q"):
                return 4, inferred
            if inferred.startswith("H"):
                return 24, inferred
            return 7, inferred
    except Exception:
        pass
    return 7, "unknown"


def profile(df: Any, state: Any) -> dict[str, Any]:
    """시계열 전용 추가 필드 반환. dispatcher 가 basic profile 에 병합."""
    target_col = state.target_column
    date_col = _detect_date_column(df)
    period, freq_str = _detect_period_and_freq(df, date_col)

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
        from statsmodels.tsa.seasonal import STL  # noqa: WPS433
        from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf  # noqa: WPS433

        series = df[target_col].dropna().astype(float)
        n = len(series)

        # ── 1. 정상성 검정 ────────────────────────────────────────────────
        # ADF 귀무가설: "단위근이 있다(비정상)" → p<0.05 이면 귀무가설 기각 = 정상
        # KPSS 귀무가설: "정상이다"             → p>0.05 이면 귀무가설 채택 = 정상
        # 두 검정 방향이 반대이므로 모두 확인해야 신뢰도가 높다.
        adf = adfuller(series)
        adf_is_stationary = bool(adf[1] < 0.05)

        try:
            _, kpss_p, *_ = kpss(series, regression="c", nlags="auto")
            kpss_p_value: Optional[float] = round(float(kpss_p), 4)
            kpss_is_stationary: Optional[bool] = kpss_p > 0.05
        except Exception:
            kpss_p_value = None
            kpss_is_stationary = None

        extra["stationarity"] = {
            "adf_statistic": round(float(adf[0]), 4),
            "adf_p_value": round(float(adf[1]), 4),
            "adf_is_stationary": adf_is_stationary,
            "kpss_p_value": kpss_p_value,
            "kpss_is_stationary": kpss_is_stationary,
            "is_stationary": adf_is_stationary and bool(kpss_is_stationary),
        }

        # ── 2. ACF / PACF ─────────────────────────────────────────────────
        # 유의 임계치: ±2/√n (95% 신뢰구간). 이 값 밖이면 해당 lag 가 유의미
        max_lags = min(20, n // 2 - 1)
        significance = 2.0 / sqrt(n)
        try:
            acf_vals = acf(series, nlags=max_lags, fft=True)
            pacf_vals = pacf(series, nlags=max_lags)
            extra["acf_pacf"] = {
                "acf": [round(float(v), 4) for v in acf_vals],
                "pacf": [round(float(v), 4) for v in pacf_vals],
                "significant_lags_acf": [i for i, v in enumerate(acf_vals[1:], 1) if abs(v) > significance],
                "significance_threshold": round(significance, 4),
            }
        except Exception:
            extra["acf_pacf"] = {
                "acf": [],
                "pacf": [],
                "significant_lags_acf": [],
                "significance_threshold": round(significance, 4),
            }

        # ── 3. STL 분해 ───────────────────────────────────────────────────
        # seasonal_strength = 1 - Var(잔차) / Var(계절 + 잔차)  [0~1, 클수록 계절성 강함]
        # trend_strength    = 1 - Var(잔차) / Var(추세 + 잔차)
        stl_result: dict[str, Any] = {"available": False, "period": period}
        if n >= 2 * period + 1:
            try:
                stl = STL(series, period=period).fit()
                resid_var = float(stl.resid.var(ddof=0))
                seasonal_var = float(stl.seasonal.var(ddof=0))
                trend_var = float(stl.trend.var(ddof=0))
                s_strength = max(0.0, 1.0 - resid_var / max(seasonal_var + resid_var, 1e-9))
                t_strength = max(0.0, 1.0 - resid_var / max(trend_var + resid_var, 1e-9))
                stl_result = {
                    "available": True,
                    "period": period,
                    "trend_var": round(trend_var, 4),
                    "seasonal_var": round(seasonal_var, 4),
                    "resid_var": round(resid_var, 4),
                    "seasonal_strength": round(s_strength, 4),
                    "trend_strength": round(t_strength, 4),
                }
            except Exception:
                pass
        extra["stl_decompose"] = stl_result

        # ── 4. 계절성 요약 ────────────────────────────────────────────────
        s_strength = float(stl_result.get("seasonal_strength") or 0.0)
        extra["seasonality"] = {
            "has_seasonality": s_strength > 0.4,
            "period": period,
            "seasonal_strength": round(s_strength, 4) if stl_result["available"] else None,
        }

        # ── 5. 추세 방향 ──────────────────────────────────────────────────
        slope = float((series.iloc[-1] - series.iloc[0]) / max(1, n))
        t_strength = float(stl_result.get("trend_strength") or 0.0)
        extra["trend"] = {
            "has_trend": t_strength > 0.4 or abs(slope) > 1e-6,
            "direction": "increasing" if slope > 0 else ("decreasing" if slope < 0 else "none"),
            "trend_strength": round(t_strength, 4) if stl_result["available"] else None,
        }

        # ── 6. IQR 이상치 비율 ────────────────────────────────────────────
        q1 = float(series.quantile(0.25))
        q3 = float(series.quantile(0.75))
        iqr = q3 - q1
        if iqr > 0:
            outlier_mask = (series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)
            extra["outlier_iqr_ratio"] = round(float(outlier_mask.mean()), 4)
        else:
            extra["outlier_iqr_ratio"] = 0.0

    except Exception as e:
        extra["timeseries_error"] = str(e)
        for key in ("stationarity", "acf_pacf", "stl_decompose", "seasonality", "trend", "outlier_iqr_ratio"):
            if key not in extra:
                extra[key] = None

    return extra

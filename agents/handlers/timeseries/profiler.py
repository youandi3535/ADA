"""agents.handlers.timeseries.profiler — 시계열 데이터 프로파일 보강 (A 담당).

기본 stat 은 common.basic_dataframe_profile 이 처리. 본 함수는 시계열 전용 추가:
  - stationarity (ADF p-value)
  - seasonality (period, var)
  - trend (direction, slope)
  - date column 자동 감지

Day 1 (A): KPSS, ACF/PACF, STL decompose 추가 예정.
"""
from __future__ import annotations

import re
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


def profile(df: Any, state: Any) -> dict[str, Any]:
    """시계열 전용 추가 필드 반환. dispatcher 가 basic profile 에 병합."""
    target_col = state.target_column
    extra: dict[str, Any] = {"date_col": _detect_date_column(df)}

    if not target_col or target_col not in df.columns:
        extra["timeseries_warning"] = "target_column 누락 — 시계열 분석 일부 생략"
        return extra

    try:
        import pandas as pd  # noqa: WPS433
        from statsmodels.tsa.stattools import adfuller  # noqa: WPS433
        from statsmodels.tsa.seasonal import seasonal_decompose  # noqa: WPS433

        series = df[target_col].dropna().astype(float)
        adf = adfuller(series)
        extra["stationarity"] = {
            "adf_statistic": float(adf[0]),
            "adf_p_value": float(adf[1]),
            "is_stationary": bool(adf[1] < 0.05),
        }

        seasonality = {"has_seasonality": False, "period": None}
        try:
            period_guess = 7 if len(series) >= 60 else None
            if period_guess and len(series) >= 2 * period_guess:
                dec = seasonal_decompose(series, model="additive", period=period_guess)
                var = float(dec.seasonal.var(ddof=0))
                seasonality = {"has_seasonality": var > 0.01, "period": period_guess}
        except Exception:
            pass
        extra["seasonality"] = seasonality

        slope = float((series.iloc[-1] - series.iloc[0]) / max(1, len(series)))
        extra["trend"] = {
            "has_trend": abs(slope) > 1e-6,
            "direction": ("increasing" if slope > 0
                          else ("decreasing" if slope < 0 else "none")),
        }
        extra["freq"] = "auto"
    except Exception as e:
        extra["timeseries_error"] = str(e)

    return extra

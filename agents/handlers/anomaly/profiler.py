"""agents.handlers.anomaly.profiler — 이상탐지 데이터 프로파일 보강 (B 담당).

Day 1 (B): outlier_iqr_ratio, contamination_estimate, dim별 isolation depth.
"""
from __future__ import annotations

from typing import Any


def profile(df: Any, state: Any) -> dict[str, Any]:
    """이상탐지 전용 추가 필드."""
    import numpy as np  # noqa: WPS433

    extra: dict[str, Any] = {}
    try:
        num_df = df.select_dtypes(include=[np.number])
        if num_df.empty:
            extra["anomaly_warning"] = "수치 컬럼 없음"
            return extra

        # IQR 기반 이상치 비율 (간이)
        outlier_ratios: dict[str, float] = {}
        for c in num_df.columns:
            q1, q3 = num_df[c].quantile(0.25), num_df[c].quantile(0.75)
            iqr = q3 - q1
            if iqr <= 0:
                continue
            low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            mask = (num_df[c] < low) | (num_df[c] > high)
            outlier_ratios[str(c)] = float(mask.mean())

        extra["outlier_ratios_iqr"] = outlier_ratios
        if outlier_ratios:
            avg_outlier = float(sum(outlier_ratios.values()) / len(outlier_ratios))
            extra["contamination_estimate"] = round(max(0.001, min(0.5, avg_outlier)), 4)
    except Exception as e:
        extra["anomaly_error"] = str(e)
    return extra

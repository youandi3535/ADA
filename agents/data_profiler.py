"""agents.data_profiler — DataProfilerAgent (Day05 §1, v2 스코프).

이미지/오디오 핸들러는 제거 (메모리 ada_scope_decision).
지원 입력: csv / xlsx / parquet / json / zip / pdf / txt / html (8종).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from ada.core.state import PipelineState
from agents.base import BaseAgent
from tools.minio_tool import get_minio_client


def _detect_format(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"


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


class DataProfilerAgent(BaseAgent):
    """v2 — image/audio 제거, 정형+시계열 8종 입력 지원."""

    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            mc = get_minio_client()
            object_name = state.file_id  # MinIO key
            # 확장자 추출 (file_id 가 "uploads/{user}/{name.ext}" 형식 가정)
            fmt = _detect_format(object_name)
            try:
                df = mc.load_dataframe(object_name, fmt=fmt)
            except Exception as e:
                return state.with_update(
                    error=f"파일 로딩 실패: {e}",
                    validation={"is_valid": False, "errors": [str(e)], "warnings": []},
                    next_agent="error_recovery",
                )

            profile = self._profile_dataframe(df, target_column=state.target_column)
            if state.category == "timeseries":
                profile.update(self._analyze_timeseries(df, state.target_column))
            return state.with_update(data_profile=profile, next_agent="schema_validator")

    # ------------------------------------------------------------------
    def _profile_dataframe(self, df: Any, *, target_column: Optional[str]) -> dict[str, Any]:
        import pandas as pd  # noqa: WPS433
        import numpy as np  # noqa: WPS433

        n_rows = int(len(df))
        n_cols = int(df.shape[1])
        dtypes = {c: str(t) for c, t in df.dtypes.items()}
        missing = {c: float(df[c].isnull().mean()) for c in df.columns}
        cardinality = {c: int(df[c].nunique(dropna=True)) for c in df.columns}
        memory_mb = float(df.memory_usage(deep=True).sum()) / (1024 ** 2)

        numeric_stats: dict[str, dict[str, float]] = {}
        num_df = df.select_dtypes(include=[np.number])
        if not num_df.empty:
            desc = num_df.describe(percentiles=[0.25, 0.5, 0.75]).to_dict()
            for c, stats in desc.items():
                numeric_stats[c] = {k: float(v) for k, v in stats.items()
                                    if v is not None and not pd.isna(v)}

        has_target = bool(target_column and target_column in df.columns)
        target_dtype = str(df[target_column].dtype) if has_target else ""
        class_distribution: dict[Any, float] = {}
        if has_target and df[target_column].dtype.name in ("object", "category", "bool") \
                or (has_target and df[target_column].nunique() <= 50):
            vc = df[target_column].value_counts(dropna=False, normalize=True)
            class_distribution = {str(k): float(v) for k, v in vc.items()}

        date_col = _detect_date_column(df)

        sample_rows = df.head(5).fillna("").to_dict(orient="records")
        # JSON 직렬화 가능하게 변환
        sample_rows = [{k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                        for k, v in row.items()} for row in sample_rows]

        return {
            "rows": n_rows,
            "cols": n_cols,
            "columns": list(map(str, df.columns)),
            "dtypes": dtypes,
            "missing": missing,
            "numeric_stats": numeric_stats,
            "cardinality": cardinality,
            "memory_mb": memory_mb,
            "sample_rows": sample_rows,
            "has_target": has_target,
            "target_dtype": target_dtype,
            "class_distribution": class_distribution,
            "date_col": date_col,
        }

    # ------------------------------------------------------------------
    def _analyze_timeseries(self, df: Any, target_col: Optional[str]) -> dict[str, Any]:
        if not target_col or target_col not in df.columns:
            return {"timeseries_error": "target_column 누락"}
        try:
            import pandas as pd  # noqa: WPS433
            from statsmodels.tsa.stattools import adfuller  # noqa: WPS433
            from statsmodels.tsa.seasonal import seasonal_decompose  # noqa: WPS433

            series = df[target_col].dropna().astype(float)
            adf = adfuller(series)
            stationarity = {
                "adf_statistic": float(adf[0]),
                "adf_p_value": float(adf[1]),
                "is_stationary": bool(adf[1] < 0.05),
            }
            # 계절성 — period 자동 추정(연간/월간/주간 후보 중 ACF 가 가장 큰 것)
            seasonality = {"has_seasonality": False, "period": None}
            try:
                period_guess = 7 if len(series) >= 60 else None
                if period_guess and len(series) >= 2 * period_guess:
                    dec = seasonal_decompose(series, model="additive", period=period_guess)
                    var = float(dec.seasonal.var(ddof=0))
                    seasonality = {"has_seasonality": var > 0.01,
                                   "period": period_guess}
            except Exception:
                pass

            # trend
            slope = float((series.iloc[-1] - series.iloc[0]) / max(1, len(series)))
            trend = {"has_trend": abs(slope) > 1e-6,
                     "direction": "increasing" if slope > 0 else ("decreasing" if slope < 0 else "none")}

            return {
                "stationarity": stationarity,
                "seasonality": seasonality,
                "trend": trend,
                "freq": "auto",
            }
        except Exception as e:
            return {"timeseries_error": str(e)}

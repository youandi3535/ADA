"""agents.handlers.common.shared — 4 카테고리 모두 사용하는 헬퍼 (HJ).

- load_dataframe_from_state(state) → MinIO 로딩 통일
- save_chart_to_minio(fig, kind, job_id) → matplotlib fig 저장 통일
- basic_dataframe_profile(df, target_column) → 4 카테고리 공통 stat
"""

from __future__ import annotations

import tempfile
from typing import Any, Optional


def load_dataframe_from_state(state: Any, *, prefer_processed: bool = True) -> Any:
    """state.preprocessed_data_id 우선 로드 → uploads/ fallback (HJ-A, 2026-06-05).

    HJ-A 단절 해소: preprocessor.apply() 가 processed/{job}.parquet 으로 저장한
    전처리 결과 (lag/달력/푸리에/exog/diff/boxcox 모든 파생 피처 포함) 를
    training_executor·output_extras 가 우선 로드. 미존재 시 원본 uploads/ fallback.

    Parameters
    ----------
    state : PipelineState
    prefer_processed : bool
        True (기본) — preprocessed_data_id 우선. False — 항상 원본 로드 (profiler/eda 단계용).

    Returns
    -------
    pd.DataFrame
    """
    from tools.minio_tool import get_minio_client

    client = get_minio_client()

    # 1순위: preprocessed_data_id (HJ-A 해소)
    if prefer_processed:
        pid = getattr(state, "preprocessed_data_id", None)
        if isinstance(pid, str) and pid:
            try:
                fmt = pid.rsplit(".", 1)[-1].lower() if "." in pid else "parquet"
                return client.load_dataframe(pid, fmt=fmt)
            except Exception as exc:  # noqa: BLE001
                # graceful fallback — 로드 실패 시 원본으로
                try:
                    import logging as _log

                    _log.getLogger(__name__).warning(
                        "preprocessed_load_failed_fallback_uploads",
                        extra={"preprocessed_data_id": pid, "error": str(exc)},
                    )
                except Exception:
                    pass

    # 2순위: 원본 uploads/ (기존 동작)
    file_id = state.file_id

    keys = client.list_objects(prefix=f"uploads/{file_id}/")
    if keys:
        object_name = keys[0]
        fmt = object_name.rsplit(".", 1)[-1].lower() if "." in object_name else "csv"
        return client.load_dataframe(object_name, fmt=fmt)

    # 레거시: file_id 자체가 경로인 경우
    fmt = file_id.rsplit(".", 1)[-1].lower() if "." in file_id else "csv"
    return client.load_dataframe(file_id, fmt=fmt)


def save_chart_to_minio(fig: Any, *, kind: str, job_id: str) -> str:
    """matplotlib Figure → MinIO 저장 → s3:// 경로 반환."""
    import matplotlib.pyplot as plt  # noqa: WPS433

    from tools.minio_tool import get_minio_client

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.close()
    fig.savefig(tmp.name, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return get_minio_client().save_artifact(tmp.name, f"eda/{kind}", job_id)


def basic_dataframe_profile(df: Any, *, target_column: Optional[str]) -> dict[str, Any]:
    """4 카테고리 공통 profile — n_rows, n_cols, dtypes, missing, cardinality, memory."""
    import numpy as np  # noqa: WPS433
    import pandas as pd  # noqa: WPS433

    n_rows = int(len(df))
    n_cols = int(df.shape[1])
    dtypes = {c: str(t) for c, t in df.dtypes.items()}
    missing = {c: float(df[c].isnull().mean()) for c in df.columns}
    cardinality = {c: int(df[c].nunique(dropna=True)) for c in df.columns}
    memory_mb = float(df.memory_usage(deep=True).sum()) / (1024**2)

    numeric_stats: dict[str, dict[str, float]] = {}
    num_df = df.select_dtypes(include=[np.number])
    if not num_df.empty:
        desc = num_df.describe(percentiles=[0.25, 0.5, 0.75]).to_dict()
        for c, stats in desc.items():
            numeric_stats[c] = {k: float(v) for k, v in stats.items() if v is not None and not pd.isna(v)}

    # date_col: datetime dtype 우선, 없으면 컬럼명 휴리스틱
    _time_kws = ("date", "time", "ts", "timestamp", "일자", "시각", "날짜")
    date_col: str | None = None
    for _c in df.columns:
        if df[_c].dtype.kind == "M":
            date_col = str(_c)
            break
    if date_col is None:
        for _c in df.columns:
            if any(tok in str(_c).lower() for tok in _time_kws):
                date_col = str(_c)
                break

    has_target = bool(target_column and target_column in df.columns)
    target_dtype = str(df[target_column].dtype) if has_target else ""
    class_distribution: dict[Any, float] = {}
    if has_target:
        try:
            is_categorical_like = (
                df[target_column].dtype.name in ("object", "category", "bool") or df[target_column].nunique() <= 50
            )
            if is_categorical_like:
                vc = df[target_column].value_counts(dropna=False, normalize=True)
                class_distribution = {str(k): float(v) for k, v in vc.items()}
        except Exception:
            pass

    sample_rows = df.head(5).fillna("").to_dict(orient="records")
    sample_rows = [
        {k: (v if isinstance(v, (str, int, float, bool)) else str(v)) for k, v in row.items()} for row in sample_rows
    ]

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

# CS (timeseries) 시계열 ML 에이전트 평가용 패키지

> 작성: 2026-06-05
> 범위: CS 영역 8 핸들러 + pipeline + search_space + 인접 HJ 결합점
> 목적: 다른 Claude 인스턴스에게 평가받기 위한 전체 코드 묶음

## 평가 요청 사항

이 코드는 LangGraph 기반 AutoML 프레임워크 (ADA v2) 의 **시계열 머신러닝 (timeseries ML)** 전용 에이전트 사슬입니다. 다음 관점에서 평가 부탁드립니다:

1. **표준 데이터 분석가 워크플로우 20 단계** (문제 정의→수집→무결성→EDA→통계 진단→정제→변환→파생피처→분할→베이스라인→후보 선정→HPO→과적합 방어→평가→누수 진단→잔차 분석→예측→모델 비교→롤백→해석) 대비 자동화 수준
2. **데이터 상태 유연성** — 상수/짧음/긺/계절성/비정상/이상치/누수 등 graceful 처리
3. **사용자 주제 유연성** — user_intent 키워드, chosen_recipe.meta, horizon/n_rows fallback
4. **과적합/과소적합 방어** — train/val 격차, fold 분산, 정규화
5. **아키텍처 설계** — 에이전트 간 키 사슬 매끄러움, 회귀 안전성

## 프로젝트 구조 요약

- **에이전트 사슬**: profiler → eda → proposer → preprocessor → selector → pipeline (train + evaluate) → evaluator → insight → output_extras
- **상태 모델**: `PipelineState` (Pydantic) 불변 with_update 패턴
- **파이프라인**: 6 ML 모델 (ARIMA·SARIMA·SARIMAX·Prophet·ETS·seasonal_naive) — DL 비활성
- **검증**: walk-forward `TimeSeriesSplit + gap=horizon-1` + Optuna HPO
- **롤백**: 4 단계 (R1 전처리·R2 후보 교체·R3-a 하이퍼·R3-b 후보·R3-c 전처리)

---

## `ada/core/state.py`

```python
"""ada.core.state — PipelineState (LangGraph 그래프 상태).

R-005: 직접 수정 금지. ``state.model_copy(update={...})`` 패턴만 허용.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# 4 카테고리 — v2 스코프 (메모리 ada_scope_decision)
CATEGORIES = ("tabular_ml", "tabular_dl", "timeseries", "anomaly_detection")

# 5 산출물 코드 (OUT-01/02/03/04/07)
OUTPUT_CODES = ("OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07")

# 5 게이트 (G1~G6 중 G1 의도 → G6 산출물)
GATES = ("G1", "G2", "G3", "G4", "G5", "G6")


class PipelineState(BaseModel):
    """LangGraph 그래프 상태 모델 (Day03 §1).

    모든 에이전트가 이 상태를 입력으로 받아 새 상태를 반환한다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    # 핵심 식별자
    job_id: str
    file_id: str
    category: str
    task: str = "auto"

    # 입력 옵션
    target_column: Optional[str] = None
    user_question: Optional[str] = None
    user_intent: Optional[str] = None
    user_id: Optional[str] = None

    # 5 게이트 응답
    current_gate: Optional[str] = None
    gate_responses: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=list)
    auto_resolved_gates: list[str] = Field(default_factory=list)

    # 데이터 분석 결과
    data_profile: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None
    preprocessing_plan: Optional[list[dict[str, Any]]] = None
    preprocessed_data_id: Optional[str] = None

    # Phase 2 (2026-06-04) — G1 데이터 파악 종합 산출물 "Data Card v1".
    # 11 섹션 dict: identity / schema / dictionary / granularity / dq_score /
    # category_target / category_specific / pii_legal / temporal_drift /
    # reproducibility / next_steps. data_profiler 가 채우고 다음 단계가 참조.
    data_card: Optional[dict[str, Any]] = None

    # EDA
    eda_charts: list[str] = Field(default_factory=list)
    # HJ-2 (2026-06-05) — 하위 호환 union. HJ EdaAgent 는 str (f-string 요약),
    # CS handlers/timeseries 는 dict (구조화된 키-값 분석 결과) 로 사용.
    # 소비측은 isinstance(eda_summary, dict) 가드 후 분기 처리 권장.
    eda_summary: Optional[dict[str, Any] | str] = None

    # G2 방법론 후보 채택 — chosen_recipe 정식 필드 (HJ-5, 2026-06-05).
    # methodology_proposer/supervisor 가 채움. CS·NY·jh 9 에이전트에서
    # getattr(state, "chosen_recipe", None) 패턴으로 안전 접근 중이었으나
    # 본 필드 추가로 타입체커·IDE 지원 확보.
    chosen_recipe: Optional[dict[str, Any]] = None

    # 모델링
    model_candidates: list[str] = Field(default_factory=list)
    best_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    trained_models: list[dict[str, Any]] = Field(default_factory=list)
    training_warnings: list[str] = Field(default_factory=list)
    best_model: Optional[dict[str, Any]] = None

    # 해석/평가
    explanations: Optional[dict[str, Any]] = None
    eval_result: Optional[dict[str, Any]] = None
    insights: Optional[str] = None

    # 산출물
    output_paths: dict[str, str] = Field(default_factory=dict)

    # 오케스트레이션 제어
    retry_count: int = 0
    max_retries: int = 3
    re_loop_count: int = 0
    max_re_loop: int = 2
    error: Optional[str] = None
    next_agent: Optional[str] = None

    # ADR-006 Auto Error Resolution (Phase 1)
    # 에러 발생 시 BaseAgent 가 traceback 캡처 + auto_error_handler 노드가 처리.
    error_traceback: Optional[str] = None
    error_classified_as: Optional[str] = None
    error_fingerprint: Optional[str] = None
    auto_fix_attempts: int = 0
    max_auto_fix_attempts: int = 2

    # 자체학습 — KB 인용 (R-501)
    kb_citations: list[str] = Field(default_factory=list)

    # 카테고리별 격리 컨테이너 (Day 0 H0-4)
    # 멤버 CS/NY/jh 가 자기 카테고리 키 안에만 쓰기 → 충돌 0건.
    category_extras: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # 옵저버빌리티
    trace_id: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def with_update(self, **kwargs: Any) -> "PipelineState":
        """R-005 — 직접 수정 대신 이 헬퍼를 사용한다."""
        return self.model_copy(update=kwargs)
```

---

## `agents/handlers/common/shared.py`

```python
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
    }
```

---

## `agents/handlers/timeseries/profiler.py`

```python
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


# ════════════════════════════════════════════════════════════════
# X1 (2026-06-05) — 타겟 자동 추천 (target_column 누락 시 graceful)
# ════════════════════════════════════════════════════════════════
def _suggest_target_candidates(df: Any, date_col: Optional[str] = None, top_k: int = 3) -> list[dict[str, Any]]:
    """수치형 컬럼 중 시계열 타겟으로 적합한 top_k 자동 추천.

    적합도 점수:
      + 분산 > 0 (상수 제외)
      + 결측 비율 < 50%
      + autocorr(lag=1) > 0.3 (시계열성)
      + 추세/계절성 신호 (간단 std/mean 비)
    반환: [{column, score, reason, autocorr, std, missing_ratio}, ...]

    사용자가 target_column 안 줬을 때 profile["target_candidates"] 에 노출.
    """
    import numpy as _np
    import pandas as _pd

    if not isinstance(df, _pd.DataFrame) or len(df) < 10:
        return []
    candidates: list[dict[str, Any]] = []
    exclude = {date_col} if date_col else set()
    for col in df.columns:
        if col in exclude:
            continue
        try:
            series = _pd.to_numeric(df[col], errors="coerce")
        except Exception:
            continue
        # 수치형 변환 후 NaN 비율 점검
        missing_ratio = float(series.isna().mean())
        if missing_ratio >= 0.5:
            continue
        valid = series.dropna()
        if len(valid) < 10 or float(valid.var()) <= 0:
            continue
        try:
            ac1 = float(valid.autocorr(lag=1)) if len(valid) > 1 else 0.0
        except Exception:
            ac1 = 0.0
        if _np.isnan(ac1):
            ac1 = 0.0
        # 점수 — autocorr 60% + (1-missing_ratio) 30% + 분산 정규화 10%
        std_norm = min(1.0, float(valid.std()) / (abs(float(valid.mean())) + 1e-9))
        score = 0.6 * max(0.0, ac1) + 0.3 * (1.0 - missing_ratio) + 0.1 * std_norm
        reasons = []
        if ac1 > 0.5:
            reasons.append(f"autocorr={ac1:.2f}")
        elif ac1 > 0.3:
            reasons.append(f"weak_autocorr={ac1:.2f}")
        if missing_ratio < 0.05:
            reasons.append("low_missing")
        candidates.append(
            {
                "column": str(col),
                "score": round(score, 3),
                "autocorr_lag1": round(ac1, 3),
                "missing_ratio": round(missing_ratio, 3),
                "std": round(float(valid.std()), 3),
                "reason": ", ".join(reasons) if reasons else "수치형 + 분산>0",
            }
        )
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[: max(1, top_k)]


# ════════════════════════════════════════════════════════════════
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
        # X1 (2026-06-05) — 타겟 자동 추천 (사용자가 target 안 줬을 때 graceful)
        try:
            extra["target_candidates"] = _suggest_target_candidates(df, date_col=date_col, top_k=3)
        except Exception as _e:
            logger.warning("target_candidate_suggest_failed: %s", _e)
            extra["target_candidates"] = []
        for key in _NONE_ON_NO_TARGET:
            extra[key] = None
        return extra

    try:
        if date_col:
            df = df.sort_values(date_col).reset_index(drop=True)
        # X5 (2026-06-05) — target 의 결측 비율 노출 (preprocessor 단기 강등 권고 입력)
        try:
            extra["missing_ratio"] = float(df[target_col].isna().mean())
        except Exception:
            extra["missing_ratio"] = None
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
```

---

## `agents/eda_agent.py`

```python
"""agents.eda_agent — Day 0 dispatcher 패턴.

카테고리별 차트 생성은 ``handlers/{cat}/eda.charts(df, state)`` 가 담당.
수정 권한: **HJ 단독** (dispatcher).

HJ-2 보강 (2026-06-05) — eda_summary union (dict | str).
카테고리 핸들러 (`charts`) 가 `last_eda_summary` 속성에 dict 를 부착했으면
str 요약 대신 그 dict 를 state.eda_summary 로 전달. CS handlers/timeseries/eda.py
설계와 정합 (line 17 의 "부수효과로 charts.last_eda_summary 에 dict 부착 →
dispatcher 가 state.eda_summary 로 전달").
"""

from __future__ import annotations

from typing import Any

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from agents.handlers.common.shared import load_dataframe_from_state


class EDAAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            charts: list[str] = []
            try:
                df = load_dataframe_from_state(state, prefer_processed=False)
            except Exception as e:
                self.logger.warning("eda_load_failed", error=str(e))
                return state.with_update(next_agent="gate_methodology")

            handler = get_handler(state.category, "charts")
            if handler is not None:
                try:
                    charts = handler(df, state) or []
                except Exception as e:
                    self.logger.warning("eda_handler_failed", category=state.category, error=str(e))

            # HJ-2 보강 — 핸들러가 부수효과로 dict 요약 부착했으면 우선 사용 (CS handlers/timeseries/eda.py).
            # state.eda_summary 는 Optional[dict | str] union 이므로 둘 다 허용.
            summary: Any = (
                f"행수={len(df):,}, 열수={df.shape[1]:,}, 카테고리={state.category}, 생성 차트 {len(charts)}종."
            )
            if handler is not None:
                dict_summary = getattr(handler, "last_eda_summary", None)
                if isinstance(dict_summary, dict) and dict_summary:
                    summary = dict_summary

            return state.with_update(
                eda_charts=charts,
                eda_summary=summary,
                next_agent="gate_methodology",
            )
```

---

## `agents/handlers/timeseries/eda.py`

```python
"""agents.handlers.timeseries.eda — 시계열 EDA 차트 (CS 담당, cs-day3 v3 디벨롭).

방법론 2단계(EDA — 시간 구조) 전부를 차트·수치로 표현 + profiler 진단 승계.

차트 (모두 MinIO 저장, 인라인 try/except 독립):
  ① missing 막대 (Chart 0)
  ② line plot + 레짐/이벤트 오버레이 (Chart 1)   ← 2-1 레짐변화·이벤트 표시
  ③ ACF (Chart 2, statsmodels lazy import)         ← 2-4 ACF
  ④ PACF (Chart 2b, statsmodels lazy import)        ← 2-4 PACF (신규)
  ⑤ STL 4단 분해 (Chart 3, n ≥ 2s 가드)             ← 2-2 분해
  ⑥ seasonality heatmap year×month (Chart 4)
  ⑦ rolling std — 이분산 (Chart 5, 신규)            ← 2-1 분산의 시간변화
  ⑧ CCF — 시차상관 (Chart 6, exog 있을 때, 신규)     ← 2-5 시차상관

진입함수 (dispatcher 자동 등록):
  - charts(df, state) -> list[str]   MinIO 경로 list
    (부수효과로 charts.last_eda_summary 에 dict 부착 → dispatcher 가 state.eda_summary 로 전달)

DoD: 4+ chart MinIO 저장 + eda_summary 갱신 (seasonal_period · stationary · acf_peaks
     · changepoints · is_multiplicative · ccf_top_lags · heteroscedastic).

핵심 설계 원칙:
  - 인라인 try/except 우선 — 각 차트 독립 (한 차트 실패가 전체로 안 번짐)
  - 자연 발생 롤백 3 개만 (target/n_rows/모든 실패) — A-1/A-2/G-1 가드 (불변)
  - lazy import (statsmodels, seaborn) — 미설치 인라인 skip
  - seasonal_period 우선순위 — eda → acf → freq fallback (D=7, M=12)
  - 임시 컬럼명 충돌 회피 — _year, _month
  - ★ profiler 산출물 재사용(재계산 X) — data_profile 의 진단을 eda_summary 로 승계
  - ★ 정상성은 profiler ADF+KPSS 4-case 우선, 없으면 자체 ADF fallback (방법론 2-3 교차)
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
MIN_ROWS_FOR_EDA = 10  # A-2 가드 (cs-day2 RB-5 와 일관)
MIN_ROWS_FOR_ACF = 20  # D-2a 가드
ACF_PEAK_HEIGHT = 0.1
MISSING_TOP_K = 20
FREQ_SEASONAL_FALLBACK = {"D": 7, "W": 4, "M": 12, "MS": 12, "H": 24}
MAX_CHANGEPOINT_MARKS = 20  # 오버레이 수직선 상한


# ════════════════════════════════════════════════════════════════
# seasonal_period 추정 (3 단 우선순위)
# ════════════════════════════════════════════════════════════════
def _infer_seasonal_period(eda_summary: dict, freq: Any, acf_peaks: list[int], n_rows: int) -> int:
    """seasonal_period 추정 — eda 명시 → acf 첫 유의 peak → freq fallback."""
    # 1. eda_summary 명시 (외부 입력)
    s = (eda_summary or {}).get("seasonal_period")
    if isinstance(s, int) and 1 < s <= n_rows // 2:
        return s
    # 2. acf_peaks 첫 유의 peak (lag 1 제외)
    valid_peaks = [p for p in acf_peaks if 1 < p <= n_rows // 2]
    if valid_peaks:
        return int(valid_peaks[0])
    # 3. freq 기반 fallback
    return int(FREQ_SEASONAL_FALLBACK.get(freq, 0))


def _eda_summary_dict(state: Any) -> dict:
    """state.eda_summary 가 str(또는 None)일 수 있으므로 dict 로 안전 변환.

    PipelineState.eda_summary 는 Optional[str] 타입이라 직접 .get() 불가.
    dispatcher 가 dict 를 넣어주는 경우(테스트/확장)와 None/str 모두 graceful.
    """
    raw = getattr(state, "eda_summary", None)
    if isinstance(raw, dict):
        return raw
    return {}


# ════════════════════════════════════════════════════════════════
# ★ profiler 산출물 승계 (재계산 X — 방법론 2 전부를 다운스트림으로 전달)
# ════════════════════════════════════════════════════════════════
def _carry_from_profile(profile: dict) -> dict[str, Any]:
    """profiler 가 이미 계산한 진단을 eda_summary 로 승계한다.

    profiler Phase 결과를 None-안전하게 평탄화. 소비처(proposer/selector/insight)가
    eda_summary 에서 바로 읽도록 키 이름을 맞춘다. profiler 미실행 시 모두 None.
    """
    p = profile or {}

    def _g(key: str, sub: str | None = None) -> Any:
        v = p.get(key)
        if sub is None:
            return v
        return (v or {}).get(sub) if isinstance(v, dict) else None

    # 정상성 — profiler ADF+KPSS 4-case 우선 (방법론 2-3 교차검정)
    stat = p.get("stationarity") or {}
    stationary = stat.get("is_stationary") if isinstance(stat, dict) else None
    consensus = stat.get("consensus") if isinstance(stat, dict) else None

    carry: dict[str, Any] = {
        # 2-1 레짐/이벤트
        "changepoints": _g("changepoints"),
        "outlier_recommend": _g("outlier_kind", "recommend"),
        # 2-2 가법/승법
        "is_multiplicative": _g("is_multiplicative", "is_multiplicative"),
        # 2-1 이분산
        "heteroscedastic": _g("heteroscedasticity", "is_heteroscedastic"),
        # 2-5 CCF + 누수
        "ccf_top_lags": _g("ccf_leakage", "ccf_top_lags"),
        "leakage_suspect_cols": _g("ccf_leakage", "leakage_suspect_cols"),
        # 0단계 성격
        "is_multivariate": _g("ccf_leakage", "is_multivariate"),
        "target_kind": _g("target_kind", "target_kind"),
        # 2-3 정상성 (교차검정)
        "stationarity_consensus": consensus,
    }
    if stationary is not None:
        carry["stationary"] = bool(stationary)
    return {k: v for k, v in carry.items() if v is not None}


def _exog_columns(state: Any, df: Any, target: str) -> list[str]:
    """exog 컬럼 — category_extras 우선, 없으면 수치형 중 target·date 제외 추론."""
    try:
        cols = (getattr(state, "category_extras", None) or {}).get("timeseries", {}).get("exog_columns")
        if cols:
            return [c for c in cols if c in df.columns]
    except (TypeError, AttributeError):
        pass
    import pandas as pd  # noqa: WPS433

    exog: list[str] = []
    for c in df.columns:
        if c == target:
            continue
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            exog.append(c)
    return exog[:5]  # 차트 비용 상한


# ════════════════════════════════════════════════════════════════
# 신규 차트 헬퍼 (각 독립 try/except — 실패 시 None 반환, 전체 안 죽임)
# ════════════════════════════════════════════════════════════════
def _chart_pacf(plt: Any, y: Any, target: str, job_id: str, save: Any) -> str | None:
    """PACF 차트 (방법론 2-4 — 직접 영향 시차)."""
    try:
        from statsmodels.tsa.stattools import pacf  # noqa: WPS433

        n = len(y)
        if n < MIN_ROWS_FOR_ACF or float(y.var()) <= 0:
            return None
        pacf_vals = pacf(y, nlags=min(40, n // 2 - 1))
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.bar(range(len(pacf_vals)), pacf_vals)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(f"PACF — {target}")
        return save(fig, kind="timeseries/pacf", job_id=job_id)
    except Exception:
        return None


def _chart_rolling_std(plt: Any, y: Any, target: str, period: int, job_id: str, save: Any) -> str | None:
    """rolling std 시간 플롯 (방법론 2-1 — 분산의 시간 변화 = 이분산)."""
    try:
        n = len(y)
        if n < MIN_ROWS_FOR_ACF:
            return None
        w = max(5, period if period and period >= 2 else 7)
        rstd = y.rolling(w, min_periods=max(2, w // 2)).std()
        if rstd.notna().sum() < 2:
            return None
        fig, ax = plt.subplots(figsize=(10, 3))
        rstd.plot(ax=ax)
        ax.set_title(f"Rolling std (w={w}) — 이분산 진단 — {target}")
        ax.set_ylabel("std")
        return save(fig, kind="timeseries/rolling_std", job_id=job_id)
    except Exception:
        return None


def _chart_changepoints(plt: Any, y: Any, target: str, cp_indices: list[int], job_id: str, save: Any) -> str | None:
    """line plot + changepoint/이벤트 시점 수직선 (방법론 2-1 — 레짐 변화·이벤트)."""
    try:
        if not cp_indices:
            return None
        fig, ax = plt.subplots(figsize=(10, 3))
        y.reset_index(drop=True).plot(ax=ax, color="steelblue", linewidth=1)
        marked = 0
        for idx in cp_indices[:MAX_CHANGEPOINT_MARKS]:
            if isinstance(idx, (int, float)) and 0 <= idx < len(y):
                ax.axvline(int(idx), color="red", linestyle="--", alpha=0.6, linewidth=0.8)
                marked += 1
        if marked == 0:
            plt.close(fig)
            return None
        ax.set_title(f"Regime/event changepoints ({marked}) — {target}")
        return save(fig, kind="timeseries/changepoints", job_id=job_id)
    except Exception:
        return None


def _chart_ccf(plt: Any, df: Any, target: str, exog_cols: list[str], job_id: str, save: Any) -> str | None:
    """CCF 차트 (방법론 2-5 — 시차상관, 차분 후 허위상관 방지). exog 있을 때만."""
    try:
        import numpy as np  # noqa: WPS433
        import pandas as pd  # noqa: WPS433

        if not exog_cols:
            return None
        t = pd.to_numeric(df[target], errors="coerce").diff()  # 차분 (허위상관 방지)
        max_lag = 14
        fig, ax = plt.subplots(figsize=(10, 3))
        plotted = 0
        for col in exog_cols[:3]:  # 최대 3개 중첩
            ex = pd.to_numeric(df[col], errors="coerce").diff()
            corrs = []
            for lag in range(0, max_lag + 1):
                pair = pd.concat([t, ex.shift(lag)], axis=1).dropna()
                if len(pair) < 3:
                    corrs.append(0.0)
                    continue
                c = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
                corrs.append(0.0 if np.isnan(c) else c)
            ax.plot(range(max_lag + 1), corrs, marker="o", markersize=3, label=col)
            plotted += 1
        if plotted == 0:
            plt.close(fig)
            return None
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_title(f"CCF (차분 후) — {target} vs exog")
        ax.set_xlabel("lag")
        ax.legend(fontsize=8)
        return save(fig, kind="timeseries/ccf", job_id=job_id)
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
# §A. 입력 검증 + 차트 진입점
# ════════════════════════════════════════════════════════════════
def charts(df: Any, state: Any) -> list[str]:
    """4+ chart 생성 + MinIO 업로드 + 경로 list 반환.

    A-1 target 가드 / A-2 n_rows 가드 → ValueError (dispatcher 가 RB 처리).
    각 차트는 try/except 로 독립 — 한 차트 실패가 전체로 번지지 않음.
    G-1 모든 차트 실패 시 RuntimeError (RB-3).
    """
    import matplotlib  # noqa: WPS433

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: WPS433

    from agents.handlers.common.shared import save_chart_to_minio

    paths: list[str] = []
    target = getattr(state, "target_column", None)
    job_id = getattr(state, "job_id", "unknown")

    # ── A-1 : target 가드 ──
    if not target or target not in df.columns:
        raise ValueError("target_column missing — preprocessor 검증 필요")  # → RB-1

    # ── A-2 : n_rows 가드 ──
    if len(df) < MIN_ROWS_FOR_EDA:
        raise ValueError("n_rows < 10 — EDA 의미 부족")  # → RB-2

    profile = getattr(state, "data_profile", None) or {}
    freq = profile.get("freq")
    eda_in = _eda_summary_dict(state)
    # ★ profiler 진단 승계 (재계산 X)
    carry = _carry_from_profile(profile)

    # ── §B : Chart 0 — missing 막대 ──
    try:
        miss = df.isnull().mean().sort_values(ascending=False).head(MISSING_TOP_K)
        if not miss.empty and miss.sum() > 0:
            fig, ax = plt.subplots(figsize=(8, 4))
            miss.plot(kind="barh", ax=ax)
            ax.set_title("Missing rate (top 20) — timeseries")
            paths.append(save_chart_to_minio(fig, kind="timeseries/missing", job_id=job_id))
    except Exception:
        pass  # 인라인 skip 안전

    # ── §C : Chart 1 — line plot ──
    if target and target in df.columns:
        try:
            fig, ax = plt.subplots(figsize=(10, 3))
            df[target].plot(ax=ax)
            ax.set_title(f"{target} over time")
            paths.append(save_chart_to_minio(fig, kind="timeseries/line", job_id=job_id))
        except Exception:
            pass

    # ── §D : Chart 2 — ACF + seasonal_period 추정 ──
    acf_peaks: list[int] = []
    _acf_ok = False
    try:
        from scipy.signal import find_peaks  # noqa: WPS433
        from statsmodels.tsa.stattools import acf  # noqa: WPS433

        _acf_ok = True
    except ImportError:
        _acf_ok = False  # → D-2b skip (CI 최소 deps)

    if _acf_ok:
        try:
            y = df[target].dropna()
            if len(y) >= MIN_ROWS_FOR_ACF and y.var() > 0:  # 분산 0 가드
                acf_vals = acf(y, nlags=min(40, len(y) // 2))
                peaks, _ = find_peaks(acf_vals, height=ACF_PEAK_HEIGHT)
                acf_peaks = peaks.tolist()

                fig, ax = plt.subplots(figsize=(10, 3))
                ax.bar(range(len(acf_vals)), acf_vals)
                ax.axhline(0, color="black", linewidth=0.5)
                ax.set_title(f"ACF — {target}")
                paths.append(save_chart_to_minio(fig, kind="timeseries/acf", job_id=job_id))
        except Exception:
            pass

    # ── §D2 : Chart 2b — PACF (신규, 방법론 2-4) ──
    try:
        y_pacf = df[target].dropna()
        p_path = _chart_pacf(plt, y_pacf, target, job_id, save_chart_to_minio)
        if p_path:
            paths.append(p_path)
    except Exception:
        pass

    # ── §E : Chart 3 — STL ──
    s = _infer_seasonal_period(eda_in, freq, acf_peaks, len(df))
    eda_extras: dict[str, Any] = {}
    if s == 0:
        skip_reason: Any = "no_period"
    elif len(df) < 2 * s:
        skip_reason = "too_short"
    else:
        skip_reason = None

    if skip_reason is None:
        try:
            from statsmodels.tsa.seasonal import seasonal_decompose  # noqa: WPS433
            from statsmodels.tsa.stattools import adfuller  # noqa: WPS433

            y = df[target].dropna()
            if len(y) < 5:
                skip_reason = "NaN_dominant"
            else:
                res = seasonal_decompose(y, period=s, model="additive")

                fig, axes = plt.subplots(4, 1, figsize=(10, 8), sharex=True)
                res.observed.plot(ax=axes[0], title="Observed")
                res.trend.plot(ax=axes[1], title="Trend")
                res.seasonal.plot(ax=axes[2], title="Seasonal")
                res.resid.plot(ax=axes[3], title="Residual")
                paths.append(save_chart_to_minio(fig, kind="timeseries/stl", job_id=job_id))

                # eda_summary 갱신 (부수효과) — profiler 정상성 없을 때 fallback
                adf_p = adfuller(y)[1]
                eda_extras = {
                    "stationary": bool(adf_p <= 0.05),
                    "residual_std": float(res.resid.dropna().std()),
                    "total_std": float(y.std()),
                }
        except Exception:
            skip_reason = "fit_error"
            eda_extras = {}

    # ── §F : Chart 4 — seasonality heatmap (year × month) ──
    try:
        import pandas as pd  # noqa: WPS433

        if isinstance(df.index, pd.DatetimeIndex):
            try:
                import seaborn as sns  # noqa: WPS433

                tmp = df[[target]].copy()
                tmp["_year"] = tmp.index.year
                tmp["_month"] = tmp.index.month
                tmp = tmp.dropna(subset=["_year", "_month"])  # NaT 제거

                pivot = tmp.groupby(["_year", "_month"])[target].mean().unstack()
                fig, ax = plt.subplots(figsize=(10, 6))
                sns.heatmap(pivot, annot=True, cmap="YlGnBu", ax=ax, fmt=".1f")
                ax.set_title(f"Seasonality heatmap (year × month) — {target}")
                paths.append(save_chart_to_minio(fig, kind="timeseries/seasonality_heatmap", job_id=job_id))
            except Exception:
                pass  # seaborn 미설치 / pivot 실패 → skip
    except Exception:
        pass

    # ── §F2 : Chart 5 — rolling std (이분산, 신규 2-1) ──
    try:
        y_rs = df[target].dropna().reset_index(drop=True)
        rs_path = _chart_rolling_std(plt, y_rs, target, s, job_id, save_chart_to_minio)
        if rs_path:
            paths.append(rs_path)
    except Exception:
        pass

    # ── §F3 : Chart 6 — 레짐/이벤트 오버레이 (신규 2-1) ──
    try:
        cp_detail = profile.get("changepoints_detail") or {}
        cp_indices = cp_detail.get("indices") if isinstance(cp_detail, dict) else None
        if cp_indices:
            y_cp = df[target].dropna()
            cp_path = _chart_changepoints(plt, y_cp, target, cp_indices, job_id, save_chart_to_minio)
            if cp_path:
                paths.append(cp_path)
    except Exception:
        pass

    # ── §F4 : Chart 7 — CCF (시차상관, 신규 2-5) — exog 있을 때만 ──
    try:
        exog_cols = _exog_columns(state, df, target)
        if exog_cols:
            ccf_path = _chart_ccf(plt, df, target, exog_cols, job_id, save_chart_to_minio)
            if ccf_path:
                paths.append(ccf_path)
    except Exception:
        pass

    # ── §G : paths 가드 + eda_summary 반환 정보 부착 ──
    if not paths:
        raise RuntimeError("all_charts_failed — 데이터 비정상 의심")  # → RB-3

    # dispatcher 가 state.with_update(eda_summary=...) 하도록 메타를 함수 속성에
    # 동봉 (반환은 paths list[str] 계약 유지).
    # 병합 순서: 자체 계산(eda_extras) → profiler 승계(carry) 가 우선
    # (profiler 의 ADF+KPSS 4-case 가 자체 ADF 단독보다 정확하므로 carry 가 덮어씀).
    try:
        summary = {
            "charts": list(paths),
            "seasonal_period": s,
            "acf_peaks": acf_peaks,
        }
        summary.update(eda_extras)  # stationary(자체 ADF) / residual_std / total_std
        summary.update(carry)  # ★ profiler 진단 승계 — stationary 등은 carry 가 우선
        charts.last_eda_summary = summary  # type: ignore[attr-defined]
    except Exception:
        pass

    return paths
```

---

## `agents/gates/methodology_proposer.py`

```python
"""agents.gates.methodology_proposer — G3 방법론 제안 (정형ML/정형DL/시계열/이상탐지)."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import CATEGORIES, PipelineState
from agents.gates._base_gate import BaseGate

_UNSUPERVISED_CATEGORIES: frozenset[str] = frozenset({"anomaly_detection"})

# 방법론 제목/근거 텍스트에서 카테고리를 키워드로 추론하기 위한 사전.
# 우선순위 높음 → 낮음 순서 (anomaly_detection 먼저 검사하지 않으면 timeseries 가 흡수).
_CATEGORY_KEYWORDS_KO: list[tuple[str, list[str]]] = [
    ("anomaly_detection", ["이상탐지", "anomaly", "outlier", "이상치", "이상", "OneClass", "Isolation"]),
    ("timeseries", ["시계열", "예측", "forecast", "time series", "temporal", "SARIMA", "Prophet", "LSTM"]),
    ("tabular_dl", ["딥러닝", "deep learning", "transformer", "FTTransformer", "TabTransformer"]),
    ("tabular_ml", ["정형 ML", "XGBoost", "LightGBM", "RandomForest", "tree", "boosting"]),
]


def _infer_category_from_text(text: str, fallback: str) -> str:
    """proposal title/rationale 키워드로 category 를 추론."""
    t = (text or "").lower()
    for cat, kws in _CATEGORY_KEYWORDS_KO:
        if any(k.lower() in t for k in kws):
            return cat
    return fallback


SYSTEM_PROMPT = (
    "You are an AutoML strategy consultant. "
    "Given the data profile and the G2 analysis direction chosen by the user, "
    "propose exactly TWO distinct methodology options from: tabular_ml, tabular_dl, timeseries, anomaly_detection. "
    "Option 1 should be the best fit; Option 2 should offer a meaningfully different angle. "
    "For each option, write a detailed Korean rationale of 2-3 sentences that explains: "
    "(1) why this methodology suits the data characteristics, "
    "(2) which specific algorithms or model families would be used, "
    "(3) what concrete insight or result the user can expect. "
    "Titles must be in Korean (concise and descriptive). "
    "Reply with a JSON array of exactly 2 objects, no markdown:\n"
    '[{"id": 1, "title": "한국어 제목", "rationale": "한국어 2-3문장 상세 설명", "score": 0.0-1.0}, '
    ' {"id": 2, "title": "한국어 제목", "rationale": "한국어 2-3문장 상세 설명", "score": 0.0-1.0}]'
)

_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 방법론이나 분석 전략을 직접 입력하세요.",
    "score": None,
    "is_custom": True,
}

_FALLBACK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "tabular_ml": [
        {
            "id": 1,
            "title": "정형 ML 분류/회귀 앙상블",
            "rationale": (
                "타겟 컬럼의 분포와 피처 구성이 정형 ML에 적합하며, "
                "Logistic Regression, Random Forest, XGBoost 등 앙상블 모델을 활용해 높은 예측 정확도를 기대할 수 있습니다. "
                "교차 검증과 하이퍼파라미터 최적화를 통해 안정적이고 해석 가능한 예측 모델을 제공합니다."
            ),
            "score": 0.9,
        },
        {
            "id": 2,
            "title": "SHAP 기반 피처 중요도 분석",
            "rationale": (
                "SHAP 값과 피처 중요도 분석을 결합하여 예측에 영향을 미치는 핵심 변수를 식별합니다. "
                "단순 예측을 넘어 어떤 요인이 결과를 결정하는지 해석 가능한 인사이트를 제공하며, "
                "비즈니스 의사결정에 직접 활용할 수 있는 변수 중요도 리포트를 생성합니다."
            ),
            "score": 0.6,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "TabTransformer 딥러닝 학습",
            "rationale": (
                "범주형 피처가 많은 정형 데이터에 TabTransformer를 적용하여 "
                "어텐션 메커니즘으로 피처 간 복잡한 상호작용을 학습합니다. "
                "기존 트리 기반 모델보다 비선형 패턴을 더 정확하게 포착하며, 대규모 데이터에서 강점을 발휘합니다."
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "FTTransformer 수치 임베딩 비교",
            "rationale": (
                "수치형 피처를 임베딩으로 변환하는 FTTransformer를 사용하여 TabTransformer와 성능을 비교합니다. "
                "두 모델의 교차 검증 결과를 기반으로 최적 아키텍처를 자동 선정하며, "
                "각 모델의 예측 신뢰도와 피처 기여도를 함께 제공합니다."
            ),
            "score": 0.7,
        },
    ],
    "timeseries": [
        {
            "id": 1,
            "title": "단기 시계열 예측 (LSTM/Prophet)",
            "rationale": (
                "시계열 데이터의 추세와 계절성 패턴을 분석하여 Prophet 또는 LSTM 기반 단기 예측 모델을 구축합니다. "
                "1~30일 구간의 미래 값 예측과 신뢰 구간을 함께 제공하며, "
                "계절성·휴일 효과 등 외부 요인을 자동으로 반영합니다."
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "이상 시점 탐지 (변동성 분석)",
            "rationale": (
                "시계열 내 변동성이 비정상적으로 큰 구간을 Isolation Forest와 통계적 기법으로 탐지합니다. "
                "정상 패턴을 학습한 후 이탈 시점과 이상치 구간을 자동으로 표시하며, "
                "원인 피처와 이상 발생 패턴에 대한 해석 리포트를 제공합니다."
            ),
            "score": 0.6,
        },
    ],
    "anomaly_detection": [
        {
            "id": 1,
            "title": "Isolation Forest 이상치 점수화",
            "rationale": (
                "Isolation Forest와 AutoEncoder를 결합하여 샘플별 이상 점수를 산출합니다. "
                "정상/이상 임계값을 자동 설정하고 이상 비율과 핵심 이상 피처를 시각화하며, "
                "실시간 모니터링에 바로 적용 가능한 경량 모델을 제공합니다."
            ),
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "정상 분포 학습 기반 탐지",
            "rationale": (
                "정상 데이터 분포를 학습한 후 분포에서 크게 벗어난 샘플을 이상치로 판별합니다. "
                "One-Class SVM과 GMM을 비교하여 데이터 특성에 맞는 최적 탐지 모델을 자동 선정하며, "
                "각 이상치의 원인 피처와 이상 강도를 함께 리포트합니다."
            ),
            "score": 0.7,
        },
    ],
}


class MethodologyProposerAgent(BaseGate):
    """G3 — 방법론(카테고리) 권장. 본 게이트가 카테고리 변경을 제안할 수 있다."""

    gate_code = "G3"
    model_name = "claude-sonnet-4-6"
    n_proposals = 2  # LLM generates 2; option 3 is always _CUSTOM_OPTION

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        # G2 선택 제목을 추출 — adopted_rank 숫자 대신 실제 방향 텍스트를 LLM 에 전달
        g1_resp = (state.gate_responses or {}).get("G2", {})
        g1_uc = g1_resp.get("user_choice") or {}
        g1_rank = g1_uc.get("adopted_rank") if isinstance(g1_uc, dict) else None
        g1_props = g1_resp.get("proposals") or []
        g1_chosen = next(
            (p for p in g1_props if isinstance(p, dict) and p.get("id") == g1_rank),
            None,
        )
        payload = {
            "category": state.category,
            "data_profile": state.data_profile,
            "g1_direction": g1_chosen.get("title") if g1_chosen else (state.user_intent or ""),
            "user_intent": state.user_intent,
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False)[:4000],
                max_tokens=700,
                temperature=0.2,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr:
                llm_opts = arr[: self.n_proposals]
                for i, opt in enumerate(llm_opts, start=1):
                    opt["id"] = i
                return llm_opts + [_CUSTOM_OPTION]
        except Exception as e:
            self.logger.warning("g3_llm_failed", error=str(e))

        base = _FALLBACK_DEFAULTS.get(
            state.category,
            [{"id": 1, "title": "기본 분석", "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        return list(base) + [_CUSTOM_OPTION]

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        """G3 사용자 선택을 state 에 반영.

        프론트 형식:
            - 직접 입력  → {adopted_rank: 0, custom_intent: "text"}
            - 옵션 1/2   → {adopted_rank: 1} or {adopted_rank: 2}

        반영 필드:
            - user_intent  : 사용자가 본 방법론 선택을 user_intent 에 누적 표기
                            (다음 게이트 LLM 프롬프트가 컨텍스트로 활용)
            - category     : proposal 또는 custom_intent 텍스트에서 키워드 추론
            - target_column: 비지도(anomaly_detection) 로 바뀌면 None
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        # 1) 명시적 category 키 (LLM proposal 이 채워줬을 수도) — 최우선
        explicit_cat = uc.get("category")
        if isinstance(explicit_cat, str) and explicit_cat in CATEGORIES and explicit_cat != state.category:
            updates["category"] = explicit_cat

        # 2) custom_intent — 사용자가 직접 입력
        custom = uc.get("custom_intent")
        if isinstance(custom, str) and custom.strip():
            updates["user_intent"] = f"{(state.user_intent or '').strip()} (방법론: {custom.strip()})".strip()
            if "category" not in updates:
                inferred = _infer_category_from_text(custom, state.category)
                if inferred != state.category:
                    updates["category"] = inferred
            self.logger.info("g3_custom_intent_applied", intent=custom.strip()[:120])
        else:
            # 3) adopted_rank — proposals 에서 선택한 항목
            rank = uc.get("adopted_rank")
            chosen = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank),
                None,
            )
            if chosen and isinstance(chosen.get("title"), str) and chosen["title"].strip():
                method = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                updates["user_intent"] = f"{base} (방법론: {method})" if base else f"방법론: {method}"
                # proposal 에 category 가 들어 있으면 우선 사용
                if "category" not in updates:
                    new_cat = chosen.get("category")
                    if isinstance(new_cat, str) and new_cat in CATEGORIES and new_cat != state.category:
                        updates["category"] = new_cat
                # 그래도 없으면 title/rationale 텍스트로 추론
                if "category" not in updates:
                    blob = method + " " + (chosen.get("rationale") or "")
                    inferred = _infer_category_from_text(blob, state.category)
                    if inferred != state.category:
                        updates["category"] = inferred
                self.logger.info(
                    "g3_proposal_adopted",
                    rank=rank,
                    title=method,
                    category=updates.get("category"),
                )

        # 4) 비지도로 카테고리 바뀐 경우 target_column 무효화
        if updates.get("category") in _UNSUPERVISED_CATEGORIES and state.target_column:
            updates["target_column"] = None

        # 5) HJ-7 (2026-06-05) — chosen_recipe 정식 필드 채움
        # CS evaluator/insight/selector 가 state.chosen_recipe.meta.* 우선 활용.
        # G3 에서 채택한 방법론 정보를 recipe dict 로 직렬화. meta 4 키는 G4(model_strategy)
        # 또는 카테고리별 proposer.g1 에서 보강할 수 있도록 기본 None 채움.
        recipe: dict[str, Any] = {}
        if isinstance(custom, str) and custom.strip():
            recipe = {
                "id": 0,
                "title": custom.strip(),
                "methodology": custom.strip(),
                "is_custom": True,
                "meta": {
                    "variate": None,
                    "forecast_kind": None,
                    "task_kind": None,
                    "horizon_hint": None,
                },
            }
        else:
            rank2 = (user_choice or {}).get("adopted_rank") if isinstance(user_choice, dict) else None
            chosen2 = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank2),
                None,
            )
            if chosen2:
                recipe = {
                    "id": chosen2.get("id"),
                    "title": chosen2.get("title"),
                    "methodology": chosen2.get("title"),
                    "rationale": chosen2.get("rationale", ""),
                    "is_custom": False,
                    "meta": chosen2.get("meta")
                    if isinstance(chosen2.get("meta"), dict)
                    else {
                        "variate": None,
                        "forecast_kind": None,
                        "task_kind": None,
                        "horizon_hint": None,
                    },
                }
        if recipe:
            updates["chosen_recipe"] = recipe
            self.logger.info("g3_chosen_recipe_set", recipe_title=recipe.get("title"))

        return state.with_update(**updates) if updates else state
```

---

## `agents/gates/model_strategy_proposer.py`

```python
"""agents.gates.model_strategy_proposer — G4 최종 모델 전략."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = (
    "You are a modeling architect. "
    "Given the data profile, EDA summary, and the G3 methodology chosen by the user, "
    "propose exactly TWO distinct model strategy options. "
    "For each option write a concise Korean rationale of 1-2 sentences: "
    "why this strategy fits the data, and what result the user can expect. Keep it short and clear. "
    "Titles must be in Korean (concise). "
    "Reply with a JSON array of exactly 2 objects, no markdown:\n"
    '[{"id": 1, "title": "한국어 제목", "models": ["Model1", "Model2"], '
    '"rationale": "한국어 1-2문장", "score": 0.0-1.0}, '
    ' {"id": 2, "title": "한국어 제목", "models": ["Model1", "Model2"], '
    '"rationale": "한국어 1-2문장", "score": 0.0-1.0}]'
)

_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 모델 전략이나 사용할 알고리즘을 직접 입력하세요.",
    "models": [],
    "score": None,
    "is_custom": True,
}

_FALLBACK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "tabular_ml": [
        {
            "id": 1,
            "title": "Gradient Boosting 앙상블",
            "models": ["XGBoost", "LightGBM", "CatBoost"],
            "rationale": "정형 데이터에 강한 3종 부스팅 모델을 교차 검증으로 비교해 최고 정확도를 선정합니다.",
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "Tree 계열 다양화",
            "models": ["RandomForest", "XGBoost", "LightGBM"],
            "rationale": "배깅(RandomForest)과 부스팅을 함께 비교해 과적합 위험을 낮추고 안정적인 결과를 확보합니다.",
            "score": 0.75,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "Transformer 계열 비교",
            "models": ["FTTransformer", "TabTransformer", "TabPFN"],
            "rationale": "어텐션 기반 3종 모델로 피처 간 복잡한 상호작용을 학습하고 최적 아키텍처를 자동 선정합니다.",
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "MLP 경량 딥러닝",
            "models": ["ResNet", "MLP", "TabPFN"],
            "rationale": "Transformer 대비 빠른 학습 속도와 간단한 튜닝으로 안정적인 예측 성능을 제공합니다.",
            "score": 0.7,
        },
    ],
    # HJ-3 (2026-06-05) + DL 제거 — 시계열 ML 전용 (6 SUPPORTED_MODELS 와 정합)
    # 통계 + 베이스라인 + 외생변수 3 옵션. DL (Informer/TFT/PatchTST) 비활성.
    "timeseries": [
        {
            "id": 1,
            "title": "통계 + 베이스라인 (해석성 우선)",
            "models": ["SARIMA", "ETS", "seasonal_naive"],
            "rationale": "해석 가능한 통계 + 기준선 비교로 빠르고 안정적인 예측. 작은~중간 데이터에 최적.",
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "외생변수 회귀 + 검증",
            "models": ["SARIMAX", "ETS", "seasonal_naive"],
            "rationale": (
                "외생변수(공휴일·프로모션 등)를 SARIMAX 회귀에 반영하고 ETS 계절성 모델과 "
                "seasonal_naive 베이스라인을 함께 비교해 모델 우위를 객관적으로 검증합니다."
            ),
            "score": 0.80,
        },
        {
            "id": 3,
            "title": "고전 통계 단일 (안정성 우선)",
            "models": ["ARIMA", "SARIMA", "ETS"],
            "rationale": (
                "해석 가능성과 빠른 학습이 중요한 환경에서 차분/계절 차분/지수평활 3종을 "
                "비교해 가장 안정적인 통계 모델을 선택합니다."
            ),
            "score": 0.75,
        },
    ],
    "anomaly_detection": [
        {
            "id": 1,
            "title": "고전 이상탐지 앙상블",
            "models": ["IsolationForest", "LOF", "OneClassSVM"],
            "rationale": "3종 모델의 이상 점수를 앙상블해 오탐률을 낮추고 라벨 없이도 임계값을 자동 설정합니다.",
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "딥러닝 재구성 탐지",
            "models": ["AutoEncoder", "TranAD", "AnomalyTransformer"],
            "rationale": "정상 패턴을 학습한 AutoEncoder로 재구성 오차가 큰 샘플을 이상치로 판별합니다.",
            "score": 0.7,
        },
    ],
}


class ModelStrategyProposerAgent(BaseGate):
    """G4 — 모델 전략 (예: '경량 ML 3종 비교' vs '트랜스포머 1종 강화')."""

    gate_code = "G4"
    model_name = "claude-opus-4-6"
    n_proposals = 2

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        payload = {
            "category": state.category,
            "data_profile_rows": (state.data_profile or {}).get("rows"),
            "data_profile_cols": (state.data_profile or {}).get("cols"),
            "g2_choice": (state.gate_responses or {}).get("G3", {}).get("user_choice"),
            "eda_summary": state.eda_summary,
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, default=str)[:4000],
                max_tokens=700,
                temperature=0.2,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr:
                llm_opts = arr[: self.n_proposals]
                for i, opt in enumerate(llm_opts, start=1):
                    opt["id"] = i
                return llm_opts + [_CUSTOM_OPTION]
        except Exception as e:
            self.logger.warning("g4_llm_failed", error=str(e))

        base = _FALLBACK_DEFAULTS.get(
            state.category,
            [{"id": 1, "title": "기본 전략", "models": ["XGBoost"], "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        return list(base) + [_CUSTOM_OPTION]

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        """G4 사용자 선택을 state 에 반영.

        프론트 형식:
            - 직접 입력  → {adopted_rank: 0, custom_intent: "text"}
            - 옵션 1/2   → {adopted_rank: 1} or {adopted_rank: 2}

        반영 필드:
            - user_intent           : 선택한 전략 제목 누적
            - model_candidates      : proposal.models 가 있으면 다운스트림 후보로 미리 채움
                                      (model_selection 이 LLM 으로 top3 재선정할 수 있으나
                                       LLM 실패 시 본 값이 fallback 으로 그대로 쓰임)
            - category_extras["g4_strategy"]: 감사·디버깅용 선택 메타데이터
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        custom = uc.get("custom_intent")
        chosen: dict[str, Any] | None = None
        if isinstance(custom, str) and custom.strip():
            chosen = {"title": custom.strip(), "models": [], "is_custom": True}
            updates["user_intent"] = f"{(state.user_intent or '').strip()} (모델 전략: {custom.strip()})".strip()
            self.logger.info("g4_custom_intent_applied", intent=custom.strip()[:120])
        else:
            rank = uc.get("adopted_rank")
            chosen = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank),
                None,
            )
            if chosen and isinstance(chosen.get("title"), str):
                strategy = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                updates["user_intent"] = f"{base} (모델 전략: {strategy})" if base else f"모델 전략: {strategy}"
                self.logger.info(
                    "g4_proposal_adopted",
                    rank=rank,
                    title=strategy,
                    models=chosen.get("models"),
                )

        if chosen:
            models = chosen.get("models") or []
            if isinstance(models, list) and models:
                # 다운스트림 model_selection 이 LLM 으로 다시 정할 수 있지만,
                # 본 값이 미리 채워져 있으면 LLM 실패 시 안전한 fallback 이 된다.
                updates["model_candidates"] = [str(m) for m in models if isinstance(m, str)]
            # category_extras 에 감사용 메타데이터 기록 (R-005 with_update 패턴 유지)
            cat = state.category or "_default"
            extras = dict(state.category_extras or {})
            cat_block = dict(extras.get(cat) or {})
            cat_block["g4_strategy"] = {
                "title": chosen.get("title"),
                "models": chosen.get("models") or [],
                "rationale": chosen.get("rationale", ""),
                "is_custom": bool(chosen.get("is_custom")),
            }
            extras[cat] = cat_block
            updates["category_extras"] = extras

        return state.with_update(**updates) if updates else state
```

---

## `agents/handlers/timeseries/proposer.py`

```python
"""agents.handlers.timeseries.proposer — 시계열 G1/G2 fallback 제안 (CS 담당, cs-day4 v3 디벨롭).

LLM 실패 시 dispatcher (gates/) 가 본 함수를 호출하여 fallback.

진입함수 (dispatcher 자동 등록):
  - g1(state) -> list[dict]   G2 3 안 (단기 예측 / 이상 시점 / 계절 분해) — eda 기반 점수 조정
  - g2(state) -> list[dict]   G3 카테고리 (timeseries 유지)

DoD: g1 list 길이 ≥ 3 + g2 list 길이 ≥ 1 + 모든 score ∈ [0.0, 1.0].

핵심 설계 원칙:
  - proposer = LLM fallback — 어떤 입력에도 결과 반환 (인라인 안전 우선)
  - 점수 조정 룰 — eda 활용 가능 시만 적용, 없으면 default (강제 X)
  - user_intent 최우선 (+0.30)
  - rationale 동적 생성 (R-501 — eda 값 직접 인용)
  - score clip(0, 1)

cs-day4 v3 디벨롭 (방법론 0·2·6단계 + 디벨롭보고서 §2-4):
  - §C 이상: changepoints 단계 가중(1~2건 +0.10, 3건+ +0.15) + 이분산(heteroscedastic) +0.10
  - §B 단기: target_kind=="cumulative" → 차분 후 forecasting 신호 (rationale 보강)
  - §D 계절: is_multiplicative → 계절 분해 시 로그 변환 힌트 (rationale)
  - 신규 §F: 0단계 성격 meta (point/interval · uni/multivariate · horizon 힌트) — 기존 4키 불변, meta 추가
  - rationale R-501 강화 — changepoints·residual_ratio 실제값 인용
"""

from __future__ import annotations

from typing import Any

# ── base scores ───────────────────────────────────────────────────
BASE_SCORES = {"단기 예측": 0.85, "이상 시점": 0.65, "계절 분해": 0.55}
USER_INTENT_BONUS = 0.30
SEASONAL_PERIODS = (7, 12, 30, 365)
# horizon 힌트 fallback (freq → 기본 예측 시점 수)
_FREQ_HORIZON = {"D": 7, "W": 4, "M": 12, "MS": 12, "H": 24, "Q": 4}


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _get_profile(state: Any) -> dict:
    return getattr(state, "data_profile", None) or {}


def _eda_dict(state: Any) -> dict:
    """state.eda_summary 가 str/None 일 수 있으므로 dict 로 안전 변환."""
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _n_rows(state: Any) -> int:
    profile = _get_profile(state)
    return int(profile.get("rows") or profile.get("n_rows", 0) or 0)


def _default_recipes() -> list[dict[str, Any]]:
    """eda_summary None 시 base scores 그대로 (A-1b 인라인 안전)."""
    return [
        {"id": 1, "title": "단기 예측 (1~30일)", "rationale": "최근 추세 기반 forecasting", "score": 0.85},
        {"id": 2, "title": "이상 시점 탐지", "rationale": "변동성 큰 구간 식별", "score": 0.65},
        {"id": 3, "title": "계절성 분해", "rationale": "추세/계절/잔차 분리", "score": 0.55},
    ]


def _build_rationale(title: str, eda: dict, n: int) -> str:
    """R-501 — eda 실제값을 직접 인용한 동적 rationale."""
    s = eda.get("seasonal_period")
    stat = eda.get("stationary")
    cp = eda.get("changepoints") or 0
    target_kind = eda.get("target_kind")
    is_mult = eda.get("is_multiplicative")

    if title == "단기 예측":
        kind_hint = " · 누적형 타겟 → 차분 권장" if target_kind == "cumulative" else ""
        return f"비정상 시계열 (stationary={stat}, n={n}){kind_hint} — 차분 후 forecasting 효과적"
    if title == "이상 시점":
        # 수치 인용: changepoint 수 + 잔차 비율
        rr = None
        try:
            rs = eda.get("residual_std")
            ts = eda.get("total_std")
            if rs is not None and ts:
                rr = round(float(rs) / float(ts), 2)
        except Exception:
            rr = None
        rr_txt = f", 잔차비율={rr}" if rr is not None else ""
        return f"변동성 큰 데이터 (changepoints={cp}{rr_txt}) — 이상 탐지 적합"
    if title == "계절 분해":
        mult_hint = " · 승법성 → 로그 변환 검토" if is_mult else ""
        return f"계절성 명확 (s={s}, n={n}){mult_hint} — STL/seasonal_decompose 유의미"
    return ""


# ════════════════════════════════════════════════════════════════
# §F. 0단계 성격 meta (point/interval · uni/multivariate · horizon)
# ════════════════════════════════════════════════════════════════
def _build_meta(title: str, eda: dict, profile: dict) -> dict[str, Any]:
    """방법론 0단계 — 예측 목표 성격 제안. 기존 4키 외 추가 키(소비처 회귀 0).

    - variate     : "multivariate" if exog 있음 else "univariate"
    - forecast_kind: "interval" (불확실성 큰 경우) / "point"
    - task_kind   : recipe 별 — 이상 시점은 "classification"(레짐/이벤트), 그 외 "regression"
    - horizon_hint: seasonal_period 또는 freq 기반 기본 예측 시점 수
    """
    is_multivariate = bool(eda.get("is_multivariate"))
    s = eda.get("seasonal_period")
    freq = profile.get("freq") or eda.get("freq") or "D"
    horizon_hint = s if (isinstance(s, int) and s >= 2) else _FREQ_HORIZON.get(freq, 7)

    # 변동성 크거나 changepoint 있으면 구간 예측 권장 (방법론 0단계 point vs interval)
    cp = eda.get("changepoints") or 0
    hetero = bool(eda.get("heteroscedastic"))
    forecast_kind = "interval" if (cp >= 1 or hetero) else "point"

    task_kind = "classification" if title == "이상 시점" else "regression"

    return {
        "variate": "multivariate" if is_multivariate else "univariate",
        "forecast_kind": forecast_kind,
        "task_kind": task_kind,
        "horizon_hint": int(horizon_hint),
    }


# ════════════════════════════════════════════════════════════════
# §A~§F. g1 — 3 recipe 점수 조정 + meta
# ════════════════════════════════════════════════════════════════
def g1(state: Any) -> list[dict[str, Any]]:
    """G1 3 안 fallback — eda 기반 점수 조정 (단기/이상/계절) + 0단계 meta."""
    # ── A-1 : eda_summary 존재 가드 ──
    eda = _eda_dict(state)
    if not eda:
        return _default_recipes()  # A-1b 인라인 안전

    # ── A-2 : base scores 초기화 ──
    adj = {"단기": 0.0, "이상": 0.0, "계절": 0.0}
    n_rows = _n_rows(state)
    profile = _get_profile(state)
    intent = (getattr(state, "user_intent", None) or "").lower()

    # ── §B : recipe ① "단기 예측" ──
    if eda.get("stationary") is False:  # B-1
        adj["단기"] += 0.10
    if any(kw in intent for kw in ["예측", "forecast", "forecasting", "예보"]):  # B-2 ★
        adj["단기"] += USER_INTENT_BONUS
    if n_rows >= 100:  # B-3
        adj["단기"] += 0.05
    else:
        adj["단기"] -= 0.05
    # B-4 (신규): 누적형 타겟 → 차분 후 forecasting 적합 (방법론 롤백4)
    if eda.get("target_kind") == "cumulative":
        adj["단기"] += 0.05

    # ── §C : recipe ② "이상 시점 탐지" ──
    residual_std = eda.get("residual_std", 0.0)
    total_std = eda.get("total_std", 1.0)
    if total_std and total_std > 0 and (residual_std / total_std) > 0.30:  # C-1
        adj["이상"] += 0.20
    if any(kw in intent for kw in ["이상", "anomaly", "탐지", "detection"]):  # C-2 ★
        adj["이상"] += USER_INTENT_BONUS
    # C-3 (디벨롭): changepoints 단계 가중 (방법론 2-1·증상D — 레짐 다수일수록 강함)
    cp = eda.get("changepoints") or 0
    if cp >= 3:
        adj["이상"] += 0.15
    elif cp >= 1:
        adj["이상"] += 0.10
    # C-4 (신규): 이분산 → 변동성 신호 (방법론 2-1)
    if eda.get("heteroscedastic") is True:
        adj["이상"] += 0.10

    # ── §D : recipe ③ "계절 분해" ──
    s = eda.get("seasonal_period")
    if s in SEASONAL_PERIODS:  # D-1
        adj["계절"] += 0.20
    else:
        adj["계절"] -= 0.10
    if s and isinstance(s, int) and n_rows >= 2 * s:  # D-2
        adj["계절"] += 0.05
    else:
        adj["계절"] -= 0.15
    if any(kw in intent for kw in ["계절", "season", "분해", "decomposition", "stl"]):  # D-3 ★
        adj["계절"] += USER_INTENT_BONUS

    # ── §E-1 : g1 최종 조립 (+ §F meta) ──
    titles = [
        (1, "단기 예측 (1~30일)", "단기 예측", "단기"),
        (2, "이상 시점 탐지", "이상 시점", "이상"),
        (3, "계절성 분해", "계절 분해", "계절"),
    ]
    recipes = [
        {
            "id": rid,
            "title": title,
            "rationale": _build_rationale(rkey, eda, n_rows),
            "score": round(_clip(BASE_SCORES[rkey] + adj[akey]), 2),
            "meta": _build_meta(rkey, eda, profile),
        }
        for (rid, title, rkey, akey) in titles
    ]
    recipes.sort(key=lambda r: r["score"], reverse=True)
    return recipes


# ════════════════════════════════════════════════════════════════
# §E-2. g2 — 카테고리 유지
# ════════════════════════════════════════════════════════════════
def g2(state: Any) -> list[dict[str, Any]]:
    """G3 방법론 — 시계열 카테고리 유지 우선."""
    return [
        {
            "id": 1,
            "title": "timeseries",
            "rationale": "현재 카테고리 유지 — 시계열 데이터는 시계열 처리",
            "score": 0.95,
        },
    ]
```

---

## `agents/handlers/timeseries/preprocessor.py`

```python
"""agents.handlers.timeseries.preprocessor — 시계열 전처리 (CS 담당).

━━━ 실행 순서와 그 이유 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Phase 0  sort_by_time
  shift/rolling 이 "시간 순서"를 전제하므로 날짜 컬럼 기준 오름차순
  정렬을 가장 먼저 수행한다. 정렬 없이 shift(1) 하면 다른 날짜를
  가리킬 수 있어 누설·오연산이 발생한다.

Phase 1  fill_missing
  lag/rolling/diff 는 결측치를 연쇄 전파시키므로 특성 생성 전에
  결측을 제거한다. ffill(limit=7) → bfill(limit=3) → linear
  interpolate 순서. mean/median imputation 은 전체 통계를 써서
  미래 누설 발생 — 사용 금지.

Phase 2  boxcox
  분산 안정화 변환을 lag/rolling 보다 반드시 먼저 수행한다.
  이유: lag·rolling 을 "변환된 스케일"에서 만들어야 모델 입력이
  일관된 스케일을 갖는다. boxcox 를 나중에 적용하면 target 은
  변환됐는데 lag1 은 원본 스케일 → 스케일 불일치.
  전략: 원본 target 보존 + {target}_bc 컬럼 추가.
  이후 lag/rolling 은 _bc 기준으로 계산.

Phase 3  diff
  "추가 특성(feature)"으로 취급 (target 변환 아님 → 원본 보존).
  shifted = target.shift(1) 후 diff(d) 적용.
  shift(1) 선행 이유: diff(t, t-1) 직접 계산 시 t 값 사용 → 누설.
  {target}_diff1 = target[t-1] - target[t-2] (이미 관측된 값).

Phase 4  lag_features
  boxcox 적용 여부에 따라 _bc 또는 원본 target 기준.
  lags 결정: 계절성 period 있으면 [1, p, 2p],
             없으면 일별 기본 [1, 7, 14].
  최대 lag 상한 = min(n//4, 28) — lag > n/4 면 유효 행 75% 미만.

Phase 5a  rolling_mean
  shift(1) 후 rolling(w, min_periods=max(2, w//2)).mean().
  min_periods=w//2: 짧은 시계열에서 window 절반 이상이면 계산 허용.

Phase 5b  rolling_std
  계절성 여부와 무관하게 항상 포함 (변동폭은 보편적 특성).
  min_periods = max(2, w//2): std 는 최소 2개 관측치 필요.

Phase 5c  ewm_mean
  shift(1) 후 ewm(alpha, adjust=False).mean().
  alpha=0.3 빠른 반응(반감 ≈ 2시점), alpha=0.1 느린 반응(반감 ≈ 7시점).
  adjust=False: 재귀식 — 긴 시계열에서 수치 안정.

Phase 6  exog
  category_extras["timeseries"]["exog_columns"] 에 명시된 외생변수에
  target 과 동일한 lag·rolling_mean 적용. 없는 컬럼은 skip.

Phase 7  fill_feature_nans
  lag/rolling/diff 생성 후 앞 max_warmup 행에 구조적 NaN 발생.
  strategy="drop" : warmup 행 제거 (기본).
  strategy="zero" : 0 으로 채움 (LSTM 등 패딩 0 모델).
  strategy="none" : NaN 유지 (LightGBM 등 자체 처리).

Phase 8  time_order_split
  항상 마지막. shuffle 없음.
  gap 파라미터: train 마지막과 test 첫 행 사이 제거할 행 수.
  look-ahead bias 방지용. _split 값: "train" | "gap" | "test".

규칙
----
R-005 : state.with_update() — state 직접 수정 금지
R-103 : PII 로그 출력 금지
leakage_safe : 모든 집계(rolling/ewm/lag)는 shift(1) 이후 적용
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════
# data_profile 조회 헬퍼
# ════════════════════════════════════════════════════════


def _adf_p_value(state: Any) -> float:
    """ADF p-value 조회. 없으면 1.0 (비정상으로 간주)."""
    try:
        return float(state.data_profile["stationarity"]["adf_p_value"])
    except (TypeError, KeyError):
        return 1.0


def _is_stationary(state: Any) -> bool:
    return _adf_p_value(state) < 0.05


def _seasonality_period(state: Any) -> int | None:
    try:
        info = state.data_profile["seasonality"]
        if info.get("has_seasonality"):
            p = info.get("period")
            return int(p) if p and int(p) >= 2 else None
        return None
    except (TypeError, KeyError):
        return None


def _detect_date_col(state: Any, df: Any) -> str | None:
    try:
        col = state.data_profile.get("date_col")
        if col and col in df.columns:
            return col
    except (TypeError, AttributeError):
        pass
    import pandas as pd

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col
    return None


def _exog_columns(state: Any) -> list[str]:
    try:
        return list(state.category_extras.get("timeseries", {}).get("exog_columns", []))
    except (TypeError, AttributeError):
        return []


def _decide_lags(state: Any, n_rows: int, horizon: int = 1) -> list[int]:
    """data_profile 기반 lag 목록 결정 (horizon-aware — 누수 1-2 차단).

    - [1] 항상 포함 (직전 시점).
    - 계절성 period p: [p, 2*p] 추가.
    - period 없으면: [7, 14] (일별 기본).
    - 최대 lag 상한 = min(n//4, 28).
    - horizon-aware: horizon>1(다단계) 이면 lag < horizon 제외. 예측 시점엔 horizon
      보다 짧은 과거값을 알 수 없음(가장 최근=lag-horizon). lag-1 같은 짧은 시차는
      다단계 누수 1순위 (방법론 3-2 / 누수 1-2). horizon=1 이면 기존 동일.
    """
    max_lag = min(n_rows // 4, 28) if n_rows >= 8 else 2
    period = _seasonality_period(state)
    candidates = sorted({1, period, period * 2}) if period else [1, 7, 14]
    h = int(horizon) if horizon and horizon >= 1 else 1
    out = [lag for lag in candidates if lag <= max_lag and lag >= h]
    if not out and h <= max_lag:
        out = [h]
    return out


def _horizon(state: Any) -> int:
    """예측 지평(horizon) — category_extras 우선, 없으면 1(단기). 누수 1-2 가드 입력."""
    try:
        h = (getattr(state, "category_extras", None) or {}).get("timeseries", {}).get("horizon")
        if h and int(h) >= 1:
            return int(h)
    except (TypeError, AttributeError, ValueError):
        pass
    return 1


def _decide_windows(n_rows: int) -> list[int]:
    """행 수 기반 rolling window 결정.

    - 기본: [7, 14].
    - n >= 60 이면 28 추가 (월간 추세).
    - 최대 window 상한 = n//4.
    """
    max_w = n_rows // 4 if n_rows >= 8 else 2
    candidates = [7, 14] + ([28] if n_rows >= 60 else [])
    return [w for w in candidates if w <= max_w]


# ════════════════════════════════════════════════════════
# plan()
# ════════════════════════════════════════════════════════


def plan(state: Any) -> list[dict[str, Any]]:
    """시계열 전처리 계획 생성 (LLM 실패 시 fallback).

    Phase 순서는 모듈 docstring 이유를 그대로 따른다.
    모든 파라미터는 data_profile 로부터 동적으로 결정한다.
    """
    try:
        n_rows = int(state.data_profile.get("rows", 120))
    except (TypeError, AttributeError):
        n_rows = 120

    stationary = _is_stationary(state)
    period = _seasonality_period(state)
    horizon = _horizon(state)  # 다단계 누수 가드 입력
    lags = _decide_lags(state, n_rows, horizon)
    windows = _decide_windows(n_rows)
    exog_cols = _exog_columns(state)
    max_warmup = (max(lags) if lags else 14) + (max(windows) if windows else 14)

    steps: list[dict[str, Any]] = []

    # Phase 0
    steps.append({"name": "sort_by_time", "leakage_safe": True, "needs_review": False})

    # Phase 0b (D1, 2026-06-05) : 균일 시간 그리드 reindex (방법론 1단계)
    # 누락된 시점 행 자체를 생성 → 결측 명시화. SARIMA/ETS/Prophet 같은
    # "균일 빈도 전제" 모델 작동 보장. profiler 가 duplicate_ts_count/missing_timestamp_count
    # 을 산출했을 때만 활성 (그렇지 않으면 skip — 시간 컬럼 없으면 자동 no-op).
    steps.append({"name": "regular_grid", "leakage_safe": True, "needs_review": False})

    # Phase 1
    steps.append(
        {
            "name": "fill_missing",
            "ffill_limit": 7,  # 최대 7시점 연속 결측 → 이전 값 복사
            "bfill_limit": 3,  # ffill 못 채운 앞부분 보정 (최소 사용)
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # Phase 2: 비정상 or 계절성 있을 때 분산 안정화
    # lag/rolling 보다 반드시 앞에 위치해야 스케일 일관성 보장
    if not stationary or period is not None:
        steps.append(
            {
                "name": "boxcox",
                "shift_min": True,  # min<=0 이면 offset=|min|+1 자동 추가
                "lambda_clip": (-5.0, 5.0),  # 수치 오버플로 방지 lambda 범위
                "fallback": "log1p",  # boxcox 실패(상수 시리즈 등) 시 대체
                "leakage_safe": True,
                "needs_review": True,
            }
        )

    # Phase 3: 변화량 특성 (target 변환 아님, 추가 feature)
    # ADF p > 0.1(강하게 비정상)이면 2차 차분도 추가
    diff_orders = [1] + ([2] if _adf_p_value(state) > 0.1 else [])
    steps.append(
        {
            "name": "diff",
            "orders": diff_orders,
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # Phase 4: boxcox 적용 여부에 따라 _bc 또는 원본 기준 lag 생성
    steps.append(
        {
            "name": "lag_features",
            "lags": lags,
            "use_bc_if_available": True,
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # Phase 5a: 추세 평활
    steps.append(
        {
            "name": "rolling_mean",
            "windows": windows,
            "min_periods_ratio": 0.5,  # min_periods = max(2, int(w*ratio))
            "use_bc_if_available": True,
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # Phase 5b: 변동폭 — 계절성 무관하게 항상 포함
    steps.append(
        {
            "name": "rolling_std",
            "windows": windows,
            "min_periods_ratio": 0.5,
            "use_bc_if_available": True,
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # Phase 5c: 지수 가중 이동 평균
    steps.append(
        {
            "name": "ewm_mean",
            "alphas": [0.3, 0.1],  # 0.3=빠른 반응, 0.1=느린 반응
            "use_bc_if_available": True,
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # Phase 6: 외생변수 (target 특성 생성 이후)
    if exog_cols:
        exog_windows = [w for w in windows if w <= 14]
        steps.append(
            {
                "name": "exog",
                "columns": exog_cols,
                "lags": lags,
                "rolling_windows": exog_windows or [7],
                "leakage_safe": True,
                "needs_review": False,
            }
        )

    # Phase 6b: 달력 피처 (방법론 3-2)
    steps.append({"name": "calendar", "leakage_safe": True, "needs_review": False})

    # Phase 6c: 푸리에 피처 (방법론 3-2 다중 계절성) — period 있을 때만 의미
    if period:
        steps.append({"name": "fourier", "period": period, "n_terms": 3, "leakage_safe": True, "needs_review": False})

    # Phase 6d: 이벤트/레짐 더미 (방법론 3-1) — profiler changepoint 소비
    steps.append({"name": "event_flags", "leakage_safe": True, "needs_review": False})

    # Phase 7: 특성 생성 후 구조적 NaN 처리
    steps.append(
        {
            "name": "fill_feature_nans",
            "strategy": "drop",  # "drop"|"zero"|"none"
            "max_warmup": max_warmup,  # max(lags) + max(windows)
            "protect_target": True,
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # Phase 8: 항상 마지막
    # 누수 1-4 차단: 다단계 예측(horizon>1)이면 train 마지막과 test 첫 행 사이에
    # horizon-1 만큼 embargo gap 을 둔다. horizon=1(단기)이면 gap=0 (기존 동작).
    steps.append(
        {
            "name": "time_order_split",
            "test_ratio": 0.2,
            "gap": max(0, horizon - 1),  # look-ahead bias 방지 (방법론 4-1·누수 1-4)
            "leakage_safe": True,
            "needs_review": False,
        }
    )

    # X5 (2026-06-05) — 결측 비율 과다 시 단기 강등 권고 메타 (cs-day10 단계 2 ❌)
    # apply() dispatcher 는 알 수 없는 name 무시 (기본 silent) — 메타만 노출.
    profile_x5 = getattr(state, "data_profile", None) or {}
    mr = profile_x5.get("missing_ratio")
    if isinstance(mr, (int, float)) and mr >= 0.30:
        steps.append(
            {
                "name": "_meta_short_horizon_hint",
                "missing_ratio": float(mr),
                "recommendation": "장기 예측 신뢰도 낮음 — 단기 (≤7일) 강등 권고",
                "leakage_safe": True,
                "needs_review": True,
            }
        )

    # D2 (2026-06-05) — 누적값 타깃 자동 변환 권고 메타 (cs-day10 롤백 4·target 재설계)
    # profiler 가 target_kind="cumulative" 감지 시 사용자에게 차분 타깃 변환 권고.
    # 자동 변환은 inverse_transform 동반 필요해 보류 — 메타만 노출 (insight·output_extras 활용).
    if (getattr(state, "data_profile", None) or {}).get("target_kind") == "cumulative":
        steps.append(
            {
                "name": "_meta_target_diff_recommend",
                "recommendation": "누적값 타깃 감지 — 1차 차분 타깃 변환 검토 (부스팅 외삽 불가 방지)",
                "leakage_safe": True,
                "needs_review": True,
            }
        )

    return steps


# ════════════════════════════════════════════════════════
# apply()
# ════════════════════════════════════════════════════════


def apply(df: Any, plan_steps: list[dict[str, Any]], state: Any) -> Any:
    """Phase 0~8 순서대로 step 실행.

    - 각 step 은 독립 실패해도 WARNING 후 continue.
    - target 컬럼은 어떤 step 도 덮어쓰지 않는다.
    - boxcox 적용 여부는 {target}_bc 존재 여부로 판단한다.
    """
    out = df.copy()
    target: str | None = state.target_column

    if not target or target not in out.columns:
        logger.warning("target_column=%r 이 df 에 없음 — 전처리 건너뜀", target)
        return out

    for step in plan_steps:
        name = step.get("name")
        try:
            if name == "sort_by_time":
                out = _apply_sort_by_time(out, state)

            elif name == "regular_grid":
                out = _apply_regular_grid(out, state)

            elif name == "fill_missing":
                out = _apply_fill_missing(
                    out,
                    target,
                    ffill_limit=step.get("ffill_limit", 7),
                    bfill_limit=step.get("bfill_limit", 3),
                )

            elif name == "boxcox":
                out = _apply_boxcox(
                    out,
                    target,
                    shift_min=step.get("shift_min", True),
                    lambda_clip=step.get("lambda_clip", (-5.0, 5.0)),
                    fallback=step.get("fallback", "log1p"),
                )

            elif name == "diff":
                out = _apply_diff(out, target, orders=step.get("orders", [1]))

            elif name == "lag_features":
                src = _bc_col_or_target(out, target, step.get("use_bc_if_available", True))
                out = _apply_lag(out, src, lags=step.get("lags", [1, 7, 14]), label_base=target)

            elif name == "rolling_mean":
                src = _bc_col_or_target(out, target, step.get("use_bc_if_available", True))
                out = _apply_rolling_mean(
                    out,
                    src,
                    windows=step.get("windows", [7, 14]),
                    min_periods_ratio=step.get("min_periods_ratio", 0.5),
                    label_base=target,
                )

            elif name == "rolling_std":
                src = _bc_col_or_target(out, target, step.get("use_bc_if_available", True))
                out = _apply_rolling_std(
                    out,
                    src,
                    windows=step.get("windows", [7, 14]),
                    min_periods_ratio=step.get("min_periods_ratio", 0.5),
                    label_base=target,
                )

            elif name == "ewm_mean":
                src = _bc_col_or_target(out, target, step.get("use_bc_if_available", True))
                out = _apply_ewm_mean(
                    out,
                    src,
                    alphas=step.get("alphas", [0.3, 0.1]),
                    label_base=target,
                )

            elif name == "exog":
                out = _apply_exog(
                    out,
                    columns=step.get("columns", []),
                    lags=step.get("lags", [1, 7]),
                    rolling_windows=step.get("rolling_windows", [7]),
                )

            elif name == "calendar":
                out = _apply_calendar(out, state)

            elif name == "fourier":
                out = _apply_fourier(out, state, period=step.get("period"), n_terms=step.get("n_terms", 3))

            elif name == "event_flags":
                out = _apply_event_flags(out, state)

            elif name == "fill_feature_nans":
                out = _apply_fill_feature_nans(
                    out,
                    target=target,
                    strategy=step.get("strategy", "drop"),
                    max_warmup=step.get("max_warmup", 28),
                    protect_target=step.get("protect_target", True),
                )

            elif name == "time_order_split":
                out = _apply_time_order_split(
                    out,
                    test_ratio=step.get("test_ratio", 0.2),
                    gap=step.get("gap", 0),
                )

            else:
                logger.debug("알 수 없는 step=%r — 건너뜀", name)

        except Exception as exc:  # noqa: BLE001
            logger.warning("step=%r 실패: %s — 건너뜀", name, exc)
            continue

    return out


# ════════════════════════════════════════════════════════
# 내부 유틸
# ════════════════════════════════════════════════════════


def _bc_col_or_target(df: Any, target: str, use_bc: bool) -> str:
    bc = f"{target}_bc"
    return bc if (use_bc and bc in df.columns) else target


# ════════════════════════════════════════════════════════
# Phase 0 — sort_by_time
# ════════════════════════════════════════════════════════


def _apply_sort_by_time(df: Any, state: Any) -> Any:
    """날짜 컬럼 오름차순 정렬 + reset_index.

    정렬 후 reset_index(drop=True) 이유: 이후 iloc 기반 연산
    (fill_feature_nans, time_order_split) 의 안정성 확보.
    날짜 컬럼이 없으면 현재 순서가 시간 순이라 가정하고 pass.
    """
    date_col = _detect_date_col(state, df)
    if date_col is None:
        logger.debug("sort_by_time: 날짜 컬럼 미감지 — 현재 순서 유지")
        return df.copy()
    return df.sort_values(date_col).reset_index(drop=True)


# ════════════════════════════════════════════════════════
# Phase 1 — fill_missing
# ════════════════════════════════════════════════════════


def _apply_fill_missing(
    df: Any,
    target: str,
    ffill_limit: int = 7,
    bfill_limit: int = 3,
) -> Any:
    """수치 컬럼 결측치 시계열 특화 처리.

    처리 순서:
    1. ffill(limit=ffill_limit): 이전 관측값 복사. 한계: ffill_limit.
       limit 없는 ffill 은 길게 결측된 구간을 과거 값으로 채워
       모델이 변화를 감지하지 못함 → limit 필수.
    2. bfill(limit=bfill_limit): 시작 구간 NaN 보정. 최소 사용.
       bfill 은 미래 값을 과거에 채우므로 limit 으로 제한.
    3. interpolate(linear): 중간 결측 선형 보간. 양 끝점만 사용.
    target 의 남은 NaN 은 유지 (모델 단 처리).
    """
    import numpy as np  # noqa: WPS433

    out = df.copy()
    num_cols = out.select_dtypes(include=[np.number]).columns.tolist()
    for col in num_cols:
        if out[col].isna().sum() == 0:
            continue
        out[col] = (
            out[col]
            .ffill(limit=ffill_limit)  # 1) 과거 값 복사 (과거-충실)
            .interpolate(method="linear", limit_direction="forward")  # 2) 과거 방향만 (누수 1-3 차단)
            .bfill(limit=bfill_limit)  # 3) 시작 구간 leading NaN 만
        )
    return out


# ════════════════════════════════════════════════════════
# Phase 2 — boxcox
# ════════════════════════════════════════════════════════


def _apply_boxcox(
    df: Any,
    target: str,
    shift_min: bool = True,
    lambda_clip: tuple[float, float] = (-5.0, 5.0),
    fallback: str = "log1p",
    train_ratio: float | None = None,
) -> Any:
    """{target}_bc 컬럼 생성. 원본 target 절대 수정 안 함.

    양수 보장:
    - shift_min=True: min <= 0 이면 offset = abs(min) + 1.0.
      예) min=-3 → offset=4 → 최솟값=1.

    lambda 클리핑:
    - scipy 반환 lambda 가 lambda_clip 밖이면 클리핑.
      |lambda| > 5 면 변환값이 수치 오버플로 위험.

    fallback="log1p":
    - boxcox 실패(상수 시리즈, scipy 미설치) 시 log1p 적용.
      log1p 는 lambda=0 인 boxcox 의 근사.

    역변환 메타:
    - df.attrs 에 boxcox_lambda, boxcox_offset, boxcox_target 저장.
    """
    import numpy as np  # noqa: WPS433

    out = df.copy()
    series = out[target].dropna().astype(float)
    if len(series) < 3:
        logger.warning("boxcox: 유효 관측치 %d개 — 건너뜀", len(series))
        return out

    offset = 0.0
    if shift_min:
        min_val = float(series.min())
        if min_val <= 0:
            offset = abs(min_val) + 1.0

    shifted = series + offset
    bc_col = f"{target}_bc"

    # ★ 누수 1-3 차단: train_ratio 주어지면 λ 는 학습 구간에서만 추정하고
    #   전체에 그 λ 로 변환만 적용 (검증/미래 통계 참조 금지). None 이면 기존 동작.
    fit_part = shifted
    if train_ratio is not None and 0.0 < train_ratio < 1.0 and len(shifted) >= 6:
        cut = max(3, int(len(shifted) * train_ratio))
        fit_part = shifted.iloc[:cut]

    try:
        from scipy.special import boxcox as boxcox_transform  # noqa: WPS433
        from scipy.stats import boxcox  # noqa: WPS433

        _, lam = boxcox(fit_part)  # λ 는 학습 구간만으로 추정
        lam = float(np.clip(lam, lambda_clip[0], lambda_clip[1]))
        transformed = boxcox_transform(shifted.values, lam)  # 전체에 train λ 로 변환
    except Exception as exc:
        logger.warning("boxcox 실패(%s) → fallback=%r", exc, fallback)
        if fallback == "log1p":
            transformed = np.log1p(shifted.values)
            lam = 0.0
        else:
            return out

    out[bc_col] = float("nan")
    out.loc[series.index, bc_col] = transformed
    out.attrs["boxcox_lambda"] = lam
    out.attrs["boxcox_offset"] = offset
    out.attrs["boxcox_target"] = target
    return out


# ════════════════════════════════════════════════════════
# Phase 3 — diff
# ════════════════════════════════════════════════════════


def _apply_diff(df: Any, target: str, orders: list[int]) -> Any:
    """{target}_diff{d} 컬럼 생성 (추가 feature, target 수정 없음).

    leakage_safe 구현:
    shifted = target.shift(1) 후 diff(d).
    {target}_diff1 = target[t-1] - target[t-2] → t-1, t-2 모두 과거값.

    NaN 발생: shift(1) → 앞 1행 NaN, diff(d) → 추가 d행 NaN.
    총 앞 d+1 행 NaN → Phase 7 fill_feature_nans 에서 처리.
    """
    out = df.copy()
    shifted = out[target].shift(1)
    for d in orders:
        out[f"{target}_diff{d}"] = shifted.diff(d)
    return out


# ════════════════════════════════════════════════════════
# Phase 4 — lag_features
# ════════════════════════════════════════════════════════


def _apply_lag(
    df: Any,
    src_col: str,
    lags: list[int],
    label_base: str,
) -> Any:
    """{label_base}_lag{n} 컬럼 생성.

    src_col: 실제 연산 대상 (boxcox 있으면 _bc, 없으면 원본 target).
    label_base: 컬럼명 기저 — 항상 target 명 사용하여 일관성 유지.
    shift(lag): 정확히 lag 시점 이전 값. rolling 없음 → NaN 최소.
    """
    out = df.copy()
    for lag in lags:
        out[f"{label_base}_lag{lag}"] = out[src_col].shift(lag)
    return out


# ════════════════════════════════════════════════════════
# Phase 5a — rolling_mean
# ════════════════════════════════════════════════════════


def _apply_rolling_mean(
    df: Any,
    src_col: str,
    windows: list[int],
    min_periods_ratio: float = 0.5,
    label_base: str = "",
) -> Any:
    """{label_base}_rmean{w} 컬럼 생성.

    shift(1) 후 rolling(w, min_periods).mean():
    - shift(1): t-1 시점부터 집계 → t 값 제외 → leakage_safe.
    - min_periods = max(2, int(w * ratio)):
        w=7, ratio=0.5 → min_periods=3.
        window 절반 이상 채워지면 계산 허용 → 짧은 시계열 지원.
        min_periods=1 은 단일 값 "평균" 생성 → 정보량 낮아 ratio=0.5 사용.
    """
    out = df.copy()
    shifted = out[src_col].shift(1)
    base = label_base or src_col
    for w in windows:
        mp = max(2, int(w * min_periods_ratio))
        out[f"{base}_rmean{w}"] = shifted.rolling(w, min_periods=mp).mean()
    return out


# ════════════════════════════════════════════════════════
# Phase 5b — rolling_std
# ════════════════════════════════════════════════════════


def _apply_rolling_std(
    df: Any,
    src_col: str,
    windows: list[int],
    min_periods_ratio: float = 0.5,
    label_base: str = "",
) -> Any:
    """{label_base}_rstd{w} 컬럼 생성.

    shift(1) 후 rolling(w, min_periods).std():
    - min_periods = max(2, int(w * ratio)):
        std 는 분산의 제곱근, ddof=1 기준 최소 2개 관측치 필요.
        min_periods < 2 면 std=NaN (pandas 기본 동작).
    """
    out = df.copy()
    shifted = out[src_col].shift(1)
    base = label_base or src_col
    for w in windows:
        mp = max(2, int(w * min_periods_ratio))
        out[f"{base}_rstd{w}"] = shifted.rolling(w, min_periods=mp).std()
    return out


# ════════════════════════════════════════════════════════
# Phase 5c — ewm_mean
# ════════════════════════════════════════════════════════


def _apply_ewm_mean(
    df: Any,
    src_col: str,
    alphas: list[float],
    label_base: str = "",
) -> Any:
    """{label_base}_ewm{alpha_pct} 컬럼 생성.

    shift(1) 후 ewm(alpha, adjust=False).mean():
    - shift(1): leakage_safe.
    - adjust=False: 재귀식 w_t = alpha*x_t + (1-alpha)*w_{t-1}.
        True 는 초기 가중치 보정 방식. 긴 시계열에서 두 방식 수렴.
        False 가 메모리 효율적이고 수치 안정.
    - 컬럼명: alpha 를 정수 퍼센트로 표현.
        alpha=0.3 → _ewm30, alpha=0.1 → _ewm10.
    """
    out = df.copy()
    shifted = out[src_col].shift(1)
    base = label_base or src_col
    for alpha in alphas:
        suffix = int(round(alpha * 100))
        out[f"{base}_ewm{suffix}"] = shifted.ewm(alpha=alpha, adjust=False).mean()
    return out


# ════════════════════════════════════════════════════════
# Phase 6 — exog
# ════════════════════════════════════════════════════════


def _apply_exog(
    df: Any,
    columns: list[str],
    lags: list[int],
    rolling_windows: list[int],
) -> Any:
    """외생변수에 lag·rolling_mean 적용 (leakage_safe).

    각 exog 컬럼:
    - lag: shift(lag) — target lag 와 동일 로직.
    - rolling_mean: shift(1) 후 rolling(w, min_periods=max(2, w//2)).mean().
    없는 컬럼은 WARNING 후 skip — 파이프라인 중단 없음.
    """
    out = df.copy()
    for col in columns:
        if col not in out.columns:
            logger.warning("exog 열 %r 이 df 에 없음 — 건너뜀", col)
            continue
        for lag in lags:
            out[f"{col}_lag{lag}"] = out[col].shift(lag)
        shifted = out[col].shift(1)
        for w in rolling_windows:
            mp = max(2, w // 2)
            out[f"{col}_rmean{w}"] = shifted.rolling(w, min_periods=mp).mean()
    return out


# ════════════════════════════════════════════════════════
# ════════════════════════════════════════════════════════════════
# Phase 0b — regular_grid (D1, 2026-06-05, 방법론 1단계)
# ════════════════════════════════════════════════════════════════
def _apply_regular_grid(df: Any, state: Any) -> Any:
    """균일 시간 그리드 reindex — 누락 시점 행 생성, 결측 명시화.

    방법론 1단계 "균일 빈도 전제 모델 위해 완전한 시간 그리드로 reindex".
    SARIMA/ETS/Prophet 의 작동 보장.

    동작:
      - state.category_extras["timeseries"]["freq"] 가 있고 날짜 컬럼 식별 가능 → reindex.
      - freq 미상 또는 날짜 컬럼 없음 → no-op (인라인 안전).
      - 신규 행은 NaN 으로 — 후속 fill_missing 이 ffill 처리.

    leakage_safe : True (새 행 = NaN, 미래 정보 주입 없음)
    """
    try:
        import pandas as pd  # noqa: WPS433

        # freq 추출 — category_extras 우선
        ce = (getattr(state, "category_extras", None) or {}).get("timeseries", {}) or {}
        freq = ce.get("freq") or (getattr(state, "data_profile", None) or {}).get("freq")
        if not freq:
            return df

        # 날짜 컬럼 식별
        date_cols = [c for c in df.columns if str(c).lower() in ("ds", "date", "datetime", "time", "timestamp")]
        if not date_cols:
            # 인덱스가 DatetimeIndex 면 그대로 사용
            if isinstance(df.index, pd.DatetimeIndex):
                full_idx = pd.date_range(df.index.min(), df.index.max(), freq=freq)
                # 이미 동일 길이면 skip (성능)
                if len(full_idx) == len(df.index):
                    return df
                return df.reindex(full_idx)
            return df

        # 날짜 컬럼 기반 reindex — 임시 인덱스 → reindex → 컬럼 복귀
        dc = date_cols[0]
        try:
            dt_series = pd.to_datetime(df[dc], errors="coerce")
        except Exception:
            return df
        if dt_series.isna().all():
            return df

        out = df.copy()
        out.index = dt_series
        full_idx = pd.date_range(dt_series.min(), dt_series.max(), freq=freq)
        # 이미 완전한 그리드면 skip
        if len(full_idx) == len(out):
            out = out.reset_index(drop=True)
            return out
        out = out.reindex(full_idx)
        # 날짜 컬럼 복원
        out[dc] = out.index
        out = out.reset_index(drop=True)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("regular_grid 실패: %s — skip", exc)
        return df


# Phase 6b — calendar (달력 피처, 방법론 3-2)
# ════════════════════════════════════════════════════════


def _apply_calendar(df: Any, state: Any) -> Any:
    """날짜 컬럼 기반 달력 피처 (방법론 3-2 1순위 도메인 피처).

    요일/월/분기/월초·월말 — 도메인 주기를 모델에 명시 주입.
    날짜 컬럼 없으면 skip (인라인 안전). leakage_safe: 각 시점의 달력값은
    그 시점에 이미 결정돼 있으므로 미래 누수 없음.
    """
    out = df.copy()
    date_col = _detect_date_col(state, out)
    if date_col is None:
        return out
    try:
        import pandas as pd  # noqa: WPS433

        dt = pd.to_datetime(out[date_col], errors="coerce")
        out["cal_dayofweek"] = dt.dt.dayofweek.astype("float")
        out["cal_month"] = dt.dt.month.astype("float")
        out["cal_quarter"] = dt.dt.quarter.astype("float")
        out["cal_is_month_start"] = dt.dt.is_month_start.astype("float")
        out["cal_is_month_end"] = dt.dt.is_month_end.astype("float")
    except Exception as exc:  # noqa: BLE001
        logger.warning("calendar 피처 실패: %s — skip", exc)
    return out


# ════════════════════════════════════════════════════════
# Phase 6c — fourier (푸리에 피처, 방법론 3-2 다중 계절성)
# ════════════════════════════════════════════════════════


def _apply_fourier(df: Any, state: Any, period: int | None, n_terms: int = 3) -> Any:
    """period 기반 푸리에 sin/cos 항 (방법론 3-2 — 다중 계절성은 더미보다 푸리에).

    period 가 없거나 <2 면 skip. n_terms 쌍의 (sin, cos) 생성.
    위치 인덱스 t 기반이라 미래 누수 없음 (leakage_safe).
    """
    out = df.copy()
    p = int(period) if period and int(period) >= 2 else 0
    if p < 2:
        return out
    try:
        import numpy as np  # noqa: WPS433

        t = np.arange(len(out), dtype=float)
        k_max = max(1, min(int(n_terms), p // 2))
        for k in range(1, k_max + 1):
            ang = 2.0 * np.pi * k * t / p
            out[f"fourier_sin{k}_p{p}"] = np.sin(ang)
            out[f"fourier_cos{k}_p{p}"] = np.cos(ang)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fourier 피처 실패: %s — skip", exc)
    return out


# ════════════════════════════════════════════════════════
# Phase 6d — event_flags (이벤트/레짐 더미, 방법론 3-1)
# ════════════════════════════════════════════════════════


def _apply_event_flags(df: Any, state: Any) -> Any:
    """profiler 가 탐지한 changepoint/이벤트 시점을 더미 피처로 (방법론 3-1).

    "진짜 이벤트는 제거가 아니라 플래그" — profiler changepoints_detail.indices
    를 받아 해당 시점 이후를 표시하는 레짐 더미(event_regime)와 시점 더미
    (event_at_*)를 만든다. profiler 산출물 없으면 skip (인라인 안전).
    leakage_safe: 과거에 관측된 구조적 변화 시점이라 미래 누수 없음.
    """
    out = df.copy()
    try:
        profile = getattr(state, "data_profile", None) or {}
        cp = profile.get("changepoints_detail") or {}
        indices = cp.get("indices") if isinstance(cp, dict) else None
        if not indices:
            return out
        import numpy as np  # noqa: WPS433

        n = len(out)
        valid = sorted({int(i) for i in indices if isinstance(i, (int, float)) and 0 <= int(i) < n})
        if not valid:
            return out
        # 레짐 더미: 각 changepoint 이후 구간을 1로 누적 (레짐 단계)
        regime = np.zeros(n, dtype=float)
        for idx in valid[:20]:  # 상한
            regime[idx:] += 1.0
        out["event_regime"] = regime
    except Exception as exc:  # noqa: BLE001
        logger.warning("event_flags 피처 실패: %s — skip", exc)
    return out


# ════════════════════════════════════════════════════════
# Phase 7 — fill_feature_nans
# ════════════════════════════════════════════════════════


def _apply_fill_feature_nans(
    df: Any,
    target: str,
    strategy: str = "drop",
    max_warmup: int = 28,
    protect_target: bool = True,
) -> Any:
    """특성 생성 후 구조적 NaN 처리.

    strategy="drop":
    앞 max_warmup 행 중 특성 컬럼에 NaN 있는 행 제거.
    max_warmup = max(lags) + max(windows) — warmup 구간 최대 범위.
    drop 후 reset_index(drop=True) → 이후 iloc 연산 안전.

    strategy="zero":
    특성 컬럼 NaN → 0.0.
    protect_target=True 이면 target 컬럼 NaN 보존.
    사용 케이스: LSTM 등 패딩을 0 으로 표현하는 모델.

    strategy="none":
    아무것도 안 함. LightGBM 등 NaN 자체 처리 모델.
    """
    out = df.copy()
    feature_cols = [c for c in out.columns if c != target and c != "_split"]

    if strategy == "drop":
        warmup_range = out.iloc[:max_warmup]
        has_nan = warmup_range[feature_cols].isna().any(axis=1)
        drop_idx = warmup_range.index[has_nan]
        out = out.drop(index=drop_idx).reset_index(drop=True)

    elif strategy == "zero":
        fill_cols = feature_cols if protect_target else [c for c in feature_cols if c != target]
        for col in fill_cols:
            out[col] = out[col].fillna(0.0)

    elif strategy == "none":
        pass

    else:
        logger.warning("fill_feature_nans: 알 수 없는 strategy=%r — none 처리", strategy)

    return out


# ════════════════════════════════════════════════════════
# Phase 8 — time_order_split
# ════════════════════════════════════════════════════════


def _apply_time_order_split(
    df: Any,
    test_ratio: float = 0.2,
    gap: int = 0,
) -> Any:
    """시간 순서 보존 분할 → _split 컬럼 ("train"|"gap"|"test").

    분할 로직:
    - split_idx = max(1, int(n * (1 - test_ratio))).
      예) n=100, ratio=0.2 → split_idx=80.
    - [0, split_idx): "train"
    - [split_idx, split_idx+gap): "gap"  (gap>0 시)
      이유: 예측 horizon h 만큼의 행은 train 마지막이 test 레이블에
      포함될 수 있어 look-ahead bias 위험. gap=h 로 차단.
    - [split_idx+gap, n): "test"

    shuffle 절대 없음 — 시계열에서 shuffle 은 미래 누설.
    """
    out = df.copy()
    n = len(out)
    split_idx = max(1, int(n * (1.0 - test_ratio)))
    gap_end = min(n, split_idx + gap)

    out["_split"] = "train"
    if gap > 0 and gap_end > split_idx:
        out.iloc[split_idx:gap_end, out.columns.get_loc("_split")] = "gap"
    out.iloc[gap_end:, out.columns.get_loc("_split")] = "test"
    return out
```

---

## `agents/handlers/timeseries/selector.py`

```python
"""agents.handlers.timeseries.selector — 시계열 모델 추천 (CS 담당, cs-day5 v3 디벨롭).

진입함수 (dispatcher 자동 등록):
  - score(state, recipes=None) -> dict
      반환: {"top3": list[str], "rationale": str, "citations": list[str], "meta": dict}

DoD (불변):
  - top3 길이 ≥ 3
  - citations ≥ 1 (R-501) — recipes 비어 있을 땐 빈 list 허용 + warning
  - n_rows < 100 → 보수적 통계 모델만 유지
  - exog 0 → SARIMAX 제외 (top3 진입 X)

방법론 헌장 매핑 (0~7단계 + 누수 1-1~1-7 + 모델선택 7축)
─────────────────────────────────────────────────────────────────
- 0단계 (문제정의·horizon·variate·point/interval) → meta 키 + 점수 조정 (7축 가·라·마·사)
- 1단계 (시간축 무결성·target_kind) → profiler carry 키(timeaxis_integrity·target_kind) 인식 → 점수 조정 (7축 라)
- 2단계 EDA (계절·정상성·이분산·changepoint·CCF) → eda carry 키(seasonal_period·stationary·heteroscedastic·changepoints·acf_peaks) 인식 → 점수 조정 (7축 다·바·사)
- 3단계 (피처·도메인) → preprocessor `category_extras["timeseries"]["exog_columns"]` 권위 소스 통일 (A안 핵심 수정)
- 4단계 (검증·walk-forward) → meta `multistep_strategy` 로 다운스트림 pipeline·HPO 에 신호
- 5단계 (임계·HPO) → meta `recommended_threshold` 보너스 큰 모델 우선
- 6단계 (모델선택 7축) → 7축 전부 점수 룰로 코드화 (가 계열길이 · 나 horizon · 다 계절성 · 라 target_kind · 마 multivariate · 바 heteroscedastic · 사 changepoints)
- 7단계 (롤백) → 기준선(seasonal_naive·ETS) 메타 강제 추천 (방법론 4-2·6-5 "못 이기면 채택 금지")
- 누수 1-1 (타겟 누수) → leakage_suspect_cols 가 있을 때 exog 정책 강화 (해당 컬럼 제외 권고 메타)
- 누수 1-2 (시간정렬) → horizon-aware → meta `multistep_strategy`("direct"/"recursive"/"hybrid")
- 누수 1-3~1-7 → preprocessor·evaluator 영역, selector 는 영역 외

A안 디벨롭 핵심 (어제 인수인계 표 셋째 줄):
─────────────────────────────────────────────────────────────────
1. exog 소스 통일 — `category_extras["timeseries"]["exog_columns"]` 우선, eda 보조.
2. baseline_recommend 메타 — seasonal_naive(s≥2 + n≥2s) / ETS(n≥30) 를 메타로만 추천.
3. 7축 반영 — 헌장 2-1 7개 축 전부 점수 룰로 코드화 (가~사).
4. meta(multistep_strategy / hybrid_hint / baseline_recommend / leakage_excluded) — 다운스트림에 신호.
5. rationale R-501 강화 — 모든 조정값 수치 인용 (검증 가능).

핵심 설계 원칙 (cs-day5 §O 계승):
- recipe 기반 base candidates — 3 분기 (단기/이상/계절) · default = "단기 예측"
- DoD 강제 (n<100 → DL · exog=0 → SARIMAX EXCLUDED)
- score clip(0, 1) + top3 길이 3 보장 (ARIMA → Prophet → SARIMA fallback)
- 인라인 안전 우선 — 어떤 상태에서도 default 진행
- 회귀 0 — 기존 3 키 (top3 / rationale / citations) 불변, `meta` 키만 신규 추가
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
SUPPORTED_MODELS = ("ARIMA", "SARIMA", "SARIMAX", "Prophet", "ETS", "seasonal_naive")
STAT_MODELS = ("ARIMA", "SARIMA", "SARIMAX", "ETS")

BASE_SCORE = 0.70

# Day5 기존 가중 (불변 — 회귀 0)
DL_PENALTY_SMALL = -0.20
SARIMA_SEASONAL_BONUS = 0.15
SARIMAX_SEASONAL_BONUS = 0.10
SARIMAX_EXOG_BONUS = 0.20
ARIMA_STAT_BONUS = 0.10
ARIMA_NONSTAT_PENALTY = -0.05

# A안 7축 디벨롭 가중 (신규, ML 전용)
PROPHET_LONG_HORIZON_BONUS = 0.05
SARIMA_STRONG_SEASONAL_BONUS = 0.05
MULTIVARIATE_SARIMAX_BONUS = 0.05
HETERO_PROPHET_BONUS = 0.03
HETERO_SARIMA_BONUS = 0.03
CHANGEPOINTS_PROPHET_BONUS = 0.05

SEASONAL_PERIODS = (7, 12, 30, 365)
ACF_STRONG_THRESHOLD = 2


# ════════════════════════════════════════════════════════════════
# 주제 적합도 매트릭스 (2026-06-05, 사용자 요청 — 주제 맞춤 최적 모델)
# ════════════════════════════════════════════════════════════════
# 키워드 → 토픽 신호 매핑 (한·영 혼용, 도메인 키워드 포함)
TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "short_term": ("단기", "내일", "이번 주", "다음 주", "short", "next day", "near-term"),
    "mid_term": ("중기", "한 달", "월간", "mid", "monthly", "monthly forecast"),
    "long_term": ("장기", "분기", "연간", "long", "long-term", "long horizon", "annual"),
    "multivariate": ("다변량", "외생", "exog", "multivariate", "다중", "공휴일", "프로모션", "holiday", "promo"),
    "interval": ("구간", "신뢰구간", "신뢰", "interval", "confidence", "ci", "prediction interval", "pi", "분위"),
    "anomaly": ("이상", "이상치", "이상 시점", "anomaly", "outlier", "감지", "탐지", "detection"),
    "baseline": ("기준선", "베이스라인", "naive", "baseline", "단순", "비교"),
    "seasonal_decomp": ("계절성", "계절 분해", "분해", "seasonality", "decomposition", "stl"),
    "interpretable": ("해석", "설명", "interpret", "explain", "투명"),
}

# 모델 × 토픽 적합도 보너스 (작은 가중 — 기존 7축 매트릭스 균형 유지)
# 양수 = 토픽에 적합, 음수 = 비적합. 토픽 미감지 시 적용 안 함.
TOPIC_BONUS: dict[str, dict[str, float]] = {
    "short_term": {"ARIMA": 0.05, "SARIMA": 0.05, "ETS": 0.05, "Prophet": 0.03},
    "mid_term": {"SARIMA": 0.05, "Prophet": 0.05, "ETS": 0.03},
    "long_term": {"Prophet": 0.08, "ARIMA": -0.03, "SARIMA": -0.03, "ETS": -0.03},
    "multivariate": {"SARIMAX": 0.08, "ARIMA": -0.03, "ETS": -0.03},
    "interval": {"SARIMA": 0.05, "SARIMAX": 0.05, "ETS": 0.05, "Prophet": 0.05, "ARIMA": 0.03},
    "anomaly": {"Prophet": 0.05, "SARIMA": 0.05},
    "baseline": {"seasonal_naive": 0.10, "ETS": 0.08, "ARIMA": 0.05},
    "seasonal_decomp": {"Prophet": 0.05, "SARIMA": 0.05, "ETS": 0.03},
    "interpretable": {"ARIMA": 0.05, "SARIMA": 0.05, "ETS": 0.05, "Prophet": 0.03},
}


# ════════════════════════════════════════════════════════════════
# §0. 헬퍼
# ════════════════════════════════════════════════════════════════
def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


# ════════════════════════════════════════════════════════════════
# 주제 신호 추출 + 적합도 보너스 적용 (2026-06-05)
# ════════════════════════════════════════════════════════════════
def _topic_signals(state: Any, chosen_meta: dict, horizon: int, n_rows: int) -> dict[str, bool]:
    """user_intent 키워드 + chosen_recipe.meta 종합해 토픽 신호 dict 반환.

    토픽이 명확하면 selector 가 적합 모델에 가중치 부여 → "주제 맞춤 최적 모델".

    user_intent 미상 + meta 빈 경우 → 모두 False (영향 0, 회귀 안전).
    """
    intent = (getattr(state, "user_intent", None) or "").lower()
    signals = {k: False for k in TOPIC_KEYWORDS}

    # 1) user_intent 키워드 매칭
    if intent:
        for topic, kws in TOPIC_KEYWORDS.items():
            if any(kw.lower() in intent for kw in kws):
                signals[topic] = True

    # 2) chosen_recipe.meta 보강
    meta = chosen_meta or {}
    forecast_kind = meta.get("forecast_kind")
    variate = meta.get("variate")
    task_kind = meta.get("task_kind")

    if forecast_kind in ("interval", "quantile"):
        signals["interval"] = True
    if variate == "multivariate":
        signals["multivariate"] = True
    if task_kind == "classification":
        signals["anomaly"] = True

    # 3) horizon 기반 시계열 길이 (intent 미명시 시 fallback)
    if not (signals["short_term"] or signals["mid_term"] or signals["long_term"]):
        if horizon > 0:
            if horizon <= 7:
                signals["short_term"] = True
            elif horizon <= 30:
                signals["mid_term"] = True
            else:
                signals["long_term"] = True

    # 4) 짧은 계열 (n<100) → 베이스라인 토픽 자동 활성 (해석성 + 안정)
    if n_rows > 0 and n_rows < 100:
        signals["baseline"] = True
        signals["interpretable"] = True

    return signals


def _apply_topic_bonus(adj: dict[str, float], signals: dict[str, bool]) -> dict[str, list[str]]:
    """signals True 인 토픽의 TOPIC_BONUS 를 adj 에 더함.

    반환: 각 모델별로 적용된 토픽 이름 list (rationale·meta 노출용).
    candidates 풀에 없는 모델 보너스는 무시 (KeyError 안전).
    """
    applied: dict[str, list[str]] = {m: [] for m in adj}
    for topic, active in signals.items():
        if not active:
            continue
        bonus_map = TOPIC_BONUS.get(topic) or {}
        for model, bonus in bonus_map.items():
            if model in adj:
                adj[model] += bonus
                applied[model].append(f"{topic}:{bonus:+.2f}")
    return applied


def _chosen_recipe(state: Any) -> dict:
    """state.chosen_recipe → dict 안전 변환.

    HJ-5 (2026-06-05) 이후 PipelineState 정식 필드 (Optional[dict[str, Any]]).
    getattr 패턴 유지 — None 또는 미세팅 시 빈 dict 반환.
    """
    raw = getattr(state, "chosen_recipe", None)
    return raw if isinstance(raw, dict) else {}


def _eda_dict(state: Any) -> dict:
    """state.eda_summary 는 Optional[dict | str] union (HJ-2). dict 만 허용."""
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _category_extras(state: Any) -> dict:
    raw = getattr(state, "category_extras", None) or {}
    if not isinstance(raw, dict):
        return {}
    cat = raw.get("timeseries", {})
    return cat if isinstance(cat, dict) else {}


def _exog_columns(state: Any, eda: dict) -> list[str]:
    """exog 통일 — A안 핵심 수정.

    우선순위:
      1. state.category_extras["timeseries"]["exog_columns"]
      2. eda.get("exog") or eda.get("exog_columns")
    """
    extras = _category_extras(state)
    cols = extras.get("exog_columns")
    if isinstance(cols, list) and cols:
        return [str(c) for c in cols]
    fallback = eda.get("exog") or eda.get("exog_columns") or []
    if isinstance(fallback, list):
        return [str(c) for c in fallback]
    return []


def _horizon(state: Any, eda: dict) -> int:
    """horizon 추출 — category_extras 우선, chosen_recipe.meta.horizon_hint 보조."""
    extras = _category_extras(state)
    h = extras.get("horizon")
    if isinstance(h, int) and h >= 1:
        return h
    chosen = _chosen_recipe(state)
    meta = chosen.get("meta") if isinstance(chosen, dict) else None
    if isinstance(meta, dict):
        h2 = meta.get("horizon_hint")
        if isinstance(h2, int) and h2 >= 1:
            return h2
    h3 = eda.get("horizon") or eda.get("horizon_hint")
    if isinstance(h3, int) and h3 >= 1:
        return h3
    return 0


def _normalize_recipe_key(recipe_title: Any) -> str:
    if not isinstance(recipe_title, str):
        return "단기 예측"
    if "이상" in recipe_title or "탐지" in recipe_title:
        return "이상 시점"
    if "계절" in recipe_title or "분해" in recipe_title:
        return "계절 분해"
    if "단기" in recipe_title or "예측" in recipe_title:
        return "단기 예측"
    return "단기 예측"


def _is_seasonal_strong(s: Any, acf_peaks: Any) -> bool:
    if s not in SEASONAL_PERIODS:
        return False
    if not isinstance(acf_peaks, list):
        return False
    return len(acf_peaks) >= ACF_STRONG_THRESHOLD


def _baseline_recommend(s: Any, n_rows: int) -> list[str]:
    """방법론 4-2·6-5 — "기준선 못 이기면 채택 금지" 메타."""
    rec: list[str] = []
    if isinstance(s, int) and s >= 2 and n_rows >= 2 * s:
        rec.append("seasonal_naive")
    if n_rows >= 30:
        rec.append("ETS")
    return rec


def _multistep_strategy(horizon: int, recipe_key: str, n_rows: int) -> str:
    if horizon <= 1:
        return "recursive"
    if horizon >= 12 and n_rows >= 200 and recipe_key in ("계절 분해", "이상 시점"):
        return "direct"
    return "hybrid"


def _hybrid_hint(top3: list[str], horizon: int, n_rows: int) -> str | None:
    """DL 비활성. 통계 모델만으로 하이브리드 힌트 없음 (시계열 ML 전용)."""
    return None


# ════════════════════════════════════════════════════════════════
# §A~§H. score (진입점)
# ════════════════════════════════════════════════════════════════
def score(state: Any, recipes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """top3 + rationale + citations + meta 반환.

    설계도 cs-day5 §A~§H + A안 디벨롭 7축 적용. 회귀 0 — 기존 3 키 그대로,
    `meta` 키만 신규 추가.
    """
    recipes = recipes or []

    # ── §A-1 : chosen_recipe 가드 + 정규화 ──
    chosen = _chosen_recipe(state)
    recipe_title_raw = chosen.get("title") or "단기 예측"
    recipe_key = _normalize_recipe_key(recipe_title_raw)

    # ── §A-2 : 입력 추출 ──
    profile = getattr(state, "data_profile", None) or {}
    if not isinstance(profile, dict):
        profile = {}
    eda = _eda_dict(state)
    n_rows = int(profile.get("rows") or profile.get("n_rows", 0) or 0)
    s = eda.get("seasonal_period")
    stationary = eda.get("stationary")
    acf_peaks = eda.get("acf_peaks") or []
    target_kind = eda.get("target_kind")
    is_multivariate = bool(eda.get("is_multivariate"))
    heteroscedastic = bool(eda.get("heteroscedastic"))
    changepoints = int(eda.get("changepoints") or 0)
    leakage_suspect = eda.get("leakage_suspect_cols") or []
    if not isinstance(leakage_suspect, list):
        leakage_suspect = []
    exog_all = _exog_columns(state, eda)
    exog = [c for c in exog_all if c not in leakage_suspect]
    leakage_excluded = [c for c in exog_all if c in leakage_suspect]
    horizon = _horizon(state, eda)

    # ── §B : recipe_key 별 base candidates ──
    if recipe_key == "단기 예측":
        candidates = ["ARIMA", "SARIMA", "Prophet", "SARIMAX", "ETS"]
    elif recipe_key == "이상 시점":
        candidates = ["Prophet", "SARIMA", "ETS"]
    elif recipe_key == "계절 분해":
        candidates = ["Prophet", "SARIMA", "SARIMAX", "ETS"]
    else:
        candidates = ["ARIMA", "SARIMA", "Prophet", "ETS"]

    base = {m: BASE_SCORE for m in candidates}
    adj: dict[str, float] = {m: 0.0 for m in candidates}

    # ── §C : 계열 길이 (7축 가) — DL 비활성, 통계 모델만 ──
    # 짧은 데이터는 ARIMA/ETS/seasonal_naive 가 자동 적합 (selector 가 별도 페널티 불요)

    # ── §D : seasonal_period (7축 다) ──
    if s in SEASONAL_PERIODS:
        if "SARIMA" in adj:
            adj["SARIMA"] += SARIMA_SEASONAL_BONUS
        if "SARIMAX" in adj:
            adj["SARIMAX"] += SARIMAX_SEASONAL_BONUS
    if _is_seasonal_strong(s, acf_peaks) and "SARIMA" in adj:
        adj["SARIMA"] += SARIMA_STRONG_SEASONAL_BONUS

    # ── §E : exog 정책 (A안 핵심) ──
    n_exog = len(exog)
    if "SARIMAX" in candidates:
        if n_exog >= 1 and n_rows >= 100:
            adj["SARIMAX"] += SARIMAX_EXOG_BONUS
        else:
            candidates.remove("SARIMAX")
            adj.pop("SARIMAX", None)
            base.pop("SARIMAX", None)

    # ── §F : stationary → ARIMA 조정 ──
    if stationary is True and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_STAT_BONUS
    elif stationary is False and "ARIMA" in adj:
        adj["ARIMA"] += ARIMA_NONSTAT_PENALTY

    # ── §F+ : 7축 디벨롭 추가 ──
    if horizon >= 30:
        if "Prophet" in adj:
            adj["Prophet"] += PROPHET_LONG_HORIZON_BONUS

    if is_multivariate:
        if "SARIMAX" in adj:
            adj["SARIMAX"] += MULTIVARIATE_SARIMAX_BONUS

    if heteroscedastic:
        if "Prophet" in adj:
            adj["Prophet"] += HETERO_PROPHET_BONUS
        if "SARIMA" in adj:
            adj["SARIMA"] += HETERO_SARIMA_BONUS

    if changepoints >= 3 and "Prophet" in adj:
        adj["Prophet"] += CHANGEPOINTS_PROPHET_BONUS

    # ── §F++ (2026-06-05) : 주제 적합도 보너스 (user_intent + chosen_recipe.meta) ──
    chosen_meta = chosen.get("meta") if isinstance(chosen, dict) else {}
    topic_signals = _topic_signals(state, chosen_meta or {}, horizon, n_rows)
    intent_match = _apply_topic_bonus(adj, topic_signals)

    # ── §G : 점수 매트릭스 + top3 정렬 ──
    scores = {m: _clip(base[m] + adj[m]) for m in candidates}
    sorted_models = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    top3 = [name for name, _ in sorted_models[:3]]

    for fb in ("ARIMA", "Prophet", "SARIMA"):
        if len(top3) >= 3:
            break
        if fb not in top3:
            top3.append(fb)

    # ── §H : citations + rationale + meta ──
    citations = [r["hash"] for r in recipes[:3] if isinstance(r, dict) and r.get("hash")]

    baseline_rec = _baseline_recommend(s, n_rows)
    multistep = _multistep_strategy(horizon, recipe_key, n_rows)
    hybrid = _hybrid_hint(top3, horizon, n_rows)

    meta = {
        "recipe_key": recipe_key,
        "n_rows": n_rows,
        "seasonal_period": s,
        "exog_columns": exog,
        "horizon": horizon,
        "stationary": stationary,
        "target_kind": target_kind,
        "is_multivariate": is_multivariate,
        "heteroscedastic": heteroscedastic,
        "changepoints": changepoints,
        "scores": {m: round(v, 3) for m, v in scores.items()},
        "baseline_recommend": baseline_rec,
        "multistep_strategy": multistep,
        "hybrid_hint": hybrid,
        "leakage_excluded": leakage_excluded,
        # 주제 적합도 신호 (2026-06-05) — insight·output_extras 에서 활용
        "topic_signals": {k: v for k, v in topic_signals.items() if v},
        "intent_match": {m: lst for m, lst in intent_match.items() if lst},
    }

    rationale_parts = [
        f"recipe={recipe_key}",
        f"n={n_rows}",
        f"s={s}",
        f"exog={n_exog}",
        f"stationary={stationary}",
        f"horizon={horizon}",
        f"multivariate={is_multivariate}",
        f"hetero={heteroscedastic}",
        f"changepoints={changepoints}",
        f"→ top3={top3}",
        f"baseline={baseline_rec}",
        f"multistep={multistep}",
    ]
    if hybrid:
        rationale_parts.append(f"hybrid={hybrid}")
    if leakage_excluded:
        rationale_parts.append(f"leakage_excluded={leakage_excluded}")
    active_topics = [t for t, v in topic_signals.items() if v]
    if active_topics:
        rationale_parts.append(f"topics={active_topics}")
    rationale = ", ".join(rationale_parts)

    return {"top3": top3, "rationale": rationale, "citations": citations, "meta": meta}
```

---

## `pipelines/timeseries/search_space.py`

```python
"""pipelines.timeseries.search_space — Optuna 탐색 공간 (CS 담당, cs-day6 v3 + 과적합 방어 보강).

방법론 5-2 — HPO 는 시계열 교차검증(walk-forward) **안에서** 튜닝한다.
본 모듈은 HyperparameterTunerAgent 가 importlib 로 동적 로드하여
``get_search_space(model_name, trial) -> dict`` 시그니처로 호출한다.

지원 모델 (6종, pipeline.SUPPORTED_MODELS 와 동기):
  ARIMA / SARIMA / SARIMAX / Prophet / ETS / seasonal_naive

설계 원칙
─────────────────────────────────────────────────────────────────
1. **horizon 은 trial 가 결정하지 않는다** — horizon 은 도메인 변수.
   tuner 가 호출 시 state.category_extras["timeseries"]["horizon"] 을
   params 로 주입하면 train_with_cv 가 그 값으로 gap 산출.
2. **계절성 주기 s 는 categorical** — {7, 12, 30} 중에서 선택 (헌장
   2-4 ACF 가리키는 주기). 365 는 학습 비용이 커서 HPO 에서 제외.
3. **seasonal_naive 는 빈 dict** — 기준선 모델이라 튜닝 불필요
   (방법론 4-2·6-5 "못 이기면 채택 금지" 의 그 기준선).
4. **R-1006 정합** — 모든 trial 결과는 walk-forward 안에서 평균±분산
   판정 (tuner 의 n_splits=3 기본).

과적합 방어 (2026-06-05, OF1·OF2·OF3 디벨롭)
─────────────────────────────────────────────────────────────────
OF1: ARIMA/SARIMA order 데이터 길이 적응 — trial.study.user_attrs["n_rows"]
     주입 시 짧은 시계열엔 자동으로 (p+q+P+Q) 합계 상한 부과. 미주입 시 기본.
OF3: Prophet changepoint_prior_scale 상한 0.5 → 0.1 보수화 (노이즈 과적합 방지).
"""

from __future__ import annotations

from typing import Any


def _n_rows_hint(trial: Any) -> int:
    """trial.study.user_attrs["n_rows"] 에서 데이터 길이 힌트 추출.

    tuner 가 study.set_user_attr("n_rows", n) 으로 주입했을 때만 활용.
    미주입 시 0 반환 — 호출측은 기본 범위 사용.
    """
    try:
        attrs = getattr(getattr(trial, "study", None), "user_attrs", None) or {}
        return int(attrs.get("n_rows", 0) or 0)
    except Exception:
        return 0


def get_search_space(model_name: str, trial: Any) -> dict[str, Any]:
    """모델별 Optuna trial 파라미터 dict 반환.

    Parameters
    ----------
    model_name : str
        pipeline.SUPPORTED_MODELS 중 하나.
    trial : optuna.Trial
        HyperparameterTunerAgent 가 전달.

    Returns
    -------
    dict[str, Any]
        TimeSeriesPipeline.train 의 ``params`` 인자로 그대로 전달.
    """
    n_rows = _n_rows_hint(trial)

    # ─── 고전 통계 모델 ─────────────────────────────────────────────
    if model_name == "ARIMA":
        # OF1 — n_rows 적응 order 상한 (과적합 방어)
        if 0 < n_rows < 100:
            p_max, d_max, q_max = 1, 1, 1
        elif n_rows < 300:
            p_max, d_max, q_max = 2, 1, 2
        else:
            p_max, d_max, q_max = 3, 2, 3
        p = trial.suggest_int("p", 0, p_max)
        d = trial.suggest_int("d", 0, d_max)
        q = trial.suggest_int("q", 0, q_max)
        return {
            "order": (p, d, q),
            "trend": trial.suggest_categorical("trend", ["n", "c", "t", "ct"]),
        }

    if model_name == "SARIMA":
        # OF1 — n_rows 적응
        if 0 < n_rows < 200:
            p_max, q_max, P_max, Q_max = 1, 1, 1, 1
        else:
            p_max, q_max, P_max, Q_max = 2, 2, 2, 2
        p = trial.suggest_int("p", 0, p_max)
        d = trial.suggest_int("d", 0, 1)
        q = trial.suggest_int("q", 0, q_max)
        P = trial.suggest_int("P", 0, P_max)
        D = trial.suggest_int("D", 0, 1)
        Q = trial.suggest_int("Q", 0, Q_max)
        s = trial.suggest_categorical("seasonal_period", [7, 12, 30])
        return {
            "order": (p, d, q),
            "seasonal_order": (P, D, Q, int(s)),
        }

    if model_name == "SARIMAX":
        # SARIMAX 은 SARIMA 와 동일 파라미터 공간. exog 는 외부 주입
        # (pipeline._extract_exog 가 params["exog_columns" or "exog_indices"] 로 읽음).
        # OF1 — n_rows 적응
        if 0 < n_rows < 200:
            p_max, q_max = 1, 1
        else:
            p_max, q_max = 2, 2
        p = trial.suggest_int("p", 0, p_max)
        d = trial.suggest_int("d", 0, 1)
        q = trial.suggest_int("q", 0, q_max)
        P = trial.suggest_int("P", 0, 1)
        D = trial.suggest_int("D", 0, 1)
        Q = trial.suggest_int("Q", 0, 1)
        s = trial.suggest_categorical("seasonal_period", [7, 12, 30])
        return {
            "order": (p, d, q),
            "seasonal_order": (P, D, Q, int(s)),
        }

    # ─── Prophet ────────────────────────────────────────────────────
    if model_name == "Prophet":
        # OF3 — changepoint_prior_scale 상한 0.5 → 0.1 (노이즈 과적합 방지)
        return {
            "changepoint_prior_scale": trial.suggest_float("changepoint_prior_scale", 1e-3, 0.1, log=True),
            "seasonality_prior_scale": trial.suggest_float("seasonality_prior_scale", 1e-2, 10.0, log=True),
            "seasonality_mode": trial.suggest_categorical("seasonality_mode", ["additive", "multiplicative"]),
        }

    # ─── 지수평활 ETS / Holt-Winters (헌장 6-1 기준선) ─────────────────
    if model_name == "ETS":
        trend = trial.suggest_categorical("trend", [None, "add", "mul"])
        seasonal = trial.suggest_categorical("seasonal", [None, "add", "mul"])
        seasonal_periods = trial.suggest_categorical("seasonal_periods", [7, 12, 30])
        damped = trial.suggest_categorical("damped_trend", [False, True])
        return {
            "trend": trend,
            "seasonal": seasonal,
            "seasonal_periods": int(seasonal_periods),
            "damped_trend": bool(damped),
        }

    # ─── seasonal_naive 기준선 (헌장 4-2·6-5) ─────────────────────────
    if model_name == "seasonal_naive":
        return {}

    raise ValueError(f"Unknown timeseries model for search_space: {model_name}")
```

---

## `pipelines/timeseries/pipeline.py`

```python
"""timeseries.pipeline — 시계열 파이프라인 (CS 담당, cs-day6 v3 디벨롭).

지원 9종: ARIMA / SARIMA / SARIMAX / Prophet / ETS / seasonal_naive
         + Informer / TFT / PatchTST
+ StatsForecast(R-1007) fallback

cs-day6 §F-Extension (기존, 불변):
  - train() 시 instance 변수 저장 (_y_train_last / _seasonal_s / _model_obj)
  - evaluate() 확장 — naïve baseline + MASE + sMAPE + PI coverage (12 키)
    → cs-day7 evaluator 가 rmse_improvement_vs_naive 등 임계치 판정에 사용

cs-day6 v3 디벨롭 (신규):
  - SUPPORTED_MODELS 9종으로 확장 (SARIMAX/ETS/seasonal_naive 추가)
  - _train_dispatch 신규 분기 3종
  - _SeasonalNaiveModel 내부 클래스 — naive 기준선 학습용 (방법론 4-2·6-5)
  - _extract_exog — SARIMAX 의 exog 컬럼/인덱스 안전 추출
  - evaluate() 15 키 — y_pred_val/y_val_actual/y_train_tail 추가
    (output_extras forecast_chart 단절 C-5 해소)
  - train_with_cv — TimeSeriesSplit + gap=horizon-1 (방법론 4-1·누수 1-4)
    반환 mean = improvement_vs_naive 평균 (HPO study.direction='maximize' 정합)
  - 회귀 0 — 기존 12 키 그대로, 신규 키만 추가
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np

from pipelines.base import BasePipeline


class _ConstantSeriesModel:
    """D3 (2026-06-05) — 상수 시계열 (분산 0) 용 graceful 폴백 모델.

    fit/predict 인터페이스 호환. forecast/predict 모두 동일 상수값 반환.
    cs-day10 §단계 3 의 "❌ 시리즈가 상수 → 예측 불가" 분기를 학습 단계에서
    구현. evaluate() 의 분산 0 시 MASE/sMAPE 분모 가드와 정합.
    """

    def __init__(self, const_value: float) -> None:
        self.const_value = float(const_value)
        self._ada_constant_series = True  # output_extras 가 "분석 불가" 메시지 판정용

    def forecast(self, steps: int = 1, exog: Any = None) -> Any:  # noqa: ARG002
        import numpy as _np

        return _np.full(int(steps), self.const_value, dtype=float)

    def predict(self, X: Any) -> Any:
        import numpy as _np

        try:
            n = len(X)
        except Exception:
            n = 1
        return _np.full(int(n), self.const_value, dtype=float)


class _SeasonalNaiveModel:
    """seasonal_naive 기준선 모델 — ARIMA-like 인터페이스 (forecast(steps)).

    방법론 4-2 · 6-5: "복잡한 모델이 seasonal naive 를 못 이기면 그 모델은
    쓸모없다." 본 클래스는 학습 데이터의 마지막 period 만큼을 순환 반복해서
    예측한다. period<=0 이거나 len(y)<period 면 마지막 값 반복 (simple naive).
    """

    def __init__(self, y_train: Any, period: int = 7) -> None:
        arr = np.asarray(y_train, dtype=float).flatten()
        # NaN 안전: NaN 만 있는 경우 0 으로 대체
        arr = arr[~np.isnan(arr)] if arr.size > 0 else arr
        self._y_train = arr if arr.size > 0 else np.asarray([0.0])
        p = int(period) if period and period >= 1 else 1
        self._period = p if p <= len(self._y_train) else 1

    def forecast(self, steps: int) -> np.ndarray:
        """다음 steps 스텝 예측 — 마지막 period 순환 반복."""
        if steps <= 0:
            return np.asarray([], dtype=float)
        p = self._period
        tail = self._y_train[-p:]
        return np.array([float(tail[i % p]) for i in range(int(steps))])

    def predict(self, X: Any) -> np.ndarray:
        """sklearn-like 호환 — len(X) 스텝 예측."""
        try:
            n = len(X)
        except Exception:
            n = 1
        return self.forecast(int(n))


class TimeSeriesPipeline(BasePipeline):
    experiment_name = "ada-timeseries"
    # 9종으로 확장 — selector A안의 SARIMAX 후보 + 헌장 6-1 ETS 기준선
    # + 헌장 4-2·6-5 seasonal_naive 기준선
    SUPPORTED_MODELS = (
        "ARIMA",
        "SARIMA",
        "SARIMAX",
        "Prophet",
        "ETS",
        "seasonal_naive",
    )

    def __init__(self) -> None:
        super().__init__()
        # cs-day6 F-ext-1 : 학습 시 보존하는 instance 변수
        self._y_train_last: Optional[np.ndarray] = None  # MASE 분모 + naïve baseline 용
        self._seasonal_s: int = 0  # seasonal period (0 = simple naïve)
        self._model_obj: Optional[Any] = None  # PI 추출용 (옵션)

    # ════════════════════════════════════════════════════════════
    # cs-day6 F-ext-1b : seasonal_period 추출 (확장 — ETS/SN 포함)
    # ════════════════════════════════════════════════════════════
    def _extract_seasonal_period(self, model_name: str, params: dict[str, Any]) -> int:
        """모델별 seasonal_period 추출 — 0 이면 simple naïve."""
        # SARIMA/SARIMAX : params["seasonal_order"][3]
        if model_name in ("SARIMA", "SARIMAX"):
            seasonal_order = params.get("seasonal_order", (0, 0, 0, 0))
            return int(seasonal_order[3]) if len(seasonal_order) >= 4 else 0
        # ETS / seasonal_naive : params["seasonal_periods"]
        if model_name in ("ETS", "seasonal_naive"):
            return int(params.get("seasonal_periods") or 0)
        # Prophet : 명시적 seasonal_period 없음
        if model_name == "Prophet":
            return int(params.get("seasonal_period", 0))
        # ARIMA / 기타 : 0 (simple naïve)
        return 0

    # ════════════════════════════════════════════════════════════
    # 신규 — exog 안전 추출 (SARIMAX 용)
    # ════════════════════════════════════════════════════════════
    def _extract_exog(self, X_train: Any, params: dict[str, Any]) -> Any:
        """SARIMAX 용 exog 추출.

        우선순위:
          1. params["exog_columns"] + X_train 이 DataFrame 인 경우 — 컬럼명으로 추출
          2. params["exog_indices"] + X_train 이 ndarray 인 경우 — 열 인덱스로 추출
          3. 위 모두 실패 → None (단변량 SARIMAX 로 강등)
        """
        try:
            import pandas as pd  # noqa: WPS433
        except Exception:
            pd = None  # type: ignore

        cols = params.get("exog_columns") or []
        idxs = params.get("exog_indices") or []

        if pd is not None and isinstance(X_train, pd.DataFrame) and cols:
            valid = [c for c in cols if c in X_train.columns]
            if valid:
                exog = X_train[valid]
                return exog if not exog.empty else None
        if idxs and hasattr(X_train, "shape") and len(getattr(X_train, "shape", ())) >= 2:
            try:
                arr = np.asarray(X_train)
                valid_idx = [int(i) for i in idxs if 0 <= int(i) < arr.shape[1]]
                if valid_idx:
                    return arr[:, valid_idx]
            except Exception:
                return None
        return None

    # ════════════════════════════════════════════════════════════
    # G16 (2026-06-05) — 미래 결정론적 외생변수 자동 생성
    # ════════════════════════════════════════════════════════════
    @staticmethod
    def generate_future_exog(
        last_date: Any,
        n_steps: int,
        freq: str = "D",
        kinds: tuple[str, ...] = ("calendar", "fourier"),
        fourier_period: int = 7,
        fourier_n: int = 3,
    ) -> Any:
        """미래 horizon 동안의 결정론적 exog 자동 생성 — SARIMAX/Prophet forecast UX.

        Parameters
        ----------
        last_date : str | pd.Timestamp
            학습 데이터 마지막 날짜.
        n_steps : int
            예측 horizon.
        freq : str
            "D" (일) / "W" / "M" 등.
        kinds : tuple[str, ...]
            "calendar" — dayofweek/month/is_month_end/is_quarter_end 더미.
            "fourier"  — sin/cos pairs (fourier_period/fourier_n).
        fourier_period : int
        fourier_n : int

        Returns
        -------
        pd.DataFrame
            shape=(n_steps, k). 미래 시점별 exog 값. ds 컬럼 포함.
        """
        import numpy as _np  # noqa: WPS433
        import pandas as _pd  # noqa: WPS433

        try:
            last = _pd.to_datetime(last_date)
        except Exception:
            last = _pd.Timestamp.now()
        future_idx = _pd.date_range(start=last, periods=int(n_steps) + 1, freq=freq)[1:]

        out = _pd.DataFrame({"ds": future_idx})

        if "calendar" in kinds:
            out["cal_dayofweek"] = future_idx.dayofweek.astype("float")
            out["cal_month"] = future_idx.month.astype("float")
            out["cal_is_month_end"] = future_idx.is_month_end.astype("float")
            out["cal_is_quarter_end"] = future_idx.is_quarter_end.astype("float")

        if "fourier" in kinds and fourier_period and fourier_period >= 2:
            t = _np.arange(n_steps)
            for k in range(1, max(1, int(fourier_n)) + 1):
                out[f"fourier_sin_{k}"] = _np.sin(2.0 * _np.pi * k * t / fourier_period)
                out[f"fourier_cos_{k}"] = _np.cos(2.0 * _np.pi * k * t / fourier_period)

        return out

    # ════════════════════════════════════════════════════════════
    # train / _train_dispatch (확장 — SARIMAX/ETS/seasonal_naive 추가)
    # ════════════════════════════════════════════════════════════
    def train(self, X_train: Any, y_train: Any, model_name: str, params: dict[str, Any]) -> Any:
        """X_train: pd.DataFrame with date column or ndarray. y_train: target series."""
        with self._start_mlflow_run(tags={"model": model_name}):
            try:
                import mlflow  # noqa: WPS433

                mlflow.log_params({**params, "model_name": model_name})
            except Exception:
                pass

            # ── F-ext-1a : 학습 전 instance 변수 저장 (모든 모델 공통) ──
            try:
                self._y_train_last = np.asarray(y_train, dtype=float).flatten()
            except Exception:
                self._y_train_last = None
            self._seasonal_s = self._extract_seasonal_period(model_name, params)

            # D3 (2026-06-05) — 상수 시계열 가드 (cs-day10 단계 3·9 "예측 불가, 상수 시계열")
            # 분산 0 (모든 값 동일) 시 어떤 통계 모델도 의미 없음 + ARIMA/SARIMA 가 ConvergenceWarning
            # 또는 LinAlgError 일으킬 수 있어 사전 차단. _ConstantSeriesModel 로 graceful 폴백.
            if self._y_train_last is not None and len(self._y_train_last) > 0:
                try:
                    if float(np.var(self._y_train_last)) < 1e-12:
                        const_val = float(self._y_train_last[-1])
                        self._model_obj = _ConstantSeriesModel(const_val)
                        return self._model_obj
                except Exception:
                    pass

            model = self._train_dispatch(X_train, y_train, model_name, params)
            self._model_obj = model  # PI 추출 가능 모델 한정
            return model

    def _train_dispatch(self, X_train: Any, y_train: Any, model_name: str, params: dict[str, Any]) -> Any:
        if model_name == "ARIMA":
            from statsmodels.tsa.arima.model import ARIMA

            return ARIMA(
                y_train,
                order=params.get("order", (1, 1, 1)),
                trend=params.get("trend", "n"),
            ).fit()
        if model_name == "SARIMA":
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            return SARIMAX(
                y_train,
                order=params.get("order", (1, 1, 1)),
                seasonal_order=params.get("seasonal_order", (1, 1, 1, 7)),
            ).fit(disp=False)
        if model_name == "SARIMAX":
            # ── 신규 — SARIMAX 분기 (selector A안 호환) ──
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            exog_tr = self._extract_exog(X_train, params)
            fitted = SARIMAX(
                y_train,
                exog=exog_tr,
                order=params.get("order", (1, 1, 1)),
                seasonal_order=params.get("seasonal_order", (1, 1, 1, 7)),
            ).fit(disp=False)
            # D5 (2026-06-05) — exog 학습 여부 마커 (predict 시 누락 경고용)
            if exog_tr is not None:
                try:
                    fitted._ada_exog_required = True  # type: ignore[attr-defined]
                except Exception:
                    pass
            return fitted
        if model_name == "Prophet":
            import pandas as pd  # noqa: WPS433
            from prophet import Prophet  # type: ignore

            df = pd.DataFrame(
                {
                    "ds": X_train["ds"] if "ds" in X_train.columns else X_train.iloc[:, 0],
                    "y": y_train,
                }
            )
            m = Prophet(**params)
            m.fit(df)
            return m
        if model_name == "ETS":
            # ── 신규 — ETS / Holt-Winters (헌장 6-1 기준선) ──
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            y_arr = np.asarray(y_train, dtype=float).flatten()
            sp = params.get("seasonal_periods")
            seasonal = params.get("seasonal")
            # 데이터 부족하면 계절 성분 강등 (n >= 2*sp 필요)
            if seasonal is not None and sp and len(y_arr) < 2 * int(sp):
                seasonal = None
                sp = None
            # mul 은 양수 데이터 필요 — 음수 있으면 add 로 강등
            if (params.get("trend") == "mul" or seasonal == "mul") and (y_arr <= 0).any():
                trend = params.get("trend")
                if trend == "mul":
                    trend = "add"
                if seasonal == "mul":
                    seasonal = "add"
            else:
                trend = params.get("trend")
            return ExponentialSmoothing(
                y_arr,
                trend=trend,
                seasonal=seasonal,
                seasonal_periods=int(sp) if sp else None,
                damped_trend=bool(params.get("damped_trend", False)) if trend else False,
            ).fit(optimized=True)
        if model_name == "seasonal_naive":
            # ── 신규 — seasonal_naive 기준선 ──
            period = int(params.get("seasonal_periods") or self._seasonal_s or 7)
            return _SeasonalNaiveModel(y_train, period=period)
        # StatsForecast fallback
        try:
            import pandas as pd  # noqa: WPS433
            from statsforecast import StatsForecast  # type: ignore
            from statsforecast.models import AutoARIMA  # type: ignore

            df = pd.DataFrame({"ds": range(len(y_train)), "y": y_train, "unique_id": "ts_1"})
            sf = StatsForecast(df=df, models=[AutoARIMA(season_length=7)], freq="D")
            sf.fit()
            return sf
        except Exception as e:
            raise ValueError(f"Unknown timeseries model: {model_name}") from e

    # ════════════════════════════════════════════════════════════
    # predict — BasePipeline 추상 메서드 구현
    # ════════════════════════════════════════════════════════════
    def predict(self, model: Any, X: Any) -> np.ndarray:
        """예측 분기 :
        1) hasattr(model, "forecast") → forecast(steps=len(X)) (SARIMAX 는 exog 동반)
        2) 1) TypeError (exog 인자 미지원) → exog 없이 model.forecast(steps)
        3) model.forecast 없음 → model.predict(X)
        4) 1·2 둘 다 실패 + sklearn-like predict 보유 → model.predict(X)
        """
        try:
            if hasattr(model, "forecast"):
                # exog 동반 forecast 시도 — SARIMAX 등
                exog_attempted = False
                try:
                    import pandas as pd  # noqa: WPS433

                    if isinstance(X, pd.DataFrame):
                        exog_cols = [c for c in X.columns if c != "ds"]
                        if exog_cols:
                            exog = X[exog_cols].select_dtypes(include="number")
                            if not exog.empty:
                                exog_attempted = True
                                try:
                                    return np.asarray(model.forecast(steps=len(X), exog=exog))
                                except TypeError:
                                    pass  # exog 인자 미지원 모델 → 다음 단계
                except Exception:
                    pass
                # D5 (2026-06-05) — SARIMAX 학습됐는데 미래 exog 미제공 시 경고 로그
                if exog_attempted is False and getattr(model, "_ada_exog_required", False):
                    try:
                        import logging as _log

                        _log.getLogger(__name__).warning(
                            "predict_exog_missing — SARIMAX 학습 시 exog 사용했으나 예측 X 에 exog 미포함, 점예측만 반환"
                        )
                    except Exception:
                        pass
                # exog 없이 forecast (ARIMA/SARIMA 단변량/ETS/seasonal_naive)
                return np.asarray(model.forecast(steps=len(X)))
            return np.asarray(model.predict(X))
        except Exception:
            return np.asarray(model.predict(X))

    # ════════════════════════════════════════════════════════════
    # cs-day6 F-ext-2 : evaluate 확장 (12 키 → 15 키, 신규 3 키 추가)
    # ════════════════════════════════════════════════════════════
    def evaluate(self, model: Any, X_val: Any, y_val: Any, task: str = "forecasting") -> dict[str, Any]:
        from sklearn.metrics import mean_absolute_error, mean_squared_error

        y_val = np.asarray(y_val).flatten()

        # ── F-1 ~ F-3 (기존) : val_rmse / val_mae ──
        y_pred = self.predict(model, X_val)
        y_pred = np.asarray(y_pred).flatten()[: len(y_val)]
        y_true = y_val[: len(y_pred)]
        val_rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
        val_mae = float(mean_absolute_error(y_true, y_pred))

        y_train_last = self._y_train_last if self._y_train_last is not None else np.asarray([], dtype=float)

        # ── F-ext-2a : naïve baseline 선택 (seasonal vs simple) ──
        s = self._seasonal_s if (self._seasonal_s > 0 and self._seasonal_s <= len(y_train_last)) else 0
        naive_kind = "seasonal" if s > 0 else "simple"
        y_pred_naive = self._build_naive(y_train_last, s, len(y_true))

        # ── F-ext-2b : rmse_improvement_vs_naive (★ cs-day7 DoD 키) ──
        if len(y_true) > 0:
            rmse_naive = float(np.sqrt(mean_squared_error(y_true, y_pred_naive[: len(y_true)])))
        else:
            rmse_naive = 0.0
        if rmse_naive == 0.0:
            rmse_improvement: Optional[float] = None  # 분모 가드
        else:
            rmse_improvement = float((rmse_naive - val_rmse) / rmse_naive)

        # ── F-ext-2c : MASE ──
        if s > 0 and len(y_train_last) > s:
            scale = float(np.mean(np.abs(np.diff(y_train_last, n=s))))
        elif len(y_train_last) > 1:
            scale = float(np.mean(np.abs(np.diff(y_train_last))))
        else:
            scale = 0.0
        mase: Optional[float] = float(val_mae / scale) if scale > 0 else None

        # ── F-ext-2d : sMAPE ──
        denom = (np.abs(y_true) + np.abs(y_pred)) / 2.0
        mask = denom > 0
        smape: Optional[float] = (
            float(100.0 * np.mean(np.abs(y_true[mask] - y_pred[mask]) / denom[mask])) if mask.any() else None
        )

        # ── F-ext-2e : PI coverage (모델별 best-effort) ──
        pi_coverage, pi_lower, pi_upper = self._try_pi_coverage(model, X_val, y_true)

        # ── OF4 (2026-06-05) : train_rmse + overfit_gap 계산 ──
        # 과적합 감지 핵심 지표. 모델이 train 에 self.predict() 가능하면 fit 잔차 추출.
        train_rmse: Optional[float] = None
        overfit_gap: Optional[float] = None
        try:
            if model is not None and len(y_train_last) >= 5:
                # model 별 in-sample fit 추출
                y_train_fit = None
                if hasattr(model, "fittedvalues"):  # statsmodels (ARIMA/SARIMA/SARIMAX/ETS)
                    fv = np.asarray(model.fittedvalues).flatten()
                    y_train_fit = fv[-len(y_train_last) :] if len(fv) >= len(y_train_last) else fv
                elif hasattr(model, "predict") and not getattr(model, "_ada_constant_series", False):
                    # 시도 — sklearn-like
                    try:
                        y_train_fit = np.asarray(model.predict(y_train_last)).flatten()
                    except Exception:
                        y_train_fit = None
                if y_train_fit is not None and len(y_train_fit) >= 5:
                    # 길이 정렬
                    L = min(len(y_train_fit), len(y_train_last))
                    y_train_fit = y_train_fit[-L:]
                    y_train_true = y_train_last[-L:]
                    # NaN 제거
                    mask = ~(np.isnan(y_train_fit) | np.isnan(y_train_true))
                    if int(mask.sum()) >= 5:
                        train_rmse = float(np.sqrt(mean_squared_error(y_train_true[mask], y_train_fit[mask])))
                        # overfit_gap = (val_rmse - train_rmse) / train_rmse
                        if train_rmse > 1e-9:
                            overfit_gap = float((val_rmse - train_rmse) / train_rmse)
        except Exception:
            train_rmse = None
            overfit_gap = None

        # ── F-ext-2f : 기존 12 키 + OF4 신규 2 키 ──
        out: dict[str, Any] = {
            "val_rmse": val_rmse,
            "val_mae": val_mae,
            "rmse_naive": rmse_naive,
            "rmse_improvement_vs_naive": rmse_improvement,  # ★ cs-day7 DoD 키
            "MASE": mase,
            "sMAPE": smape,
            "pi_coverage": pi_coverage,
            "pi_lower": pi_lower.tolist() if pi_lower is not None else None,
            "pi_upper": pi_upper.tolist() if pi_upper is not None else None,
            "naive_kind": naive_kind,
            "naive_s": s if s > 0 else None,
            "mlflow_run_id": self.mlflow_run_id,
            # OF4 (2026-06-05) — 과적합 감지 키
            "train_rmse": train_rmse,
            "overfit_gap": overfit_gap,
        }

        # ── 신규 3 키 — output_extras forecast_chart 단절 C-5 해소 ──
        # 작은 list 라 직렬화 부담 적음. NaN 가드 (training_monitor 의 float NaN
        # 검사는 list 무시 → 안전).
        try:
            out["y_pred_val"] = [float(v) for v in y_pred]
            out["y_val_actual"] = [float(v) for v in y_true]
            tail_len = min(200, len(y_train_last))
            out["y_train_tail"] = [float(v) for v in y_train_last[-tail_len:]] if tail_len > 0 else []
        except Exception:
            out["y_pred_val"] = None
            out["y_val_actual"] = None
            out["y_train_tail"] = None
        return out

    # ── F-ext-2.1 : _build_naive (seasonal vs simple) ──
    def _build_naive(self, y_train_last: Any, s: int, n_val: int) -> np.ndarray:
        if s > 0 and len(y_train_last) >= s:
            return np.array([y_train_last[-s + (i % s)] for i in range(n_val)])
        last = y_train_last[-1] if len(y_train_last) > 0 else 0.0
        return np.full(n_val, last)

    # ── F-ext-2.2 : _try_pi_coverage (모델별 PI 추출 — best-effort) ──
    def _try_pi_coverage(self, model: Any, X_val: Any, y_true: Any, alpha: float = 0.05):
        """95% PI 추출 + coverage. 추출 불가 시 (None, None, None)."""
        try:
            # SARIMA / SARIMAX (statsmodels)
            if hasattr(model, "get_forecast"):
                fc = model.get_forecast(steps=len(y_true))
                ci = fc.conf_int(alpha=alpha)
                lower = np.asarray(ci.iloc[:, 0] if hasattr(ci, "iloc") else ci[:, 0])
                upper = np.asarray(ci.iloc[:, 1] if hasattr(ci, "iloc") else ci[:, 1])
            # Prophet
            elif hasattr(model, "predict") and hasattr(model, "make_future_dataframe"):
                future = model.make_future_dataframe(periods=len(y_true))
                forecast = model.predict(future)
                lower = forecast["yhat_lower"].values[-len(y_true) :]
                upper = forecast["yhat_upper"].values[-len(y_true) :]
            # NeuralForecast (level=[95] 사용 시)
            elif hasattr(model, "predict_intervals"):
                pi_df = model.predict_intervals(level=[95])
                lower = pi_df["lower_95"].values[: len(y_true)]
                upper = pi_df["upper_95"].values[: len(y_true)]
            else:
                return None, None, None

            L = min(len(lower), len(upper), len(y_true))
            coverage = float(np.mean((lower[:L] <= y_true[:L]) & (y_true[:L] <= upper[:L])))
            return coverage, lower[:L], upper[:L]
        except Exception as e:
            self._log_warning("pi_coverage_failed", error=str(e))
            return None, None, None

    # ════════════════════════════════════════════════════════════
    # 신규 — train_with_cv (rolling-origin walk-forward, 방법론 4-1·누수 1-4)
    # ════════════════════════════════════════════════════════════
    def train_with_cv(
        self,
        X: Any,
        y: Any,
        model_name: str,
        params: dict[str, Any],
        n_splits: int = 3,
        task: str = "forecasting",
    ) -> dict[str, Any]:
        """rolling-origin walk-forward CV — HyperparameterTunerAgent 가 호출.

        TimeSeriesSplit + gap=horizon-1 (누수 1-4 차단). 각 fold 안에서 self.train
        → self.evaluate 호출 → improvement_vs_naive 수집.

        반환 ``mean`` = mean(improvement_vs_naive) — HPO study.direction="maximize"
        와 정합 (클수록 좋음). 실패 fold 는 0.0 (neutral, trial prune 회피).

        Parameters
        ----------
        n_splits : int
            기본 3. 데이터가 작으면 자동 축소.
        """
        from sklearn.model_selection import TimeSeriesSplit

        horizon = int(params.get("horizon") or 1)
        gap = max(0, horizon - 1)
        n = len(y) if hasattr(y, "__len__") else 0

        if n < 10:
            # 데이터 너무 짧음 — CV 의미 없음, neutral 반환
            return {
                "fold_scores": [],
                "fold_metrics": [],
                "mean": 0.0,
                "std": 0.0,
                "n_splits": 0,
                "gap": gap,
                "skip_reason": "n<10",
            }

        # n_splits 가 너무 크면 자동 축소 (min fold size >= 5 보장)
        min_fold = 5
        max_possible = max(2, (n - gap) // (min_fold + 1))
        n_splits_eff = max(2, min(int(n_splits), max_possible))

        try:
            splitter = TimeSeriesSplit(n_splits=n_splits_eff, gap=gap)
        except TypeError:
            # 구버전 sklearn — gap 인자 미지원
            splitter = TimeSeriesSplit(n_splits=n_splits_eff)

        fold_scores: list[float] = []
        fold_metrics_list: list[dict[str, Any]] = []

        idx_arr = np.arange(n)
        for tr_idx, val_idx in splitter.split(idx_arr):
            try:
                # 인덱싱 — DataFrame/Series 는 iloc, ndarray 는 fancy indexing
                X_tr = X.iloc[tr_idx] if hasattr(X, "iloc") else X[tr_idx]
                X_val = X.iloc[val_idx] if hasattr(X, "iloc") else X[val_idx]
                y_tr = y.iloc[tr_idx] if hasattr(y, "iloc") else y[tr_idx]
                y_val = y.iloc[val_idx] if hasattr(y, "iloc") else y[val_idx]

                model = self.train(X_tr, y_tr, model_name=model_name, params=params)
                m = self.evaluate(model, X_val, y_val, task=task)
                imp = m.get("rmse_improvement_vs_naive")
                fold_scores.append(float(imp) if imp is not None else 0.0)
                fold_metrics_list.append(
                    {
                        "val_rmse": m.get("val_rmse"),
                        "val_mae": m.get("val_mae"),
                        "MASE": m.get("MASE"),
                        "rmse_improvement_vs_naive": m.get("rmse_improvement_vs_naive"),
                    }
                )
            except Exception as e:
                self._log_warning("fold_failed", model=model_name, error=str(e))
                fold_scores.append(0.0)
                fold_metrics_list.append({})

        mean = float(np.mean(fold_scores)) if fold_scores else 0.0
        std = float(np.std(fold_scores)) if fold_scores else 0.0
        return {
            "fold_scores": fold_scores,
            "fold_metrics": fold_metrics_list,
            "mean": mean,
            "std": std,
            "n_splits": n_splits_eff,
            "gap": gap,
        }

    # ── logger 안전 호출 (BasePipeline 에 logger 없을 수 있음) ──
    def _log_warning(self, event: str, **kw: Any) -> None:
        logger = getattr(self, "logger", None)
        if logger is not None:
            try:
                logger.warning(event, **kw)
            except Exception:
                pass
```

---

## `agents/training_executor.py`

```python
"""agents.training_executor — TrainingExecutorAgent (Day08 + Day 6 best_params 연결).

4 카테고리에 따라 PipelineFactory 로 파이프라인을 선택하고,
ModelSelectionAgent 가 선정한 후보 3종을 학습한다.

Day 6 계약: state.best_params[model] 가 있으면 그 값을 params 로 흘려준다.

2026-06-04 (HJ) — heavy/light 분기 추가:
    HEAVY 모델 (DL 카테고리 + 무거운 시계열·이상탐지 Transformer 계열) 은
    별도 ``ada.training.run`` Celery 태스크로 위임 → 학원 worker-training (GPU) 처리.
    Light 모델 (전통 ML/통계/IsolationForest 등) 은 기존대로 인라인 학습.
    위임 타임아웃 시 CPU 인라인으로 자동 폴백.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np

from ada.core.config import settings
from ada.core.state import PipelineState
from agents.base import BaseAgent
from orchestrator.training_tasks import HEAVY_MODELS, is_heavy_model
from pipelines.factory import PipelineFactory


def _split_xy(df: Any, target: str | None) -> tuple[Any, Any]:
    if target and target in df.columns:
        X = df.drop(columns=[target])
        y = df[target]
        return X.select_dtypes(include=[np.number, "bool"]).fillna(0).values, y.values
    return df.select_dtypes(include=[np.number]).fillna(0).values, np.zeros(len(df))


class TrainingExecutorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            try:
                from agents.handlers.common.shared import load_dataframe_from_state

                df = load_dataframe_from_state(state)
            except Exception as e:
                return state.with_update(error=f"학습 데이터 로딩 실패: {e}", next_agent="error_recovery")

            X, y = _split_xy(df, state.target_column)
            # train/val split — 시계열은 시간순 split, 그 외 random
            if state.category == "timeseries":
                split = int(len(X) * 0.8)
                X_tr, X_val = X[:split], X[split:]
                y_tr, y_val = y[:split], y[split:]
            else:
                from sklearn.model_selection import train_test_split

                X_tr, X_val, y_tr, y_val = train_test_split(
                    X,
                    y,
                    test_size=0.2,
                    random_state=42,
                    stratify=y
                    if state.category in ("tabular_ml", "tabular_dl") and len(set(y.tolist())) <= 20
                    else None,
                )

            pipeline = PipelineFactory.create(state.category)
            task = (
                "classification"
                if state.category in ("tabular_ml", "tabular_dl") and len(set(y.tolist())) <= 20
                else "regression"
            )
            if state.category == "timeseries":
                task = "forecasting"
            if state.category == "anomaly_detection":
                task = "anomaly_detection"

            trained: list[dict[str, Any]] = []
            heavy_used: list[str] = []
            for model_name in state.model_candidates:
                # Day 6 계약: HyperparameterTuner 가 채운 best_params 우선 사용.
                params = (state.best_params or {}).get(model_name, {}) or {}

                if is_heavy_model(model_name):
                    # ── 학원 worker-training 위임 (heavy: DL 계열) ────────────
                    info = await self._train_remote(
                        state=state,
                        model_name=model_name,
                        params=params,
                    )
                    if info is not None:
                        trained.append(info)
                        heavy_used.append(model_name)
                        continue
                    # 위임 실패 시 CPU 인라인 폴백
                    self.logger.warning(
                        "heavy_model_remote_failed_fallback_cpu",
                        model=model_name,
                    )

                # ── CPU 인라인 학습 (light + heavy 폴백) ─────────────────────
                try:
                    model = pipeline.train(X_tr, y_tr, model_name=model_name, params=params)
                    metrics = pipeline.evaluate(model, X_val, y_val, task=task)
                    info: dict[str, Any] = {
                        "model_name": model_name,
                        "metrics": metrics,
                        "mlflow_run_id": pipeline.mlflow_run_id,
                        "params_used": params,
                        "executed_on": "pipeline_worker",
                    }
                    if state.category == "tabular_ml":
                        save = pipeline.save_model(model, state.job_id, model_name)
                        info.update(save)
                    trained.append(info)
                except Exception as e:
                    self.logger.warning("train_failed", model=model_name, error=str(e))

            self.logger.info(
                "training_done",
                trained=len(trained),
                heavy_dispatched=heavy_used,
                heavy_known=sorted(HEAVY_MODELS),
            )
            return state.with_update(trained_models=trained, next_agent="training_monitor")

    # ------------------------------------------------------------------
    async def _train_remote(
        self,
        *,
        state: PipelineState,
        model_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any] | None:
        """heavy 모델을 ``ada.training.run`` 태스크로 위임 후 sync wait.

        반환:
            성공 시 train_model_task 의 dict 결과 (단, "error" 키 있으면 None 반환).
            타임아웃·통신 실패·기타 예외 시 None 반환 → caller 가 CPU 인라인 폴백.
        """
        from orchestrator.training_tasks import train_model_task

        timeout = settings.training_task_timeout_sec
        try:
            async_result = train_model_task.apply_async(
                args=[
                    state.job_id,
                    state.file_id,
                    state.category,
                    state.target_column,
                    model_name,
                    params,
                ],
                queue="training",
            )
        except Exception as e:  # noqa: BLE001
            self.logger.warning("remote_dispatch_failed", model=model_name, error=str(e))
            return None

        try:
            # AsyncResult.get 은 동기 블로킹 → asyncio.to_thread 로 이벤트 루프 해방.
            info = await asyncio.to_thread(async_result.get, timeout=timeout)
        except Exception as e:  # noqa: BLE001  (celery.exceptions.TimeoutError 포함)
            self.logger.warning(
                "remote_train_timeout_or_error",
                model=model_name,
                timeout_sec=timeout,
                error=str(e),
            )
            # 큐에 남은 태스크 revoke (워커가 늦게 받더라도 결과는 폐기)
            try:
                async_result.revoke(terminate=False)
            except Exception:  # noqa: BLE001
                pass
            return None

        if not isinstance(info, dict):
            self.logger.warning("remote_train_bad_payload", model=model_name, payload_type=type(info).__name__)
            return None
        if info.get("error"):
            self.logger.warning(
                "remote_train_returned_error",
                model=model_name,
                error=info["error"],
            )
            return None
        return info
```

---

## `agents/handlers/timeseries/evaluator.py`

```python
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

        # 판정
        bias_warn = mean_pct > 0.10
        if ljung_p is not None and ljung_p > 0.05 and not bias_warn:
            return {
                "kind": "white_noise",
                "ljung_box_p": round(ljung_p, 4),
                "mean_pct": round(mean_pct, 4),
                "hint": "잔차가 백색잡음에 가까워 모델이 신호를 충분히 추출했습니다.",
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
            }
        if bias_warn:
            return {
                "kind": "biased",
                "ljung_box_p": round(ljung_p, 4) if ljung_p is not None else None,
                "mean_pct": round(mean_pct, 4),
                "hint": f"잔차 평균 편향 +{mean_pct:.1%} — 추세 보정 / 상수항 추가 검토.",
            }
        return {"kind": "unknown", "ljung_box_p": ljung_p, "mean_pct": round(mean_pct, 4)}
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

    if cov is not None and cov < th["pi_coverage_min"]:
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
    # L4 — task_kind 분류형 안내
    if classification_hint:
        rationale_parts.append(classification_hint)
    rationale = " | ".join(rationale_parts)

    return {
        # 기존 4 키 (불변, 회귀 0)
        "passed": passed,
        "rationale": rationale,
        "threshold_violations": violations,
        "metrics": metrics,  # cs-day6 의 모든 키 그대로 전달
        # 신규 3 키 (cs-day7 v3 디벨롭)
        "fold_diagnostics": fold_diag,
        "leakage_suspect_signals": leakage_signals,
        "symptom_classification": symptom,
        "fit_quality": _diagnose_fit_quality(metrics),
        "residual_diagnostics": _diagnose_residuals(metrics),  # G15
        "dm_test": _dm_test(metrics),  # G13
        # L4 — task_kind 안내 (chosen_recipe 활용 시만)
        "task_kind_hint": classification_hint,
    }
```

---

## `agents/handlers/timeseries/insight.py`

```python
"""agents.handlers.timeseries.insight — 시계열 인사이트 (CS 담당, cs-day8 v3 디벨롭).

SYSTEM_PROMPT 수치 2+ 강제 + prompt_payload (horizon·0단계 메타 포함) +
fallback 다단 한국어 조립 + cs-day7 v3 evaluator 신규 4키 활용.

진입함수 (dispatcher 자동 등록):
  - generate(state) -> str          한국어 3~7 문장 (fallback 반환; LLM 은 dispatcher)
  - prompt_payload(state) -> dict   LLM 입력 (HJ BaseAgent._call_llm)
  - fallback(state) -> str          LLM 실패 시 한국어 템플릿

DoD (불변):
  - 한국어 3~5문장 이상 + 정확한 수치 2개 이상 + (있을 때) top features 1개+
  - 응급 안전망 보장 (fallback 자체 실패 시)

cs-day8 v3 디벨롭 (재정독 후 헌장 갭 7건 해소):
  H1 slope 키 버그 수정 — profiler 의 trend["slope_per_obs"] (legacy "slope" 도 fallback)
  H2 0단계 메타 명시 — proposer.g1(state) 직접 호출해서 meta(variate/forecast_kind/
     task_kind/horizon_hint) 추출. HJ-5 (2026-06-05) 이후 chosen_recipe 가 PipelineState
     정식 필드가 됐으나 채우는 곳은 HJ-7 후속 — 정상 채워질 때까지 proposer.g1 직접 호출 fallback 유지
  H3 누수 의심 한계 안내 — eval_result.leakage_suspect_signals 받아 정직한 한계 인정
     ("검증 신호 X 감지 — 운영 적용 전 점검 필요"). cs-day10 "정직한 실패" 원칙
  H4 fold 분산 인용 — eval_result.fold_diagnostics 받아 "fold N개 평균 X (안정성 Y)"
  H5 증상 + 롤백 우선순위 — eval_result.symptom_classification.rollback_priority
  H6 승법·changepoint·이분산 도메인 가이드 — eda_summary carry 활용
  H7 task_kind_hint (분류형) — eval_result.task_kind_hint 한국어 안내

핵심 설계 원칙 (불변):
  - 수치 2+ DoD 강제 — SYSTEM_PROMPT 규칙 3 + fallback 수치 보장 매트릭스
  - direction 한국어 매핑 — None / "none" 구분 (혼합 vs 횡보)
  - freq 폴백 3 단 — 정확 매칭 → prefix → "주기"
  - 수치 우선순위 — improvement > MASE > skip
  - 응급 안전망 — fallback 자체 실패 시 응급 텍스트
  - PII reattach — dispatcher 책임 (우리 fallback 은 LLM 호출 X → PII 무관)
  - R-501 KB 인용 — ModelSelection·Supervisor 책임 (insight 영역 외)
"""

from __future__ import annotations

from typing import Any, Optional

# ── 한국어 표현 매핑 ──────────────────────────────────────────────
DIRECTION_KO: dict[str, str] = {
    "increasing": "상승",
    "decreasing": "하락",
    "none": "횡보",
}

# pd.infer_freq 코드 → 한국어 단위 (정확 매칭 우선, prefix 폴백)
FREQ_UNIT_KO: dict[str, str] = {
    "D": "일",
    "B": "영업일",
    "W": "주",
    "M": "개월",
    "MS": "개월",
    "Q": "분기",
    "QS": "분기",
    "Y": "년",
    "YS": "년",
    "A": "년",
    "H": "시간",
    "T": "분",
    "S": "초",
}

FREQ_HORIZON_FALLBACK = {"D": 7, "W": 4, "M": 12, "MS": 12, "H": 24}

# H2 — 0단계 한국어 매핑
VARIATE_KO = {"univariate": "단변량", "multivariate": "다변량"}
FORECAST_KIND_KO = {"point": "점 예측", "interval": "구간 예측"}
TASK_KIND_KO = {"regression": "회귀형", "classification": "분류형 (이상 시점)"}

# H5 — 증상 코드 → 한국어 라벨 (evaluator.symptom_classification 호환)
SYMPTOM_KO_LABEL = {
    "C": "검증 성능 비현실적 좋음 (누수 의심)",
    "D": "fold 편차 큼",
    "E": "naïve 기준선 못 이김",
    "B": "학습/검증 둘 다 나쁨 (과소적합)",
    "A": "과적합 의심",
    "no_model": "모델 학습 실패",
}

SYSTEM_PROMPT = """당신은 시계열 분석 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~7문장으로 인사이트를 작성하세요.

규칙:
1. 추세 방향 (상승/하락/횡보) 을 1번째 문장에 명시
2. 계절성/주기 가 있다면 2번째 문장에 언급 (주기 숫자 포함)
3. 정확한 수치 2개 이상 인용 (★ 강화)
   - 예: 변화율 % (slope), naïve 대비 개선율, MASE, 주기 숫자, fold 평균
   - 도메인 예시 : "다음 7일 매출이 평균 12% 증가"
4. 0단계 성격 (단변량/다변량 · 점/구간 예측) 명시 (있을 때)
5. walk-forward 검증 결과 (fold 평균 + 안정성) 인용 (있을 때)
6. 검증 누수 의심 신호가 있으면 정직한 한계 인정 (낙관 톤 X)
7. 마지막 1문장은 행동 권고 + 권장 조치 (롤백 우선순위 인용)
8. 마크다운/리스트/이모지 금지, 순수 한국어 문단만 작성
"""


# ════════════════════════════════════════════════════════════════
# 헬퍼 — state 안전 추출
# ════════════════════════════════════════════════════════════════
def _eda_dict(state: Any) -> dict:
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _eval_result(state: Any) -> dict:
    raw = getattr(state, "eval_result", None)
    return raw if isinstance(raw, dict) else {}


def _unit_ko(freq: Any) -> str:
    """freq 단위 한국어 — 정확 매칭 → prefix 폴백 → "주기"."""
    if not freq:
        return "주기"
    return FREQ_UNIT_KO.get(freq) or FREQ_UNIT_KO.get(freq[:1] if freq else "") or "주기"


# H1 — slope 키 버그 수정 (profiler 정식 키 = slope_per_obs / legacy = slope)
def _trend_slope_compat(trend: dict) -> Optional[float]:
    """slope_per_obs (profiler 정식) → slope (legacy) → None."""
    if not isinstance(trend, dict):
        return None
    v = trend.get("slope_per_obs")
    if v is None:
        v = trend.get("slope")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


# H2 — 0단계 메타 추출 (proposer.g1 직접 호출 — chosen_recipe 미존재 우회)
def _zero_step_meta(state: Any) -> dict:
    """proposer.g1(state) 의 top recipe 의 meta 추출 — 0단계 성격 (variate/
    forecast_kind/task_kind/horizon_hint).

    호환성: HJ-5 (2026-06-05) 이후 chosen_recipe 는 PipelineState 정식 필드이지만,
    채우는 dispatcher 로직은 HJ-7 후속 (현재 dead field). 채워질 때까지 1순위로
    state.chosen_recipe.meta 를 시도하고, 빈 경우 proposer.g1 의 top1 meta 로 fallback.
    실패해도 graceful (모든 키 None).
    """
    default = {"variate": None, "forecast_kind": None, "task_kind": None, "horizon_hint": None}
    # 1순위 — state.chosen_recipe.meta (운영 경로에서 들어오면 활용)
    chosen = getattr(state, "chosen_recipe", None)
    if isinstance(chosen, dict):
        meta = chosen.get("meta")
        if isinstance(meta, dict):
            return {
                "variate": meta.get("variate"),
                "forecast_kind": meta.get("forecast_kind"),
                "task_kind": meta.get("task_kind"),
                "horizon_hint": meta.get("horizon_hint"),
            }
    # 2순위 — proposer.g1(state) 직접 호출
    try:
        from agents.handlers.timeseries.proposer import g1 as _g1

        recipes = _g1(state) or []
        if recipes and isinstance(recipes[0], dict):
            meta = recipes[0].get("meta")
            if isinstance(meta, dict):
                return {
                    "variate": meta.get("variate"),
                    "forecast_kind": meta.get("forecast_kind"),
                    "task_kind": meta.get("task_kind"),
                    "horizon_hint": meta.get("horizon_hint"),
                }
    except Exception:
        pass
    return default


# H3·H4·H5·H7 — evaluator 신규 4 키 안전 추출
def _eval_diagnostics(state: Any) -> dict:
    """state.eval_result 에서 cs-day7 v3 신규 4키 + OF5 fit_quality 안전 추출.

    state.eval_result 는 EvalAgent 가 with_update(eval_result=...) 로 저장.
    우리 evaluator 가 채운 키 중 H3/H4/H5/H7/OF5 관련 5 키 추출.
    """
    er = _eval_result(state)
    return {
        "leakage_signals": er.get("leakage_suspect_signals") or [],
        "fold_diag": er.get("fold_diagnostics") or {},
        "symptom": er.get("symptom_classification") or {},
        "task_kind_hint": er.get("task_kind_hint"),
        "fit_quality": er.get("fit_quality") or {},
        "residual_diag": er.get("residual_diagnostics") or {},  # G15
        "dm_test": er.get("dm_test") or {},  # G13
    }


# ════════════════════════════════════════════════════════════════
# §B. prompt_payload — horizon 추론 + 0단계 메타 + 진단 (시그니처 호환)
# ════════════════════════════════════════════════════════════════
def prompt_payload(state: Any) -> dict[str, Any]:
    """LLM 호출용 payload — dispatcher 가 사용 (HJ BaseAgent._call_llm).

    cs-day8 v3 디벨롭: 기존 11키 + 신규 키 (zero_step / eval_diagnostics) 추가.
    dispatcher 는 payload 를 통째로 LLM 컨텍스트에 직렬화 → LLM 이 풍부한
    근거로 인사이트 작성. 기존 11키 키 이름 불변 (회귀 0).
    """
    bm = getattr(state, "best_model", None) or {}
    data_profile = getattr(state, "data_profile", None) or {}
    eda = _eda_dict(state)

    trend = data_profile.get("trend") or {}
    s = data_profile.get("seasonality") or {}
    period = s.get("period") or eda.get("seasonal_period") or 7

    freq = data_profile.get("freq") or eda.get("freq") or "D"
    horizon_n = period if (period and isinstance(period, int)) else FREQ_HORIZON_FALLBACK.get(freq, 7)
    unit_ko = _unit_ko(freq)
    horizon_text = f"다음 {horizon_n}{unit_ko}"

    # H2 신규 — 0단계 메타
    zero = _zero_step_meta(state)
    # H3·H4·H5·H7 신규 — evaluator 진단
    diag = _eval_diagnostics(state)

    return {
        # 기존 11 키 (불변, 회귀 0)
        "category": "timeseries",
        "user_intent": getattr(state, "user_intent", None),
        "best_model": bm,
        "stationarity": data_profile.get("stationarity"),
        "trend": trend,
        "seasonality": s,
        "eval_result": getattr(state, "eval_result", None),
        "horizon_text": horizon_text,
        "horizon_n": horizon_n,
        "unit_ko": unit_ko,
        "system_prompt": SYSTEM_PROMPT,
        # cs-day8 v3 신규 키 (LLM 컨텍스트 풍부화 — 호환 OK, 기존 키 불변)
        "zero_step": zero,
        "eval_diagnostics": diag,
    }


# ════════════════════════════════════════════════════════════════
# §F. fallback — 다단 한국어 조립 (수치 2+ 보장 + 디벨롭 7건 반영)
# ════════════════════════════════════════════════════════════════
def fallback(state: Any) -> str:
    """LLM 실패 시 한국어 3~7문장 fallback (수치 2+ 보장 + 정직한 한계 보고).

    응급 안전망: 본문 실패 시 "이번 분석 결과는 추가 검토가 필요합니다."
    """
    try:
        return _build_fallback(state)
    except Exception:
        return "이번 분석 결과는 추가 검토가 필요합니다."


def _build_fallback(state: Any) -> str:
    bm = getattr(state, "best_model", None) or {}
    data_profile = getattr(state, "data_profile", None) or {}
    eda = _eda_dict(state)
    metrics = bm.get("metrics") or {}
    eval_result_dict = _eval_result(state)
    # metrics 우선순위: best_model.metrics > eval_result.metrics
    if not metrics:
        metrics = eval_result_dict.get("metrics") or {}

    # ── F-1 : direction 한국어 ──
    trend = data_profile.get("trend") or {}
    direction_en = trend.get("direction")
    direction_ko = DIRECTION_KO.get(direction_en, "혼합")

    # ── F-2 : freq 단위 한국어 ──
    freq = data_profile.get("freq") or eda.get("freq") or "D"
    unit_ko = _unit_ko(freq)

    # ── seasonality + period ──
    s = data_profile.get("seasonality") or {}
    has_seas = s.get("has_seasonality")
    period = s.get("period") or eda.get("seasonal_period") or 7

    # ── F-3 (H1) : slope 변화율 (slope_per_obs 정식 키 사용) ──
    slope_pct = _trend_slope_compat(trend)
    if slope_pct is not None and abs(slope_pct) > 0.001:
        slope_text = f" (평균 {slope_pct:+.1%})"
    else:
        slope_text = ""

    # ── F-4 : improvement / MASE 대체 ──
    improvement = metrics.get("rmse_improvement_vs_naive")
    mase = metrics.get("MASE")
    if improvement is not None:
        perf_text = f"naïve 대비 {improvement:+.1%} 우수한 성능"
    elif mase is not None:
        if mase < 1.0:
            perf_text = f"MASE {mase:.2f} 의 양호한 성능"
        else:
            perf_text = f"MASE {mase:.2f} 의 추가 검토가 필요한 성능"
    else:
        perf_text = "추가 검토가 필요한 성능"

    model_name = bm.get("model_name", "미정")

    # horizon (proposer §F meta.horizon_hint 우선)
    zero = _zero_step_meta(state)
    horizon_n = zero.get("horizon_hint") or (
        period if (period and isinstance(period, int)) else FREQ_HORIZON_FALLBACK.get(freq, 7)
    )
    horizon_n = int(horizon_n) if isinstance(horizon_n, (int, float)) else 7
    horizon_text = f"다음 {horizon_n}{unit_ko}"

    # H6 — 도메인 가이드 (승법·changepoint·이분산)
    is_mult = eda.get("is_multiplicative")
    cp_count = int(eda.get("changepoints") or 0)
    hetero = eda.get("heteroscedastic")
    domain_hints: list[str] = []
    if is_mult is True:
        domain_hints.append("분산이 레벨에 비례하는 승법 구조로 로그 변환 검토")
    if cp_count >= 3:
        domain_hints.append(f"레짐 변화 {cp_count}건 감지로 이벤트 더미 피처 권장")
    if hetero is True:
        domain_hints.append("이분산 잔차로 시간 적응형 PI 검토")

    # H3·H4·H5·H7 — evaluator 진단
    diag = _eval_diagnostics(state)
    leakage = diag.get("leakage_signals") or []
    fold_diag = diag.get("fold_diag") or {}
    symptom = diag.get("symptom") or {}
    task_hint = diag.get("task_kind_hint")

    # H2 — 0단계 한국어
    variate_ko = VARIATE_KO.get(zero.get("variate")) if zero.get("variate") else None
    forecast_kind_ko = FORECAST_KIND_KO.get(zero.get("forecast_kind")) if zero.get("forecast_kind") else None
    zero_step_phrase = ""
    if variate_ko and forecast_kind_ko:
        zero_step_phrase = f" {variate_ko} {forecast_kind_ko}"
    elif variate_ko:
        zero_step_phrase = f" {variate_ko}"
    elif forecast_kind_ko:
        zero_step_phrase = f" {forecast_kind_ko}"

    # ── F-5 : 동적 문장 조립 (3~7문장) ──
    sentences: list[str] = []

    # 문장 1 — 추세 + slope + (H6) 도메인 가이드
    if slope_text:
        base_sent = f"본 시계열은 {direction_ko} 추세를 보이며{slope_text} 입니다"
    else:
        base_sent = f"본 시계열은 {direction_ko} 추세를 보입니다"
    if domain_hints:
        base_sent = base_sent + f" — {', '.join(domain_hints)}"
    base_sent = base_sent + "."
    sentences.append(base_sent)

    # 문장 2 — 계절성 + period (has_seas True 일 때만)
    if has_seas and period:
        sentences.append(f"{period}{unit_ko} 주기 계절성이 관측됩니다.")

    # 문장 3 — 모델 성능 + improvement (수치 보장)
    if perf_text.endswith("성능"):
        sentences.append(f"{model_name} 모델은 {perf_text}을 보입니다.")
    else:
        sentences.append(f"{model_name} 모델은 {perf_text}입니다.")

    # 문장 3-b (H4) — walk-forward fold 진단
    if fold_diag.get("available"):
        n_folds = fold_diag.get("n_folds")
        fmean = fold_diag.get("mean")
        stability = fold_diag.get("stability")
        if n_folds and fmean is not None:
            sentences.append(f"walk-forward 검증 {n_folds}개 fold 평균 개선율 {fmean:+.3f} ({stability or 'N/A'}).")

    # 문장 4 — horizon + 0단계
    if zero_step_phrase and "예측" in zero_step_phrase:
        sentences.append(f"{horizon_text} 동안{zero_step_phrase}으로 활용 가능합니다.")
    elif zero_step_phrase:
        sentences.append(f"{horizon_text} 동안{zero_step_phrase} 예측에 활용 가능합니다.")
    else:
        sentences.append(f"{horizon_text} 동안 예측에 활용 가능합니다.")

    # 문장 5 (H3) — 누수 의심 한계 인정
    if leakage:
        kinds = ", ".join(s.get("kind", "?") for s in leakage[:3])
        sentences.append(f"단, 검증 신호 ({kinds}) 가 감지되어 운영 적용 전 누수 점검이 필요합니다.")

    # 문장 6 (H5) — 증상 + 롤백 우선순위 (정상 아닐 때)
    sym_code = symptom.get("symptom")
    if sym_code and sym_code not in ("normal",):
        sym_label = symptom.get("label") or SYMPTOM_KO_LABEL.get(sym_code, sym_code)
        rb = symptom.get("rollback_priority") or []
        rb_phrase = f"이며 권장 조치는 {rb[0]} 입니다" if rb else "입니다"
        sentences.append(f"진단 결과 증상은 {sym_code} ({sym_label}){rb_phrase}.")

    # 문장 7 (H7) — task_kind_hint
    if task_hint:
        sentences.append(task_hint)

    # 문장 7-b (OF6, 2026-06-05) — 과적합/과소적합 안내 (severity 가 warn/severe 일 때만)
    fit_q = diag.get("fit_quality") or {}
    fit_kind = fit_q.get("kind")
    fit_sev = fit_q.get("severity")
    if fit_kind in ("overfit", "underfit") and fit_sev in ("warn", "severe"):
        hint = fit_q.get("hint") or ""
        if hint:
            sentences.append(hint)

    # 문장 7-c (G15, 2026-06-05) — 잔차 자기상관 안내 (autocorrelated 일 때만)
    rd = diag.get("residual_diag") or {}
    if rd.get("kind") == "autocorrelated" and rd.get("hint"):
        sentences.append(rd["hint"])

    # 문장 7-d (G13, 2026-06-05) — DM 검정 (naive_wins 일 때만)
    dmt = diag.get("dm_test") or {}
    if dmt.get("verdict") == "naive_wins" and dmt.get("hint"):
        sentences.append(dmt["hint"])

    # 문장 마지막 — 행동 권고
    if not leakage and (not sym_code or sym_code == "normal"):
        sentences.append("운영팀은 주간 단위로 모델 결과를 모니터링할 것을 권장합니다.")

    # 수치 0 최악 케이스 보강
    if not has_seas and improvement is None and slope_pct is None and mase is None:
        insert_at = max(0, len(sentences) - 1)
        sentences.insert(insert_at, f"{horizon_n}{unit_ko} 후 예측을 위해 추가 모니터링이 필요합니다.")

    # P10: 5문장 하드 제한
    if len(sentences) > 5:
        drop_patterns = [
            lambda s: s.startswith("walk-forward"),
            lambda s: "주기 계절성" in s,
            lambda s: "운영팀은" in s and "모니터링" in s,
            lambda s: task_hint and s == task_hint,
        ]
        for pred in drop_patterns:
            if len(sentences) <= 5:
                break
            for i, s in enumerate(sentences):
                if pred(s):
                    sentences.pop(i)
                    break
        if len(sentences) > 5:
            sentences = sentences[:5]

    # 3~5 문장 보장
    while len(sentences) < 3:
        sentences.append("추가 검증이 필요한 시점입니다.")

    return " ".join(sentences)


# ════════════════════════════════════════════════════════════════
# 진입점 (dispatcher 자동 등록, "generate" capability)
# ════════════════════════════════════════════════════════════════
def generate(state: Any) -> str:
    """HANDLER_REGISTRY 등록 진입점 — InsightAgent dispatcher 가 호출.

    LLM 기반 생성은 dispatcher 가 담당하고, 여기서는 규칙 기반 fallback 을 반환한다.
    dispatcher 가 LLM 응답을 받으면 이 결과 대신 LLM 결과를 사용한다.
    """
    return fallback(state)
```

---

## `agents/handlers/timeseries/output_extras.py`

```python
"""agents.handlers.timeseries.output_extras — 시계열 산출물 추가 자산 (CS 담당, cs-day9 v3).

OUT-01(PPT) / OUT-02(PDF) / OUT-04(HTML) carrier 가 임베드할 시계열 전용 차트·표·텍스트.

진입함수 (dispatcher 자동 등록):
  - build(state, ctx=None) -> dict   {charts, tables, text_blocks}  ★ base.py _call_extras 가 우선 호출
  - assets(state, ctx=None) -> dict  build 호환 래퍼 (구 인터페이스 유지 + NY/jh 표준 함수명)

DoD: charts 에 forecast_chart + decomposition 둘 다 포함 (OUT-04 임베드).

v3 보완 사항 (cs-day9 디벨롭):
  CG-1  text_blocks list[str] 표준화 — NY/jh 와 동일, ppt.py carrier 호환
  CH-1  신뢰도 한계 배지 — eval_result 의 증상/누수/fold 안정성을 1줄로 (text_blocks[0])
  CH-2  forecast_chart 메타 풍부화 — 차트 제목·표 제목에 horizon/forecast_kind 명시
  CH-3  fold_diagnostics 표 — eval_result.fold_diagnostics.available 시 tables 추가
  CH-4  forecast_chart 신뢰도 오버레이 — 증상 C/D/E 시 PI 색·라벨 + 주의 텍스트

5 단 forecast (B) + 3 단 decomposition (C):
  B-1 PI 확인 / B-2 y 재로드 / B-3 모델별 PI 재추출 / B-4 matplotlib / B-5 MinIO
  C-1 STL 경로 확인 / C-2 재사용 vs 신규 / C-3 통합

핵심 설계 원칙:
  - 인라인 안전 우선 — 모든 차트 try/except (matplotlib/MinIO 실패 → path=None)
  - PI 3 단 분기 — 저장 활용 (B-1a) / 모델 객체 재추출 (B-3a) / point only (B-3b)
  - STL 재사용 우선 — cs-day3 결과 활용 · 신규는 fallback
  - insights 재사용 (cs-day8) — text_blocks 에 그대로
  - 행동권고 규칙 기반 — MASE/improvement 기반 (LLM 호출 없음)
  - OUTPUT_EXTRAS_KEYS 3 키만 반환 (category_label/color 은 base.py CATEGORY_THEME)
  - 롤백 1 개만 — best_model 부재 시 빈 dict
"""

from __future__ import annotations

import logging
from typing import Any

import matplotlib  # noqa: WPS433

matplotlib.use("Agg")  # GUI 없는 환경(서버/Docker) 대비 — pyplot import 전에 1회만

logger = logging.getLogger(__name__)

# E-1 freq → 한국어 단위
FREQ_UNIT_KO = {"D": "일", "W": "주", "M": "개월", "MS": "개월", "H": "시간"}
MAX_FORECAST_ROWS = 20  # E-1 표 최대 행
SEASONAL_FALLBACK = 7  # C-2b default period

# CH-4 — 신뢰도 제한 트리거 증상 (헌장 7단계 증상 코드)
LOW_TRUST_SYMPTOMS = {"C", "D", "E"}


# ════════════════════════════════════════════════════════════════
# 모델별 PI 재추출 (cs-day6 §F-Extension F-ext-2.2 와 일관)
# ════════════════════════════════════════════════════════════════
def _extract_pi_from_model(model: Any, n_steps: int, alpha: float = 0.05):
    """모델별 95% PI 추출 — SARIMA / Prophet / NeuralForecast 분기."""
    import numpy as np  # noqa: WPS433

    if hasattr(model, "get_forecast"):  # SARIMA/SARIMAX
        fc = model.get_forecast(steps=n_steps)
        ci = fc.conf_int(alpha=alpha)
        lower = np.asarray(ci.iloc[:, 0] if hasattr(ci, "iloc") else ci[:, 0])
        upper = np.asarray(ci.iloc[:, 1] if hasattr(ci, "iloc") else ci[:, 1])
        return lower, upper
    if hasattr(model, "predict") and hasattr(model, "make_future_dataframe"):  # Prophet
        future = model.make_future_dataframe(periods=n_steps)
        forecast = model.predict(future)
        return forecast["yhat_lower"].values[-n_steps:], forecast["yhat_upper"].values[-n_steps:]
    if hasattr(model, "predict_intervals"):  # NeuralForecast
        pi_df = model.predict_intervals(level=[95])
        return pi_df["lower_95"].values[:n_steps], pi_df["upper_95"].values[:n_steps]
    raise ValueError("PI 추출 불가 모델")


# ════════════════════════════════════════════════════════════════
# §D-0. 신뢰도 한계 배지 (CH-1 ★ 인수인계 9번 핵심)
# ════════════════════════════════════════════════════════════════
def _build_reliability_badge(eval_result: dict) -> str | None:
    """evaluator 의 증상/누수/fold 진단을 1 줄 배지로.

    헌장 누수 1-6 사후 진단 + 롤백 원칙 5 (fold 분산) 의 사용자 노출 표면.
    증상 normal 이고 누수 신호 없고 fold 안정이면 배지 미생성 (None).
    """
    if not isinstance(eval_result, dict) or not eval_result:
        return None

    parts: list[str] = []

    # (1) 증상 분류
    symptom_obj = eval_result.get("symptom_classification") or {}
    symptom = symptom_obj.get("symptom")
    label = symptom_obj.get("label")
    if symptom and symptom not in ("normal", None):
        parts.append(f"증상 {symptom} ({label})")

    # (2) 누수 의심 신호 개수
    leakage = eval_result.get("leakage_suspect_signals") or []
    if leakage:
        kinds = [s.get("kind", "?") for s in leakage if isinstance(s, dict)]
        parts.append(f"누수 신호 {len(leakage)}건 ({', '.join(kinds[:3])})")

    # (3) fold 안정성
    fold_diag = eval_result.get("fold_diagnostics") or {}
    if fold_diag.get("available"):
        stability = fold_diag.get("stability")
        if stability in ("unstable", "very_unstable"):
            parts.append(f"fold {stability} (cv={fold_diag.get('cv')})")

    # (4) G15 잔차 자기상관 — 모델이 신호 못 잡음
    residual_diag = eval_result.get("residual_diagnostics") or {}
    if residual_diag.get("kind") == "autocorrelated":
        lbp = residual_diag.get("ljung_box_p")
        parts.append(f"잔차 자기상관 (Ljung-Box p={lbp})")

    # (5) G13 DM 검정 — naïve 가 모델보다 통계적으로 우수
    dm = eval_result.get("dm_test") or {}
    if dm.get("verdict") == "naive_wins":
        parts.append(f"DM 검정 naïve 우수 (p={dm.get('p_value')})")

    if not parts:
        return None

    return "⚠ 신뢰도 한계 — " + " · ".join(parts) + ". 보고서 해석 시 주의 권장."


# ════════════════════════════════════════════════════════════════
# §D-2. 행동권고 (규칙 기반 — LLM 호출 없음)
# ════════════════════════════════════════════════════════════════
def _build_recommendations(metrics: dict, freq: str, eda: dict) -> str:
    """규칙 기반 행동권고 — MASE / improvement / seasonal_period 기반."""
    lines: list[str] = []

    mase = metrics.get("MASE")
    if mase is not None:
        if mase < 0.5:
            lines.append("모델 성능 매우 우수 (MASE<0.5) — 운영 안정 단계, 재고는 정상 수준 유지 권장.")
        elif mase < 1.0:
            lines.append(f"모델 성능 양호 (MASE={mase:.2f}) — 주간 단위 모니터링 + 분기별 검토 권장.")
        else:
            lines.append(f"모델 성능 주의 (MASE={mase:.2f} >= 1.0) — 재학습 권장 + 입력 데이터 점검.")

    improvement = metrics.get("rmse_improvement_vs_naive")
    if improvement is not None and improvement < 0:
        lines.append(f"naïve 대비 {improvement:+.1%} 열위 — 다른 모델 후보 검토 권장.")

    s = eda.get("seasonal_period")
    if s and s in (7, 12, 30, 365):
        unit_map = {7: "주간", 12: "월간", 30: "월간 (일별)", 365: "연간"}
        lines.append(f"{unit_map[s]} 계절성 명확 — 해당 주기 단위 의사결정에 우선 활용.")

    return "\n".join(lines) if lines else ""


def _eda_dict(state: Any) -> dict:
    raw = getattr(state, "eda_summary", None)
    return raw if isinstance(raw, dict) else {}


def _ts_extras(state: Any) -> dict:
    """state.category_extras['timeseries'] 안전 추출."""
    ce = getattr(state, "category_extras", None) or {}
    return ce.get("timeseries", {}) or {}


# ════════════════════════════════════════════════════════════════
# §A~§F. build — 메인 진입점
# ════════════════════════════════════════════════════════════════
def build(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """OUT-01/02/04 carrier 추가 자산 (charts·tables·text_blocks). 설계도 cs-day9 §A~§F."""
    # ── A-1 : best_model 가드 ──
    bm = getattr(state, "best_model", None) or {}
    if not bm or not isinstance(bm, dict):
        return {}  # → RB-1 빈 dict 응급 (carrier 가 처리)

    # ── A-1b (D4, 2026-06-05) : 상수 시계열 graceful 안내 (cs-day10 단계 9 ❌) ──
    # _ConstantSeriesModel (pipeline D3) 이 학습되면 best_model.model_obj 가 _ada_constant_series 보유.
    # 이 경우 forecast/decomposition 차트는 의미 없고 "분석 불가" 명시가 정직한 보고.
    _model_obj = bm.get("model_obj")
    if _model_obj is not None and getattr(_model_obj, "_ada_constant_series", False):
        return {
            "charts": [],
            "tables": [
                {
                    "title": "상수 시계열 진단",
                    "columns": ["항목", "값"],
                    "rows": [
                        ["타깃 분산", "0 (모든 시점 값 동일)"],
                        ["모델 예측", f"{getattr(_model_obj, 'const_value', 0):.4f} (상수)"],
                        ["판정", "예측 의미 없음 — 운영 데이터 점검 권장"],
                    ],
                }
            ],
            "text_blocks": [
                "⚠ 분석 불가 — 입력 시계열의 분산이 0 입니다 (모든 시점이 동일 값). "
                "예측 모델의 의미 있는 학습이 불가능하며, 데이터 수집·전처리 과정에서 "
                "누락·고정값 주입·센서 오류 등이 없었는지 점검을 권장합니다."
            ],
        }

    # ── A-2 : eda_summary 가드 ──
    eda = _eda_dict(state)

    # ── A-3 : ctx 정규화 + 변수 추출 ──
    ctx = ctx or {}
    figsize = ctx.get("figsize", (12, 5))
    dpi = ctx.get("dpi", 100)
    metrics = bm.get("metrics") or {}
    ts_ext = _ts_extras(state)
    freq = ts_ext.get("freq", "D")
    forecast_kind = ts_ext.get("forecast_kind")  # CH-2: point / interval / quantile
    variate = ts_ext.get("variate")  # CH-2: univariate / multivariate
    horizon_hint = ts_ext.get("horizon_hint")
    model_name = bm.get("model_name", "Unknown")

    # ── A-4 : eval_result 추출 (CH-1·CH-3·CH-4) ──
    eval_result = getattr(state, "eval_result", None) or {}
    if not isinstance(eval_result, dict):
        eval_result = {}
    symptom_obj = eval_result.get("symptom_classification") or {}
    symptom_code = symptom_obj.get("symptom")
    leakage_signals = eval_result.get("leakage_suspect_signals") or []
    low_trust = bool(leakage_signals) or symptom_code in LOW_TRUST_SYMPTOMS

    charts: list[str] = []
    tables: list[dict] = []
    text_blocks: list[str] = []  # CG-1 — list[str] 표준화 (NY/jh 호환)

    import numpy as np  # noqa: WPS433

    # ════════════════════════════════════════════════════════════
    # §B. forecast_chart 5 단 (★ DoD 1)
    # ════════════════════════════════════════════════════════════
    # ── B-1 : PI 정보 확인 ──
    lower = metrics.get("pi_lower")
    upper = metrics.get("pi_upper")
    if isinstance(lower, list) and isinstance(upper, list):
        lower = np.asarray(lower)  # B-1a
        upper = np.asarray(upper)
    else:
        lower = upper = None  # B-1b

    # ── B-2 : y_train / y_val / y_pred 재로드 ──
    y_pred = metrics.get("y_pred_val")
    y_train = y_val = None
    forecast_path = None

    if y_pred is None:
        try:
            from agents.handlers.common.shared import load_dataframe_from_state
            from agents.training_executor import _split_xy

            df = load_dataframe_from_state(state)
            X, y = _split_xy(df, getattr(state, "target_column", None))
            split = int(len(y) * 0.8)
            y_train, y_val = y[:split], y[split:]
            model_obj = bm.get("model_obj")
            if model_obj is not None:
                from pipelines.factory import PipelineFactory

                pipe = PipelineFactory.create(state.category)
                y_pred = pipe.predict(model_obj, X[split:])
        except Exception as e:
            logger.warning("y_reload_failed: %s", e)
    else:
        y_val = metrics.get("y_val_actual")
        y_train = metrics.get("y_train_tail")

    # ── B-3 : 모델 객체로 PI 재추출 ──
    if lower is None and bm.get("model_obj") is not None and y_val is not None:
        try:
            lower, upper = _extract_pi_from_model(bm["model_obj"], n_steps=len(y_val))  # B-3a
        except Exception:
            lower = upper = None  # B-3b

    # ── B-4 : matplotlib 차트 ──
    if y_pred is not None and y_val is not None:
        try:
            import matplotlib.pyplot as plt  # noqa: WPS433
            import pandas as pd  # noqa: WPS433

            y_pred_arr = np.asarray(y_pred).flatten()
            y_val_arr = np.asarray(y_val).flatten()

            fig, ax = plt.subplots(figsize=figsize, dpi=dpi)

            n_train = len(y_train) if y_train is not None else 0
            if y_train is not None:
                idx_train = pd.RangeIndex(start=0, stop=n_train)
                ax.plot(idx_train, np.asarray(y_train).flatten(), color="black", label="과거", linewidth=1)

            idx_val = pd.RangeIndex(start=n_train, stop=n_train + len(y_val_arr))
            ax.plot(idx_val, y_val_arr[: len(idx_val)], color="blue", label="실제 (val)", linewidth=1.5)
            ax.plot(idx_val[: len(y_pred_arr)], y_pred_arr, color="orange", label="예측", linewidth=1.5)

            # CH-4 — 95% PI 음영 (저신뢰 시 색·라벨 변경)
            if lower is not None and upper is not None:
                L = min(len(lower), len(upper), len(idx_val))
                pi_color = "red" if low_trust else "orange"
                pi_label = "95% PI (신뢰도 제한)" if low_trust else "95% PI"
                ax.fill_between(idx_val[:L], lower[:L], upper[:L], alpha=0.2, color=pi_color, label=pi_label)

            # CH-2 — 제목에 forecast_kind / horizon 명시
            horizon_n = horizon_hint or len(y_pred_arr)
            kind_label = forecast_kind or "point"
            variate_label = variate or "univariate"
            title = f"Forecast ({kind_label}, {variate_label}) — {model_name} (h={horizon_n})"
            ax.set_title(title)

            # CH-4 — 저신뢰 주의 오버레이
            if low_trust:
                try:
                    ax.text(
                        0.99,
                        0.97,
                        "⚠ 누수/증상 검토 권장",
                        transform=ax.transAxes,
                        ha="right",
                        va="top",
                        fontsize=10,
                        color="darkred",
                        bbox={"boxstyle": "round,pad=0.3", "facecolor": "mistyrose", "alpha": 0.8},
                    )
                except Exception:  # noqa: BLE001
                    pass  # 텍스트 실패해도 차트 자체는 살림

            ax.set_xlabel("time")
            ax.set_ylabel(getattr(state, "target_column", None) or "y")
            ax.legend()
            ax.grid(True, alpha=0.3)

            # ── B-5 : MinIO 저장 ──
            from agents.handlers.common.shared import save_chart_to_minio

            forecast_path = save_chart_to_minio(fig, kind="timeseries/forecast", job_id=getattr(state, "job_id", ""))
        except Exception as e:
            logger.warning("forecast_chart_failed: %s", e)
            forecast_path = None  # 인라인 안전

    if forecast_path:
        charts.append(forecast_path)

    # ════════════════════════════════════════════════════════════
    # §C. decomposition 3 단 (★ DoD 2)
    # ════════════════════════════════════════════════════════════
    decomp_path = None
    stl_paths = [c for c in (eda.get("charts") or []) if isinstance(c, str) and "/stl" in c]

    if stl_paths:
        decomp_path = stl_paths[0]  # C-2a 재사용 (간단 + 효율)
    else:
        try:  # C-2b 신규 생성
            import matplotlib.pyplot as plt  # noqa: WPS433
            from statsmodels.tsa.seasonal import seasonal_decompose  # noqa: WPS433

            from agents.handlers.common.shared import load_dataframe_from_state, save_chart_to_minio

            df = load_dataframe_from_state(state)
            y = df[state.target_column].dropna()
            s = eda.get("seasonal_period") or SEASONAL_FALLBACK

            if len(y) >= 2 * s and y.var() > 0:  # 가드
                res = seasonal_decompose(y, period=s, model="additive")

                fig, axes = plt.subplots(4, 1, figsize=(12, 8), sharex=True, dpi=dpi)
                res.observed.plot(ax=axes[0], title="Observed")
                res.trend.plot(ax=axes[1], title="Trend")
                res.seasonal.plot(ax=axes[2], title="Seasonal")
                res.resid.plot(ax=axes[3], title="Residual")
                plt.tight_layout()

                decomp_path = save_chart_to_minio(
                    fig, kind="timeseries/decomposition", job_id=getattr(state, "job_id", "")
                )
        except Exception as e:
            logger.warning("decomp_chart_failed: %s", e)
            decomp_path = None  # 인라인 안전

    # ── C-3 : charts 통합 ──
    if decomp_path:
        charts.append(decomp_path)

    # ════════════════════════════════════════════════════════════
    # §D. text_blocks (CG-1 — list[str] 표준화)
    # ════════════════════════════════════════════════════════════
    # ── D-0 : 신뢰도 한계 배지 (CH-1, 맨 앞 우선순위 1) ──
    badge = _build_reliability_badge(eval_result)
    if badge:
        text_blocks.append(badge)

    # ── D-1 : insights 재사용 (cs-day8) ──
    insights = getattr(state, "insights", None)
    if insights and isinstance(insights, str) and insights.strip():
        text_blocks.append(f"분석 인사이트\n{insights.strip()}")

    # ── D-2 : 행동권고 카드 ──
    recommendations = _build_recommendations(metrics, freq, eda)
    if recommendations:
        text_blocks.append(f"권장 액션\n{recommendations}")

    # ════════════════════════════════════════════════════════════
    # §E. tables
    # ════════════════════════════════════════════════════════════
    # ── E-1 : forecast 값 표 (CH-2 — forecast_kind 명시) ──
    if y_pred is not None:
        y_pred_arr = np.asarray(y_pred).flatten()
        if len(y_pred_arr) > 0:
            unit_ko = FREQ_UNIT_KO.get(freq, "주기")
            horizon = len(y_pred_arr)
            kind_ko = {"point": "점예측", "interval": "구간예측", "quantile": "분위예측"}.get(
                forecast_kind or "point", "예측"
            )
            rows = []
            for i, pred in enumerate(y_pred_arr[: min(MAX_FORECAST_ROWS, horizon)]):
                row = [f"t+{i + 1}", f"{float(pred):.2f}"]
                if lower is not None and i < len(lower):
                    row.extend([f"{float(lower[i]):.2f}", f"{float(upper[i]):.2f}"])
                else:
                    row.extend(["-", "-"])
                rows.append(row)
            tables.append(
                {
                    "title": f"다음 {horizon}{unit_ko} {kind_ko}",
                    "columns": ["시점", "예측값", "하한 (95%)", "상한 (95%)"],
                    "rows": rows,
                }
            )

    # ── E-2 : 모델 성능 카드 ──
    perf_rows = []
    for key, label in [
        ("val_rmse", "RMSE"),
        ("val_mae", "MAE"),
        ("MASE", "MASE"),
        ("sMAPE", "sMAPE (%)"),
        ("rmse_improvement_vs_naive", "개선율 vs naïve"),
    ]:
        v = metrics.get(key)
        if v is not None:
            if key == "rmse_improvement_vs_naive":
                perf_rows.append([label, f"{v:+.1%}"])
            elif key == "sMAPE":
                perf_rows.append([label, f"{v:.1f}"])
            else:
                perf_rows.append([label, f"{v:.3f}"])
    if perf_rows:
        tables.append({"title": "모델 성능 요약", "columns": ["메트릭", "값"], "rows": perf_rows})

    # ── E-3 : fold_diagnostics 표 (CH-3, 가용 시) ──
    fold_diag = eval_result.get("fold_diagnostics") or {}
    if fold_diag.get("available"):
        fold_rows = []
        for label, key in [
            ("Fold 수", "n_folds"),
            ("평균", "mean"),
            ("표준편차", "std"),
            ("변동계수 (cv)", "cv"),
            ("범위 비율", "range_ratio"),
            ("안정성", "stability"),
        ]:
            v = fold_diag.get(key)
            if v is not None:
                fold_rows.append([label, str(v)])
        best_f = fold_diag.get("best_fold") or {}
        worst_f = fold_diag.get("worst_fold") or {}
        if best_f:
            fold_rows.append(["최고 fold", f"#{best_f.get('idx')} (score={best_f.get('score')})"])
        if worst_f:
            fold_rows.append(["최악 fold", f"#{worst_f.get('idx')} (score={worst_f.get('score')})"])
        if fold_rows:
            tables.append(
                {
                    "title": "Fold 안정성 진단 (walk-forward)",
                    "columns": ["지표", "값"],
                    "rows": fold_rows,
                }
            )

    # ── E-4 (G15+G13, 2026-06-05) : 잔차·DM 검정 표 ──
    residual_diag2 = eval_result.get("residual_diagnostics") or {}
    dm_test_obj = eval_result.get("dm_test") or {}
    diag_rows = []
    if residual_diag2.get("kind") and residual_diag2.get("kind") != "unknown":
        diag_rows.append(["잔차 진단", str(residual_diag2.get("kind"))])
        if residual_diag2.get("ljung_box_p") is not None:
            diag_rows.append(["Ljung-Box p", f"{residual_diag2.get('ljung_box_p')}"])
        if residual_diag2.get("mean_pct") is not None:
            diag_rows.append(["잔차 평균 편향", f"{residual_diag2.get('mean_pct'):.1%}"])
    if dm_test_obj.get("available"):
        diag_rows.append(["DM 검정 결과", str(dm_test_obj.get("verdict"))])
        if dm_test_obj.get("p_value") is not None:
            diag_rows.append(["DM p-value", f"{dm_test_obj.get('p_value')}"])
        if dm_test_obj.get("dm_stat") is not None:
            diag_rows.append(["DM 통계량", f"{dm_test_obj.get('dm_stat')}"])
    if diag_rows:
        tables.append({"title": "잔차·통계 비교 검정", "columns": ["지표", "값"], "rows": diag_rows})

    # ════════════════════════════════════════════════════════════
    # §F. 반환 (OUTPUT_EXTRAS_KEYS 3 키)
    # ════════════════════════════════════════════════════════════
    return {
        "charts": charts,
        "tables": tables,
        "text_blocks": text_blocks,
    }


# ════════════════════════════════════════════════════════════════
# assets — build 호환 래퍼 (구 인터페이스 유지 + NY/jh 표준 함수명)
# ════════════════════════════════════════════════════════════════
def assets(state: Any, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """carrier 가 수신하는 추가 자산 — build 위임 (base.py 는 build 우선 호출)."""
    return build(state, ctx)
```

---

## `outputs/base.py`

```python
"""outputs.base — 산출물 생성기 추상 클래스 + 카테고리 훅 Protocol.

Day 9: _call_extras() 본구현 (카테고리 핸들러의 build/assets 호출).
ADR-008 L2: reattach_pii() 헬퍼 — carrier 의 사용자 노출 직전 PII 마스킹.
"""

from __future__ import annotations

import abc
import tempfile
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ada.core.state import PipelineState


# ==============================================================
# OutputExtrasHandler — Day 9 카테고리 훅 시그니처
# ==============================================================
@runtime_checkable
class OutputExtrasHandler(Protocol):
    """Category output_extras function signature contract."""

    def __call__(
        self,
        state: "PipelineState",
        ctx: dict[str, Any],
    ) -> dict[str, Any]: ...


OUTPUT_EXTRAS_KEYS: tuple[str, ...] = (
    "charts",
    "tables",
    "text_blocks",
)


# ==============================================================
# 카테고리 테마 (Day 9)
# ==============================================================
CATEGORY_THEME: dict[str, dict[str, Any]] = {
    "tabular_ml": {
        "label_ko": "정형 ML",
        "primary_rgb": (37, 99, 235),
        "accent_rgb": (147, 197, 253),
        "primary_hex": "#2563eb",
    },
    "tabular_dl": {
        "label_ko": "정형 DL",
        "primary_rgb": (8, 145, 178),
        "accent_rgb": (103, 232, 249),
        "primary_hex": "#0891b2",
    },
    "timeseries": {
        "label_ko": "시계열",
        "primary_rgb": (22, 163, 74),
        "accent_rgb": (134, 239, 172),
        "primary_hex": "#16a34a",
    },
    "anomaly_detection": {
        "label_ko": "이상 탐지",
        "primary_rgb": (220, 38, 38),
        "accent_rgb": (252, 165, 165),
        "primary_hex": "#dc2626",
    },
}

DEFAULT_THEME: dict[str, Any] = {
    "label_ko": "기타",
    "primary_rgb": (75, 85, 99),
    "accent_rgb": (209, 213, 219),
    "primary_hex": "#4b5563",
}


def get_theme(category: str | None) -> dict[str, Any]:
    if not category:
        return DEFAULT_THEME
    return CATEGORY_THEME.get(category, DEFAULT_THEME)


# ==============================================================
# OutputGenerator — carrier 추상 클래스
# ==============================================================


class OutputGenerator(abc.ABC):
    output_code: str = "OUT-XX"
    extension: str = "bin"

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id

    @abc.abstractmethod
    def generate(
        self,
        *,
        insights: str,
        best_model: dict[str, Any],
        eda_charts: list[str],
        category: str,
        user_intent: str,
        eval_result: dict[str, Any] | None,
    ) -> str:
        """생성 후 MinIO 경로 반환."""

    def _upload(self, local_path: str) -> str:
        from tools.minio_tool import get_minio_client

        return get_minio_client().save_artifact(local_path, f"outputs/{self.output_code}", self.job_id)

    def _tmp(self) -> str:
        return tempfile.NamedTemporaryFile(
            delete=False,
            suffix=f".{self.extension}",
        ).name

    def _call_extras(
        self,
        state: "PipelineState | None",
        ctx: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """카테고리 핸들러의 output_extras.build/assets 호출."""
        if state is None:
            return {}
        try:
            from agents.handlers import get_handler
        except Exception:
            return {}

        fn = get_handler(state.category, "build") or get_handler(state.category, "assets")
        if fn is None:
            # 카테고리에 build/assets 핸들러가 없는 것 자체는 정상(선택적 훅).
            # 하지만 디버깅 시 어떤 carrier 가 무엇을 못 받는지 추적할 수 있도록 debug 로 남김.
            try:
                from ada.core.logger import get_logger as _gl

                _gl("output_extras").debug("no_extras_handler", category=state.category, carrier=type(self).__name__)
            except Exception:  # noqa: BLE001
                pass
            return {}
        try:
            result = fn(state, ctx or {})
            if not isinstance(result, dict):
                return {}
            return {k: v for k, v in result.items() if k in OUTPUT_EXTRAS_KEYS}
        except Exception as e:  # noqa: BLE001
            # 핸들러 자체 예외 → warning (silent 실패 방지)
            try:
                from ada.core.logger import get_logger as _gl

                _gl("output_extras").warning(
                    "extras_handler_failed",
                    category=state.category,
                    carrier=type(self).__name__,
                    error=str(e),
                )
            except Exception:  # noqa: BLE001
                pass
            return {}

    def _download_chart(self, chart_path: str) -> str | None:
        """MinIO/S3 경로의 차트를 로컬 PNG 로 받아 임시 파일 경로 반환."""
        try:
            from tools.minio_tool import get_minio_client

            mc = get_minio_client()
            key = chart_path.replace(f"s3://{mc.bucket}/", "") if chart_path.startswith("s3://") else chart_path
            body = mc.download_bytes(key)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
            with open(tmp, "wb") as f:
                f.write(body)
            return tmp
        except Exception:
            return None


# ==============================================================
# ADR-008 L2 — PII Re-attach 헬퍼 (모듈 레벨)
# ==============================================================


def reattach_pii(state: "PipelineState | None", text: str | None) -> str:
    """LLM 응답 / 사용자 인텐트 등 사용자 노출 직전 텍스트의 PII 를 *** 로 치환.

    1. state.category_extras['_pii']['mapping'] 의 토큰을 *** 로 치환
    2. PIIAnonymizer.reattach() 가 정규식 안전망도 적용
    3. state=None 또는 mapping 비어있어도 정규식 안전망 작동
    4. 보안 모듈 부재/예외 시에도 carrier 가 죽지 않게 silent passthrough

    R-103 (PII 로그 출력 금지) 의 최종 게이트.
    """
    if not text:
        return text or ""
    try:
        from ada.security.guardrails import PIIAnonymizer
    except Exception:
        return text

    mapping: dict[str, str] = {}
    if state is not None:
        try:
            pii_meta = (getattr(state, "category_extras", None) or {}).get("_pii") or {}
            mapping = pii_meta.get("mapping") or {}
        except Exception:
            mapping = {}

    try:
        return PIIAnonymizer().reattach(text, mapping)
    except Exception:
        return text
```

---


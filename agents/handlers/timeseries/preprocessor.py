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


def _ccf_top_lags(state: Any) -> dict[str, int]:
    """P4 (2026-06-14) — profiler.ccf_top_lags 추출. {col_name: best_lag}."""
    try:
        profile = getattr(state, "data_profile", None) or {}
        if not isinstance(profile, dict):
            return {}
        ccf_meta = profile.get("ccf_top_lags")
        if not isinstance(ccf_meta, dict):
            inner = profile.get("ccf_leakage")
            ccf_meta = inner.get("ccf_top_lags") if isinstance(inner, dict) else None
        if not isinstance(ccf_meta, dict):
            return {}
        out: dict[str, int] = {}
        for col, meta in ccf_meta.items():
            if isinstance(meta, dict):
                lag = int(meta.get("lag") or 0)
                if lag >= 1:
                    out[col] = lag
        return out
    except (TypeError, AttributeError, ValueError):
        return {}


def _is_multiplicative(state: Any) -> bool:
    """P3 (2026-06-14) — profiler.multiplicative.is_multiplicative 신호 추출."""
    try:
        profile = getattr(state, "data_profile", None) or {}
        if not isinstance(profile, dict):
            return False
        mult = profile.get("multiplicative")
        return bool(mult.get("is_multiplicative")) if isinstance(mult, dict) else False
    except (TypeError, AttributeError):
        return False


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

    # Phase 2: 비정상 or 계절성 있을 때 분산 안정화 (P3 — multiplicative 도 트리거)
    is_multi = _is_multiplicative(state)
    if not stationary or period is not None or is_multi:
        bc_step: dict[str, Any] = {
            "name": "boxcox",
            "shift_min": True,
            "lambda_clip": (-5.0, 5.0),
            "fallback": "log1p",
            "leakage_safe": True,
            "needs_review": True,
        }
        if is_multi:
            # P3 — 승법 구조 명시 → lambda=0 (log) 강제
            bc_step["force_lambda"] = 0.0
            bc_step["reason"] = "multiplicative — log 변환 강제 (P3)"
        steps.append(bc_step)

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
        # P4 (2026-06-14) — CCF top_lags 자동 병합 (외생변수 시차 자동화)
        ccf_lags_map = _ccf_top_lags(state)
        exog_lags = list(lags)
        h_guard = max(1, _horizon(state))
        for col, ccf_lag in ccf_lags_map.items():
            if col in exog_cols and ccf_lag >= h_guard and ccf_lag not in exog_lags:
                exog_lags.append(ccf_lag)
        exog_lags = sorted(set(exog_lags))[:8]  # 과적합 방어 — 최대 8개
        steps.append(
            {
                "name": "exog",
                "columns": exog_cols,
                "lags": exog_lags,
                "rolling_windows": exog_windows or [7],
                "leakage_safe": True,
                "needs_review": False,
                "ccf_lags_used": {c: ccf_lags_map[c] for c in ccf_lags_map if c in exog_cols},
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

    # ★ 누수 1-3 차단: boxcox λ 를 "학습 구간만으로" 추정하기 위한 train_ratio 도출.
    #   분할 비율은 plan 의 time_order_split.test_ratio(없으면 0.2)에서 가져와
    #   train_ratio = 1 - test_ratio. 동일 step 이 Phase 8 에서 실제 분할에도 쓰이므로
    #   λ 추정 경계와 평가 분할 경계가 자연히 일치한다(스플릿 정합).
    _train_ratio: float | None = None
    try:
        _test_ratio = 0.2
        for _st in plan_steps:
            if _st.get("name") == "time_order_split":
                _test_ratio = float(_st.get("test_ratio", 0.2))
                break
        if 0.0 < _test_ratio < 1.0:
            _train_ratio = 1.0 - _test_ratio
    except (TypeError, ValueError):
        _train_ratio = None

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
                    train_ratio=_train_ratio,
                    force_lambda=step.get("force_lambda"),  # P3 — multiplicative 시 lambda=0
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
    force_lambda: float | None = None,
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

        if force_lambda is not None:
            lam = float(force_lambda)  # P3 — multiplicative → lambda=0 (log) 강제
        else:
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
        drop_mask = out.iloc[:max_warmup][feature_cols].isna().any(axis=1)
        keep_idx = list(out.index[max_warmup:]) + list(out.index[:max_warmup][~drop_mask])
        out = out.loc[sorted(keep_idx)].reset_index(drop=True)
    elif strategy == "zero":
        fill_cols = feature_cols if not protect_target else [c for c in feature_cols if c != target]
        for col in fill_cols:
            out[col] = out[col].fillna(0.0)
    elif strategy == "none":
        pass
    else:
        logger.warning("fill_feature_nans: 알 수 없는 strategy=%r — none 처리", strategy)
    return out


def _apply_time_order_split(df: Any, test_ratio: float = 0.2, gap: int = 0) -> Any:
    """시간 순서 보존 분할 → _split 컬럼 ("train"|"gap"|"test")."""
    out = df.copy()
    n = len(out)
    split_idx = max(1, int(n * (1.0 - test_ratio)))
    gap_end = min(n, split_idx + gap)
    out["_split"] = "train"
    if gap > 0 and gap_end > split_idx:
        out.iloc[split_idx:gap_end, out.columns.get_loc("_split")] = "gap"
    out.iloc[gap_end:, out.columns.get_loc("_split")] = "test"
    return out

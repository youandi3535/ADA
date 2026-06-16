"""agents.handlers.anomaly.preprocessor — 이상탐지 전처리 (NY 담당, Day 2 v3).

3 단계 전처리: RobustScaler → Winsorize → PCA(95%)

진입함수 (dispatcher 자동 등록):
  - plan(state) -> list[dict]                메타
  - apply(df, plan_steps, state) -> (df, state)  학습 시 (HJ PR2 contract)
  - apply_transform(df, fitted_state) -> ndarray  추론 시 (학습/추론 일관성)

DoD: pytest 그린 + scaler 객체 보존 + 차원 축소된 행렬.

의심 검증 결과 (셜록홈즈):
  E-1·E-2·E-3 → apply_transform() 함수 추가
  B-1 → nearly_constant_cols 메타
  B-2 → Day 1 missing_ratio 활용 (30% 초과 컬럼 drop)
  B-3 → np.isfinite 가드
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ─────────────────────────────────────────────────────
DEFAULT_WINSOR_Q_LO = 0.01
DEFAULT_WINSOR_Q_HI = 0.99
DEFAULT_PCA_VARIANCE = 0.95
MIN_ROWS_FOR_PCA = 10
MISSING_RATIO_DROP_THRESHOLD = 0.3  # B-2
NEARLY_CONSTANT_RATIO = 0.05  # B-1
RANDOM_STATE = 42


# ── 공개 진입점 1: plan ───────────────────────────────────────────
def plan(state: Any) -> list[dict[str, Any]]:  # noqa: ARG001
    """전처리 계획 — 메타 정보."""
    return [
        {"name": "robust_scale", "needs_review": False},
        {
            "name": "winsorize",
            "quantile_low": DEFAULT_WINSOR_Q_LO,
            "quantile_high": DEFAULT_WINSOR_Q_HI,
            "needs_review": False,
        },
        {"name": "pca", "variance_ratio": DEFAULT_PCA_VARIANCE, "needs_review": False},
    ]


# ── 헬퍼: 빈 결과 ─────────────────────────────────────────────────
def _empty_result(
    state: Any,
    n_rows: int,
    reason: str,
    constant_cols_dropped: list[str] | None = None,
    high_missing_cols_dropped: list[str] | None = None,
) -> tuple[Any, Any]:
    import numpy as np
    import pandas as pd

    empty_df = pd.DataFrame(np.empty((n_rows, 0)))
    artifacts = {
        "n_rows_in": n_rows,
        "n_cols_in": 0,
        "n_cols_out": 0,
        "scaler": None,
        "winsor_limits": {},
        "pca": None,
        "feature_names_in": [],
        "feature_names_out": [],
        "dim_reduction_ratio": 0.0,
        "pca_components_used": 0,
        "applied_steps": [],
        "skipped_steps": [{"step": "all", "reason": reason}],
        "constant_cols_dropped": constant_cols_dropped or [],
        "nearly_constant_cols": [],
        "high_missing_cols_dropped": high_missing_cols_dropped or [],
        "inf_rows_dropped": 0,
        "has_time": False,
        "preprocessor_warnings": [reason],
        "input_encoding": {},
        "impute_medians": {},
    }
    extras = dict(state.category_extras or {})
    cat_block = dict(extras.get("anomaly_detection") or {})
    cat_block["preprocessor_artifacts"] = artifacts
    extras["anomaly_detection"] = cat_block
    return empty_df, state.with_update(category_extras=extras)


# ── 헬퍼: 거의-상수 컬럼 감지 (B-1) ──────────────────────────────
def _detect_nearly_constant(num_df: Any, threshold: float = NEARLY_CONSTANT_RATIO) -> list[str]:
    """변동률 < threshold 컬럼 식별 (drop 안 함, 알림용)."""
    nearly = []
    for c in num_df.columns:
        s = num_df[c].dropna()
        if len(s) == 0:
            continue
        most_common = s.value_counts(normalize=True).iloc[0]
        if most_common > (1 - threshold):
            nearly.append(str(c))
    return nearly


# ── 헬퍼: inf 행 제거 (B-3) ──────────────────────────────────────
def _validate_finite(num_df: Any) -> tuple[Any, int]:
    """inf/-inf 포함 행만 제거. NaN 은 보존(결측 처리 단계의 median 대체 대상).

    (G-2, 2026-06-16) 이전엔 np.isfinite 로 inf+NaN 행을 함께 제거해, 뒤따르는 결측
    대체가 무력화됐다. isinf 로 바꿔 결측 행을 median 단계까지 살린다. inf 가 없으면
    기존과 동일(무회귀).
    """
    import numpy as np

    if num_df.empty:
        return num_df, 0
    inf_mask = np.isinf(num_df.values).any(axis=1)  # NaN 은 inf 가 아니라 보존됨
    n_inf = int(inf_mask.sum())
    return num_df[~inf_mask], n_inf


# ── 헬퍼: 입력 견고화 (G-1, NY 2026-06-16) ───────────────────────
# "수치 컬럼만 취하고 나머지 폐기" → "문자로 들어온 숫자 복원 + 범주형 자동 인코딩"
# 으로 확장. 어떤 데이터(글자·기호·깨진값)가 와도 정보를 버리지 않는다.
# 설계 결정(에이전트 자동 판단, 사용자 개입 없음):
#   · object 컬럼만 추가 처리 — 수치/bool/datetime 경로는 손대지 않아 무회귀.
#   · 1순위 숫자 복원: '$1,234'·'1.2K'·'12%'·'1,234'·'(123)' 등 → 셀 80%+ 파싱되면 수치 편입.
#   · 2순위 범주형 → **빈도 인코딩**(컬럼명 보존). 이상탐지에서 희귀 범주가 자연히 큰
#     이상 신호가 되고, 원핫과 달리 차원이 안 터져 후단 PCA 와도 안전 → "정답에 가까운" 선택.
#   · 고카디널리티(>50, ID성)·상수 컬럼은 노이즈라 drop.
COERCE_SUCCESS_RATIO = 0.8
HIGH_CARDINALITY_DROP = 50


def _coerce_numeric_like(s: Any) -> Any:
    """문자로 들어온 숫자를 수치로 복원. 파싱 불가 셀은 NaN."""
    import pandas as pd

    txt = s.astype(str).str.strip()
    txt = txt.str.replace(r"^\((.*)\)$", r"-\1", regex=True)  # 회계식 음수 (123)→-123
    up = txt.str.upper()
    mult = pd.Series(1.0, index=s.index)
    mult[up.str.endswith("K")] = 1e3
    mult[up.str.endswith("M")] = 1e6
    mult[up.str.endswith("B")] = 1e9
    base = up.str.replace(r"[,$€£¥%\s]", "", regex=True).str.replace(r"(?<=[0-9])[KMB]$", "", regex=True)
    return pd.to_numeric(base, errors="coerce") * mult


def _robustify_input(df: Any, profile: dict | None = None) -> tuple[Any, dict[str, Any]]:
    """수치 + 복원숫자 + 빈도인코딩 범주형을 합친 견고한 수치 DataFrame 반환.

    반환: (num_df, input_encoding_meta). 수치만 있던 데이터면 결과는 기존과 동일(추가 0).
    """
    import pandas as pd

    out = df.copy()
    coerced_cols: list[str] = []
    freq_maps: dict[str, dict] = {}
    encoded_cols: list[str] = []
    dropped_high_card: list[str] = []

    for col in list(out.columns):
        s = out[col]
        # 수치/bool/datetime 은 기존 동작 그대로 (select_dtypes 가 처리) — 무회귀 핵심.
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s) or pd.api.types.is_datetime64_any_dtype(s):
            continue
        # 1순위: 문자로 들어온 숫자 복원
        coerced = _coerce_numeric_like(s)
        nonnull = int(s.notna().sum())
        if nonnull > 0 and (int(coerced.notna().sum()) / nonnull) >= COERCE_SUCCESS_RATIO:
            out[col] = coerced
            coerced_cols.append(str(col))
            continue
        # 2순위: 범주형 → 카디널리티 판단
        card = int(s.astype(str).nunique(dropna=True))
        if card <= 1:
            out = out.drop(columns=[col])
            continue
        if card > HIGH_CARDINALITY_DROP:
            out = out.drop(columns=[col])
            dropped_high_card.append(str(col))
            continue
        # 빈도 인코딩 (컬럼명 보존 → 후단 PCA·추론 일관성 안전)
        fmap = s.astype(str).value_counts(normalize=True).to_dict()
        out[col] = s.astype(str).map(fmap).fillna(0.0)
        freq_maps[str(col)] = fmap
        encoded_cols.append(str(col))

    import numpy as np

    num_df = out.select_dtypes(include=[np.number])
    meta = {
        "coerced_cols": coerced_cols,
        "freq_maps": freq_maps,
        "encoded_cols": encoded_cols,
        "dropped_high_card": dropped_high_card,
    }
    return num_df, meta


def _robustify_input_transform(df: Any, input_encoding: dict | None) -> Any:
    """추론 시 — 학습에서 결정된 복원/인코딩을 동일 적용 후 수치 DataFrame 반환."""
    import numpy as np

    if not input_encoding:
        return df.select_dtypes(include=[np.number])
    out = df.copy()
    for col in input_encoding.get("coerced_cols", []):
        if col in out.columns:
            out[col] = _coerce_numeric_like(out[col])
    for col, fmap in input_encoding.get("freq_maps", {}).items():
        if col in out.columns:
            out[col] = out[col].astype(str).map(fmap).fillna(0.0)  # unseen 범주 → 0
    return out.select_dtypes(include=[np.number])


# ── 헬퍼: RobustScaler ────────────────────────────────────────────
def _robust_scale(num_df: Any) -> tuple[Any, Any]:
    from sklearn.preprocessing import RobustScaler

    scaler = RobustScaler(quantile_range=(25.0, 75.0))
    X = scaler.fit_transform(num_df.values)
    return X, scaler


# ── 헬퍼: Winsorize ───────────────────────────────────────────────
def _winsorize(X, q_lo, q_hi, col_names):
    import numpy as np

    limits = {}
    X_out = X.copy()
    for j in range(X.shape[1]):
        lo = float(np.quantile(X[:, j], q_lo))
        hi = float(np.quantile(X[:, j], q_hi))
        X_out[:, j] = np.clip(X[:, j], lo, hi)
        col = col_names[j] if j < len(col_names) else f"col{j}"
        limits[col] = (lo, hi)
    return X_out, limits


# ── 헬퍼: PCA ─────────────────────────────────────────────────────
def _pca_reduce(X, variance_ratio=DEFAULT_PCA_VARIANCE):
    from sklearn.decomposition import PCA

    n_rows, n_cols = X.shape
    if n_cols < 2 or n_rows < MIN_ROWS_FOR_PCA:
        return X, None, n_cols
    pca = PCA(n_components=variance_ratio, random_state=RANDOM_STATE, svd_solver="full")
    X_reduced = pca.fit_transform(X)
    return X_reduced, pca, int(pca.n_components_)


# ── 공개 진입점 2: apply (학습 시) ────────────────────────────────
def apply(df: Any, plan_steps: list[dict] | None, state: Any) -> tuple[Any, Any]:  # noqa: ARG001
    """3 단계 전처리. (df, state) 튜플 반환 (HJ PR2 contract). 학습 시점에 사용."""
    import pandas as pd

    profile = getattr(state, "data_profile", {}) or {}

    # 1. 입력 견고화 (G-1) — 수치 + 문자숫자 복원 + 범주형 빈도인코딩. 수치만 있으면 기존과 동일.
    num_df, input_encoding = _robustify_input(df, profile)
    if num_df.empty:
        return _empty_result(state, len(df), "수치/복원/인코딩 후에도 사용 가능한 컬럼 0개")

    # 2. B-2: Day 1 missing_ratio — 30% 초과 컬럼 drop
    missing_ratio = profile.get("missing_ratio_per_col", {})
    high_miss = [str(c) for c in num_df.columns if missing_ratio.get(str(c), 0.0) > MISSING_RATIO_DROP_THRESHOLD]
    if high_miss:
        num_df = num_df.drop(columns=high_miss)

    # 3. 상수 컬럼
    const_cols = [str(c) for c in num_df.columns if num_df[c].nunique(dropna=True) <= 1]
    if const_cols:
        num_df = num_df.drop(columns=const_cols)
    if num_df.shape[1] == 0:
        return _empty_result(
            state, len(df), "모든 컬럼 상수/결측", constant_cols_dropped=const_cols, high_missing_cols_dropped=high_miss
        )

    # 4. B-1: 거의-상수 알림
    nearly_const = _detect_nearly_constant(num_df)

    # 5. B-3: inf 행 제거
    num_df, n_inf = _validate_finite(num_df)

    # 6. 결측 처리 — 시계열(C3/C4)은 순서 보존 보간.
    #    (G-2, 2026-06-16) 점(C1/C2)은 dropna 로 행을 통째 삭제하던 것 → 과반(>50%) 결측
    #    행만 신뢰 불가로 제거하고, 나머지는 컬럼 median 으로 대체해 표본을 보존한다.
    #    median 은 (apply_split 경유 시) train 구간에서만 fit → artifacts 에 박혀 val/추론에
    #    동일 적용되므로 평가 누수가 없다. 결측이 없으면 이 블록은 기존과 동일(무회귀).
    has_time = bool(profile.get("has_time_column", False))
    if has_time:
        num_df = num_df.interpolate(method="linear", limit_direction="both").ffill().bfill()
    impute_medians: dict[str, float] = {}
    if bool(num_df.isna().any().any()):
        row_keep = num_df.isna().mean(axis=1) <= 0.5
        num_df = num_df[row_keep]
        med = num_df.median(numeric_only=True)
        impute_medians = {str(k): float(v) for k, v in med.items() if pd.notna(v)}
        num_df = num_df.fillna(med)
    num_df = num_df.dropna()  # median 이 NaN 인 전결측 컬럼 잔여 안전망
    if num_df.shape[0] == 0:
        return _empty_result(
            state, len(df), "모든 행 결측/inf", constant_cols_dropped=const_cols, high_missing_cols_dropped=high_miss
        )

    n_rows_in, n_cols_in = num_df.shape
    col_names = [str(c) for c in num_df.columns]
    applied, skipped = [], []
    warnings_list = []

    if nearly_const:
        warnings_list.append(f"거의-상수 컬럼 {len(nearly_const)}개 (drop 안 함)")
    if n_inf > 0:
        warnings_list.append(f"inf 행 {n_inf}개 제거")
    if high_miss:
        warnings_list.append(f"결측률 >30% 컬럼 {len(high_miss)}개 제거")

    # 7. 3 단계
    X, scaler = _robust_scale(num_df)
    applied.append("robust_scale")
    X, winsor_limits = _winsorize(X, DEFAULT_WINSOR_Q_LO, DEFAULT_WINSOR_Q_HI, col_names)
    applied.append("winsorize")
    if has_time:  # ★ D2-2: 시계열(C3/C4)은 PCA skip — 시간 구조 보존 (TranAD/AT 가 raw 시퀀스 필요)
        pca, n_used = None, X.shape[1]
    else:
        X, pca, n_used = _pca_reduce(X, DEFAULT_PCA_VARIANCE)
    if pca is not None:
        applied.append("pca")
        feat_names = [f"pc{i}" for i in range(n_used)]
    else:
        skipped.append({"step": "pca", "reason": f"n_cols={n_cols_in}<2 or n_rows<{MIN_ROWS_FOR_PCA}"})
        feat_names = col_names

    processed_df = pd.DataFrame(X, columns=feat_names)

    artifacts = {
        "n_rows_in": n_rows_in,
        "n_cols_in": n_cols_in,
        "n_cols_out": int(X.shape[1]),
        "scaler": scaler,
        "winsor_limits": winsor_limits,
        "pca": pca,
        "feature_names_in": col_names,
        "feature_names_out": feat_names,
        "dim_reduction_ratio": float(X.shape[1] / max(1, n_cols_in)),
        "pca_components_used": n_used,
        "applied_steps": applied,
        "skipped_steps": skipped,
        "constant_cols_dropped": const_cols,
        "nearly_constant_cols": nearly_const,
        "high_missing_cols_dropped": high_miss,
        "inf_rows_dropped": n_inf,
        "has_time": has_time,
        "preprocessor_warnings": warnings_list,
        "input_encoding": input_encoding,  # G-1: 추론 시 동일 복원/인코딩 재현
        "impute_medians": impute_medians,  # G-2: 추론/val 결측 대체용 train median
    }
    extras = dict(state.category_extras or {})
    cat_block = dict(extras.get("anomaly_detection") or {})
    cat_block["preprocessor_artifacts"] = artifacts
    extras["anomaly_detection"] = cat_block
    new_state = state.with_update(category_extras=extras)

    return processed_df, new_state


# ── 공개 진입점 3: apply_transform (추론 시) ★ E-1·E-2·E-3 ────
def apply_transform(df: Any, fitted_state: dict[str, Any]) -> Any:
    """Day 6 추론 시 사용. apply() 결과로 새 데이터를 학습 시와 동일 변환.

    학습/추론 일관성 보장. 컬럼 순서·NaN·inf·PCA None 모두 자동 가드.
    """
    import numpy as np
    import pandas as pd

    # 1. 학습 시 drop 컬럼 제거
    df = df.drop(columns=fitted_state["constant_cols_dropped"], errors="ignore")
    df = df.drop(columns=fitted_state["high_missing_cols_dropped"], errors="ignore")

    # 2. 입력 견고화 재현(학습과 동일: 문자숫자 복원 + 빈도인코딩) + inf 만 제거(NaN 보존)
    df = _robustify_input_transform(df, fitted_state.get("input_encoding"))
    inf_mask = np.isinf(df.values).any(axis=1)  # NaN 은 아래 median 대체로 보존
    df = df[~inf_mask]

    # 3. 결측 처리 — 시계열 보간(순서 보존) / 점은 train median 대체(G-2) 후 잔여 dropna
    if fitted_state.get("has_time", False):
        df = df.interpolate(method="linear", limit_direction="both").ffill().bfill()
    medians = fitted_state.get("impute_medians") or {}
    if medians:
        df = df.fillna(pd.Series(medians))
    df = df.dropna()

    # 4. 학습 시점 컬럼 순서 강제
    expected = fitted_state["feature_names_in"]
    df = df[expected]

    # 5. RobustScaler
    X = fitted_state["scaler"].transform(df.values)

    # 6. Winsorize
    for j, col in enumerate(expected):
        lo, hi = fitted_state["winsor_limits"][col]
        X[:, j] = np.clip(X[:, j], lo, hi)

    # 7. PCA (None 가드)
    if fitted_state["pca"] is not None:
        X = fitted_state["pca"].transform(X)

    return X


# ── 공개 진입점 4: apply_split (학습 누수 차단 — split-first → train fit → val transform) ──
#
# feature_engineer 가 get_handler(category, "apply_split") 로 자동 우선 사용한다
# (미등록이면 apply 폴백). scaler/winsor/PCA 를 "전체 df" 가 아니라 "train 구간"
# 에만 fit 하여 평가 누수를 차단하는 진입점.
#
# 흐름:
#   1) split 먼저 (경계: category_extras["anomaly_detection"]["split_index"]
#                      → 시간 컬럼(시간순 ordinal) → 무작위 비율 순).
#   2) train 으로만 apply() 호출 → fitted statistics(scaler·winsor_limits·pca)
#      가 train 에 갇힘. 산출물은 preprocessor_artifacts 로 적립됨.
#   3) val 은 apply_transform(df_val, artifacts) 로 transform-only 재적용
#      (fit 안 함 → 누수 없음). 학습/추론 일관성 함수 재사용.
#   4) leakage_safe_split 메타 적립 (evaluator 가 n_train 소비).
#
# 반환: (df_train_proc, df_val_proc, new_state)
#   - 두 DataFrame 은 동일 컬럼(feature_names_out) → feature_engineer 의 concat 안전.
DEFAULT_SPLIT_TEST_RATIO = 0.2


def _split_ts() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _resolve_split_boundary(df: Any, state: Any, test_ratio: float) -> tuple[Any, str]:
    """train/val 행 분할 — (train_index, val_index 를 담은 (df_train, df_val), 방법명) 반환.

    우선순위:
      1) category_extras["anomaly_detection"]["split_index"] (정수) — 명시 경계.
      2) 시간 컬럼 존재 → 시간순 정렬 후 앞 train / 뒤 val (시계열 누수 방지).
      3) 무작위 비율 (RANDOM_STATE 고정 → 재현).
    어떤 경우든 df_train/df_val 둘 다 reset_index(drop=True).
    """
    import numpy as np  # noqa: WPS433

    n = len(df)
    cat = (getattr(state, "category_extras", None) or {}).get("anomaly_detection", {}) or {}

    # 1) 명시 split_index
    si = cat.get("split_index")
    if isinstance(si, (int, float)) and 0 < int(si) < n:
        cut = int(si)
        df_tr = df.iloc[:cut].reset_index(drop=True)
        df_val = df.iloc[cut:].reset_index(drop=True)
        return (df_tr, df_val), "explicit_split_index"

    # 2) 시간 컬럼 → 시간순 분할
    profile = getattr(state, "data_profile", {}) or {}
    time_cands = profile.get("time_column_candidates") or []
    time_col = None
    if profile.get("has_time_column") and time_cands:
        c0 = time_cands[0]
        if c0 in df.columns:
            time_col = c0
    if time_col is not None:
        try:
            import pandas as pd  # noqa: WPS433

            order = pd.to_datetime(df[time_col], errors="coerce")
            if order.isna().all():
                order = df[time_col]
            df_sorted = df.assign(_ord=order).sort_values("_ord").drop(columns=["_ord"])
            cut = max(1, int(n * (1.0 - test_ratio)))
            df_tr = df_sorted.iloc[:cut].reset_index(drop=True)
            df_val = df_sorted.iloc[cut:].reset_index(drop=True)
            return (df_tr, df_val), "time_ordered"
        except Exception:  # noqa: BLE001 — 시간 분할 실패 → 무작위 폴백
            pass

    # 3) 무작위 비율
    rng = np.random.default_rng(RANDOM_STATE)
    perm = rng.permutation(n)
    cut = max(1, int(n * (1.0 - test_ratio)))
    tr_idx = np.sort(perm[:cut])
    val_idx = np.sort(perm[cut:])
    df_tr = df.iloc[tr_idx].reset_index(drop=True)
    df_val = df.iloc[val_idx].reset_index(drop=True)
    return (df_tr, df_val), "random_ratio"


def apply_split(
    df: Any,
    plan_steps: list[dict] | None,
    state: Any,
    *,
    test_ratio: float = DEFAULT_SPLIT_TEST_RATIO,
) -> tuple[Any, Any, Any]:
    """누수 방지 전처리 — split 후 train 으로만 fit, val 은 transform-only.

    Returns
    -------
    (df_train_proc, df_val_proc, new_state)
    """
    import pandas as pd  # noqa: WPS433

    # 데이터가 너무 작아 분할 무의미 → 기존 apply 폴백 (회귀 방지, train==전체).
    if df is None or len(df) < 4:
        df_proc, new_state = apply(df, plan_steps, state)
        empty_val = df_proc.iloc[0:0].copy()
        return df_proc, empty_val, new_state

    # 1) split 먼저
    (df_train, df_val), split_method = _resolve_split_boundary(df, state, test_ratio)

    # 2) train 으로만 fit (preprocessor_artifacts 적립)
    df_train_proc, state_after = apply(df_train, plan_steps, state)

    # 3) fitted artifacts 추출 → val 에 transform-only
    extras_after = getattr(state_after, "category_extras", None) or {}
    cat_after = extras_after.get("anomaly_detection", {}) or {}
    artifacts = cat_after.get("preprocessor_artifacts", {}) or {}
    feat_out = list(artifacts.get("feature_names_out") or list(df_train_proc.columns))

    try:
        X_val = apply_transform(df_val, artifacts)
        df_val_proc = pd.DataFrame(X_val, columns=feat_out)
    except Exception:  # noqa: BLE001 — val transform 실패 → 빈 val (train 단독 진행)
        df_val_proc = df_train_proc.iloc[0:0].copy()

    # 컬럼 정합 보장 (apply_transform 출력은 학습과 동일 feature_names_out)
    if list(df_val_proc.columns) != list(df_train_proc.columns):
        df_val_proc = df_val_proc.reindex(columns=list(df_train_proc.columns))

    # 4) leakage_safe_split 메타 적립 (evaluator.n_train 소비)
    new_extras = dict(extras_after)
    cat_block = dict(new_extras.get("anomaly_detection", {}) or {})
    cat_block["leakage_safe_split"] = {
        "method": "split_first_train_fit",
        "split_method": split_method,
        "n_train": int(len(df_train_proc)),
        "n_val": int(len(df_val_proc)),
        "test_ratio": float(test_ratio),
        "random_state": int(RANDOM_STATE),
        "ts": _split_ts(),
    }
    new_extras["anomaly_detection"] = cat_block
    new_state = state_after.with_update(category_extras=new_extras)

    return df_train_proc, df_val_proc, new_state

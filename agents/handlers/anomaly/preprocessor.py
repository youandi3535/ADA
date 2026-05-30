"""agents.handlers.anomaly.preprocessor — 이상탐지 전처리 (NY 담당, Day 2 v3).

3 단계 전처리: RobustScaler → Winsorize → PCA(95%)

진입함수 (dispatcher 자동 등록):
  - plan(state) -> list[dict]                메타
  - apply(df, plan_steps, state) -> dict     학습 시 (17 필드 반환)
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
    n_rows: int,
    reason: str,
    constant_cols_dropped: list[str] | None = None,
    high_missing_cols_dropped: list[str] | None = None,
) -> dict[str, Any]:
    import numpy as np

    return {
        "X_processed": np.empty((n_rows, 0)),
        "n_rows_in": n_rows,
        "n_cols_in": 0,
        "n_cols_out": 0,
        "scaler": None,
        "winsor_limits": {},
        "pca": None,
        "feature_names_in": [],
        "dim_reduction_ratio": 0.0,
        "pca_components_used": 0,
        "applied_steps": [],
        "skipped_steps": [{"step": "all", "reason": reason}],
        "feature_names_out": [],
        "constant_cols_dropped": constant_cols_dropped or [],
        "nearly_constant_cols": [],
        "high_missing_cols_dropped": high_missing_cols_dropped or [],
        "inf_rows_dropped": 0,
        "preprocessor_warnings": [reason],
    }


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
    """inf/-inf 포함 행 제거. 제거된 행 수 반환."""
    import numpy as np

    if num_df.empty:
        return num_df, 0
    finite_mask = np.isfinite(num_df.values).all(axis=1)
    n_inf = int((~finite_mask).sum())
    return num_df[finite_mask], n_inf


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
def apply(df: Any, plan_steps: list[dict] | None, state: Any) -> dict[str, Any]:  # noqa: ARG001
    """3 단계 전처리 + 17 필드 반환. 학습 시점에 사용."""
    import numpy as np

    profile = getattr(state, "data_profile", {}) or {}

    # 1. 수치 컬럼
    num_df = df.select_dtypes(include=[np.number])
    if num_df.empty:
        return _empty_result(len(df), "수치 컬럼 0개")

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
            len(df), "모든 컬럼 상수/결측", constant_cols_dropped=const_cols, high_missing_cols_dropped=high_miss
        )

    # 4. B-1: 거의-상수 알림
    nearly_const = _detect_nearly_constant(num_df)

    # 5. B-3: inf 행 제거
    num_df, n_inf = _validate_finite(num_df)

    # 6. 결측 처리 — 시계열(C3/C4)은 순서 보존 보간, 점(C1/C2)은 dropna (D2-1)
    has_time = bool(profile.get("has_time_column", False))
    if has_time:
        num_df = num_df.interpolate(method="linear", limit_direction="both").ffill().bfill()
    num_df = num_df.dropna()
    if num_df.shape[0] == 0:
        return _empty_result(
            len(df), "모든 행 결측/inf", constant_cols_dropped=const_cols, high_missing_cols_dropped=high_miss
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

    return {
        "X_processed": X,
        "n_rows_in": n_rows_in,
        "n_cols_in": n_cols_in,
        "n_cols_out": int(X.shape[1]),
        "scaler": scaler,
        "winsor_limits": winsor_limits,
        "pca": pca,
        "feature_names_in": col_names,
        "dim_reduction_ratio": float(X.shape[1] / max(1, n_cols_in)),
        "pca_components_used": n_used,
        "applied_steps": applied,
        "skipped_steps": skipped,
        "feature_names_out": feat_names,
        "constant_cols_dropped": const_cols,
        "nearly_constant_cols": nearly_const,
        "high_missing_cols_dropped": high_miss,
        "inf_rows_dropped": n_inf,
        "has_time": has_time,
        "preprocessor_warnings": warnings_list,
    }


# ── 공개 진입점 3: apply_transform (추론 시) ★ E-1·E-2·E-3 ────
def apply_transform(df: Any, fitted_state: dict[str, Any]) -> Any:
    """Day 6 추론 시 사용. apply() 결과로 새 데이터를 학습 시와 동일 변환.

    학습/추론 일관성 보장. 컬럼 순서·NaN·inf·PCA None 모두 자동 가드.
    """
    import numpy as np

    # 1. 학습 시 drop 컬럼 제거
    df = df.drop(columns=fitted_state["constant_cols_dropped"], errors="ignore")
    df = df.drop(columns=fitted_state["high_missing_cols_dropped"], errors="ignore")

    # 2. 수치만 + inf 제거
    df = df.select_dtypes(include=[np.number])
    finite_mask = np.isfinite(df.values).all(axis=1)
    df = df[finite_mask]

    # 3. 결측 처리 — 시계열 보간(순서 보존) / 점 dropna (D2-1)
    if fitted_state.get("has_time", False):
        df = df.interpolate(method="linear", limit_direction="both").ffill().bfill()
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

"""agents.handlers.anomaly.profiler — 이상탐지 데이터 프로파일 (NY 담당, v3).

Day 1 v3 책임 — DataFrame 을 받아 47+ 키의 이상탐지 전용 프로파일 dict 반환.

v3 추가 키 (2026-05-28 — Day 1 설계 정합화):
  V1  ①  n_features_categorical          — 범주형 컬럼 수 (Day 2 preprocessor 분기)
  V2  ⑥  is_approximately_gaussian       — Z-score 신뢰성 통합 플래그 (skew<1 ∧ |kurt|<3)
  V3  ⑧  intrinsic_dim_ratio             — pca_n_components_95 / pca_total_dims

v2 추가 키 (Q4 의심 검증 후 패치) — 모두 유지:
  P1  ②  outlier_ratios_iqr_strict       — 3×IQR (heavy-tail 보강)
  P2  ③  zscore_unreliable_cols          — std » MAD 가드
  P3  ④  modz_unreliable_cols            — high skew 가드
  P4  ⑦  mahalanobis_threshold_dynamic   — 동적 percentile
  P5  ⑧  pca_n_components_90,
         last_pc_variance                — 엄격한 reduction 조건
  P7  ⑫  contamination_method,
         contamination_source_breakdown   — trimmed mean
  P8  ⑫  high_contamination_suspected    — 고오염 경고
  P9  ⑪  time_column_false_positive_risk — 연도-숫자 가드
  P11 ⑪  Unix epoch int 감지
  P12 ⑨  most_anomalous_dim_permutation  — 다변량 IF importance
  P13 ⑨  most_anomalous_dim_confidence   — score spread 기반

12 섹션 호출 순서 (v2 변경: ⑥ → ④):
  ① → ⑥ → ② → ③ → ④ → ⑤ → ⑦ → ⑧ → ⑨ → ⑩ → ⑪ → ⑫ → 후처리 → ⑬

후속 단계 핵심 인용 키:
  - contamination_estimate      → Day 6 pipeline
  - contamination_method        → "trimmed_mean" 명시
  - has_time_column             → Day 5 selector
  - pca_dim_reduction_possible  → Day 2/5 (조건 강화)
  - most_anomalous_dim_permutation + confidence → Day 8 insight
  - recommended_model_hints     → Day 5

설계 원칙:
  - 방어적: 모든 섹션 독립 try/except
  - 재현성: random_state=42 + n_jobs=1
  - deprecation 회피: infer_datetime_format 미사용
  - 호환성: 기존 v1 키 30+ 모두 유지
"""

from __future__ import annotations

from typing import Any

# ── 모듈 상수 ───────────────────────────────────────────────────────────────
RANDOM_STATE = 42
MAD_NORMAL_CONSTANT = 0.6745
IQR_MULTIPLIER = 1.5
IQR_STRICT_MULTIPLIER = 3.0
Z_THRESHOLD = 3.0
MODIFIED_Z_THRESHOLD = 3.5
HIGH_CORRELATION_THRESHOLD = 0.8
HIGH_SKEW_THRESHOLD = 2.0
HIGH_KURTOSIS_THRESHOLD = 7.0
MAHALANOBIS_PERCENTILE = 97.5
PCA_TARGET_VARIANCE = 0.95
PCA_VARIANCE_90 = 0.90
PCA_LAST_PC_THRESHOLD = 0.05
IF_SUBSAMPLE_THRESHOLD = 10_000
LOF_SUBSAMPLE_THRESHOLD = 5_000
LOF_DEFAULT_NEIGHBORS = 20
MIN_ROWS_FOR_MULTIVARIATE = 20
MIN_ROWS_RELIABLE = 50
CONTAMINATION_MIN = 0.001
CONTAMINATION_MAX = 0.5
CONTAMINATION_DEFAULT = 0.05
TIME_PARSE_SAMPLE = 20
TIME_PARSE_MIN_HITS = 5

# v2 신규
ZSCORE_UNRELIABLE_RATIO = 5.0  # std > 5×MAD → Z 신뢰도 낮음
TRIMMED_MEAN_MIN_SOURCES = 4  # 4 소스 이상일 때만 trim
HIGH_CONTAM_IF_LOF_THRESHOLD = 0.20  # IF/LOF > 0.2 + IQR/Z/ModZ < 0.01 → 의심
HIGH_CONTAM_UNIVARIATE_THRESHOLD = 0.01
MOST_ANOMALOUS_DIM_SPREAD_HIGH = 0.05  # IF score spread > 0.05 → confidence high
DYNAMIC_PERCENTILE_MIN = 90.0  # 동적 percentile 하한
DYNAMIC_PERCENTILE_MAX = 99.0  # 동적 percentile 상한
UNIX_EPOCH_MIN = 1_000_000_000  # 2001-09-09
UNIX_EPOCH_MAX = 10_000_000_000  # 2286-11-20


# ── 공개 진입점 ─────────────────────────────────────────────────────────────


def profile(df: Any, state: Any) -> dict[str, Any]:  # noqa: ARG001
    """DataFrame → 이상탐지 전용 프로파일 dict (v2)."""
    import numpy as np
    import pandas as pd

    extra: dict[str, Any] = {}
    warnings: list[str] = []

    num_df_raw: pd.DataFrame = df.select_dtypes(include=[np.number])
    if num_df_raw.empty:
        return {
            "anomaly_warning": "수치 컬럼 없음 — 이상탐지 프로파일 중단",
            "n_rows": int(len(df)),
            "n_numeric_cols": 0,
            "profile_warnings": ["수치 컬럼 0개 — 모든 섹션 스킵"],
        }

    num_df: pd.DataFrame = num_df_raw.dropna()
    n_rows_raw = int(len(df))
    n_rows = int(len(num_df))

    if n_rows < MIN_ROWS_RELIABLE:
        warnings.append(f"유효 행 수 {n_rows}개 — 신뢰도 낮음 (권장 최소: {MIN_ROWS_RELIABLE})")

    # ① 기본 통계
    try:
        extra.update(_basic_stats(df, num_df_raw, num_df, n_rows_raw))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"기본 통계 실패: {e}")

    # ⑥ 분포 특성 (v2: ④ 앞으로 이동 — high_skew_cols 가 ④ 의 입력)
    try:
        extra.update(_distribution_shape(num_df))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"분포 특성 분석 실패: {e}")

    # ② IQR (v2: 1.5 + 3.0 동시)
    try:
        extra.update(_outlier_iqr(num_df))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"IQR 분석 실패: {e}")

    # ③ Z-score (v2: unreliable_cols)
    try:
        extra.update(_outlier_zscore(num_df))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Z-score 분석 실패: {e}")

    # ④ Modified Z (v2: high_skew_cols 받아 unreliable 결정)
    try:
        high_skew = extra.get("high_skew_cols", []) or []
        extra.update(_outlier_modified_z(num_df, high_skew))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Modified Z-score 분석 실패: {e}")

    # ⑤ 투표 이상치
    try:
        extra.update(_outlier_vote(num_df, extra))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"투표 이상치 분석 실패: {e}")

    # ⑦ 다변량
    if n_rows >= MIN_ROWS_FOR_MULTIVARIATE and num_df.shape[1] >= 2:
        try:
            extra.update(_multivariate(num_df, warnings))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"다변량 분석 실패: {e}")
    else:
        warnings.append(f"다변량 분석 생략 — 행 수 < {MIN_ROWS_FOR_MULTIVARIATE} 또는 수치 컬럼 < 2")

    # ⑧ PCA (v2: n90, last_pc_variance + 엄격 조건)
    if num_df.shape[1] >= 2 and n_rows >= 2:
        try:
            extra.update(_pca_analysis(num_df))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"PCA 분석 실패: {e}")
            extra.setdefault("pca_n_components_95", num_df.shape[1])
            extra.setdefault("pca_n_components_90", num_df.shape[1])
            extra.setdefault("pca_total_dims", num_df.shape[1])
            extra.setdefault("pca_dim_reduction_possible", False)
            extra.setdefault("last_pc_variance", 0.0)
    else:
        extra["pca_n_components_95"] = max(1, num_df.shape[1])
        extra["pca_n_components_90"] = max(1, num_df.shape[1])
        extra["pca_total_dims"] = num_df.shape[1]
        extra["pca_explained_variance_ratio"] = [1.0] if num_df.shape[1] >= 1 else []
        extra["pca_dim_reduction_possible"] = False
        extra["last_pc_variance"] = 0.0

    # ⑨ Isolation Forest (v2: permutation importance)
    try:
        extra.update(_isolation_analysis(num_df, warnings))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Isolation Forest 분석 실패: {e}")
        extra.setdefault("isolation_depth_per_dim", {})
        extra.setdefault("isolation_outlier_ratio", None)
        extra.setdefault("most_anomalous_dim", None)
        extra.setdefault("most_anomalous_dim_permutation", None)
        extra.setdefault("most_anomalous_dim_confidence", "low")

    # ⑩ LOF
    if n_rows >= MIN_ROWS_FOR_MULTIVARIATE:
        try:
            extra.update(_lof_analysis(num_df, warnings))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"LOF 분석 실패: {e}")
            extra.setdefault("lof_outlier_ratio", None)
    else:
        warnings.append(f"LOF 생략 — 행 수 < {MIN_ROWS_FOR_MULTIVARIATE}")
        extra["lof_outlier_ratio"] = None

    # ⑪ 시간 컬럼 (v2: false positive 가드 + Unix epoch int)
    try:
        extra.update(_time_column_analysis(df))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"시간 컬럼 분석 실패: {e}")
        extra.setdefault("has_time_column", False)
        extra.setdefault("time_column_candidates", [])
        extra.setdefault("time_column_false_positive_risk", [])

    # ⑫ Contamination (v2: trimmed mean + 고오염 경고)
    try:
        extra.update(_estimate_contamination(extra, n_rows))
    except Exception as e:  # noqa: BLE001
        warnings.append(f"contamination 추정 실패: {e}")
        extra["contamination_estimate"] = CONTAMINATION_DEFAULT
        extra["contamination_confidence"] = "low"
        extra["contamination_sources_used"] = 0
        extra["contamination_method"] = "default_fallback"
        extra["contamination_source_breakdown"] = {}
        extra["high_contamination_suspected"] = False

    # 후처리: Mahalanobis 동적 임계 (⑫ 후 contamination 알아낸 뒤)
    distances = extra.pop("_mahalanobis_distances", None)
    if distances is not None:
        try:
            contam = float(extra.get("contamination_estimate", CONTAMINATION_DEFAULT))
            target_pct = 100.0 - contam * 100.0
            target_pct = max(DYNAMIC_PERCENTILE_MIN, min(DYNAMIC_PERCENTILE_MAX, target_pct))
            thr_dyn = float(np.percentile(distances, target_pct))
            extra["mahalanobis_threshold_dynamic"] = round(thr_dyn, 4)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"마할라노비스 동적 임계 실패: {e}")
            extra["mahalanobis_threshold_dynamic"] = None
    else:
        extra.setdefault("mahalanobis_threshold_dynamic", None)

    # ⑬ 모델 힌트
    extra["recommended_model_hints"] = _model_hints(extra)

    extra["rows"] = n_rows_raw
    extra["profile_warnings"] = warnings
    return extra


# ── 섹션별 내부 함수 ────────────────────────────────────────────────────────


def _basic_stats(df: Any, num_raw: Any, num_clean: Any, n_rows_raw: int) -> dict[str, Any]:
    """① 기본 통계 (v3: V1 n_features_categorical 추가)."""
    missing = {str(c): float(num_raw[c].isna().mean()) for c in num_raw.columns}
    constant: list[str] = []
    for c in num_clean.columns:
        if num_clean[c].nunique(dropna=True) <= 1:
            constant.append(str(c))
    dup_ratio = float(df.duplicated().mean()) if n_rows_raw > 0 else 0.0
    n_cat = int(df.select_dtypes(include=["object", "category"]).shape[1])
    return {
        "n_rows": n_rows_raw,
        "n_numeric_cols": int(num_raw.shape[1]),
        "n_features_categorical": n_cat,
        "missing_ratio_per_col": missing,
        "constant_cols": constant,
        "duplicate_row_ratio": round(dup_ratio, 4),
        "has_constant_cols": len(constant) > 0,
    }


def _distribution_shape(num_df: Any) -> dict[str, Any]:
    """⑥ 분포 특성 (v2: ④ 앞으로 이동, v3: V2 gaussian flag 추가)."""
    skew = {str(c): round(float(num_df[c].skew()), 3) for c in num_df.columns}
    kurt = {str(c): round(float(num_df[c].kurt()), 3) for c in num_df.columns}
    high_skew = [c for c, v in skew.items() if abs(v) > HIGH_SKEW_THRESHOLD]
    high_kurt = [c for c, v in kurt.items() if v > HIGH_KURTOSIS_THRESHOLD]
    all_gaussian = bool(skew and all(abs(v) < 1.0 for v in skew.values()) and all(abs(v) < 3.0 for v in kurt.values()))
    return {
        "skewness_per_col": skew,
        "kurtosis_per_col": kurt,
        "high_skew_cols": high_skew,
        "high_kurtosis_cols": high_kurt,
        "is_approximately_gaussian": all_gaussian,
    }


def _outlier_iqr(num_df: Any) -> dict[str, Any]:
    """② IQR — Tukey 1.5×IQR + 3×IQR 동시 (v2 P1).

    1.5×IQR: 표준 컷 (정규 0.7%)
    3×IQR:  Tukey "far out", heavy-tail 보강 (정규 0.00006%)
    """
    ratios_15: dict[str, float] = {}
    ratios_30: dict[str, float] = {}
    for c in num_df.columns:
        col = num_df[c]
        q1 = float(col.quantile(0.25))
        q3 = float(col.quantile(0.75))
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low_15 = q1 - IQR_MULTIPLIER * iqr
        high_15 = q3 + IQR_MULTIPLIER * iqr
        low_30 = q1 - IQR_STRICT_MULTIPLIER * iqr
        high_30 = q3 + IQR_STRICT_MULTIPLIER * iqr
        ratios_15[str(c)] = round(float(((col < low_15) | (col > high_15)).mean()), 4)
        ratios_30[str(c)] = round(float(((col < low_30) | (col > high_30)).mean()), 4)
    return {
        "outlier_ratios_iqr": ratios_15,
        "outlier_ratios_iqr_strict": ratios_30,
    }


def _outlier_zscore(num_df: Any) -> dict[str, Any]:
    """③ Z-score (v2 P2: unreliable_cols)."""
    import numpy as np

    ratios: dict[str, float] = {}
    unreliable: list[str] = []
    for c in num_df.columns:
        col = num_df[c]
        std = float(col.std())
        if std <= 0:
            continue
        mean = float(col.mean())
        z = (col - mean).abs() / std
        ratios[str(c)] = round(float((z > Z_THRESHOLD).mean()), 4)
        # Z 신뢰도 가드: std » MAD 면 Z 가 self-masked
        vals = col.to_numpy(dtype=float, copy=False)
        median = float(np.median(vals))
        mad = float(np.median(np.abs(vals - median)))
        if mad > 0 and std > mad * ZSCORE_UNRELIABLE_RATIO:
            unreliable.append(str(c))
    return {
        "outlier_ratios_zscore": ratios,
        "zscore_unreliable_cols": unreliable,
    }


def _outlier_modified_z(num_df: Any, high_skew_cols: list[str]) -> dict[str, Any]:
    """④ Modified Z (v2 P3: high skew 컬럼 unreliable).

    Q4-2 검증: 0.6745 가 LogNormal/Cauchy 에서 σ̂ 과소추정 → false positive 폭증.
    → high_skew_cols 인 컬럼은 modz_unreliable_cols 에 기록, ⑫ 에서 제외.
    """
    import numpy as np

    ratios: dict[str, float] = {}
    unreliable: list[str] = list(map(str, high_skew_cols))  # high skew 컬럼은 자동 unreliable
    skew_set = set(unreliable)
    for c in num_df.columns:
        vals = num_df[c].to_numpy(dtype=float, copy=False)
        if vals.size == 0:
            continue
        median = float(np.median(vals))
        mad = float(np.median(np.abs(vals - median)))
        if mad <= 0:
            continue
        mz = MAD_NORMAL_CONSTANT * np.abs(vals - median) / mad
        ratios[str(c)] = round(float((mz > MODIFIED_Z_THRESHOLD).mean()), 4)
        # 별도 ratio 가 너무 높으면 (>0.20) 도 unreliable 후보
        if str(c) not in skew_set and ratios[str(c)] > 0.20:
            unreliable.append(str(c))
    return {
        "outlier_ratios_modified_z": ratios,
        "modz_unreliable_cols": unreliable,
    }


def _outlier_vote(num_df: Any, extra: dict[str, Any]) -> dict[str, Any]:
    """⑤ 투표 이상치."""
    import numpy as np

    iqr_ratios = extra.get("outlier_ratios_iqr", {}) or {}
    z_ratios = extra.get("outlier_ratios_zscore", {}) or {}
    mz_ratios = extra.get("outlier_ratios_modified_z", {}) or {}

    common_cols = set(iqr_ratios) & set(z_ratios) & set(mz_ratios)
    if not common_cols:
        return {"outlier_vote_ratio": {}}

    vote_ratios: dict[str, float] = {}
    for c in common_cols:
        col_vals = num_df[c].to_numpy(dtype=float, copy=False)
        if col_vals.size == 0:
            continue

        flags = np.zeros(len(col_vals), dtype=np.int8)

        q1 = float(num_df[c].quantile(0.25))
        q3 = float(num_df[c].quantile(0.75))
        iqr = q3 - q1
        if iqr > 0:
            low = q1 - IQR_MULTIPLIER * iqr
            high = q3 + IQR_MULTIPLIER * iqr
            flags += ((col_vals < low) | (col_vals > high)).astype(np.int8)

        std = float(num_df[c].std())
        if std > 0:
            mean = float(num_df[c].mean())
            flags += (np.abs(col_vals - mean) / std > Z_THRESHOLD).astype(np.int8)

        median = float(np.median(col_vals))
        mad = float(np.median(np.abs(col_vals - median)))
        if mad > 0:
            mz = MAD_NORMAL_CONSTANT * np.abs(col_vals - median) / mad
            flags += (mz > MODIFIED_Z_THRESHOLD).astype(np.int8)

        vote_ratios[str(c)] = round(float((flags >= 2).mean()), 4)

    return {"outlier_vote_ratio": vote_ratios}


def _multivariate(num_df: Any, warnings: list[str]) -> dict[str, Any]:
    """⑦ 다변량 — 고상관 + 마할라노비스 (v2 P4: 동적 임계 준비)."""
    import numpy as np

    result: dict[str, Any] = {}

    # 고상관 쌍
    try:
        corr = num_df.corr(numeric_only=True)
        cols = list(corr.columns)
        high_pairs: list[tuple[Any, Any, float]] = []
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                v = float(corr.iloc[i, j])
                if not (v == v):
                    continue
                if abs(v) > HIGH_CORRELATION_THRESHOLD:
                    high_pairs.append((cols[i], cols[j], round(v, 3)))
        result["high_correlation_pairs"] = high_pairs
    except Exception as e:  # noqa: BLE001
        warnings.append(f"상관관계 계산 실패: {e}")
        result["high_correlation_pairs"] = []

    # 마할라노비스
    try:
        X = num_df.to_numpy(dtype=float, copy=False)
        if X.shape[0] < X.shape[1] + 1:
            warnings.append("마할라노비스 거리 생략 — 행 수가 컬럼 수+1 보다 적음 (공분산 불안정)")
            result["mahalanobis_outlier_ratio"] = None
            result["mahalanobis_threshold_p975"] = None
        else:
            mean = X.mean(axis=0)
            cov = np.cov(X.T)
            if cov.ndim == 0:
                cov = cov.reshape(1, 1)
            inv_cov = np.linalg.pinv(cov)
            diff = X - mean
            sq = np.einsum("ij,jk,ik->i", diff, inv_cov, diff)
            sq = np.clip(sq, 0.0, None)
            mahal = np.sqrt(sq)
            threshold = float(np.percentile(mahal, MAHALANOBIS_PERCENTILE))
            result["mahalanobis_outlier_ratio"] = round(float((mahal > threshold).mean()), 4)
            result["mahalanobis_threshold_p975"] = round(threshold, 4)
            # v2 P4: 동적 임계 계산용 distances 저장 (private, 후처리에서 pop)
            result["_mahalanobis_distances"] = mahal.tolist()
    except Exception as e:  # noqa: BLE001
        warnings.append(f"마할라노비스 거리 계산 실패: {e}")
        result["mahalanobis_outlier_ratio"] = None

    return result


def _pca_analysis(num_df: Any) -> dict[str, Any]:
    """⑧ PCA (v2 P5: n90 + last_pc_variance + 엄격 조건)."""
    import numpy as np
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    n_cols = int(num_df.shape[1])
    n_rows = int(num_df.shape[0])
    n_components = min(n_cols, max(1, n_rows - 1))

    X = StandardScaler().fit_transform(num_df)
    pca = PCA(n_components=n_components, random_state=RANDOM_STATE).fit(X)

    evr = np.asarray(pca.explained_variance_ratio_, dtype=float)
    cumvar = np.cumsum(evr)

    idx_95 = int(np.searchsorted(cumvar, PCA_TARGET_VARIANCE))
    n95 = min(idx_95 + 1, n_components, n_cols)
    n95 = max(1, n95)

    idx_90 = int(np.searchsorted(cumvar, PCA_VARIANCE_90))
    n90 = min(idx_90 + 1, n_components, n_cols)
    n90 = max(1, n90)

    last_pc_variance = float(evr[-1]) if len(evr) > 0 else 0.0

    # v2 엄격 조건: n90 ≤ n_cols/2 AND last_pc < 5%
    reduction_possible = n90 <= max(1, n_cols // 2) and last_pc_variance < PCA_LAST_PC_THRESHOLD

    intrinsic_ratio = float(n95 / max(1, n_cols))

    return {
        "pca_n_components_95": n95,
        "pca_n_components_90": n90,
        "pca_total_dims": n_cols,
        "intrinsic_dim_ratio": round(intrinsic_ratio, 4),
        "pca_explained_variance_ratio": [round(float(v), 4) for v in evr[:10]],
        "last_pc_variance": round(last_pc_variance, 4),
        "pca_dim_reduction_possible": reduction_possible,
    }


def _isolation_analysis(num_df: Any, warnings: list[str]) -> dict[str, Any]:
    """⑨ IF (v2 P12·P13: permutation importance + confidence)."""
    import numpy as np
    from sklearn.ensemble import IsolationForest

    result: dict[str, Any] = {}

    # 컬럼별 1D (v1 유지)
    dim_scores: dict[str, float] = {}
    for c in num_df.columns:
        vals = num_df[[c]].to_numpy(dtype=float, copy=False)
        if vals.shape[0] < 10:
            continue
        try:
            ifo = IsolationForest(
                n_estimators=100,
                contamination="auto",
                random_state=RANDOM_STATE,
                n_jobs=1,
            )
            ifo.fit(vals)
            mean_score = float(np.mean(ifo.score_samples(vals)))
            dim_scores[str(c)] = round(mean_score, 4)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"IF 1D 실패({c}): {e}")
            continue

    result["isolation_depth_per_dim"] = dim_scores
    if dim_scores:
        result["most_anomalous_dim"] = min(dim_scores, key=lambda k: dim_scores[k])
    else:
        result["most_anomalous_dim"] = None

    # 전체 다변량
    try:
        X = num_df.to_numpy(dtype=float, copy=False)
        if X.shape[0] > IF_SUBSAMPLE_THRESHOLD:
            rng = np.random.default_rng(RANDOM_STATE)
            idx = rng.choice(X.shape[0], IF_SUBSAMPLE_THRESHOLD, replace=False)
            X_fit = X[idx]
            warnings.append(f"IF 전체 분석: {IF_SUBSAMPLE_THRESHOLD}행 서브샘플 사용 (원본 {X.shape[0]}행)")
        else:
            X_fit = X

        ifo_all = IsolationForest(
            n_estimators=100,
            contamination="auto",
            random_state=RANDOM_STATE,
            n_jobs=1,
        )
        ifo_all.fit(X_fit)
        preds = ifo_all.predict(X)
        result["isolation_outlier_ratio"] = round(float((preds == -1).mean()), 4)

        # v2 P12: Permutation importance (다변량 IF 사용)
        try:
            baseline = ifo_all.score_samples(X)
            perm_imp: dict[str, float] = {}
            rng_perm = np.random.default_rng(RANDOM_STATE)
            for i, c in enumerate(num_df.columns):
                X_perm = X.copy()
                X_perm[:, i] = rng_perm.permutation(X_perm[:, i])
                perm_scores = ifo_all.score_samples(X_perm)
                imp = float(np.mean(np.abs(baseline - perm_scores)))
                perm_imp[str(c)] = round(imp, 4)
            result["permutation_importance_per_dim"] = perm_imp
            if perm_imp:
                most_perm = max(perm_imp, key=lambda k: perm_imp[k])
                result["most_anomalous_dim_permutation"] = most_perm
                # v2 P13: confidence from spread
                vals = list(perm_imp.values())
                spread = max(vals) - min(vals)
                if spread > MOST_ANOMALOUS_DIM_SPREAD_HIGH:
                    result["most_anomalous_dim_confidence"] = "high"
                elif spread > MOST_ANOMALOUS_DIM_SPREAD_HIGH / 2:
                    result["most_anomalous_dim_confidence"] = "medium"
                else:
                    result["most_anomalous_dim_confidence"] = "low"
            else:
                result["most_anomalous_dim_permutation"] = None
                result["most_anomalous_dim_confidence"] = "low"
        except Exception as e:  # noqa: BLE001
            warnings.append(f"permutation importance 실패: {e}")
            result["most_anomalous_dim_permutation"] = None
            result["most_anomalous_dim_confidence"] = "low"

    except Exception as e:  # noqa: BLE001
        warnings.append(f"IF 전체 분석 실패: {e}")
        result["isolation_outlier_ratio"] = None
        result["most_anomalous_dim_permutation"] = None
        result["most_anomalous_dim_confidence"] = "low"

    return result


def _lof_analysis(num_df: Any, warnings: list[str]) -> dict[str, Any]:
    """⑩ LOF."""
    import numpy as np
    from sklearn.neighbors import LocalOutlierFactor

    X = num_df.to_numpy(dtype=float, copy=False)
    if X.shape[0] > LOF_SUBSAMPLE_THRESHOLD:
        rng = np.random.default_rng(RANDOM_STATE)
        idx = rng.choice(X.shape[0], LOF_SUBSAMPLE_THRESHOLD, replace=False)
        X = X[idx]
        warnings.append(f"LOF 분석: {LOF_SUBSAMPLE_THRESHOLD}행 서브샘플 사용 (원본 {num_df.shape[0]}행)")

    n_neighbors = min(LOF_DEFAULT_NEIGHBORS, max(1, X.shape[0] - 1))
    lof = LocalOutlierFactor(
        n_neighbors=n_neighbors,
        contamination="auto",
        n_jobs=1,
    )
    preds = lof.fit_predict(X)
    return {"lof_outlier_ratio": round(float((preds == -1).mean()), 4)}


def _time_column_analysis(df: Any) -> dict[str, Any]:
    """⑪ 시간 컬럼 (v2 P9: false positive 가드 + P11: Unix epoch)."""
    import pandas as pd

    time_candidates: list[str] = []

    for c in df.columns:
        col = df[c]
        if pd.api.types.is_datetime64_any_dtype(col):
            time_candidates.append(str(c))
            continue
        if col.dtype == object:
            sample = col.dropna().head(TIME_PARSE_SAMPLE)
            if len(sample) < TIME_PARSE_MIN_HITS:
                continue
            try:
                parsed = pd.to_datetime(sample, errors="raise")
                if len(parsed) >= TIME_PARSE_MIN_HITS:
                    time_candidates.append(str(c))
            except Exception:  # noqa: BLE001
                continue

    # v2 P11: Unix epoch int 감지
    for c in df.columns:
        if str(c) in time_candidates:
            continue
        col = df[c]
        if pd.api.types.is_integer_dtype(col):
            sample = col.dropna().head(TIME_PARSE_SAMPLE)
            if len(sample) < TIME_PARSE_MIN_HITS:
                continue
            try:
                vmin = float(sample.min())
                vmax = float(sample.max())
                if UNIX_EPOCH_MIN <= vmin and vmax <= UNIX_EPOCH_MAX:
                    time_candidates.append(str(c))
            except Exception:  # noqa: BLE001
                continue

    # v2 P9: false positive 위험 컬럼 식별
    fp_risk: list[str] = []
    for c in time_candidates:
        try:
            col = df[c]
            if pd.api.types.is_integer_dtype(col):
                # Unix int 는 fp_risk 검사 스킵 (정상 timestamp 가정)
                continue
            parsed = pd.to_datetime(col, errors="coerce").dropna()
            if len(parsed) >= TIME_PARSE_MIN_HITS:
                if parsed.dt.month.nunique() == 1 and parsed.dt.day.nunique() == 1:
                    fp_risk.append(c)
        except Exception:  # noqa: BLE001
            continue

    result: dict[str, Any] = {
        "has_time_column": len(time_candidates) > 0,
        "time_column_candidates": time_candidates,
        "time_column_false_positive_risk": fp_risk,
    }

    if time_candidates:
        col_name = time_candidates[0]
        try:
            col = df[col_name]
            if pd.api.types.is_integer_dtype(col):
                ts = pd.to_datetime(col, unit="s", errors="coerce").dropna().sort_values()
            else:
                ts = pd.to_datetime(col, errors="coerce").dropna().sort_values()
            if len(ts) >= 2:
                total_days = (ts.iloc[-1] - ts.iloc[0]).total_seconds() / 86400.0
                gaps = ts.diff().dropna().dt.total_seconds()
                median_gap = float(gaps.median())
                gap_q1 = float(gaps.quantile(0.25))
                gap_q3 = float(gaps.quantile(0.75))
                gap_iqr = gap_q3 - gap_q1
                if gap_iqr > 0:
                    time_gap_anomalies = int((gaps > median_gap + IQR_MULTIPLIER * 2 * gap_iqr).sum())
                else:
                    time_gap_anomalies = 0
                result.update(
                    {
                        "time_range_days": round(total_days, 1),
                        "time_median_gap_sec": round(median_gap, 1),
                        "time_gap_anomaly_count": time_gap_anomalies,
                    }
                )
        except Exception:  # noqa: BLE001
            pass

    return result


def _estimate_contamination(extra: dict[str, Any], n_rows: int) -> dict[str, Any]:
    """⑫ Contamination (v2 P7·P8: trimmed mean + 고오염 경고).

    v1 단순 평균 → v2 trimmed mean. Q4-7 MSE -18% 개선.
    unreliable_cols 는 평균에서 자동 제외.
    """
    sources: list[float] = []
    breakdown: dict[str, float] = {}

    # IQR×1.5
    iqr_vals = list((extra.get("outlier_ratios_iqr") or {}).values())
    if iqr_vals:
        v = float(sum(iqr_vals) / len(iqr_vals))
        sources.append(v)
        breakdown["iqr_mean"] = round(v, 4)

    # IQR×3.0 (보수적 — 보조 정보로만 breakdown 에 보관, 소스에는 미포함)
    iqr3_vals = list((extra.get("outlier_ratios_iqr_strict") or {}).values())
    if iqr3_vals:
        breakdown["iqr_strict_mean"] = round(float(sum(iqr3_vals) / len(iqr3_vals)), 4)

    # Z (unreliable 제외)
    z_ratios = extra.get("outlier_ratios_zscore") or {}
    z_unreliable = set(extra.get("zscore_unreliable_cols") or [])
    z_clean = [v for c, v in z_ratios.items() if c not in z_unreliable]
    if z_clean:
        v = float(sum(z_clean) / len(z_clean))
        sources.append(v)
        breakdown["zscore_mean"] = round(v, 4)
    if z_unreliable:
        breakdown["zscore_excluded_cols"] = len(z_unreliable)

    # ModZ (unreliable 제외)
    mz_ratios = extra.get("outlier_ratios_modified_z") or {}
    mz_unreliable = set(extra.get("modz_unreliable_cols") or [])
    mz_clean = [v for c, v in mz_ratios.items() if c not in mz_unreliable]
    if mz_clean:
        v = float(sum(mz_clean) / len(mz_clean))
        sources.append(v)
        breakdown["modz_mean"] = round(v, 4)
    if mz_unreliable:
        breakdown["modz_excluded_cols"] = len(mz_unreliable)

    # Vote
    vote_vals = list((extra.get("outlier_vote_ratio") or {}).values())
    if vote_vals:
        v = float(sum(vote_vals) / len(vote_vals))
        sources.append(v)
        breakdown["vote_mean"] = round(v, 4)

    # IF
    if_v = extra.get("isolation_outlier_ratio")
    if if_v is not None:
        sources.append(float(if_v))
        breakdown["if_ratio"] = round(float(if_v), 4)

    # LOF
    lof_v = extra.get("lof_outlier_ratio")
    if lof_v is not None:
        sources.append(float(lof_v))
        breakdown["lof_ratio"] = round(float(lof_v), 4)

    n_src = len(sources)

    if n_src == 0:
        return {
            "contamination_estimate": CONTAMINATION_DEFAULT,
            "contamination_confidence": "low",
            "contamination_sources_used": 0,
            "contamination_method": "default_fallback",
            "contamination_source_breakdown": breakdown,
            "high_contamination_suspected": False,
        }

    # v2 P7: trimmed mean (4+ 소스일 때만)
    if n_src >= TRIMMED_MEAN_MIN_SOURCES:
        srcs_sorted = sorted(sources)
        trimmed = srcs_sorted[1:-1]
        estimate = float(sum(trimmed) / len(trimmed))
        method = "trimmed_mean"
    else:
        estimate = float(sum(sources) / len(sources))
        method = "simple_mean"

    estimate = round(max(CONTAMINATION_MIN, min(CONTAMINATION_MAX, estimate)), 4)

    # 신뢰도
    if n_src >= 5 and n_rows >= 500:
        confidence = "high"
    elif n_src >= 3 and n_rows >= 100:
        confidence = "medium"
    else:
        confidence = "low"

    # v2 P8: 고오염 의심
    univariate_low = all(
        breakdown.get(k, 1.0) < HIGH_CONTAM_UNIVARIATE_THRESHOLD
        for k in ("iqr_mean", "zscore_mean", "modz_mean")
        if k in breakdown
    )
    has_univariate = any(k in breakdown for k in ("iqr_mean", "zscore_mean", "modz_mean"))
    multivariate_high = (
        breakdown.get("if_ratio", 0.0) > HIGH_CONTAM_IF_LOF_THRESHOLD
        or breakdown.get("lof_ratio", 0.0) > HIGH_CONTAM_IF_LOF_THRESHOLD
    )
    high_contam_suspected = bool(has_univariate and univariate_low and multivariate_high)

    return {
        "contamination_estimate": estimate,
        "contamination_confidence": confidence,
        "contamination_sources_used": n_src,
        "contamination_method": method,
        "contamination_source_breakdown": breakdown,
        "high_contamination_suspected": high_contam_suspected,
    }


def _model_hints(extra: dict[str, Any]) -> list[str]:
    """⑬ 모델 힌트."""
    hints: list[str] = []
    contam = float(extra.get("contamination_estimate", CONTAMINATION_DEFAULT))
    has_time = bool(extra.get("has_time_column", False))
    pca_possible = bool(extra.get("pca_dim_reduction_possible", False))
    n_rows = int(extra.get("n_rows", 0))
    n_cols = int(extra.get("n_numeric_cols", 1))

    hints.append("IsolationForest")

    if contam < 0.02:
        hints.append("OneClassSVM")
    else:
        hints.append("LOF")

    if has_time:
        hints.append("TranAD")
    if pca_possible and n_cols > 5:
        hints.append("AutoEncoder")
    if n_rows >= 5000:
        hints.append("DeepSVDD")

    seen: set[str] = set()
    deduped: list[str] = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
    return deduped

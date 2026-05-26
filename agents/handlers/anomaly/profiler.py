"""agents.handlers.anomaly.profiler — 이상탐지 데이터 프로파일 (NY 담당).

Day 1 (NY) 구현 항목:
  ① 기본 통계        — 행수·열수·결측·중복·상수 컬럼
  ② 이상치 비율 3종  — IQR / Z-score / Modified Z-score (MAD 기반)
  ③ 투표 이상치      — 3가지 방법 중 2개 이상 동의 시 확정
  ④ 분포 특성        — 왜도·첨도·고왜도·고첨도 컬럼 목록
  ⑤ 다변량 분석      — 고상관 쌍·마할라노비스 거리 이상치 비율
  ⑥ PCA 차원 분석    — 95% 분산 차원·설명력·압축 가능 여부
  ⑦ Isolation Forest — 컬럼별 score + 전체 이상치 비율 + 최다 이상 컬럼
  ⑧ LOF             — 전체 이상치 비율 (n≤5000 한정, 초과 시 서브샘플)
  ⑨ 시간 컬럼 감지   — datetime 컬럼 존재·범위·간격 이상
  ⑩ contamination    — 앙상블 추정 + 신뢰도 (low/medium/high)
  ⑪ 모델 힌트        — selector 선행 추천 목록
  ⑫ 경고 목록        — 데이터 품질·분석 한계 메시지
"""

from __future__ import annotations

from typing import Any

# ── 공개 진입점 ─────────────────────────────────────────────────────────────


def profile(df: Any, state: Any) -> dict[str, Any]:  # noqa: ARG001
    """DataFrame → 이상탐지 전용 프로파일 dict 반환.

    모든 섹션은 독립 try/except 로 보호 — 하나 실패해도 나머지는 계속.
    반환 dict 의 최상위 키는 아래 '섹션별 접두어' 참고.
    """
    import numpy as np
    import pandas as pd

    extra: dict[str, Any] = {}
    warnings: list[str] = []

    # ── 수치 컬럼만 추출 (결측 제거 전) ──────────────────────────────────
    num_df_raw: pd.DataFrame = df.select_dtypes(include=[np.number])
    if num_df_raw.empty:
        extra["anomaly_warning"] = "수치 컬럼 없음 — 프로파일 중단"
        return extra

    num_df: pd.DataFrame = num_df_raw.dropna()
    n_rows_raw = len(df)
    n_rows = len(num_df)

    if n_rows < 10:
        warnings.append(f"유효 행 수 {n_rows}개 — 신뢰도 낮음 (권장 최소: 50)")

    # ── ① 기본 통계 ──────────────────────────────────────────────────────
    extra.update(_basic_stats(df, num_df_raw, num_df, n_rows_raw))

    # ── ② IQR 이상치 비율 ────────────────────────────────────────────────
    try:
        extra.update(_outlier_iqr(num_df))
    except Exception as e:
        warnings.append(f"IQR 분석 실패: {e}")

    # ── ③ Z-score 이상치 비율 ────────────────────────────────────────────
    try:
        extra.update(_outlier_zscore(num_df))
    except Exception as e:
        warnings.append(f"Z-score 분석 실패: {e}")

    # ── ④ Modified Z-score (MAD 기반, 비정규 분포에 강건) ────────────────
    try:
        extra.update(_outlier_modified_z(num_df))
    except Exception as e:
        warnings.append(f"Modified Z-score 분석 실패: {e}")

    # ── ⑤ 투표 이상치 비율 (3가지 방법 앙상블) ──────────────────────────
    try:
        extra.update(_outlier_vote(num_df, extra))
    except Exception as e:
        warnings.append(f"투표 이상치 분석 실패: {e}")

    # ── ⑥ 분포 특성 (왜도·첨도) ─────────────────────────────────────────
    try:
        extra.update(_distribution_shape(num_df))
    except Exception as e:
        warnings.append(f"분포 특성 분석 실패: {e}")

    # ── ⑦ 다변량 분석 (고상관·마할라노비스) ──────────────────────────────
    if n_rows >= 20 and num_df.shape[1] >= 2:
        try:
            extra.update(_multivariate(num_df, warnings))
        except Exception as e:
            warnings.append(f"다변량 분석 실패: {e}")
    else:
        warnings.append("다변량 분석 생략 — 행 수 < 20 또는 수치 컬럼 < 2")

    # ── ⑧ PCA 차원 분석 ──────────────────────────────────────────────────
    if num_df.shape[1] >= 2:
        try:
            extra.update(_pca_analysis(num_df))
        except Exception as e:
            warnings.append(f"PCA 분석 실패: {e}")
    else:
        extra["pca_n_components_95"] = 1
        extra["pca_total_dims"] = num_df.shape[1]

    # ── ⑨ Isolation Forest 분석 ──────────────────────────────────────────
    try:
        extra.update(_isolation_analysis(num_df, warnings))
    except Exception as e:
        warnings.append(f"Isolation Forest 분석 실패: {e}")

    # ── ⑩ LOF 이상치 비율 ────────────────────────────────────────────────
    if n_rows >= 20:
        try:
            extra.update(_lof_analysis(num_df, warnings))
        except Exception as e:
            warnings.append(f"LOF 분석 실패: {e}")
    else:
        warnings.append("LOF 생략 — 행 수 < 20")

    # ── ⑪ 시간 컬럼 감지 ─────────────────────────────────────────────────
    try:
        extra.update(_time_column_analysis(df))
    except Exception as e:
        warnings.append(f"시간 컬럼 분석 실패: {e}")

    # ── ⑫ contamination 앙상블 추정 ──────────────────────────────────────
    try:
        extra.update(_estimate_contamination(extra, n_rows))
    except Exception as e:
        warnings.append(f"contamination 추정 실패: {e}")
        extra["contamination_estimate"] = 0.05
        extra["contamination_confidence"] = "low"

    # ── ⑬ 모델 힌트 ──────────────────────────────────────────────────────
    extra["recommended_model_hints"] = _model_hints(extra)

    # selector 호환 키
    extra["rows"] = n_rows_raw

    extra["profile_warnings"] = warnings
    return extra


# ── 섹션별 내부 함수 ────────────────────────────────────────────────────────


def _basic_stats(df: Any, num_raw: Any, num_clean: Any, n_rows_raw: int) -> dict[str, Any]:

    missing = {str(c): float(num_raw[c].isna().mean()) for c in num_raw.columns}
    constant = [str(c) for c in num_clean.columns if num_clean[c].nunique() <= 1]
    dup_ratio = float(df.duplicated().mean()) if n_rows_raw > 0 else 0.0
    return {
        "n_rows": n_rows_raw,
        "n_numeric_cols": int(num_raw.shape[1]),
        "missing_ratio_per_col": missing,
        "constant_cols": constant,
        "duplicate_row_ratio": round(dup_ratio, 4),
        "has_constant_cols": len(constant) > 0,
    }


def _outlier_iqr(num_df: Any) -> dict[str, Any]:
    ratios: dict[str, float] = {}
    for c in num_df.columns:
        q1, q3 = num_df[c].quantile(0.25), num_df[c].quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        ratios[str(c)] = round(float(((num_df[c] < low) | (num_df[c] > high)).mean()), 4)
    return {"outlier_ratios_iqr": ratios}


def _outlier_zscore(num_df: Any) -> dict[str, Any]:
    ratios: dict[str, float] = {}
    for c in num_df.columns:
        std = float(num_df[c].std())
        if std <= 0:
            continue
        z = (num_df[c] - num_df[c].mean()).abs() / std
        ratios[str(c)] = round(float((z > 3).mean()), 4)
    return {"outlier_ratios_zscore": ratios}


def _outlier_modified_z(num_df: Any) -> dict[str, Any]:
    """Modified Z-score: MAD(중앙절대편차) 기반 — 정규 분포 가정 없이 강건."""
    import numpy as np

    ratios: dict[str, float] = {}
    for c in num_df.columns:
        vals = num_df[c].values.astype(float)
        median = float(np.median(vals))
        mad = float(np.median(np.abs(vals - median)))
        if mad <= 0:
            continue
        # 상수 0.6745 = norm.ppf(0.75) — MAD → std 변환 계수
        mz = 0.6745 * np.abs(vals - median) / mad
        ratios[str(c)] = round(float((mz > 3.5).mean()), 4)
    return {"outlier_ratios_modified_z": ratios}


def _outlier_vote(num_df: Any, extra: dict[str, Any]) -> dict[str, Any]:
    """3가지 방법 중 2개 이상이 이상치로 표시한 행 비율."""
    import numpy as np

    iqr = extra.get("outlier_ratios_iqr", {})
    zscore = extra.get("outlier_ratios_zscore", {})
    mz = extra.get("outlier_ratios_modified_z", {})

    cols = set(iqr) & set(zscore) & set(mz)
    if not cols:
        return {"outlier_vote_ratio": {}}

    vote_ratios: dict[str, float] = {}
    for c in cols:
        col = num_df[c].values.astype(float)
        median = float(np.median(col))
        std = float(num_df[c].std())
        mad = float(np.median(np.abs(col - median)))

        q1, q3 = float(num_df[c].quantile(0.25)), float(num_df[c].quantile(0.75))
        iqr_range = q3 - q1

        flags = np.zeros(len(col), dtype=int)
        if iqr_range > 0:
            flags += ((col < q1 - 1.5 * iqr_range) | (col > q3 + 1.5 * iqr_range)).astype(int)
        if std > 0:
            flags += (np.abs(col - col.mean()) / std > 3).astype(int)
        if mad > 0:
            flags += (0.6745 * np.abs(col - median) / mad > 3.5).astype(int)

        vote_ratios[str(c)] = round(float((flags >= 2).mean()), 4)

    return {"outlier_vote_ratio": vote_ratios}


def _distribution_shape(num_df: Any) -> dict[str, Any]:
    """왜도·첨도 + 이상 분포 컬럼 목록."""
    skew = {str(c): round(float(num_df[c].skew()), 3) for c in num_df.columns}
    kurt = {str(c): round(float(num_df[c].kurt()), 3) for c in num_df.columns}
    high_skew = [c for c, v in skew.items() if abs(v) > 2]
    high_kurt = [c for c, v in kurt.items() if v > 7]
    return {
        "skewness_per_col": skew,
        "kurtosis_per_col": kurt,
        "high_skew_cols": high_skew,
        "high_kurtosis_cols": high_kurt,
    }


def _multivariate(num_df: Any, warnings: list[str]) -> dict[str, Any]:
    """고상관 쌍 탐지 + 마할라노비스 거리 이상치 비율."""
    import numpy as np

    result: dict[str, Any] = {}

    # 고상관 쌍
    corr = num_df.corr()
    high_pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            v = float(corr.iloc[i, j])
            if abs(v) > 0.8:
                high_pairs.append((cols[i], cols[j], round(v, 3)))
    result["high_correlation_pairs"] = high_pairs

    # 마할라노비스 거리 (특이값 분해 방식, 역행렬 불안정 대비)
    try:
        X = num_df.values.astype(float)
        mean = X.mean(axis=0)
        cov = np.cov(X.T)
        # 정규화된 역행렬: pinv 사용 (singular matrix 대비)
        inv_cov = np.linalg.pinv(cov)
        diff = X - mean
        mahal = np.sqrt(np.einsum("ij,jk,ik->i", diff, inv_cov, diff))
        threshold = np.percentile(mahal, 97.5)
        result["mahalanobis_outlier_ratio"] = round(float((mahal > threshold).mean()), 4)
        result["mahalanobis_threshold_p975"] = round(float(threshold), 4)
    except Exception as e:
        warnings.append(f"마할라노비스 거리 계산 실패: {e}")
        result["mahalanobis_outlier_ratio"] = None

    return result


def _pca_analysis(num_df: Any) -> dict[str, Any]:
    """95% 분산 설명 차원 수·설명력·압축 가능 여부."""
    import numpy as np
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler

    n_cols = num_df.shape[1]
    X = StandardScaler().fit_transform(num_df)
    pca = PCA(n_components=min(n_cols, len(num_df) - 1)).fit(X)

    evr = pca.explained_variance_ratio_.tolist()
    cumvar = np.cumsum(evr)
    n95 = int(np.searchsorted(cumvar, 0.95)) + 1
    n95 = min(n95, n_cols)

    return {
        "pca_n_components_95": n95,
        "pca_total_dims": n_cols,
        "pca_explained_variance_ratio": [round(v, 4) for v in evr[:10]],
        "pca_dim_reduction_possible": n95 < int(n_cols * 0.8),
    }


def _isolation_analysis(num_df: Any, warnings: list[str]) -> dict[str, Any]:
    """컬럼별 1D IsolationForest score + 전체 다변량 이상치 비율."""
    import numpy as np
    from sklearn.ensemble import IsolationForest

    result: dict[str, Any] = {}

    # 컬럼별 1D score
    dim_scores: dict[str, float] = {}
    for c in num_df.columns:
        vals = num_df[[c]].values
        if len(vals) < 10:
            continue
        ifo = IsolationForest(n_estimators=100, contamination="auto", random_state=42)
        ifo.fit(vals)
        dim_scores[str(c)] = round(float(np.mean(ifo.score_samples(vals))), 4)
    result["isolation_depth_per_dim"] = dim_scores

    # 가장 이상 밀도 높은 컬럼 (score 최소값)
    if dim_scores:
        result["most_anomalous_dim"] = min(dim_scores, key=lambda k: dim_scores[k])

    # 전체 다변량 이상치 비율
    try:
        X = num_df.values
        # 대용량 서브샘플 (10000행 초과 시)
        if len(X) > 10000:
            idx = np.random.default_rng(42).choice(len(X), 10000, replace=False)
            X_fit = X[idx]
            warnings.append("IF 전체 분석: 10000행 서브샘플 사용")
        else:
            X_fit = X
        ifo_all = IsolationForest(n_estimators=100, contamination="auto", random_state=42)
        ifo_all.fit(X_fit)
        preds = ifo_all.predict(X)
        result["isolation_outlier_ratio"] = round(float((preds == -1).mean()), 4)
    except Exception as e:
        warnings.append(f"IF 전체 분석 실패: {e}")
        result["isolation_outlier_ratio"] = None

    return result


def _lof_analysis(num_df: Any, warnings: list[str]) -> dict[str, Any]:
    """LOF(Local Outlier Factor) 이상치 비율 — 5000행 초과 시 서브샘플."""
    import numpy as np
    from sklearn.neighbors import LocalOutlierFactor

    X = num_df.values
    if len(X) > 5000:
        idx = np.random.default_rng(42).choice(len(X), 5000, replace=False)
        X = X[idx]
        warnings.append("LOF 분석: 5000행 서브샘플 사용")

    n_neighbors = min(20, len(X) - 1)
    lof = LocalOutlierFactor(n_neighbors=n_neighbors, contamination="auto")
    preds = lof.fit_predict(X)
    return {"lof_outlier_ratio": round(float((preds == -1).mean()), 4)}


def _time_column_analysis(df: Any) -> dict[str, Any]:
    """datetime 컬럼 자동 감지 + 시간 범위·간격 이상 탐지."""
    import pandas as pd

    time_candidates = []
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            time_candidates.append(str(c))
        elif df[c].dtype == object:
            sample = df[c].dropna().head(20)
            try:
                parsed = pd.to_datetime(sample, infer_datetime_format=True, errors="raise")
                if len(parsed) >= 5:
                    time_candidates.append(str(c))
            except Exception:
                pass

    result: dict[str, Any] = {
        "has_time_column": len(time_candidates) > 0,
        "time_column_candidates": time_candidates,
    }

    if time_candidates:
        col = time_candidates[0]
        try:
            ts = pd.to_datetime(df[col], infer_datetime_format=True, errors="coerce").dropna().sort_values()
            if len(ts) >= 2:
                total_days = (ts.iloc[-1] - ts.iloc[0]).total_seconds() / 86400
                gaps = ts.diff().dropna().dt.total_seconds()
                median_gap = float(gaps.median())
                gap_iqr = float(gaps.quantile(0.75) - gaps.quantile(0.25))
                time_gap_anomalies = int((gaps > median_gap + 3 * gap_iqr).sum()) if gap_iqr > 0 else 0
                result.update(
                    {
                        "time_range_days": round(total_days, 1),
                        "time_median_gap_sec": round(median_gap, 1),
                        "time_gap_anomaly_count": time_gap_anomalies,
                    }
                )
        except Exception:
            pass

    return result


def _estimate_contamination(extra: dict[str, Any], n_rows: int) -> dict[str, Any]:
    """다중 방법 앙상블 contamination 추정 + 신뢰도 분류."""
    sources: list[float] = []

    for key in ("outlier_ratios_iqr", "outlier_ratios_zscore", "outlier_ratios_modified_z", "outlier_vote_ratio"):
        vals = list(extra.get(key, {}).values())
        if vals:
            sources.append(float(sum(vals) / len(vals)))

    for key in ("isolation_outlier_ratio", "lof_outlier_ratio"):
        v = extra.get(key)
        if v is not None:
            sources.append(float(v))

    if not sources:
        return {
            "contamination_estimate": 0.05,
            "contamination_confidence": "low",
        }

    estimate = float(sum(sources) / len(sources))
    estimate = round(max(0.001, min(0.5, estimate)), 4)

    # 신뢰도: 방법 수 + 데이터 크기 기준
    if len(sources) >= 5 and n_rows >= 500:
        confidence = "high"
    elif len(sources) >= 3 and n_rows >= 100:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "contamination_estimate": estimate,
        "contamination_confidence": confidence,
        "contamination_sources_used": len(sources),
    }


def _model_hints(extra: dict[str, Any]) -> list[str]:
    """프로파일 결과 기반 모델 힌트 — selector 가 이를 참조해 최종 결정."""
    hints: list[str] = []
    contam = extra.get("contamination_estimate", 0.05)
    has_time = extra.get("has_time_column", False)
    pca_possible = extra.get("pca_dim_reduction_possible", False)
    n_rows = extra.get("n_rows", 0)
    n_cols = extra.get("n_numeric_cols", 1)

    # 기본 — 항상 포함
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

    return hints

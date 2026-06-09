"""agents.handlers.tabular.profiler — 정형 데이터 추가 프로파일 (jh 담당)."""

from __future__ import annotations

from typing import Any


def compute_preprocessing_thresholds_suggested(
    df: Any,
    profile: dict[str, Any],
    hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """데이터 특성 기반 전처리 임계값 추천. preprocessor가 0-4 우선순위로 소비."""
    import math

    import numpy as np

    n_rows = max(int(df.shape[0]), 1)
    n_features = int(df.shape[1])

    # available_ram_mb
    try:
        import psutil

        available_ram_mb = psutil.virtual_memory().available // (1024 * 1024)
    except Exception:
        available_ram_mb = 2048

    # corr_condition_number — numeric 컬럼 기반
    try:
        num_df = df.select_dtypes(include=[np.number])
        if num_df.shape[1] >= 2:
            corr_condition_number = float(np.linalg.cond(num_df.corr().values))
        else:
            corr_condition_number = 1.0
    except Exception:
        corr_condition_number = 1.0

    # missing_pct — profile dict 우선, 없으면 직접 계산
    missing_raw = profile.get("missing")
    if missing_raw and isinstance(missing_raw, dict):
        missing_vals = list(missing_raw.values())
    else:
        missing_vals = list(df.isna().mean().values)

    if len(missing_vals) >= 2:
        m_mean = float(np.mean(missing_vals))
        m_std = float(np.std(missing_vals))
        missing_drop_threshold = float(np.clip(m_mean + 2 * m_std, 0.3, 0.9))
    else:
        missing_drop_threshold = 0.3

    return {
        "target_encoding_min_card": max(20, int(math.sqrt(n_rows))),
        "id_col_unique_ratio": round(1 - 1 / math.log(max(n_rows, 3)), 4),
        "missing_drop_threshold": round(missing_drop_threshold, 4),
        "smote_imbalance_entropy_threshold": 0.85,
        "smote_max_synthetic_mem_mb": int(available_ram_mb * 0.30),
        "vif_threshold": 5.0 if corr_condition_number > 30 else 10.0,
        "vif_max_drop_ratio": round(min(0.3, 1 - 1 / math.sqrt(max(n_features, 4))), 4),
        "balance_dod_pass_ratio": 0.9,
        "_computed_with": {
            "n_rows": n_rows,
            "n_features": n_features,
            "available_ram_gb": round(available_ram_mb / 1024, 2),
            "corr_condition_number": round(corr_condition_number, 4),
        },
    }


def profile(df: Any, state: Any) -> dict[str, Any]:
    """class balance, VIF (top 5), correlation cluster, cardinality 등급."""
    import numpy as np  # noqa: WPS433

    extra: dict[str, Any] = {}
    target = state.target_column
    try:
        # 클래스 불균형 — 분류 한정
        if target and target in df.columns:
            vc = df[target].value_counts(normalize=True, dropna=False)
            if 1 < len(vc) <= 50:
                imbalance = float(vc.max() / max(vc.min(), 1e-9))
                extra["class_imbalance_ratio"] = round(imbalance, 3)

        # 카디널리티 등급
        card_levels: dict[str, str] = {}
        for c in df.columns:
            if c == target:
                continue
            n = int(df[c].nunique(dropna=True))
            if n <= 2:
                card_levels[c] = "binary"
            elif n <= 10:
                card_levels[c] = "low"
            elif n <= 50:
                card_levels[c] = "medium"
            else:
                card_levels[c] = "high"
        extra["cardinality_levels"] = card_levels

        # VIF (수치형 top 10)  — 간이 구현: cor(X, X) 역행렬 대각
        num_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != target][:10]
        if len(num_cols) >= 2:
            from numpy.linalg import LinAlgError, inv

            try:
                M = df[num_cols].fillna(0).corr().values
                if not np.isnan(M).any():
                    vif = np.diag(inv(M))
                    extra["vif_top"] = {col: round(float(v), 2) for col, v in zip(num_cols, vif)}
            except LinAlgError:
                pass

        # 상관 클러스터 — |corr| >= 0.7 인 수치형 컬럼을 연결 컴포넌트로 묶기
        if len(num_cols) >= 2:
            corr_mat = df[num_cols].fillna(0).corr().abs()
            # Union-Find 로 연결 컴포넌트 구성
            parent = {c: c for c in num_cols}

            def find(x: str) -> str:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            for i, ci in enumerate(num_cols):
                for cj in num_cols[i + 1 :]:
                    if corr_mat.loc[ci, cj] >= 0.7:
                        ri, rj = find(ci), find(cj)
                        if ri != rj:
                            parent[rj] = ri

            clusters: dict[str, list[str]] = {}
            for c in num_cols:
                root = find(c)
                clusters.setdefault(root, []).append(c)

            # 단독 컬럼(클러스터 크기 1)은 제외하고 인덱스 재부여
            grouped = [sorted(v) for v in clusters.values() if len(v) > 1]
            extra["correlation_clusters"] = {f"cluster_{i}": g for i, g in enumerate(grouped)}

    except Exception as e:
        extra["tabular_warning"] = str(e)

    # Day 11 (jh) — EDA 보강: id-like / target leakage / mutual_info
    try:
        extra.update(_detect_id_like_and_leakage(df, target))
    except Exception as e:
        extra["eda_detection_warning"] = str(e)

    try:
        extra["mutual_info_top"] = _compute_mutual_info_top(df, target)
    except Exception as e:
        extra["mutual_info_warning"] = str(e)

    extra["preprocessing_thresholds_suggested"] = compute_preprocessing_thresholds_suggested(df, extra)

    # ── archetype 분류 ──────────────────────────────────────────────────────
    # 신호를 individual 키로만 두지 않고, "이 데이터는 어떤 archetype 인가"를
    # 1 개(+우선순위 후보들)로 종합 판단해 selector/insight/output_extras 가
    # 데이터 맞춤 결정을 할 수 있게 함.
    try:
        # data_profile 폴백 — profile 이 아직 state 에 반영 안 됐을 수 있어
        # df.shape 기반 rows/cols 를 안전하게 주입.
        merged_profile = dict(extra)
        merged_profile.setdefault("rows", int(df.shape[0]))
        merged_profile.setdefault("cols", int(df.shape[1]))
        # dtypes 주입 — classify_archetypes 가 numeric 필터에 사용
        merged_profile.setdefault("dtypes", {c: str(df[c].dtype) for c in df.columns})
        # numeric 통계도 archetype 의 회귀 heteroscedasticity 추정에 필요
        try:
            num_df = df.select_dtypes(include=[np.number])
            merged_profile.setdefault(
                "numeric_stats",
                {
                    c: {
                        "mean": float(num_df[c].mean()) if num_df[c].notna().any() else 0.0,
                        "std": float(num_df[c].std()) if num_df[c].notna().any() else 0.0,
                    }
                    for c in num_df.columns
                },
            )
        except Exception:
            pass

        from agents.handlers.tabular.archetype import classify_archetypes

        extra["archetype"] = classify_archetypes(merged_profile, state)
    except Exception as e:
        extra["archetype_warning"] = str(e)

    return extra


# ───────────────────────────────────────────────────────────────────────────
# Day 11 (jh) — EDA 보강 헬퍼
# ───────────────────────────────────────────────────────────────────────────


def _detect_id_like_and_leakage(df: Any, target: str | None) -> dict[str, Any]:
    """id-like 컬럼 + target leakage 의심 컬럼 검출.

    id-like : unique_ratio ≥ 0.99 → PK 추정. 학습 피처로 부적절.
    target leakage : target 과 |corr| ≥ 0.95 numeric 컬럼 → 누수 의심.
                     (예: target=label, feature=label_encoded_id 같은 거)
    """
    import numpy as np

    n_rows = int(len(df))
    if n_rows == 0:
        return {"id_like_columns": [], "target_leakage_suspects": []}

    id_like: list[str] = []
    for col in df.columns:
        if col == target:
            continue
        try:
            # 연속 float 는 unique_ratio=1.0 이 정상 — id-like 오탐 방지
            if "float" in str(df[col].dtype).lower():
                continue
            uniq = int(df[col].nunique(dropna=True))
            if n_rows > 0 and (uniq / n_rows) >= 0.99:
                id_like.append(str(col))
        except Exception:
            continue

    leakage: list[dict[str, Any]] = []
    if target and target in df.columns:
        try:
            # numeric 컬럼만 — 상관계수 계산 가능
            num_df = df.select_dtypes(include=[np.number])
            if target in num_df.columns and num_df.shape[1] >= 2:
                # target 이 numeric 이면 직접 corr
                corrs = num_df.corr()[target].drop(labels=[target], errors="ignore")
                for col, c in corrs.items():
                    if not np.isfinite(c):
                        continue
                    if abs(float(c)) >= 0.95 and str(col) != target:
                        leakage.append({"column": str(col), "correlation": round(float(c), 4)})
            elif target in df.columns:
                # target 이 categorical — class encoding 후 numeric 피처들과 corr 추정
                # (간이: target 을 factorize 한 코드와의 상관)
                try:
                    import pandas as pd  # noqa: WPS433

                    y_code, _ = pd.factorize(df[target].astype(str))
                    for col in num_df.columns:
                        if col == target:
                            continue
                        x = df[col].fillna(df[col].median()).values
                        if x.std() == 0:
                            continue
                        c = float(np.corrcoef(x, y_code)[0, 1])
                        if not np.isfinite(c):
                            continue
                        if abs(c) >= 0.95:
                            leakage.append({"column": str(col), "correlation": round(c, 4)})
                except Exception:
                    pass
        except Exception:
            pass

    return {"id_like_columns": id_like, "target_leakage_suspects": leakage}


def _compute_mutual_info_top(df: Any, target: str | None, top_k: int = 10) -> dict[str, float]:
    """피처 ↔ target mutual information score top K.

    sklearn.feature_selection.mutual_info_classif / mutual_info_regression 활용.
    n_rows > 50000 시 무거우니 50000 행 샘플링 가드.
    target categorical(분류) vs numeric(회귀) 자동 분기.
    """
    import pandas as pd

    if not target or target not in df.columns:
        return {}
    n_rows = int(len(df))
    if n_rows < 30:  # 너무 작으면 MI 신뢰 불가
        return {}

    # 샘플링 가드 — 대용량에선 5만 행 무작위 샘플
    sample_df = df
    if n_rows > 50_000:
        sample_df = df.sample(n=50_000, random_state=42)

    # 분류/회귀 결정
    y = sample_df[target]
    n_unique = int(y.nunique(dropna=True))
    is_classification = n_unique <= 50

    # numeric 피처만 (categorical 은 mutual_info 가 자동 처리 가능하나 일관성 위해 단순화)
    feature_cols = [c for c in sample_df.columns if c != target]
    X = sample_df[feature_cols].copy()

    # 결측 처리 — numeric median, object frequency 인코딩
    for c in X.columns:
        if pd.api.types.is_numeric_dtype(X[c]):
            X[c] = X[c].fillna(X[c].median() if X[c].notna().any() else 0.0)
        else:
            # frequency encoding (간이) — 결측 빈도 0 으로
            freq = X[c].value_counts(normalize=True, dropna=False)
            X[c] = X[c].map(freq).fillna(0.0)

    X_arr = X.to_numpy(dtype=float)
    y_arr = y.fillna(y.mode().iloc[0] if y.mode().size > 0 else 0).to_numpy()

    try:
        if is_classification:
            from sklearn.feature_selection import mutual_info_classif

            mi = mutual_info_classif(X_arr, y_arr, random_state=42)
        else:
            from sklearn.feature_selection import mutual_info_regression

            mi = mutual_info_regression(X_arr, y_arr, random_state=42)
    except Exception:
        return {}

    # top_k 정렬
    pairs = sorted(
        zip(feature_cols, mi.tolist()),
        key=lambda kv: kv[1],
        reverse=True,
    )[:top_k]
    return {str(c): round(float(v), 4) for c, v in pairs}

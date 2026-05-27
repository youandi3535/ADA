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

    extra["preprocessing_thresholds_suggested"] = compute_preprocessing_thresholds_suggested(df, extra)
    return extra

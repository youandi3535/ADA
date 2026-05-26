"""agents.handlers.tabular.profiler — 정형 데이터 추가 프로파일 (jh 담당)."""

from __future__ import annotations

from typing import Any


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
    return extra

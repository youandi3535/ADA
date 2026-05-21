"""agents.handlers.tabular.profiler — 정형 데이터 추가 프로파일 (C 담당)."""
from __future__ import annotations

from typing import Any


def profile(df: Any, state: Any) -> dict[str, Any]:
    """class balance, VIF (top 5), cardinality 등급."""
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
        num_cols = [c for c in df.select_dtypes(include=[np.number]).columns
                    if c != target][:10]
        if len(num_cols) >= 2:
            from numpy.linalg import inv, LinAlgError
            try:
                M = df[num_cols].fillna(0).corr().values
                if not np.isnan(M).any():
                    vif = np.diag(inv(M))
                    extra["vif_top"] = {col: round(float(v), 2)
                                          for col, v in zip(num_cols, vif)}
            except LinAlgError:
                pass
    except Exception as e:
        extra["tabular_warning"] = str(e)
    return extra

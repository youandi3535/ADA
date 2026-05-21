"""agents.handlers.tabular.proposer — G1/G2 fallback (C 담당)."""
from __future__ import annotations

from typing import Any


def g1(state: Any) -> list[dict[str, Any]]:
    return [
        {"id": 1, "title": "분류/회귀 예측", "rationale": "타겟 컬럼 기반 지도학습",
         "score": 0.85},
        {"id": 2, "title": "피처 중요도 분석", "rationale": "주요 변수 식별",
         "score": 0.65},
        {"id": 3, "title": "세그먼트 비교", "rationale": "타겟 분포에 따른 집단 분석",
         "score": 0.55},
    ]


def g2(state: Any) -> list[dict[str, Any]]:
    """G2 — n_rows 충분하면 DL 도 후보."""
    profile = state.data_profile or {}
    n_rows = int(profile.get("rows", 0))
    base = [
        {"id": 1, "title": state.category, "rationale": "현재 카테고리 유지",
         "score": 0.9},
    ]
    if n_rows >= 5000 and state.category == "tabular_ml":
        base.append({"id": 2, "title": "tabular_dl",
                     "rationale": "데이터 충분 — DL 비교 권장",
                     "score": 0.7})
    return base

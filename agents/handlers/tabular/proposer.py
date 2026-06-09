"""agents.handlers.tabular.proposer — G2/G3 fallback (jh 담당).

Day 11+ (jh, decision-aware):
    archetype 분류 결과를 G1/G2 제안에 반영.
    - extreme_imbalance → G2 에 anomaly_detection 카테고리 권고 (정형 분류 부적합 신호)
    - p_gg_n → G1 에 "차원 축소·피처 선택" 옵션 가산
"""

from __future__ import annotations

from typing import Any


def _archetype_primary(state: Any) -> str | None:
    profile = getattr(state, "data_profile", None) or {}
    return ((profile.get("archetype") or {}).get("primary")) or None


def g1(state: Any) -> list[dict[str, Any]]:
    """G1 — 분석 방향 fallback 제안."""
    base = [
        {"id": 1, "title": "분류/회귀 예측", "rationale": "타겟 컬럼 기반 지도학습", "score": 0.85},
        {"id": 2, "title": "피처 중요도 분석", "rationale": "주요 변수 식별", "score": 0.65},
        {"id": 3, "title": "세그먼트 비교", "rationale": "타겟 분포에 따른 집단 분석", "score": 0.55},
    ]
    primary = _archetype_primary(state)
    if primary == "p_gg_n":
        base.append({
            "id": 4,
            "title": "차원 축소·피처 선택",
            "rationale": "피처가 행보다 많거나 동등 — 정규화 선형 모델 또는 피처 선택 우선",
            "score": 0.75,
        })
    return base


def g2(state: Any) -> list[dict[str, Any]]:
    """G2 — 분석 방법론 fallback 제안.

    decision-aware:
      - extreme_imbalance (>=1000:1) -> tabular_ml 부적합 -> anomaly_detection 최우선 권고
      - n_rows >= 5000 + tabular_ml -> tabular_dl 비교 옵션
    """
    profile = state.data_profile or {}
    n_rows = int(profile.get("rows", 0))
    primary = _archetype_primary(state)

    if primary == "extreme_imbalance":
        return [
            {
                "id": 1,
                "title": "anomaly_detection",
                "rationale": (
                    "클래스 비율 1:1000 이상 — 정형 분류 보다 이상탐지 모델이 적합. "
                    "SMOTE 도 메모리 폭주 위험."
                ),
                "score": 0.95,
            },
            {
                "id": 2,
                "title": state.category,
                "rationale": "참고용 — 현재 카테고리 유지 시 cost-sensitive 임계치 필수",
                "score": 0.45,
            },
        ]

    base = [
        {"id": 1, "title": state.category, "rationale": "현재 카테고리 유지", "score": 0.9},
    ]
    if n_rows >= 5000 and state.category == "tabular_ml":
        base.append({"id": 2, "title": "tabular_dl", "rationale": "데이터 충분 — DL 비교 권장", "score": 0.7})
    return base

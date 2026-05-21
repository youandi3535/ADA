"""agents.handlers.timeseries.proposer — 시계열 G1/G2 fallback 제안 (A 담당).

LLM 실패 시 dispatcher (gates/) 가 본 함수를 호출하여 3안 fallback.
"""
from __future__ import annotations

from typing import Any


def g1(state: Any) -> list[dict[str, Any]]:
    """G1 분석 방향 3안 — 시계열."""
    return [
        {"id": 1, "title": "단기 예측 (1~30일)", "rationale": "최근 추세 기반 forecasting",
         "score": 0.85},
        {"id": 2, "title": "이상 시점 탐지", "rationale": "변동성 큰 구간 식별",
         "score": 0.65},
        {"id": 3, "title": "계절성 분해", "rationale": "추세/계절/잔차 분리",
         "score": 0.55},
    ]


def g2(state: Any) -> list[dict[str, Any]]:
    """G2 방법론 — 시계열 카테고리 유지 우선."""
    return [
        {"id": 1, "title": "timeseries", "rationale": "현재 카테고리 유지", "score": 0.95},
    ]

"""agents.handlers.anomaly.proposer — G1/G2 fallback (NY 담당)."""

from __future__ import annotations

from typing import Any


def g1(state: Any) -> list[dict[str, Any]]:
    return [
        {"id": 1, "title": "이상치 점수화", "rationale": "샘플별 anomaly score 산출", "score": 0.85},
        {"id": 2, "title": "정상 분포 학습", "rationale": "OneClassSVM/AE 등 정상 표현", "score": 0.7},
        {"id": 3, "title": "Top-N 알림", "rationale": "상위 N 이상치 리포트", "score": 0.6},
    ]


def g2(state: Any) -> list[dict[str, Any]]:
    return [
        {"id": 1, "title": "anomaly_detection", "rationale": "현재 카테고리 유지", "score": 0.95},
    ]

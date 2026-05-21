"""agents.handlers.timeseries.selector — 시계열 모델 추천 (A 담당).

기본 top3: Prophet / SARIMA / TFT.
Day 5 (A): 길이/계절성/exog 유무 기반 score 매트릭스로 동적 결정.
"""
from __future__ import annotations

from typing import Any


def score(state: Any, recipes: list[dict[str, Any]]) -> dict[str, Any]:
    """top3 + rationale + citations."""
    profile = state.data_profile or {}
    n_rows = int(profile.get("rows", 0))

    # 짧은 시계열은 TFT/Informer 같은 DL 부적합
    if n_rows < 100:
        top3 = ["ARIMA", "SARIMA", "Prophet"]
        rationale = "데이터가 100행 미만이라 통계 모델 위주 추천"
    elif n_rows < 1000:
        top3 = ["Prophet", "SARIMA", "TFT"]
        rationale = "중간 길이 시계열 — Prophet/SARIMA 안정 + TFT 비교"
    else:
        top3 = ["Prophet", "TFT", "PatchTST"]
        rationale = "충분한 시계열 길이 — DL 트랜스포머 후보 우선"

    citations = [r["hash"] for r in recipes[:3] if r.get("hash")]
    return {"top3": top3, "rationale": rationale, "citations": citations}

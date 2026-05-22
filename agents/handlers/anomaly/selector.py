"""agents.handlers.anomaly.selector — 이상탐지 모델 추천 (NY 담당)."""

from __future__ import annotations

from typing import Any


def score(state: Any, recipes: list[dict[str, Any]]) -> dict[str, Any]:
    profile = state.data_profile or {}
    n_rows = int(profile.get("rows", 0))
    contam = float(profile.get("contamination_estimate", 0.05))

    if n_rows < 1000:
        top3 = ["IsolationForest", "LOF", "OneClassSVM"]
        rationale = "소규모 데이터 — 고전 이상탐지 3종"
    elif contam < 0.02:
        top3 = ["OneClassSVM", "IsolationForest", "AutoEncoder"]
        rationale = "이상치 비율이 매우 낮음 — 정상 분포 학습 우선"
    else:
        top3 = ["IsolationForest", "AutoEncoder", "TranAD"]
        rationale = "충분한 데이터 + 이상치 비율 보통 — IForest + DL 강화"

    citations = [r["hash"] for r in recipes[:3] if r.get("hash")]
    return {"top3": top3, "rationale": rationale, "citations": citations}

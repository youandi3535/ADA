"""agents.handlers.tabular.selector — 정형 ML/DL 모델 추천 (C 담당)."""
from __future__ import annotations

from typing import Any


def score(state: Any, recipes: list[dict[str, Any]]) -> dict[str, Any]:
    profile = state.data_profile or {}
    n_rows = int(profile.get("rows", 0))
    n_classes = len(profile.get("class_distribution") or {})
    imb = float(profile.get("class_imbalance_ratio", 1.0))

    if state.category == "tabular_dl":
        top3 = ["FTTransformer", "TabTransformer", "TabPFN"]
        rationale = "DL 카테고리 — 트랜스포머 3종 비교"
    elif n_rows >= 5000 and n_classes >= 2 and imb < 10:
        top3 = ["XGBoost", "LightGBM", "CatBoost"]
        rationale = "충분한 데이터 + 균형 — Gradient Boosting 3종"
    elif imb >= 10:
        top3 = ["LightGBM", "CatBoost", "RandomForest"]
        rationale = "클래스 불균형 — class_weight 지원 모델 우선"
    else:
        top3 = ["RandomForest", "XGBoost", "LightGBM"]
        rationale = "기본 권장 Tabular baseline"

    citations = [r["hash"] for r in recipes[:3] if r.get("hash")]
    return {"top3": top3, "rationale": rationale, "citations": citations}

"""agents.handlers.tabular.selector — 정형 ML/DL 모델 추천 (jh 담당)."""

from __future__ import annotations

from typing import Any


def _infer_task_type(state: Any) -> str:
    """state 기반 task 유형 추정 — 분류/회귀.

    우선순위: state.task → data_profile.task_type → class_distribution 존재 여부.
    """
    task = getattr(state, "task", "auto")
    if task in ("classification", "regression"):
        return task
    profile = state.data_profile or {}
    pt = profile.get("task_type")
    if pt in ("classification", "regression"):
        return pt
    # 휴리스틱: class_distribution 있고 항목 ≤ 50 → 분류
    cd = profile.get("class_distribution") or {}
    if cd and len(cd) <= 50:
        return "classification"
    # 분류 신호 없으면 회귀
    return "regression"


def _baselines_for(state: Any) -> list[str]:
    """task 유형별 베이스라인 모델 목록.

    Day 11 (jh) — Dummy + 선형 베이스라인을 항상 비교군에 포함.
    "강모델이 더미보다 얼마나 나은가" 격차가 모델 가치를 정의함.

    tabular_dl 은 베이스라인 비교 대상 외 (DL 끼리 비교 의도) → 빈 리스트.
    """
    if state.category == "tabular_dl":
        return []
    task = _infer_task_type(state)
    if task == "classification":
        return ["Dummy", "LogisticRegression"]
    return ["Dummy", "Ridge"]


def score(state: Any, recipes: list[dict[str, Any]]) -> dict[str, Any]:
    """모델 추천 — top3 + baselines + rationale + citations.

    반환 키:
        top3 : G4 사용자 선택지 (3개)
        baselines : 비교용 베이스라인 (분류 ["Dummy","LogisticRegression"],
                    회귀 ["Dummy","Ridge"]). DL 카테고리는 [].
        rationale : 추천 사유 (한국어)
        citations : KB recipe hash 인용

    Day 11 (jh) — baselines 키 추가. ModelSelectionAgent 가
    state.model_candidates = baselines + top3 로 합쳐 학습하도록 함.
    G4 UI 에는 top3 만 노출 (baselines 는 백그라운드 비교용).
    """
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
    baselines = _baselines_for(state)
    return {
        "top3": top3,
        "baselines": baselines,
        "rationale": rationale,
        "citations": citations,
    }

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


def _extract_signals(state: Any) -> dict[str, Any]:
    """data_profile 에서 모델 추천에 쓸 신호 4개 추출.

    Day 11 (jh) — 단순 if-else 룰 대신 신호 기반 점수 매트릭스로 전환.

    신호:
        n_rows : 행 수
        numeric_ratio : numeric 컬럼 / 전체 컬럼 비율 (0~1)
        high_card_count : cardinality_levels 가 "high" 인 컬럼 개수
        imbalance_ratio : 클래스 불균형 비율 (분류만, 회귀는 1.0)
    """
    profile = state.data_profile or {}
    n_rows = int(profile.get("rows", 0))
    imbalance = float(profile.get("class_imbalance_ratio", 1.0))

    # numeric 비율 — dtypes 에서 numeric 카운트 / 전체
    dtypes = profile.get("dtypes") or {}
    target = getattr(state, "target_column", None)
    feature_dtypes = {k: v for k, v in dtypes.items() if k != target}
    if feature_dtypes:
        numeric_count = sum(
            1
            for t in feature_dtypes.values()
            if any(s in str(t).lower() for s in ("int", "float", "number"))
        )
        numeric_ratio = numeric_count / len(feature_dtypes)
    else:
        numeric_ratio = 0.5  # 정보 없으면 중립

    # high-cardinality 개수 — profiler 가 채운 cardinality_levels 활용
    card_levels = profile.get("cardinality_levels") or {}
    high_card_count = sum(1 for lvl in card_levels.values() if lvl == "high")

    return {
        "n_rows": n_rows,
        "numeric_ratio": float(numeric_ratio),
        "high_card_count": int(high_card_count),
        "imbalance_ratio": float(imbalance),
    }


def _score_ml_models(signals: dict[str, Any]) -> dict[str, float]:
    """tabular_ml 4 모델 점수 매트릭스 — 신호별 가산.

    설계 의도:
      - RandomForest : 소량/안정성 강함, 대용량엔 overfit 위험
      - XGBoost : 균형 + numeric 위주 대용량에서 최강
      - LightGBM : 불균형 + 고카디 처리 강함, 대용량 빠름
      - CatBoost : 고카디 + 불균형 둘 다 강함, native 처리

    기본 0.5 + 신호 가산. 0~1 사이 점수.
    """
    n_rows = signals["n_rows"]
    nr = signals["numeric_ratio"]
    hc = signals["high_card_count"]
    imb = signals["imbalance_ratio"]

    is_large = n_rows >= 5000
    is_small = 0 < n_rows < 500
    is_imbalanced = imb >= 10
    is_numeric_heavy = nr >= 0.7
    has_high_card = hc >= 2

    rf = 0.55
    if is_small:
        rf += 0.10  # 소량 안정성
    if is_imbalanced:
        rf += 0.05  # class_weight 지원
    if is_large:
        rf -= 0.05  # overfit 위험

    xgb = 0.50
    if is_large:
        xgb += 0.15
    if is_numeric_heavy:
        xgb += 0.10
    if not is_imbalanced:
        xgb += 0.05  # 균형 데이터에서 강함

    lgb = 0.50
    if is_large:
        lgb += 0.15
    if is_imbalanced:
        lgb += 0.15  # class_weight 지원
    if has_high_card:
        lgb += 0.10  # 고카디 처리

    cb = 0.45  # 시작이 조금 낮음 (학습 느림 트레이드오프)
    if is_large:
        cb += 0.10
    if has_high_card:
        cb += 0.20  # native categorical
    if is_imbalanced:
        cb += 0.15  # class_weights 지원

    return {
        "RandomForest": round(rf, 3),
        "XGBoost": round(xgb, 3),
        "LightGBM": round(lgb, 3),
        "CatBoost": round(cb, 3),
    }


def _build_rationale(signals: dict[str, Any], top3: list[str]) -> str:
    """점수 매트릭스 기반 추천 사유 한국어 1~2문장."""
    n_rows = signals["n_rows"]
    imb = signals["imbalance_ratio"]
    hc = signals["high_card_count"]
    nr = signals["numeric_ratio"]

    reasons: list[str] = []
    if n_rows >= 5000:
        reasons.append("대용량")
    elif 0 < n_rows < 500:
        reasons.append("소량")
    if imb >= 10:
        reasons.append("불균형")
    if hc >= 2:
        reasons.append("고카디널리티")
    if nr >= 0.7:
        reasons.append("수치형 위주")

    feature_desc = " · ".join(reasons) if reasons else "기본 분포"
    return f"데이터 특성({feature_desc}) 기반 점수 매트릭스로 상위 3종 자동 선정: {', '.join(top3)}."


def _apply_archetype_constraints(
    ranked: list[tuple[str, float]],
    archetype_info: dict[str, Any],
) -> tuple[list[tuple[str, float]], list[str]]:
    """archetype 의 expected_decisions 로 점수 매트릭스를 보정.

    - selector_top1_in 의 모델이 ranked 에 없으면 base 0.70 으로 주입 후 가산.
    - selector_top1_in 에 있는 기존 모델은 +0.20 * confidence.
    - selector_top1_not_in 모델은 -0.30 * confidence.

    Day 11++ — primary_confidence 를 보정 폭에 곱함. 경계선 매칭(conf≈0.5)이면
    보정이 약화돼 archetype 룰이 점수표를 강제로 뒤집지 않음.
    """
    expected = archetype_info.get("expected") or {}
    include = expected.get("selector_top1_in") or set()
    exclude = expected.get("selector_top1_not_in") or set()
    if not include and not exclude:
        return ranked, []

    # primary_confidence 가 없으면 보수적으로 1.0 (기존 동작 유지)
    conf = float(archetype_info.get("primary_confidence", 1.0))
    conf = max(0.0, min(1.0, conf))
    include_boost = 0.20 * conf
    exclude_penalty = 0.30 * conf

    adjusted: dict[str, float] = {name: float(score_val) for name, score_val in ranked}
    injected: list[str] = []

    # include 의 모델이 dict 에 없으면 base 0.70 으로 주입 (confidence 무관 — 후보 자체는 노출)
    for model in include:
        if model not in adjusted:
            adjusted[model] = 0.70
            injected.append(model)

    # 가산/감점 적용 (confidence 가중)
    for name in list(adjusted.keys()):
        new = adjusted[name]
        if include and name in include:
            new += include_boost
        if exclude and name in exclude:
            new -= exclude_penalty
        adjusted[name] = round(new, 3)

    notes: list[str] = []
    conf_tag = f" (신뢰도 {conf:.0%})" if conf < 0.85 else ""
    if include:
        tag = "우선 주입+가산" if injected else "우선 가산"
        notes.append(f"{tag}{conf_tag}: {', '.join(sorted(include))}")
    if exclude:
        notes.append(f"감점{conf_tag}: {', '.join(sorted(exclude))}")

    re_ranked = sorted(adjusted.items(), key=lambda kv: (-kv[1], kv[0]))
    return re_ranked, notes


def score(state: Any, recipes: list[dict[str, Any]]) -> dict[str, Any]:
    """모델 추천 — top3 + baselines + rationale + citations + archetype.

    반환 키:
        top3 : G4 사용자 선택지 (3개)
        baselines : 비교용 베이스라인 (분류 ["Dummy","LogisticRegression"],
                    회귀 ["Dummy","Ridge"]). DL 카테고리는 [].
        rationale : 추천 사유 (한국어, archetype 매칭 시 archetype 설명 포함)
        citations : KB recipe hash 인용
        model_scores : tabular_ml 신호별 점수 매트릭스 결과 (디버깅·관찰용)
        archetype : profile["archetype"] 의 primary/matched/expected 요약 (insight·
                    output_extras 가 동일 ground truth 사용)

    Day 11 (jh) — 단순 if-else 룰 → 신호 기반 점수 매트릭스 전환.

    Day 11+ (jh, decision-aware) — 신호 4개 → archetype 분류 → 점수 보정 추가.
        예: target_leakage_suspected → 보수적 모델(RF/LR/Ridge/Dummy) 가산, GBDT 배제.
        예: p_gg_n → 정규화 선형(LR/Ridge/Lasso) 가산, 트리/DL 배제.
        archetype 매칭 안 되면 (clean_balanced) 기존 점수 그대로.
    """
    # archetype 정보 (profiler 가 이미 채워둠)
    profile = getattr(state, "data_profile", None) or {}
    archetype_info = profile.get("archetype") or {"primary": None, "matched": [], "expected": {}}

    if state.category == "tabular_dl":
        # DL 카테고리는 archetype 영향 받지 않음 (트랜스포머 3 종 비교가 의도)
        top3 = ["FTTransformer", "TabTransformer", "TabPFN"]
        rationale = "DL 카테고리 — 트랜스포머 3종 비교"
        model_scores: dict[str, float] = {}
    else:
        signals = _extract_signals(state)
        model_scores = _score_ml_models(signals)
        # 점수 내림차순 + 동점 시 모델명 알파벳 순 (결정적)
        ranked = sorted(model_scores.items(), key=lambda kv: (-kv[1], kv[0]))

        # archetype 보정 — 데이터 archetype 에 맞는 모델 강제·배제
        ranked_after, adjust_notes = _apply_archetype_constraints(ranked, archetype_info)

        top3 = [name for name, _ in ranked_after[:3]]
        base_rationale = _build_rationale(signals, top3)

        # archetype 매칭 결과를 사용자 가시 rationale 에 1 줄 추가
        primary = archetype_info.get("primary")
        if primary and primary != "clean_balanced" and adjust_notes:
            rationale = (
                f"{base_rationale} 데이터 archetype='{primary}' 으로 추가 보정: "
                + "; ".join(adjust_notes)
                + "."
            )
        else:
            rationale = base_rationale

    citations = [r["hash"] for r in recipes[:3] if r.get("hash")]
    baselines = _baselines_for(state)
    return {
        "top3": top3,
        "baselines": baselines,
        "rationale": rationale,
        "citations": citations,
        "model_scores": model_scores,
        "archetype": {
            "primary": archetype_info.get("primary"),
            "primary_confidence": archetype_info.get("primary_confidence"),
            "matched": archetype_info.get("matched", []),
            "confidences": archetype_info.get("confidences", {}),
            "signals": archetype_info.get("signals", {}),
        },
    }

"""agents.handlers.tabular.insight — 정형 인사이트 (jh 담당)."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """당신은 정형 데이터 분석 인사이트 작성자입니다.
다음 데이터를 보고 한국어 3~5문장으로 인사이트를 작성하세요.

규칙:
1. 정확도/F1/AUC 같은 정확한 수치 1개 이상 인용
2. SHAP top3 피처 중 1개 이상 자연스럽게 언급
3. baseline 대비 격차(improvement_over_baseline.primary_lift) 가 제공되면
   "기본값 대비 +X 향상" 식으로 1문장 포함 → 모델 가치를 정량화
4. 마지막 1문장은 비즈니스 행동 권고
5. 마크다운/리스트/이모지 금지
"""


def prompt_payload(state: Any) -> dict[str, Any]:
    # Day 11 (jh) — baseline 격차도 함께 전달.
    eval_result = state.eval_result or {}
    return {
        "category": state.category,
        "user_intent": state.user_intent,
        "best_model": state.best_model,
        "shap_top": (state.explanations or {}).get("shap_top_features"),
        "eval_result": eval_result,
        "improvement_over_baseline": eval_result.get("improvement_over_baseline") or {},
        "baseline_used": eval_result.get("baseline_used") or {},
        "class_imbalance_ratio": (state.data_profile or {}).get("class_imbalance_ratio"),
    }


def fallback(state: Any) -> str:
    bm = state.best_model or {}
    metrics = bm.get("metrics", {})
    f1 = metrics.get("val_f1")
    auc = metrics.get("val_roc_auc")
    parts = [f"본 분석은 {bm.get('model_name', '미정')} 모델이 가장 우수한 성능을 보였습니다."]
    if f1 is not None:
        parts.append(f"검증 F1 점수는 {float(f1):.2f} 입니다.")
    if auc is not None:
        parts.append(f"ROC AUC 는 {float(auc):.2f} 입니다.")

    # Day 11 (jh) — baseline 격차 1문장 추가 (있으면).
    eval_result = state.eval_result or {}
    improvement = eval_result.get("improvement_over_baseline") or {}
    primary_lift = improvement.get("primary_lift")
    primary_metric = improvement.get("primary_metric")
    baseline_used = eval_result.get("baseline_used") or {}
    baseline_name = baseline_used.get("name")
    if primary_lift is not None and primary_metric and baseline_name:
        sign = "+" if primary_lift >= 0 else ""
        parts.append(
            f"기본값 모델({baseline_name}) 대비 {primary_metric}이 {sign}{float(primary_lift):.2f} 향상되었습니다."
        )

    parts.append("실무에서는 본 모델 예측 결과를 의사결정 보조 자료로 활용 권장합니다.")
    return " ".join(parts)

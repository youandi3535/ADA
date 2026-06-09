"""outputs.architect.audience_adapter — 청중 자동 추정 (Phase 2).

청중 4 등급 자동 추정:
    c_level / manager / analyst / external_client

추정 시그널 (휴리스틱):
    - user_intent / business_context 의 키워드
    - meta.classification 등급
    - 분석 유형 (시계열 forecasting vs anomaly diagnostic)
    - 출력 형식 (PPT 만 → 발표용 → c_level/manager 가능성↑)
    - 길이 hint (10~12 → c_level, 16~20 → analyst)

설계:
    - 사용자가 답변 안 묻고 *자동 추정*. (정책 K-3 — 사용자 확정 결정)
    - 신뢰도 0.5 미만이면 "analyst" 로 폴백 (가장 풍부한 정보를 받는 톤).
    - signals 리스트에 추정 근거를 남겨 보고서 디버깅용.
"""

from __future__ import annotations

from typing import Any

from outputs.context.schema import AudienceInference, ReportContext

# ==============================================================
# 시그널 사전
# ==============================================================

_C_LEVEL_KEYWORDS_KO = (
    "임원",
    "경영진",
    "이사회",
    "ceo",
    "cfo",
    "coo",
    "cto",
    "투자",
    "결정",
    "의사결정",
    "전략",
    "예산",
    "비용 절감",
    "수익",
)
_MANAGER_KEYWORDS_KO = (
    "팀장",
    "본부",
    "팀",
    "운영",
    "관리",
    "팀원",
    "예산",
    "리포팅",
    "주간",
    "월간",
    "분기",
)
_ANALYST_KEYWORDS_KO = (
    "분석",
    "모델",
    "성능",
    "지표",
    "메트릭",
    "shap",
    "튜닝",
    "feature",
    "재현",
    "실험",
    "재학습",
    "노트북",
)
_EXTERNAL_KEYWORDS_KO = (
    "고객사",
    "납품",
    "외부",
    "client",
    "제출",
    "감사",
    "규제",
    "컨설팅",
    "위탁",
)


# ==============================================================
# 공개 API
# ==============================================================


def adapt_audience(ctx: ReportContext) -> AudienceInference:
    """ReportContext 로부터 청중 추정.

    이미 ``ctx.domain.audience_inference`` 가 적립돼 있고 confidence>=0.7 면 그대로 반환.
    """
    existing = ctx.domain.audience_inference
    if existing and existing.confidence >= 0.7 and not existing.auto_inferred:
        return existing

    intent = (ctx.meta.user_intent or "").lower()
    question = (ctx.meta.user_question or "").lower()
    biz = (ctx.meta.business_context or "").lower()
    classification = (ctx.meta.classification or "").lower()
    length_hint = ctx.meta.length_hint.get("pptx", [10, 20])
    output_forms = ctx.meta.output_forms or ["pptx"]
    text = " ".join([intent, question, biz])

    # 점수 누적
    scores = {"c_level": 0.0, "manager": 0.0, "analyst": 0.0, "external_client": 0.0}
    signals: list[str] = []

    for kw in _C_LEVEL_KEYWORDS_KO:
        if kw in text:
            scores["c_level"] += 1.0
            signals.append(f"c_level kw: {kw}")
    for kw in _MANAGER_KEYWORDS_KO:
        if kw in text:
            scores["manager"] += 1.0
            signals.append(f"manager kw: {kw}")
    for kw in _ANALYST_KEYWORDS_KO:
        if kw in text:
            scores["analyst"] += 0.8
            signals.append(f"analyst kw: {kw}")
    for kw in _EXTERNAL_KEYWORDS_KO:
        if kw in text:
            scores["external_client"] += 1.2
            signals.append(f"external kw: {kw}")

    # 분류 등급
    if classification in ("confidential", "strictly confidential"):
        scores["external_client"] += 0.5
        scores["c_level"] += 0.5
        signals.append(f"classification: {classification}")

    # 길이 hint
    upper = length_hint[1] if len(length_hint) > 1 else 20
    if upper <= 12:
        scores["c_level"] += 0.8
        signals.append("short_length_hint_c_level")
    elif upper >= 18:
        scores["analyst"] += 0.5
        signals.append("long_length_hint_analyst")

    # 출력 형식
    if set(output_forms) == {"pptx"} or output_forms == ["pptx"]:
        scores["c_level"] += 0.3
        scores["manager"] += 0.3
        signals.append("pptx_only")
    if "md" in output_forms or "html" in output_forms:
        scores["analyst"] += 0.3
        signals.append("includes_dev_forms")

    # 카테고리 힌트 — anomaly_detection 진단형은 보통 manager/analyst
    if ctx.meta.category == "anomaly_detection":
        scores["analyst"] += 0.4
        scores["manager"] += 0.2
        signals.append("category_anomaly")

    # 도메인 인용 풍부 → external_client 가능성↑
    if len(ctx.domain.web_citations) + len(ctx.domain.kb_citations) >= 3:
        scores["external_client"] += 0.5
        signals.append("rich_citations")

    # 최고 점수
    chosen = max(scores, key=lambda k: scores[k])
    chosen_score = scores[chosen]
    total = sum(scores.values()) or 1.0
    confidence = chosen_score / total

    # 0.4 미만 → analyst 폴백 (가장 정보 풍부)
    if confidence < 0.4 or chosen_score < 1.0:
        chosen = "analyst"
        confidence = max(confidence, 0.4)
        signals.append("fallback_analyst")

    return AudienceInference(
        level=chosen,
        confidence=round(confidence, 3),
        signals=signals[:12],
        auto_inferred=True,
    )


# ==============================================================
# 청중별 출력 가이드 (Architect 가 Skeleton 선정 후 사용)
# ==============================================================


def audience_profile(level: str) -> dict[str, Any]:
    """청중별 톤·강조·길이 가이드 — SlideContentGenerator·Skeleton 이 참조."""
    profiles: dict[str, dict[str, Any]] = {
        "c_level": {
            "tone": "단정·간결",
            "endings_ko": "합니다",  # 격식체
            "emphasis": ["결론", "임팩트", "리스크"],
            "max_body_words": 40,
            "max_tech_terms_per_slide": 3,
            "preferred_skeleton": ["ML Pitch"],
            "slide_count_range": [10, 14],
            "show_code_in_main": False,
            "include_appendix_methodology": False,
        },
        "manager": {
            "tone": "분석적·실행지향",
            "endings_ko": "합니다",
            "emphasis": ["방법", "결과", "실행"],
            "max_body_words": 70,
            "max_tech_terms_per_slide": 6,
            "preferred_skeleton": ["ML Pitch"],
            "slide_count_range": [14, 18],
            "show_code_in_main": False,
            "include_appendix_methodology": True,
        },
        "analyst": {
            "tone": "정확·재현",
            "endings_ko": "한다",
            "emphasis": ["데이터", "방법", "한계"],
            "max_body_words": 120,
            "max_tech_terms_per_slide": 999,
            "preferred_skeleton": ["ML Pitch"],
            "slide_count_range": [16, 20],
            "show_code_in_main": True,
            "include_appendix_methodology": True,
        },
        "external_client": {
            "tone": "공손·근거",
            "endings_ko": "드립니다",
            "emphasis": ["가치", "신뢰성", "근거"],
            "max_body_words": 60,
            "max_tech_terms_per_slide": 4,
            "preferred_skeleton": ["ML Pitch"],
            "slide_count_range": [14, 20],
            "show_code_in_main": False,
            "include_appendix_methodology": True,
        },
    }
    return profiles.get(level, profiles["analyst"])

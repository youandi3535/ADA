"""outputs.architect.business_impact_quantifier — metric → 비즈니스 단위 환산 (Phase 2).

ReportContext.evaluation.metrics 와 domain.inferred_use_case 를 보고 ``BusinessKPI`` 추정.
정확한 ROI 계산은 도메인 입력 필요 — 본 모듈은 *추정 + 가정 명시*.

추정 룰 (use_case 별):
    이탈 예측 → "예상 월간 이탈 감소", 단위 "%"
    수요 예측 → "재고비용 감소", 단위 "%"
    이상 탐지 → "오탐 감소", 단위 "%"
    일반 분류 → "예측 정확도 향상", 단위 "%p"

모든 KPI 는 ``confidence: low | medium`` — high 는 도메인 입력 받았을 때만.
"""

from __future__ import annotations

from outputs.context.schema import BusinessKPI, ReportContext


def quantify_business_impact(ctx: ReportContext) -> ReportContext:
    """ReportContext 의 evaluation.business_kpi 를 in-place 보강.

    Returns:
        in-place 보강된 ReportContext.
    """
    # 이미 적립돼 있으면 스킵 (사용자 입력 보존)
    if ctx.evaluation.business_kpi:
        return ctx

    use_case = (ctx.domain.inferred_use_case or "").lower()
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "").lower()
    text = use_case + " " + intent
    pm = ctx.evaluation.primary_metric or {}
    primary_value = pm.get("value")

    kpis: list[BusinessKPI] = []

    # 이탈 예측
    if any(kw in text for kw in ("이탈", "churn", "해지", "탈퇴")):
        if isinstance(primary_value, (int, float)) and 0 < primary_value < 1:
            est = round(primary_value * 15, 1)  # heuristic
            kpis.append(
                BusinessKPI(
                    name="예상 월간 이탈률 감소",
                    unit="%p",
                    estimated_value=est,
                    assumptions=["현재 이탈률 대비 모델 적용 시 상대 감소", "분류 임계값 0.5 가정"],
                    confidence="low",
                )
            )
    # 수요·매출 예측 — jh 2026-06-11: "예측" 단독 키워드 제거.
    # 거의 모든 intent 에 "예측" 이 포함돼 (예: Titanic "생존 예측") 무관한
    # "재고 회전 개선 8.0%" 하드코딩 KPI 가 Exec Summary 에 노출되던 오염 수정.
    elif any(kw in text for kw in ("수요", "매출", "판매", "재고", "forecast")):
        kpis.append(
            BusinessKPI(
                name="재고 회전 개선",
                unit="%",
                estimated_value=8.0,
                assumptions=["예측 정확도 향상 → 안전재고 축소 가능", "기존 baseline 대비"],
                confidence="low",
            )
        )
    # 이상 탐지
    elif any(kw in text for kw in ("이상", "anomaly", "탐지", "장애")):
        kpis.append(
            BusinessKPI(
                name="오탐 감소",
                unit="%",
                estimated_value=20.0,
                assumptions=["기존 룰베이스 대비", "precision 임계값 0.8 기준"],
                confidence="low",
            )
        )
    # 일반 분류·회귀
    else:
        if isinstance(primary_value, (int, float)):
            kpis.append(
                BusinessKPI(
                    name="예측 정확도 향상",
                    unit="%p",
                    estimated_value=round(primary_value * 100, 1) if 0 < primary_value < 1 else float(primary_value),
                    assumptions=["baseline 대비 절대 향상치", "현재 사용 지표 기준"],
                    confidence="low",
                )
            )

    # 공통 KPI — 분석 리드타임 절감 (ADA 가치)
    kpis.append(
        BusinessKPI(
            name="분석 리드타임 절감",
            unit="%",
            estimated_value=80.0,
            assumptions=["수작업 3~6주 대비 ADA 자동 1일 내 산출", "재현·재실행 비용 0"],
            confidence="medium",
        )
    )

    ctx.evaluation.business_kpi = kpis
    return ctx

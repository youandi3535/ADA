"""outputs.architect.skeletons.psi — PSI Skeleton (Phase 2).

Problem → Solution → Impact 구조 — 솔루션 제안형 / pitch deck.
사용자가 보여준 ADA 16장 덱이 이 스타일.

고정 14장 + 가변 0~6장 = 14~20장.
"""

from __future__ import annotations

from typing import Any

from outputs.architect.plan import (
    MessageNode,
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
)
from outputs.architect.skeletons._common import (
    build_agenda,
    build_closing,
    build_cover,
    build_exec_summary,
    insert_tech_slides,
    make_section,
    primary_metric_ref,
)
from outputs.context.schema import ReportContext

SKELETON_NAME = "PSI"


def build(ctx: ReportContext, audience_profile: dict[str, Any], length_target: int = 16) -> ReportPlan:
    sections: list[SectionSpec] = []
    root = MessageNode(id="root", role="claim", text="PSI 결론", parent_id=None)

    # Front matter
    front = make_section(
        "front_matter", "Front Matter", kind="cover", slides=[build_cover(ctx), build_exec_summary(ctx)]
    )
    sections.append(front)

    chosen = ctx.model_selection.chosen or {}
    pm = ctx.evaluation.primary_metric or {}

    # P-1 시장·맥락
    p1 = SlideSpec(
        id="p1_market",
        section_id="problem",
        layout="one_message",
        role="evidence",
        so_what=f"{ctx.domain.inferred_industry or '본 산업'} 의 {ctx.domain.inferred_use_case or '대상 과제'} 가 중요한 이유",
        title_ko="시장·맥락",
        body_outline=[f"산업: {ctx.domain.inferred_industry or '-'}", f"과제: {ctx.domain.inferred_use_case or '-'}"],
        thread_part="setup",
        parent_message_id="root",
    )
    # P-2 페인 포인트
    issues = ctx.eda.data_quality_issues or []
    p2 = SlideSpec(
        id="p2_pain",
        section_id="problem",
        layout="chart_callout",
        role="evidence",
        so_what="현재 방식의 핵심 페인포인트를 식별했습니다",
        title_ko="페인 포인트",
        body_outline=[it.get("issue", "이슈") for it in issues[:3]] or ["수작업·일관성 부족·재현성 미흡"],
        thread_part="conflict",
        parent_message_id="root",
    )
    # P-3 기존 솔루션 한계
    p3 = SlideSpec(
        id="p3_alt_limits",
        section_id="problem",
        layout="comparison_table",
        role="evidence",
        so_what="기존 솔루션 대비 본 접근의 차별성",
        title_ko="기존 솔루션 한계",
        body_outline=["AutoML: 게이트·해석성 부족", "수작업: 일관성·속도 한계", "본 접근: HITL + 자동화 + 재현 가능"],
        parent_message_id="root",
    )
    sections.append(
        make_section("problem", "Section 1 — 문제 (Why now)", kind="context", divider=True, slides=[p1, p2, p3])
    )

    # S-1 솔루션 개요
    s1 = SlideSpec(
        id="s1_overview",
        section_id="solution",
        layout="one_message",
        role="claim",
        so_what=f"본 솔루션 한 줄: {chosen.get('name', '-')} 모델로 자동화된 분석·보고",
        title_ko="솔루션 개요",
        body_outline=[f"선정: {chosen.get('name', '-')}", f"근거: {chosen.get('justification', '')[:80]}"],
        thread_part="resolution",
        parent_message_id="root",
    )
    sections.append(make_section("solution", "Section 2 — 솔루션", kind="recommendation", divider=True, slides=[s1]))

    # 기술 스택·아키텍처 강제 삽입 (Solution 섹션 안)
    insert_tech_slides(sections[-1], ctx, space_available=2)

    # S-3 차별화 — Comparative 매트릭스
    s3 = SlideSpec(
        id="s3_differentiation",
        section_id="solution",
        layout="2x2_matrix",
        role="evidence",
        so_what="기존 대비 차별화 — 자동화·신뢰성 축",
        title_ko="차별화 포인트",
        body_outline=[
            "자동화 (높음)·신뢰성 (높음): 본 솔루션",
            "자동화 (높음)·신뢰성 (낮음): AutoML",
            "자동화 (낮음)·신뢰성 (높음): 수작업",
            "자동화 (낮음)·신뢰성 (낮음): 임시 스크립트",
        ],
        parent_message_id="root",
    )
    sections[-1].slides.append(s3)

    # I-1 핵심 KPI
    i1 = SlideSpec(
        id="i1_kpi",
        section_id="impact",
        layout="kpi_cards_4",
        role="evidence",
        so_what=f"{pm.get('name', '-')} {pm.get('value', '-')} + 비즈니스 임팩트 KPI",
        title_ko="핵심 성과",
        body_outline=[f"{kpi.name}: {kpi.estimated_value} {kpi.unit}" for kpi in ctx.evaluation.business_kpi[:4]]
        or [f"{pm.get('name', '-')}: {pm.get('value', '-')}"],
        required_refs=primary_metric_ref(ctx),
        parent_message_id="root",
    )
    # I-2 모델 분석 후 적용 효과 (구 Before/After)
    chosen_name = chosen.get("name", "-")
    i2 = SlideSpec(
        id="i2_before_after",
        section_id="impact",
        layout="comparison_before_after",
        role="evidence",
        so_what=f"{chosen_name} 적용 전후 운영·성능 변화",
        title_ko="모델 분석 후 적용 효과",
        body_outline=[
            "AS-IS 분석 소요  ·  수작업 평균 3~6주 / 재현 불가",
            "AS-IS 일관성  ·  팀별 표준 부재, 결과 산포",
            "AS-IS 모니터링  ·  사후 수동 검증",
            "AS-IS 의사결정  ·  주관·경험 의존",
            f"TO-BE 분석 자동화  ·  {chosen_name} 파이프라인 1일 내 완료",
            "TO-BE 재현 가능  ·  Companion 코드·MLflow 추적",
            f"TO-BE 성능 임계 통과  ·  {pm.get('name', '-')} {pm.get('value', '-')} 달성",
            "TO-BE 운영 안정  ·  분기 재학습·드리프트 알람 자동화",
        ],
        parent_message_id="root",
    )
    # I-3 ROI
    i3 = SlideSpec(
        id="i3_roi",
        section_id="impact",
        layout="kpi_cards_3",
        role="evidence",
        so_what=f"예상 비즈니스 효과: {_first_kpi(ctx)}",
        title_ko="ROI / 비즈니스 임팩트",
        body_outline=[
            f"{kpi.name}: {kpi.estimated_value} {kpi.unit} ({kpi.confidence})"
            for kpi in ctx.evaluation.business_kpi[:3]
        ]
        or ["임팩트 추정 — 추가 데이터 필요"],
        parent_message_id="root",
    )
    sections.append(make_section("impact", "Section 3 — 임팩트", kind="evidence", divider=True, slides=[i1, i2, i3]))

    # Risk
    risk_lines = [
        f"{lim.scenario or '리스크'}: {lim.description}" for lim in ctx.limitations.generalization_risk[:3]
    ] or [
        "리스크 1: 분포 변화 대응 — 분기 재학습 권고",
        "리스크 2: 데이터 부족 세그먼트 — 추가 수집",
    ]
    risk = SlideSpec(
        id="risk_mitigation",
        section_id="risk",
        layout="comparison_table",
        role="caveat",
        so_what="주요 리스크와 대응책 정리",
        title_ko="Risk & Mitigation",
        body_outline=risk_lines,
        parent_message_id="root",
    )
    sections.append(make_section("risk", "Section 4 — 리스크", kind="caveat", divider=False, slides=[risk]))

    # Roadmap — 실행 계획 + 향후 고도화 (단계별 도입 + 추가 디벨롭 방향)
    road = SlideSpec(
        id="roadmap",
        section_id="roadmap",
        layout="process_flow_gantt",
        role="action",
        so_what="단계별 실행 계획 + 운영 후 모델·기능 고도화 방향",
        title_ko="실행 계획 및 향후 고도화",
        body_outline=[
            "Phase 1 (0~30일)  ·  파일럿 운영, 핵심 지표 모니터링, 운영팀 인수인계",
            "Phase 2 (30~90일)  ·  운영 환경 단계 배포, 세그먼트별 검증, 알람·SLA 설정",
            "Phase 3 (90일+)  ·  전사 확장, 분기 재학습 자동화, MLflow run 기반 거버넌스",
            "고도화 1  ·  추가 피처 발굴 (행동·실시간 신호 연동)",
            "고도화 2  ·  멀티 모델 앙상블 + 개인화 세그먼트 적용",
            "고도화 3  ·  A/B 테스트 인프라 + 도메인 룰 결합 운영",
        ],
        thread_part="resolution",
        parent_message_id="root",
    )
    sections.append(
        make_section("roadmap", "Section 5 - 로드맵 & 고도화", kind="recommendation", divider=False, slides=[road])
    )

    # Closing
    sections.append(make_section("closing", "Closing", kind="closing", divider=False, slides=[build_closing(ctx)]))

    titles = [s.title for s in sections if s.id not in ("front_matter", "closing")]
    front.slides.append(build_agenda(titles))

    thread = NarrativeThread(
        setup=f"{ctx.domain.inferred_industry or ctx.meta.category} 시장의 {ctx.domain.inferred_use_case or '과제'} 가 중요",
        conflict=(issues[0].get("issue") if issues else "수작업·재현성 부족"),
        resolution=f"{chosen.get('name', '-')} 자동화로 {pm.get('name', '-')} {pm.get('value', '-')} 달성·확장",
    )
    return ReportPlan(
        skeleton=SKELETON_NAME,
        audience=audience_profile.get("level", "analyst")
        if isinstance(audience_profile.get("level"), str)
        else "analyst",
        output_form="pptx",
        slide_count_target=length_target,
        sections=sections,
        narrative_thread=thread,
        message_tree=[root],
        meta={"skeleton_version": "1.0"},
    )


def _first_kpi(ctx: ReportContext) -> str:
    if ctx.evaluation.business_kpi:
        k = ctx.evaluation.business_kpi[0]
        return f"{k.name} {k.estimated_value} {k.unit}"
    return "추정 — 추가 데이터 필요"

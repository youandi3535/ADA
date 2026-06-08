"""outputs.architect.skeletons.comparative — Comparative Skeleton (Phase 2).

비교 의사결정형. 기준→대안→매트릭스→민감도→권고.
고정 13장 + 가변 0~7장 = 13~20장.
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

SKELETON_NAME = "Comparative"


def build(ctx: ReportContext, audience_profile: dict[str, Any], length_target: int = 14) -> ReportPlan:
    chosen = ctx.model_selection.chosen or {}
    pm = ctx.evaluation.primary_metric or {}
    cands = ctx.model_selection.candidates
    sections: list[SectionSpec] = []
    root = MessageNode(id="root", role="claim", text=f"{chosen.get('name', '-')} 추천")

    front = make_section(
        "front_matter", "Front Matter", kind="cover", slides=[build_cover(ctx), build_exec_summary(ctx)]
    )
    sections.append(front)

    # 의사결정 맥락
    context_slide = SlideSpec(
        id="decision_context",
        section_id="context",
        layout="one_message",
        role="evidence",
        so_what=f"{len(cands)}개 후보 중 최적 선정 — 본 비교의 목적·제약",
        title_ko="의사결정 맥락",
        body_outline=[
            f"카테고리: {ctx.meta.category}",
            f"의도: {ctx.meta.user_intent}",
            f"제약: {ctx.meta.business_context or '명시 안 됨'}",
        ],
        thread_part="setup",
        parent_message_id="root",
    )
    sections.append(make_section("context", "Section 1 — 맥락", kind="context", divider=True, slides=[context_slide]))

    # 평가 기준
    criteria = SlideSpec(
        id="criteria",
        section_id="criteria",
        layout="comparison_table",
        role="evidence",
        so_what="비교 기준 4개와 가중치 (합 100%)",
        title_ko="평가 기준",
        body_outline=[
            f"성능 ({pm.get('name', 'primary')}): 40%",
            "해석성: 25%",
            "학습/추론 속도: 20%",
            "운영 안정성: 15%",
        ],
        parent_message_id="root",
    )
    sections.append(make_section("criteria", "Section 2 — 기준", kind="context", divider=False, slides=[criteria]))

    # 대안 개요
    cands_overview = SlideSpec(
        id="alternatives",
        section_id="alternatives",
        layout="kpi_cards_4",
        role="evidence",
        so_what=f"{len(cands)}개 후보 — 가족·강점·약점 요약",
        title_ko="대안 후보",
        body_outline=[f"{c.name} ({c.family}): {c.why_tried[:50]}" for c in cands[:4]] or ["후보 미식별"],
        parent_message_id="root",
    )
    matrix = SlideSpec(
        id="score_matrix",
        section_id="alternatives",
        layout="comparison_table",
        role="evidence",
        so_what=f"가중 점수: {chosen.get('name', '-')} 가 1위",
        title_ko="평가 매트릭스",
        body_outline=[f"{c.name}: {c.score if c.score is not None else '-'}점" for c in cands[:5]] or ["점수 미식별"],
        parent_message_id="root",
    )
    viz = SlideSpec(
        id="viz_2x2",
        section_id="alternatives",
        layout="2x2_matrix",
        role="evidence",
        so_what="2축 비교 — 성능 × 운영성",
        title_ko="비교 시각화",
        body_outline=[
            "우상단 (성능·운영성 高): " + chosen.get("name", "-"),
            "좌상단 (성능 高·운영성 低): 차선",
            "우하단 (성능 低·운영성 高): 단순 baseline",
            "좌하단: 폐기 후보",
        ],
        parent_message_id="root",
    )
    sections.append(
        make_section(
            "alternatives", "Section 3 — 대안 비교", kind="evidence", divider=True, slides=[cands_overview, matrix, viz]
        )
    )

    # Top 3 심화
    deep_section = make_section("deep_dive", "Section 4 — Top 후보 심화", kind="evidence", divider=False)
    for i, c in enumerate(cands[:3]):
        deep_section.slides.append(
            SlideSpec(
                id=f"deep_{i}",
                section_id="deep_dive",
                layout="chart_callout",
                role="evidence",
                so_what=f"{c.name}: 강점·약점·적용 시나리오",
                title_ko=f"심화 — {c.name}",
                body_outline=[c.why_tried or "강점 미식별", c.why_dropped or "약점 미식별"],
                parent_message_id="root",
            )
        )
    sections.append(deep_section)

    # 민감도
    sensitivity = SlideSpec(
        id="sensitivity",
        section_id="sensitivity",
        layout="comparison_table",
        role="evidence",
        so_what="가중치 ±20% 변동 시 추천 안정성 확인",
        title_ko="민감도 분석",
        body_outline=[
            "성능 가중치 ±20%: 추천 동일",
            "해석성 가중치 ±20%: 추천 동일",
            "운영 가중치 ±20%: 차선 1회 역전",
        ],
        parent_message_id="root",
    )
    sections.append(
        make_section("sensitivity", "Section 5 — 민감도", kind="evidence", divider=False, slides=[sensitivity])
    )

    # 권고
    rec = SlideSpec(
        id="recommendation",
        section_id="recommendation",
        layout="one_message_big_number",
        role="action",
        so_what=f"권고: {chosen.get('name', '-')} — Trade-off 명시",
        title_ko="권고 & Trade-off",
        body_outline=[chosen.get("justification", "1위 후보 — 종합 점수 최우수")[:120]],
        thread_part="resolution",
        required_refs=primary_metric_ref(ctx),
        parent_message_id="root",
    )
    sections.append(
        make_section("recommendation", "Section 6 — 권고", kind="recommendation", divider=True, slides=[rec])
    )

    # 기술
    tech_section = make_section("solution", "기술 구성", kind="evidence", divider=False)
    insert_tech_slides(tech_section, ctx, space_available=1)
    sections.append(tech_section)

    # Closing
    sections.append(make_section("closing", "Closing", kind="closing", divider=False, slides=[build_closing(ctx)]))

    titles = [s.title for s in sections if s.id not in ("front_matter", "closing")]
    front.slides.append(build_agenda(titles))

    thread = NarrativeThread(
        setup=f"{len(cands)}개 후보 모델 비교 필요",
        conflict="각 후보는 trade-off 가 다름 — 단일 우위 후보 부재",
        resolution=f"{chosen.get('name', '-')} 권고 — 가중 합 1위 + 민감도 안정",
    )
    return ReportPlan(
        skeleton=SKELETON_NAME,
        audience=audience_profile.get("level", "manager")
        if isinstance(audience_profile.get("level"), str)
        else "manager",
        output_form="pptx",
        slide_count_target=length_target,
        sections=sections,
        narrative_thread=thread,
        message_tree=[root],
        meta={"skeleton_version": "1.0"},
    )

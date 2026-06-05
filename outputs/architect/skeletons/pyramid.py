"""outputs.architect.skeletons.pyramid — Pyramid Principle Skeleton (Phase 2).

결론 → 3 근거 → 권고. C-level 시간제약 브리핑.
고정 10장 + 가변 0~4장 = 10~14장.
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

SKELETON_NAME = "Pyramid"


def build(ctx: ReportContext, audience_profile: dict[str, Any], length_target: int = 12) -> ReportPlan:
    chosen = ctx.model_selection.chosen or {}
    pm = ctx.evaluation.primary_metric or {}
    sections: list[SectionSpec] = []
    root = MessageNode(id="root", role="claim", text=f"{chosen.get('name', '-')} 도입 권고")

    # Cover + Conclusion
    front = make_section(
        "front_matter", "Front Matter", kind="cover", slides=[build_cover(ctx), build_exec_summary(ctx)]
    )
    sections.append(front)

    # 결론 (Single Answer) — 큰 타이포
    conclusion = SlideSpec(
        id="conclusion",
        section_id="conclusion",
        layout="one_message_big_number",
        role="claim",
        so_what=f"{chosen.get('name', '-')} 도입으로 {pm.get('name', '-')} {pm.get('value', '-')} 달성, 비즈니스 임팩트 {_kpi_one(ctx)} 기대",
        title_ko="최종 결론",
        body_outline=[chosen.get("justification", "")[:120] or "최우선 후보로 선정"],
        thread_part="resolution",
        required_refs=primary_metric_ref(ctx),
        parent_message_id="root",
    )
    sections.append(make_section("conclusion", "결론", kind="recommendation", divider=False, slides=[conclusion]))

    # 3 근거 카드 (그룹화)
    grouped = SlideSpec(
        id="three_reasons",
        section_id="reasons",
        layout="kpi_cards_3",
        role="claim",
        so_what="이 결론은 3가지로 뒷받침됩니다: 성능 / 임팩트 / 신뢰성",
        title_ko="3 핵심 근거",
        body_outline=["근거 1: 성능 — 다음 슬라이드", "근거 2: 비즈니스 임팩트 — 그 다음", "근거 3: 신뢰성 — 그 다음"],
        parent_message_id="root",
    )
    # 근거 1 — 성능
    r1 = SlideSpec(
        id="reason_perf",
        section_id="reasons",
        layout="kpi_cards_4",
        role="evidence",
        so_what=f"{pm.get('name', '-')} {pm.get('value', '-')} — baseline 대비 우수",
        title_ko="근거 1 — 성능",
        body_outline=[f"{k}: {v.get('value')}" for k, v in list(ctx.evaluation.metrics.items())[:4]] or ["지표 미식별"],
        required_refs=primary_metric_ref(ctx),
        parent_message_id="root",
    )
    # 근거 2 — 임팩트
    r2 = SlideSpec(
        id="reason_impact",
        section_id="reasons",
        layout="kpi_cards_4",
        role="evidence",
        so_what="비즈니스 임팩트 4개 KPI 종합",
        title_ko="근거 2 — 임팩트",
        body_outline=[f"{k.name}: {k.estimated_value} {k.unit}" for k in ctx.evaluation.business_kpi[:4]]
        or ["추정 — 추가 데이터 필요"],
        parent_message_id="root",
    )
    # 근거 3 — 신뢰성
    r3 = SlideSpec(
        id="reason_trust",
        section_id="reasons",
        layout="comparison_table",
        role="evidence",
        so_what="신뢰성: 검증·세그먼트 일관·해석성",
        title_ko="근거 3 — 신뢰성",
        body_outline=[
            f"세그먼트 분석: {len(ctx.evaluation.per_segment)}건",
            f"해석성: SHAP top {len(ctx.interpretation.global_importance[:3])} 식별",
            "재현 가능: Companion 코드 제공",
        ],
        parent_message_id="root",
    )
    sections.append(make_section("reasons", "근거 3", kind="evidence", divider=True, slides=[grouped, r1, r2, r3]))

    # 권고 옵션 (2x2)
    rec = SlideSpec(
        id="rec_options",
        section_id="recommendation",
        layout="2x2_matrix",
        role="action",
        so_what="권고 A 우선, 차선 B — Impact·Feasibility 매트릭스",
        title_ko="권고 옵션",
        body_outline=[
            "A: 즉시 운영 도입 (높은 임팩트·실행성)",
            "B: 단계 파일럿 (중간 임팩트·실행성)",
            "C: 추가 데이터 수집 (낮은 임팩트·실행성)",
        ],
        thread_part="resolution",
        parent_message_id="root",
    )
    # 리스크
    risk = SlideSpec(
        id="risk",
        section_id="recommendation",
        layout="comparison_table",
        role="caveat",
        so_what="주요 리스크 3건 모두 완화책 보유",
        title_ko="리스크 & 대응",
        body_outline=[
            f"{lim.description} → {lim.mitigation or '대응 검토'}" for lim in ctx.limitations.generalization_risk[:3]
        ]
        or ["리스크 자가검증 미흡 — 보강 필요"],
        parent_message_id="root",
    )
    # 로드맵
    road = SlideSpec(
        id="roadmap",
        section_id="recommendation",
        layout="process_flow",
        role="action",
        so_what="0~30 / 30~90 / 90일+ 3단계 실행",
        title_ko="실행 로드맵",
        body_outline=["0~30일: 파일럿 시작", "30~90일: 운영 전환", "90일+: 확장·재학습 주기 확립"],
        thread_part="resolution",
        parent_message_id="root",
    )
    sections.append(
        make_section("recommendation", "권고", kind="recommendation", divider=True, slides=[rec, risk, road])
    )

    # 기술 강제 — 통합 1장 (C-level 은 간결)
    tech_section = make_section("solution", "기술 구성", kind="evidence", divider=False)
    insert_tech_slides(tech_section, ctx, space_available=1)
    sections.append(tech_section)

    # Closing
    sections.append(make_section("closing", "Closing", kind="closing", divider=False, slides=[build_closing(ctx)]))

    titles = [s.title for s in sections if s.id not in ("front_matter", "closing")]
    front.slides.append(build_agenda(titles))

    thread = NarrativeThread(
        setup=f"{ctx.domain.inferred_use_case or ctx.meta.category} 결정 필요",
        conflict="기존 방식·baseline 의 성능·신뢰성 한계",
        resolution=f"{chosen.get('name', '-')} 도입 권고 — {pm.get('name', '-')} {pm.get('value', '-')}",
    )
    return ReportPlan(
        skeleton=SKELETON_NAME,
        audience=audience_profile.get("level", "c_level")
        if isinstance(audience_profile.get("level"), str)
        else "c_level",
        output_form="pptx",
        slide_count_target=length_target,
        sections=sections,
        narrative_thread=thread,
        message_tree=[root],
        meta={"skeleton_version": "1.0"},
    )


def _kpi_one(ctx: ReportContext) -> str:
    if ctx.evaluation.business_kpi:
        k = ctx.evaluation.business_kpi[0]
        return f"{k.estimated_value} {k.unit}"
    return "추정 — 추가 데이터 필요"

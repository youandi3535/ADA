"""outputs.architect.skeletons.scqa — SCQA Skeleton (Phase 2).

Situation → Complication → Question → Answer → Evidence → Action 6 단계.
일반 분석 보고서 / 기본 fallback.

고정 12장 + 가변 0~8장 = 12~20장.
"""

from __future__ import annotations

from typing import Any

from outputs.architect.plan import (
    MessageNode,
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
    VisualSpec,
)
from outputs.architect.skeletons._common import (
    build_agenda,
    build_closing,
    build_cover,
    build_exec_summary,
    eda_top_chart_refs,
    insert_tech_slides,
    make_section,
    primary_metric_ref,
)
from outputs.context.schema import ReportContext

SKELETON_NAME = "SCQA"


def build(
    ctx: ReportContext,
    audience_profile: dict[str, Any],
    length_target: int = 16,
) -> ReportPlan:
    """SCQA Skeleton → ReportPlan.

    Args:
        ctx: 정규화된 ReportContext.
        audience_profile: AudienceAdapter.audience_profile() 결과.
        length_target: 목표 슬라이드 수 (10~20).
    """
    sections: list[SectionSpec] = []
    messages: list[MessageNode] = []
    root = MessageNode(id="root", role="claim", text="SCQA 보고서 root", parent_id=None)
    messages.append(root)

    # ── Front matter (3장) ────────────────────────────────────
    cover = build_cover(ctx)
    exec_s = build_exec_summary(ctx)
    front = make_section(
        "front_matter",
        "Front Matter",
        kind="cover",
        divider=False,
        slides=[cover, exec_s],  # Agenda 는 sections 완성 후 삽입
    )
    sections.append(front)

    # ── S — Situation (1장) ───────────────────────────────────
    s_slide = SlideSpec(
        id="s_situation",
        section_id="situation",
        layout="one_message",
        role="evidence",
        so_what=f"{ctx.domain.inferred_industry or ctx.meta.category} 산업의 {ctx.domain.inferred_use_case or '대상 과제'} 가 본 분석 출발점입니다",
        title_ko="현황",
        body_outline=[
            f"산업: {ctx.domain.inferred_industry or '미식별'}",
            f"과제: {ctx.domain.inferred_use_case or ctx.meta.user_intent or '미지정'}",
            f"데이터 규모: {ctx.dataset.shape.get('rows', 0):,} 행 × {ctx.dataset.shape.get('cols', 0)} 열",
        ],
        thread_part="setup",
        parent_message_id="root",
    )
    sections.append(make_section("situation", "Section 1 — 현황", kind="context", divider=True, slides=[s_slide]))

    # ── C — Complication (1장) ────────────────────────────────
    quality_issues = ctx.eda.data_quality_issues or []
    issue_lines = [
        f"{it.get('issue', '데이터 품질 이슈')} (영향: {it.get('severity', 'medium')})" for it in quality_issues[:3]
    ] or ["현재까지 발견된 중대한 품질 이슈 없음 — 추가 검증 권장"]
    c_slide = SlideSpec(
        id="c_complication",
        section_id="complication",
        layout="chart_callout" if quality_issues else "one_message",
        role="evidence",
        so_what="현재 운영 환경의 핵심 제약·문제를 다음과 같이 식별했습니다",
        title_ko="문제 정의",
        body_outline=issue_lines,
        thread_part="conflict",
        parent_message_id="root",
        data_refs=eda_top_chart_refs(ctx, top_k=1),
    )
    sections.append(make_section("complication", "Section 2 — 문제", kind="context", divider=False, slides=[c_slide]))

    # ── Q — Question (1장) ────────────────────────────────────
    q_slide = SlideSpec(
        id="q_question",
        section_id="question",
        layout="one_message",
        role="claim",
        so_what=f"본 분석은 다음 질문에 답합니다: {ctx.meta.user_intent or ctx.meta.user_question or '미지정'}",
        title_ko="분석 질문",
        body_outline=[
            f"핵심 질문: {ctx.meta.user_question or ctx.meta.user_intent or '-'}",
            f"분석 대상 타깃: {ctx.dataset.detected_target or '비지도/이상탐지'}",
            f"카테고리: {ctx.meta.category}",
        ],
        parent_message_id="root",
    )
    sections.append(make_section("question", "Section 3 — 질문", kind="context", divider=False, slides=[q_slide]))

    # ── A — Answer (1장) ──────────────────────────────────────
    chosen = ctx.model_selection.chosen or {}
    pm = ctx.evaluation.primary_metric or {}
    a_slide = SlideSpec(
        id="a_answer",
        section_id="answer",
        layout="one_message_big_number",
        role="claim",
        so_what=f"결론: {chosen.get('name', '-')} 모델로 {pm.get('name', '-')} {pm.get('value', '-')} 를 달성했습니다",
        title_ko="핵심 답",
        body_outline=[
            f"선정 모델: {chosen.get('name', '-')} (이유: {chosen.get('justification', '')[:80]})",
            f"대표 지표: {pm.get('name', '-')} = {pm.get('value', '-')}",
            "본 결론을 뒷받침하는 근거는 다음 Evidence 섹션에서 단계별로 제시",
        ],
        thread_part="resolution",
        parent_message_id="root",
        required_refs=primary_metric_ref(ctx),
    )
    sections.append(make_section("answer", "Section 4 — 답", kind="recommendation", divider=True, slides=[a_slide]))

    # ── E — Evidence (가변 4~7장) ─────────────────────────────
    evidence_section = make_section("evidence", "Section 5 — 근거", kind="evidence", divider=True)

    # E-1 데이터 & 전처리 (1장)
    evidence_section.slides.append(
        SlideSpec(
            id="e1_data_preproc",
            section_id="evidence",
            layout="process_flow",
            role="evidence",
            so_what=f"{ctx.dataset.shape.get('rows', 0):,}건 데이터를 {len(ctx.preprocessing.applied_steps)}단계 전처리로 정제했습니다",
            title_ko="데이터 & 전처리",
            body_outline=[f"{i + 1}. {s.op}" for i, s in enumerate(ctx.preprocessing.applied_steps[:5])]
            or ["전처리 단계 미식별"],
            parent_message_id="root",
            visual_spec=VisualSpec(
                type="diagram_process_linear",
                title="전처리 파이프라인",
                spec={"steps": [s.op for s in ctx.preprocessing.applied_steps[:6]]},
            ),
        )
    )

    # E-2 EDA 핵심 발견 (1~3장, severity 우선)
    critical_charts = [c for c in ctx.eda.charts if getattr(c, "severity", "info") in ("important", "critical")]
    if not critical_charts and ctx.eda.charts:
        critical_charts = list(ctx.eda.charts)[:1]
    for i, ch in enumerate(critical_charts[:3]):
        evidence_section.slides.append(
            SlideSpec(
                id=f"e2_eda_{i}",
                section_id="evidence",
                layout="chart_callout",
                role="evidence",
                so_what=getattr(ch, "finding", "") or f"EDA 발견 #{i + 1}",
                title_ko=f"EDA #{i + 1}",
                data_refs=[getattr(ch, "ref_id", "")] if getattr(ch, "ref_id", None) else [],
                visual_spec=VisualSpec(
                    type="chart_annotated_bar",
                    title=getattr(ch, "title_ko", "") or getattr(ch, "chart_type", "차트"),
                    caption=getattr(ch, "finding", ""),
                    data_refs=[getattr(ch, "ref_id", "")] if getattr(ch, "ref_id", None) else [],
                ),
                parent_message_id="root",
            )
        )

    # E-3 모델 비교 (1장)
    candidates_count = len(ctx.model_selection.candidates)
    evidence_section.slides.append(
        SlideSpec(
            id="e3_model_comparison",
            section_id="evidence",
            layout="comparison_table",
            role="evidence",
            so_what=f"{candidates_count}개 후보 중 {chosen.get('name', '-')} 가 baseline 대비 우수한 결과",
            title_ko="모델 비교",
            body_outline=[f"{c.name} ({c.family})" for c in ctx.model_selection.candidates[:5]] or ["후보 미식별"],
            parent_message_id="root",
        )
    )

    # E-4 성능 평가 (1장)
    evidence_section.slides.append(
        SlideSpec(
            id="e4_performance",
            section_id="evidence",
            layout="kpi_cards_4",
            role="evidence",
            so_what=f"{pm.get('name', '-')} {pm.get('value', '-')} 외 핵심 지표 종합 성능",
            title_ko="성능 평가",
            body_outline=[f"{k}: {v.get('value')}" for k, v in list(ctx.evaluation.metrics.items())[:4]]
            or ["지표 미식별"],
            required_refs=primary_metric_ref(ctx),
            parent_message_id="root",
        )
    )

    # E-5 해석 (1장, 풍부할 때만)
    if ctx.interpretation.global_importance:
        top_imp = ctx.interpretation.global_importance[:3]
        evidence_section.slides.append(
            SlideSpec(
                id="e5_interpretation",
                section_id="evidence",
                layout="chart_callout",
                role="evidence",
                so_what=f"{top_imp[0].feature} 가 결과의 주요 동인입니다",
                title_ko="모델 해석",
                body_outline=[f"{imp.feature} ({imp.method}, importance={imp.importance:.3f})" for imp in top_imp],
                visual_spec=VisualSpec(
                    type="chart_annotated_bar",
                    title="Global Feature Importance Top-3",
                    spec={"items": [(i.feature, i.importance) for i in top_imp]},
                ),
                parent_message_id="root",
            )
        )
    sections.append(evidence_section)

    # ── 기술스택·아키텍처 강제 삽입 (Action 섹션 앞) ───────────
    # 본 위치를 별도 섹션으로 분리 (Solution/Method)
    tech_section = make_section("solution", "Section 6 — 기술 구성", kind="evidence", divider=False)
    # length 여유 계산 — 현재 + 추후 추가 슬라이드 고려
    current_count = sum(len(s.slides) for s in sections) + 1  # +1 for agenda
    remaining_action_limit_appendix = 3  # Action(1) + Limitation(1) + Closing(1)
    space_for_tech = max(1, length_target - current_count - remaining_action_limit_appendix)
    space_for_tech = min(2, space_for_tech)
    insert_tech_slides(tech_section, ctx, space_available=space_for_tech)
    sections.append(tech_section)

    # ── Action — 권고 (1~2장) ──────────────────────────────────
    action_lines = []
    if ctx.evaluation.business_kpi:
        action_lines.extend(
            [f"{kpi.name}: {kpi.estimated_value} {kpi.unit}" for kpi in ctx.evaluation.business_kpi[:3]]
        )
    if ctx.limitations.revalidation_window:
        action_lines.append(f"재검증 주기: {ctx.limitations.revalidation_window}")
    if not action_lines:
        action_lines = [
            "권고 액션 1: 모델을 운영 환경에 단계 배포",
            "권고 액션 2: 모니터링 대시보드 구축",
            "권고 액션 3: 분기별 재학습",
        ]
    action_section = make_section(
        "action",
        "Section 7 — 권고",
        kind="recommendation",
        divider=True,
        slides=[
            SlideSpec(
                id="action_recommendations",
                section_id="action",
                layout="kpi_cards_3",
                role="action",
                so_what=f"본 결론을 기반으로 다음 {min(3, len(action_lines))}개 액션을 권고합니다",
                title_ko="권고 액션",
                body_outline=action_lines[:3],
                thread_part="resolution",
                parent_message_id="root",
            ),
        ],
    )
    sections.append(action_section)

    # ── Limitations (1장) ──────────────────────────────────────
    lim_lines = [f"{lim.description} (영향: {lim.impact})" for lim in ctx.limitations.data_gaps[:2]] + [
        str(c) for c in ctx.limitations.model_caveats[:2]
    ]
    if not lim_lines:
        lim_lines = ["본 분석의 한계 자가검증 미흡 — 추가 검토 권장"]
    limit_section = make_section(
        "limitations",
        "Section 8 — 한계 & Next",
        kind="caveat",
        divider=False,
        slides=[
            SlideSpec(
                id="limitations",
                section_id="limitations",
                layout="quote",
                role="caveat",
                so_what="본 분석의 한계를 명시하고 후속 권고를 제시합니다",
                title_ko="한계 & Next Steps",
                body_outline=lim_lines[:4],
                parent_message_id="root",
            ),
        ],
    )
    sections.append(limit_section)

    # ── Closing ────────────────────────────────────────────────
    closing_section = make_section("closing", "Closing", kind="closing", divider=False, slides=[build_closing(ctx)])
    sections.append(closing_section)

    # ── Agenda 삽입 (front_matter 맨 뒤) ───────────────────────
    section_titles = [s.title for s in sections if s.id not in ("front_matter", "closing")]
    front.slides.append(build_agenda(section_titles))

    # ── NarrativeThread + 메시지 트리 마무리 ───────────────────
    thread = NarrativeThread(
        setup=f"{ctx.domain.inferred_industry or ctx.meta.category} 의 {ctx.domain.inferred_use_case or '대상 과제'} 가 현 상황",
        conflict=issue_lines[0] if quality_issues else "주요 문제·제약 식별 필요",
        resolution=f"{chosen.get('name', '-')} 모델로 {pm.get('name', '-')} {pm.get('value', '-')} 달성",
    )

    plan = ReportPlan(
        skeleton=SKELETON_NAME,
        audience=audience_profile.get("level", "analyst")
        if isinstance(audience_profile.get("level"), str)
        else "analyst",
        output_form="pptx",
        slide_count_target=length_target,
        sections=sections,
        narrative_thread=thread,
        message_tree=messages,
        meta={"skeleton_version": "1.0"},
    )
    return plan

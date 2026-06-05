"""outputs.architect.skeletons.analysis_standard — Analysis Standard (Phase 2).

학술·규제 보고형. 배경→데이터→방법→결과→토의→한계→참고문헌.
고정 16장 + 가변 0~4장 = 16~20장. 학술 톤 — '권고' 대신 '시사·관찰'.
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
    eda_top_chart_refs,
    insert_tech_slides,
    make_section,
    primary_metric_ref,
)
from outputs.context.schema import ReportContext

SKELETON_NAME = "Analysis Standard"


def build(ctx: ReportContext, audience_profile: dict[str, Any], length_target: int = 18) -> ReportPlan:
    chosen = ctx.model_selection.chosen or {}
    pm = ctx.evaluation.primary_metric or {}
    sections: list[SectionSpec] = []
    root = MessageNode(id="root", role="claim", text="학술/규제 보고서 root")

    front = make_section(
        "front_matter", "Front Matter", kind="cover", slides=[build_cover(ctx), build_exec_summary(ctx)]
    )
    sections.append(front)

    # 배경
    bg = SlideSpec(
        id="background",
        section_id="background",
        layout="one_message",
        role="evidence",
        so_what=f"{ctx.domain.inferred_industry or ctx.meta.category} 의 {ctx.domain.inferred_use_case or '대상'} 가 본 보고 대상입니다",
        title_ko="배경 & 문제 정의",
        body_outline=[
            f"산업: {ctx.domain.inferred_industry or '-'}",
            f"규제 힌트: {', '.join(ctx.domain.regulatory_hints[:3]) or '없음'}",
        ],
        thread_part="setup",
        parent_message_id="root",
    )
    sections.append(make_section("background", "Section 1 — 배경", kind="context", divider=True, slides=[bg]))

    # 데이터
    data_source = SlideSpec(
        id="data_source",
        section_id="data",
        layout="comparison_table",
        role="evidence",
        so_what=f"데이터: {ctx.dataset.shape.get('rows', 0):,}건 / {ctx.dataset.shape.get('cols', 0)}컬럼",
        title_ko="데이터 출처·기간·표본",
        body_outline=[
            f"행: {ctx.dataset.shape.get('rows', 0):,}",
            f"열: {ctx.dataset.shape.get('cols', 0)}",
            f"소스: {ctx.dataset.file_meta.get('source', '-')}",
        ],
        parent_message_id="root",
    )
    data_dict = SlideSpec(
        id="data_dict",
        section_id="data",
        layout="appendix_table",
        role="evidence",
        so_what="변수 사전 — 주요 변수 정의·단위·결측률",
        title_ko="데이터 사전",
        body_outline=[f"{col}: {dtype}" for col, dtype in list(ctx.dataset.dtypes.items())[:8]] or ["변수 정보 미식별"],
        parent_message_id="root",
    )
    sections.append(
        make_section("data", "Section 2 — 데이터", kind="evidence", divider=True, slides=[data_source, data_dict])
    )

    # 방법
    method_pre = SlideSpec(
        id="method_pre",
        section_id="method",
        layout="process_flow",
        role="evidence",
        so_what=f"전처리 {len(ctx.preprocessing.applied_steps)} 단계 — 모든 step rationale 명시",
        title_ko="방법론 — 전처리",
        body_outline=[f"{s.op}: {s.rationale[:50]}" for s in ctx.preprocessing.applied_steps[:5]]
        or ["전처리 단계 미식별"],
        parent_message_id="root",
    )
    method_model = SlideSpec(
        id="method_model",
        section_id="method",
        layout="comparison_table",
        role="evidence",
        so_what=f"{chosen.get('name', '-')} ({chosen.get('family', '-')}) — 튜닝 trials {ctx.training.tuning_summary.get('trials', '-')}",
        title_ko="방법론 — 모델·튜닝",
        body_outline=[
            f"선정: {chosen.get('name', '-')}",
            f"가족: {chosen.get('family', '-')}",
            f"근거: {chosen.get('justification', '')[:80]}",
        ],
        parent_message_id="root",
    )
    sections.append(
        make_section("method", "Section 3 — 방법", kind="evidence", divider=True, slides=[method_pre, method_model])
    )

    # 결과
    result_primary = SlideSpec(
        id="result_primary",
        section_id="results",
        layout="kpi_cards_4",
        role="evidence",
        so_what=f"{pm.get('name', '-')} {pm.get('value', '-')} ± CI — 주요 지표 종합",
        title_ko="결과 — 1차 지표",
        body_outline=[f"{k}: {v.get('value')}" for k, v in list(ctx.evaluation.metrics.items())[:4]] or ["지표 미식별"],
        required_refs=primary_metric_ref(ctx),
        parent_message_id="root",
    )
    result_eda = SlideSpec(
        id="result_eda",
        section_id="results",
        layout="chart_callout",
        role="evidence",
        so_what="EDA 분석 핵심 발견",
        title_ko="결과 — EDA",
        data_refs=eda_top_chart_refs(ctx, top_k=2),
        parent_message_id="root",
    )
    result_interp = SlideSpec(
        id="result_interp",
        section_id="results",
        layout="chart_callout",
        role="evidence",
        so_what=(
            f"{ctx.interpretation.global_importance[0].feature} 가 결과의 주요 동인"
            if ctx.interpretation.global_importance
            else "해석 데이터 미식별"
        ),
        title_ko="결과 — 해석",
        body_outline=[f"{i.feature} ({i.method}: {i.importance:.3f})" for i in ctx.interpretation.global_importance[:3]]
        or ["해석 미식별"],
        parent_message_id="root",
    )
    sections.append(
        make_section(
            "results",
            "Section 4 — 결과",
            kind="evidence",
            divider=True,
            slides=[result_primary, result_eda, result_interp],
        )
    )

    # 토의·시사
    discussion = SlideSpec(
        id="discussion",
        section_id="discussion",
        layout="quote",
        role="claim",
        so_what="본 결과의 학술적·실무적 함의",
        title_ko="토의 (Discussion)",
        body_outline=[
            "관찰 1: 주요 동인 식별로 후속 연구·실험 가능",
            "관찰 2: 모델 성능은 baseline 대비 유의미한 향상",
            "관찰 3: 한계는 다음 섹션에서 명시",
        ],
        thread_part="resolution",
        parent_message_id="root",
    )
    sections.append(
        make_section("discussion", "Section 5 — 토의", kind="recommendation", divider=False, slides=[discussion])
    )

    # 한계
    lim_items = [(f"데이터 한계: {g.description}", g.impact) for g in ctx.limitations.data_gaps[:2]] + [
        (f"모델 한계: {c}", "medium") for c in ctx.limitations.model_caveats[:2]
    ]
    if not lim_items:
        lim_items = [
            ("한계 자가검증 미흡", "high"),
            ("재현·외부 검증 필요", "medium"),
            ("표본 대표성 추가 검토 권장", "low"),
        ]
    limit = SlideSpec(
        id="limitations",
        section_id="limitations",
        layout="comparison_table",
        role="caveat",
        so_what="본 분석의 한계와 후속 권고 명시",
        title_ko="한계 (Limitations)",
        body_outline=[f"{desc} (영향: {imp})" for desc, imp in lim_items[:5]],
        parent_message_id="root",
    )
    sections.append(make_section("limitations", "Section 6 — 한계", kind="caveat", divider=False, slides=[limit]))

    # 참고문헌
    refs = SlideSpec(
        id="references",
        section_id="references",
        layout="appendix_table",
        role="meta",
        so_what="KB·외부 인용 색인",
        title_ko="참고문헌",
        body_outline=[f"KB: {c.title}" for c in ctx.domain.kb_citations[:5]]
        + [f"외부: {c.title}" for c in ctx.domain.web_citations[:5]]
        or ["인용 미수집"],
        parent_message_id="root",
    )
    sections.append(make_section("references", "Section 7 — 참고", kind="appendix", divider=False, slides=[refs]))

    # 기술 (학술 톤에서는 1장 통합)
    tech_section = make_section("solution", "기술·재현", kind="evidence", divider=False)
    insert_tech_slides(tech_section, ctx, space_available=1)
    sections.append(tech_section)

    # Closing
    sections.append(make_section("closing", "Closing", kind="closing", divider=False, slides=[build_closing(ctx)]))

    titles = [s.title for s in sections if s.id not in ("front_matter", "closing")]
    front.slides.append(build_agenda(titles))

    thread = NarrativeThread(
        setup=f"{ctx.domain.inferred_industry or ctx.meta.category} 의 {ctx.domain.inferred_use_case or '대상 과제'}",
        conflict=(
            ctx.eda.data_quality_issues[0].get("issue") if ctx.eda.data_quality_issues else "검증 가설 정의 필요"
        ),
        resolution=f"{chosen.get('name', '-')} 적용 — {pm.get('name', '-')} {pm.get('value', '-')}",
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

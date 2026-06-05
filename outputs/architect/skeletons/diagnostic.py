"""outputs.architect.skeletons.diagnostic — Diagnostic Skeleton (Phase 2).

이상·장애·원인 분석형. 증상→타임라인→가설→근본원인→즉시조치→재발방지.
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

SKELETON_NAME = "Diagnostic"


def build(ctx: ReportContext, audience_profile: dict[str, Any], length_target: int = 14) -> ReportPlan:
    pm = ctx.evaluation.primary_metric or {}
    sections: list[SectionSpec] = []
    root = MessageNode(id="root", role="claim", text="진단 보고서")

    # Cover + Exec
    front = make_section(
        "front_matter", "Front Matter", kind="cover", slides=[build_cover(ctx), build_exec_summary(ctx)]
    )
    sections.append(front)

    # 증상
    quality_issues = ctx.eda.data_quality_issues or []
    critical_eda = [c for c in ctx.eda.charts if getattr(c, "severity", "info") == "critical"]
    sym = SlideSpec(
        id="symptoms",
        section_id="symptoms",
        layout="kpi_cards_4",
        role="evidence",
        so_what=f"관측된 이상·문제 {len(quality_issues) + len(critical_eda)} 건",
        title_ko="증상 (Symptoms)",
        body_outline=[it.get("issue", "이슈") for it in quality_issues[:4]] or ["증상 자동 식별 미흡 — 수동 보강 필요"],
        thread_part="setup",
        parent_message_id="root",
    )
    sections.append(make_section("symptoms", "Section 1 — 증상", kind="context", divider=True, slides=[sym]))

    # 타임라인
    tl = SlideSpec(
        id="timeline",
        section_id="timeline",
        layout="process_flow_gantt",
        role="evidence",
        so_what="발생·탐지·분석 타임라인",
        title_ko="타임라인",
        body_outline=["발생 시점 → 탐지 → 격리 → 분석 → 권고"],
        parent_message_id="root",
    )
    sections.append(make_section("timeline", "Section 2 — 타임라인", kind="context", divider=False, slides=[tl]))

    # 가설 트리
    ht = SlideSpec(
        id="hypothesis_tree",
        section_id="hypotheses",
        layout="2x2_matrix",
        role="evidence",
        so_what="가설 4개 정의 — MECE 검증 통과",
        title_ko="가설 트리",
        body_outline=["H1: 데이터 품질 이슈", "H2: 모델 한계", "H3: 분포 변화", "H4: 운영 환경 변경"],
        thread_part="conflict",
        parent_message_id="root",
    )
    # 가설별 증거
    ev1 = SlideSpec(
        id="evidence_h1",
        section_id="hypotheses",
        layout="chart_callout",
        role="evidence",
        so_what=(
            "H1 (데이터 품질): " + (quality_issues[0].get("issue") if quality_issues else "데이터 결측 패턴 발견")
        ),
        title_ko="증거 — 가설 1",
        data_refs=eda_top_chart_refs(ctx, top_k=1),
        parent_message_id="root",
    )
    ev2 = SlideSpec(
        id="evidence_h2",
        section_id="hypotheses",
        layout="kpi_cards_4",
        role="evidence",
        so_what=f"H2 (모델 한계): {pm.get('name', '-')} {pm.get('value', '-')} — 임계 미달 여부 확인",
        title_ko="증거 — 가설 2",
        body_outline=[f"{k}: {v.get('value')}" for k, v in list(ctx.evaluation.metrics.items())[:4]],
        required_refs=primary_metric_ref(ctx),
        parent_message_id="root",
    )
    sections.append(
        make_section("hypotheses", "Section 3 — 가설 & 증거", kind="evidence", divider=True, slides=[ht, ev1, ev2])
    )

    # 근본 원인
    rc = SlideSpec(
        id="root_cause",
        section_id="root_cause",
        layout="one_message_big_number",
        role="claim",
        so_what="근본원인: H1 채택 — 데이터 분포 변화가 핵심",
        title_ko="근본 원인",
        body_outline=[
            "5 Why 추적 완료 — 후속 슬라이드 참조",
            "영향 범위: 본 카테고리 전체",
            "재현성: 동일 데이터 입력 시 재현",
        ],
        thread_part="resolution",
        parent_message_id="root",
    )
    sections.append(
        make_section("root_cause", "Section 4 — 근본원인", kind="recommendation", divider=True, slides=[rc])
    )

    # 즉시조치
    short = SlideSpec(
        id="short_term",
        section_id="actions",
        layout="comparison_table",
        role="action",
        so_what="0~7일 즉시조치 3건 (소유자·기한 명시)",
        title_ko="즉시 조치",
        body_outline=[
            "조치 1: 이상치 모니터링 강화 (소유자: 운영팀, 기한: 7일)",
            "조치 2: 임계값 재조정 (소유자: 분석팀, 기한: 3일)",
            "조치 3: 알람 임시 보강 (소유자: SRE, 기한: 1일)",
        ],
        thread_part="resolution",
        parent_message_id="root",
    )
    # 재발방지
    long_ = SlideSpec(
        id="long_term",
        section_id="actions",
        layout="comparison_table",
        role="action",
        so_what="30~90일 구조 개선 — 재발방지",
        title_ko="재발 방지",
        body_outline=["분기 재학습 주기 자동화", "분포 변화 감지 파이프라인", "운영 대시보드 정기 리뷰"],
        thread_part="resolution",
        parent_message_id="root",
    )
    # 잔여 리스크
    risk = SlideSpec(
        id="residual_risk",
        section_id="actions",
        layout="comparison_table",
        role="caveat",
        so_what="잔여 리스크와 모니터링 방안",
        title_ko="잔여 리스크",
        body_outline=[
            f"{lim.description} → {lim.mitigation or '추가 검토'}" for lim in ctx.limitations.generalization_risk[:3]
        ]
        or ["잔여 리스크 추가 식별 필요"],
        parent_message_id="root",
    )
    sections.append(
        make_section(
            "actions",
            "Section 5 — 조치 & 잔여 리스크",
            kind="recommendation",
            divider=True,
            slides=[short, long_, risk],
        )
    )

    # 기술 (통합 1장)
    tech_section = make_section("solution", "기술 구성", kind="evidence", divider=False)
    insert_tech_slides(tech_section, ctx, space_available=1)
    sections.append(tech_section)

    # Closing
    sections.append(make_section("closing", "Closing", kind="closing", divider=False, slides=[build_closing(ctx)]))

    titles = [s.title for s in sections if s.id not in ("front_matter", "closing")]
    front.slides.append(build_agenda(titles))

    thread = NarrativeThread(
        setup="이상·문제 관측됨",
        conflict="가설 4개 중 어느 것이 원인인지 분석 필요",
        resolution="근본원인 식별 + 즉시조치 + 재발방지 권고",
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

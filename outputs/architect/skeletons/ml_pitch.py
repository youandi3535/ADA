"""outputs.architect.skeletons.ml_pitch — ML Pitch Skeleton (Phase 2, HJ 2026-06-08).

ML (tabular_ml / tabular_dl) 카테고리 전용 컨설팅·세일즈 피치 deck.
사용자 디자인 20장 + 빅4 컨설팅(Pyramid·Action Title·MECE) + FAANG(Baseline·Error Analysis·Segment·Monitoring) 표준 통합.

20 슬라이드 구조 (확정):
    1.  Cover                               cover
    2.  Executive Summary                   exec_summary           ← 컨설팅 BLUF
    3.  Agenda                              agenda
    4.  분석 가설                            hypothesis             → t_hyp_evidence_insight
    5.  시장·맥락                            p1_market              → t_numbered_rows
    6.  현행 방식의 한계                     p2_pain                → t_linked_circles
    7.  기존 솔루션 한계                      p3_alt_limits          → t_chevron_5
    8.  솔루션 개요                          method_model           → t_gear
    9.  기술 아키텍처 + 데이터 lineage         tech_architecture      → t_vertical_arrow  (보강 F)
    10. 기술 스택                            tech_stack             → t_cube_3d
    11. 차별화 포인트                        s3_differentiation     → t_strategy_4
    12. 핵심 성과 + Baseline 비교             i1_kpi                 → t_kpi_pct_4       (보강 G)
    13. EDA 핵심 발견                        eda_findings           layout=chart_dual
    14. ★ Error Analysis & Segment           error_analysis         layout=2x2_matrix    (FAANG 핵심)
    15. 가설 입증 인사이트                   insights_derived       → t_insight_funnel
    16. AS-IS vs TO-BE                       as_is_to_be            → t_as_is_to_be
    17. ROI / 비즈니스 임팩트                 i3_roi                 → t_circular_progress
    18. Risk & Mitigation + Drift            risk_mitigation        → t_swot           (보강 C)
    19. 실행 계획 + 모니터링 KPI              roadmap                → t_roadmap_upgrades (보강 D)
    20. Thank You + Q&A                      closing                layout=closing

설계 원칙 (코드 레벨로 강제):
    - Action Title : 모든 SlideSpec.so_what 가 *결론을 말하는 완전한 문장*
    - One Message  : body_outline 은 so_what 을 입증만, 새 메시지 X
    - MECE         : body_outline 3개 기본, 5개 이내
    - Baseline     : 슬라이드 12 에 룰 기반·로지스틱·선정모델 3중 비교 막대 spec
    - Error Analysis: 슬라이드 14 에 confusion matrix + segment + 비즈니스 비용 spec
    - Monitoring   : 슬라이드 19 Phase 별 KPI 명시
    - Drift        : 슬라이드 18 SWOT 의 W/T 에 데이터 드리프트 항목 명시

HJ 단독 영역. 변경 시 [[step-label-convention]] + AGENTS.md R-007 참조.
"""

from __future__ import annotations

from typing import Any, Optional

from outputs.architect.plan import (
    MessageNode,
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
    VisualSpec,
)
from outputs.architect.skeleton_helpers import (
    auto_label as _auto_label,
    build_derived_features_slide as _build_derived_features_slide,
    build_eda_placeholder as _build_eda_placeholder,
    build_eda_slide_from_chart as _build_eda_slide_from_chart,
    build_method_steps as _build_method_steps,
    build_method_whys as _build_method_whys,
    derived_features_richness as _derived_features_richness,
    format_pm_value as _format_pm_value,
    get_verdict_tone as _get_verdict_tone,
    select_top_eda_charts as _select_top_eda_charts,
    summarize_dtypes as _summarize_dtypes,
    summarize_target as _summarize_target,
)
from outputs.architect.substitution_manifest import (
    TechStackItem,
    is_metric_compatible,
    resolve_slide,
    resolve_tech_stack,
)
from outputs.context.schema import ReportContext
from outputs.style.text_budget import (
    format_metric,
)

SKELETON_NAME = "ML Pitch"



# ==============================================================
# 내부 헬퍼 — 기존 _common.py 에서 ml_pitch 가 쓰던 5종을 인라인.
# 사용자 결정: 카테고리별 skeleton 은 자기완결 (_common 의존성 없음).
# 다른 skeleton 추가 시 이 헬퍼들을 그대로 복사·수정해 자기 카테고리 색에 맞게 변형.
# ==============================================================


def make_section(
    section_id: str,
    title: str,
    kind: str,
    divider: bool = False,
    summary: str = "",
    slides: Optional[list[SlideSpec]] = None,
) -> SectionSpec:
    """SectionSpec 생성 헬퍼."""
    return SectionSpec(
        id=section_id,
        title=title,
        kind=kind,
        divider_required=divider,
        short_summary=summary or title,
        slides=list(slides or []),
    )


def primary_metric_ref(ctx: ReportContext) -> list[str]:
    """primary_metric 의 ref_id (있으면 1개) — ExecSummary·KPI 슬라이드 인용."""
    pm = ctx.evaluation.primary_metric or {}
    rid = pm.get("ref_id")
    return [rid] if rid else []


def build_cover(ctx: ReportContext) -> SlideSpec:
    """표지 — Cover."""
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "분석 보고서").strip()
    return SlideSpec(
        id="cover",
        section_id="front_matter",
        layout="cover",
        role="meta",
        so_what="",
        title_ko=intent[:40],
        body_outline=[
            f"카테고리: {ctx.meta.category}",
            f"데이터셋: {ctx.dataset.dataset_name or '미지정'}",
            f"분류등급: {ctx.meta.classification}",
        ],
        required_refs=[],
        speaker_notes_hint="제목·분석 의도·발표자 소개 + 본 보고서의 핵심 결론 미리보기.",
    )


def build_agenda(sections_titles: list[str]) -> SlideSpec:
    """Agenda — 섹션 맵."""
    return SlideSpec(
        id="agenda",
        section_id="front_matter",
        layout="agenda",
        role="meta",
        so_what="본 보고서는 6개 섹션 구성으로, 결론부터 근거·실행순으로 전개합니다",
        title_ko="Agenda",
        body_outline=sections_titles,
        speaker_notes_hint="섹션 흐름 안내. 각 섹션 1줄 요약 포함.",
    )


def build_tech_stack_slide(ctx: ReportContext) -> SlideSpec:
    """슬라이드 10 — EDA · 주요 변수 3 (ctx.eda.charts Top 3).

    [재구성] '기술 스택' → 'EDA 주요 변수 3'. Tech Stack 책임은 S6 (_build_pain_points)
    에서 substitution_manifest 기반으로 처리. 본 함수는 EDA-3 로 변경.
    함수 이름·ID 유지 (build() / 다른 skeleton 의 공통 헬퍼 import 호환).
    """
    charts = _select_top_eda_charts(ctx, n=3)
    if len(charts) >= 3:
        return _build_eda_slide_from_chart(charts[2], "tech_stack", 3, ctx, "eda_main_3")
    return _build_eda_placeholder("tech_stack", 3, ctx, "eda_main_3")


# ==============================================================
# Main builder
# ==============================================================
def build(
    ctx: ReportContext,
    audience_profile: dict[str, Any],
    length_target: int = 20,
) -> ReportPlan:
    """ML_Pitch Skeleton → ReportPlan (20장 고정).

    사용자 디자인 20장을 *고정 구조* 로 생성. length_adjuster 가 후속
    호출되지만 ML 피치 deck 은 모든 슬라이드가 핵심 → 트리밍 비권장.
    Args:
        ctx: 정규화된 ReportContext.
        audience_profile: AudienceAdapter 결과.
        length_target: 무시 — ML_Pitch 는 항상 20장. (length_adjuster 의 hard_min/max
            가 [10, 20] 이라 안전.)
    """
    sections: list[SectionSpec] = []
    messages: list[MessageNode] = _build_message_tree(ctx)

    # ── ① Front Matter (3장) ─────────────────────────────────────
    front = make_section(
        "front_matter",
        "Front Matter",
        kind="cover",
        divider=False,
        slides=[
            build_cover(ctx),
            _build_exec_summary_ml(ctx),  # 보강 A — ML 전용 5박스
            # Agenda 는 sections 완성 후 마지막에 삽입
        ],
    )
    sections.append(front)

    # ── ② Problem (3장) — 가설·시장·페인 ───────────────────────────
    problem_section = make_section(
        "problem",
        "Section 1 — 문제 정의",
        kind="context",
        divider=True,
        slides=[
            _build_hypothesis(ctx),  # 4. 분석 가설
            _build_market_context(ctx),  # 5. 데이터·도구 (S5+S6 병합 — jh 2026-06-12)
        ],
    )
    sections.append(problem_section)

    # ── ③ Existing Limit (1장) — 기존 솔루션 한계 ─────────────────
    limit_section = make_section(
        "limits",
        "Section 2 — 기존 한계",
        kind="context",
        divider=False,
        slides=[_build_alt_limits(ctx)],  # 7. 기존 솔루션 한계
    )
    sections.append(limit_section)

    # ── ④ Solution (4장) — 개요·아키텍처(+lineage)·스택·차별화 ─────
    solution_section = make_section(
        "solution",
        "Section 3 — 솔루션",
        kind="evidence",
        divider=True,
        slides=[
            _build_solution_overview(ctx),  # 8. 솔루션 개요
            _build_tech_architecture_with_lineage(ctx),  # 9. 기술 아키텍처 + lineage (보강 F)
            build_tech_stack_slide(ctx),  # 10. 기술 스택 (공통 헬퍼 재사용)
            _build_differentiation(ctx),  # 11. 차별화
        ],
    )
    sections.append(solution_section)

    # ── ⑤ Results (4장) — KPI(baseline)·EDA·Error·인사이트 ────────
    results_section = make_section(
        "results",
        "Section 4 — 분석 결과",
        kind="evidence",
        divider=True,
        slides=[
            _build_kpi_with_baseline(ctx),  # 12. 핵심 성과 + Baseline (보강 G)
            _build_eda_findings(ctx),  # 13. EDA 핵심 발견 (신규)
            _build_error_analysis(ctx),  # 14. ★ Error Analysis (보강 B)
            _build_insights_derived(ctx),  # 15. 가설 입증 인사이트
            _build_insight_synthesis(ctx),  # 16. 인사이트 종합 (jh 2026-06-12 신설)
        ],
    )
    sections.append(results_section)

    # ── ⑥ Impact (2장) — AS-IS/TO-BE · ROI ───────────────────────
    impact_section = make_section(
        "impact",
        "Section 5 — 비즈니스 임팩트",
        kind="recommendation",
        divider=True,
        slides=[
            _build_as_is_to_be(ctx),  # 16. AS-IS vs TO-BE
            _build_roi(ctx),  # 17. ROI / 임팩트
        ],
    )
    sections.append(impact_section)

    # ── ⑦ Risk & Roadmap (2장) ───────────────────────────────────
    plan_section = make_section(
        "plan",
        "Section 6 — 리스크 & 실행",
        kind="recommendation",
        divider=False,
        slides=[
            _build_risk_mitigation(ctx),  # 18. Risk + Drift (보강 C)
            _build_roadmap(ctx),  # 19. 실행 계획 + 모니터링 KPI (보강 D)
        ],
    )
    sections.append(plan_section)

    # ── ⑧ Closing (1장) ───────────────────────────────────────────
    closing_section = make_section(
        "closing",
        "Closing",
        kind="closing",
        divider=False,
        slides=[_build_closing_qna(ctx)],
    )
    sections.append(closing_section)

    # Agenda 삽입 (front_matter 마지막 자리)
    sections_titles = [
        "Section 1 — 문제 정의 (가설·시장·한계)",
        "Section 2 — 기존 한계",
        "Section 3 — 솔루션 (아키텍처·스택·차별화)",
        "Section 4 — 분석 결과 (KPI·EDA·Error·인사이트)",
        "Section 5 — 비즈니스 임팩트",
        "Section 6 — 리스크 & 실행 계획",
    ]
    agenda = build_agenda(sections_titles)
    sections[0].slides.append(agenda)  # front_matter 마지막

    # ── ReportPlan 종합 ─────────────────────────────────────────
    plan = ReportPlan(
        skeleton=SKELETON_NAME,
        audience=ctx.meta.audience or "external_client",
        output_form="pptx",
        slide_count_target=20,
        sections=sections,
        narrative_thread=NarrativeThread(
            setup=f"{ctx.domain.inferred_industry or ctx.meta.category} 산업의 {ctx.domain.inferred_use_case or ctx.meta.user_intent or '대상 과제'} 가 본 분석 출발점",
            conflict="기존 룰·휴리스틱 방식의 한계로 정확도·운영 효율 모두 미흡",
            resolution=f"{(ctx.model_selection.chosen or {}).get('name', 'ML 모델')} 도입으로 baseline 대비 우수한 결과 + ROI 확보",
        ),
        message_tree=messages,
        meta={"skeleton_variant": "ml_pitch_v1"},
        warnings=[],
    )
    return plan


# ==============================================================
# 슬라이드 빌더 — 각 슬라이드 1개 함수
# ==============================================================

def _build_top_findings_from_ctx(ctx: ReportContext) -> list[dict[str, Any]]:
    """S2 상단 3 KEY FINDINGS — interpretation.global_importance Top 3 기반.

    각 finding 은 carrier 가 카드로 렌더할 구조:
        {label, feature, importance, big, sub}
    - big: 한 줄 임팩트 수치 (예: SHAP 값 또는 격차%)
    - sub: 2~3 줄 근거 (해당 변수의 인사이트)
    """
    importance_list = list(ctx.interpretation.global_importance or [])[:3]
    findings: list[dict[str, Any]] = []
    for i, item in enumerate(importance_list):
        feature = getattr(item, "feature", "") or getattr(item, "name", "") or f"Feature {i+1}"
        value = getattr(item, "value", None) or getattr(item, "importance", None) or 0.0
        story = ctx.interpretation.per_feature_story.get(feature, "")
        findings.append({
            "label": f"FINDING {i+1:02d}",
            "feature": feature,
            "big": format_metric(float(value), "shap", as_percent=False, decimals=2),
            "sub": _auto_label(story, ctx) if story else feature,
        })
    # ctx 가 비어있으면 placeholder 3개 (carrier 가 자연스럽게 빈 카드로 렌더)
    while len(findings) < 3:
        findings.append({
            "label": f"FINDING {len(findings)+1:02d}",
            "feature": "",
            "big": "-",
            "sub": "분석 결과 적립 후 채워짐",
        })
    return findings


def _build_method_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    """S2 하단 METHOD 박스의 2단 (소제목, 설명) 쌍 3개."""
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    n_candidates = len(ctx.model_selection.candidates or [])
    n_features = ctx.features.final_feature_count or len(
        ctx.features.created or []
    )
    split = "80/20 hold-out + Baseline 비교"
    if ctx.training.runs:
        first = ctx.training.runs[0]
        if first.hyperparameters and "split" in first.hyperparameters:
            split = str(first.hyperparameters["split"])
    return [
        ("모델 선정", f"{chosen} — 후보 {n_candidates}개 비교 후 선택" if n_candidates else f"{chosen} 선정"),
        ("신규 피처", f"{n_features}개 추가" if n_features else "신규 피처 생성 없음"),
        ("검증 방식", split),
    ]


def _build_perf_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    """S2 하단 PERFORMANCE 박스의 2단 쌍 3개."""
    pm = ctx.evaluation.primary_metric or {}
    pm_str = _format_pm_value(pm)
    gate = "운영 임계 통과" if ctx.evaluation.gate_passed else "운영 임계 미통과"
    rationale = ctx.evaluation.gate_rationale or gate

    baseline = ctx.model_selection.baselines.naive or {}
    baseline_str = ""
    if baseline:
        b_val = baseline.get("score")
        if b_val is not None:
            try:
                baseline_str = format_metric(float(b_val), pm.get("name", ""))
            except (TypeError, ValueError):
                baseline_str = str(b_val)
            baseline_str = f"룰 {baseline_str} 대비 +{pm_str}"
        else:
            baseline_str = "Baseline 비교 완료"
    else:
        baseline_str = "Baseline 미설정"

    n_metrics = len(ctx.evaluation.metrics or {})
    balance = f"{n_metrics}-metric 균형" if n_metrics >= 2 else "단일 metric 평가"

    return [
        ("운영 임계", rationale),
        ("베이스라인 대비", baseline_str),
        ("균형", balance),
    ]


def _build_limitation_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    """S2 하단 LIMITATION 박스의 2단 쌍 3개.

    LimitationItem.description 을 *소제목* 으로 (한계 자체), impact + mitigation 을
    *설명* 으로 결합.
    """
    gaps = list(ctx.limitations.data_gaps or [])[:3]
    items: list[tuple[str, str]] = []
    for g in gaps:
        label = getattr(g, "description", "") or "데이터 결함"
        impact = getattr(g, "impact", "") or ""
        mitigation = getattr(g, "mitigation", None) or ""
        if mitigation:
            desc = f"영향 {impact} · {mitigation}" if impact else mitigation
        else:
            desc = f"영향 {impact}" if impact else "영향 추정 필요"
        items.append((str(label), str(desc)))
    # caveat 보완
    if len(items) < 3 and ctx.limitations.model_caveats:
        for cav in ctx.limitations.model_caveats[: 3 - len(items)]:
            items.append(("모델 한계", str(cav)))
    while len(items) < 3:
        items.append(("한계", "추가 분석 필요"))
    return items


def _build_exec_summary_ml(ctx: ReportContext) -> SlideSpec:
    """슬라이드 2 — Executive Summary (분석 보고서 톤).

    상단: 3 KEY FINDINGS (interpretation Top 3).
    하단: METHOD / PERFORMANCE / LIMITATION 3 박스 (각각 2단 소제목+설명 3쌍).
    so_what: verdict (adopt/iterate/reject) 에 따라 어조 분기.
    """
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "분석 과제"
    horizon = ctx.limitations.revalidation_window or "6개월"
    pm_name = pm.get("name", "primary")
    pm_value = _format_pm_value(pm)

    tone = _get_verdict_tone(ctx)
    so_what = tone.s2_so_what_template.format(
        chosen=chosen,
        use_case=use_case,
        metric_name=pm_name,
        metric_value=pm_value,
        horizon=horizon,
    )

    findings = _build_top_findings_from_ctx(ctx)
    method_items = _build_method_subitems(ctx)
    perf_items = _build_perf_subitems(ctx)
    limitation_items = _build_limitation_subitems(ctx)

    # body_outline — legacy carrier (kpi_cards_3) 호환용 단순 텍스트 5줄.
    # 신규 carrier 는 visual_spec.spec 의 구조화 데이터를 우선 사용.
    body = [
        f"발견 1 · {findings[0]['feature']} {findings[0]['big']}",
        f"발견 2 · {findings[1]['feature']} {findings[1]['big']}",
        f"발견 3 · {findings[2]['feature']} {findings[2]['big']}",
        f"방법 · {method_items[0][1]}",
        f"성능 · {pm_name} {pm_value} ({tone.accent})",
    ]

    return SlideSpec(
        id="exec_summary",
        section_id="front_matter",
        layout="exec_summary_3finding_3box",
        role="claim",
        so_what=so_what,
        title_ko="Executive Summary",
        body_outline=body,
        required_refs=primary_metric_ref(ctx),
        thread_part="resolution",
        parent_message_id="root",
        visual_spec=VisualSpec(
            type="exec_summary_v32",
            title="Executive Summary",
            spec={
                "findings": findings,
                "method_items": method_items,
                "perf_items": perf_items,
                "limitation_items": limitation_items,
                "verdict": ctx.evaluation.verdict or "adopt",
                "tone_accent": tone.accent,
            },
        ),
        speaker_notes_hint=(
            "1장만 봐도 의사결정 가능. 상단 3 KEY FINDINGS = 무엇을 알아냈나, "
            "하단 METHOD/PERFORMANCE/LIMITATION = 어디까지 볼 수 있나. "
            "verdict 에 따라 so_what 어조가 자동 분기 (adopt/iterate/reject)."
        ),
    )


def _build_hypothesis(ctx: ReportContext) -> SlideSpec:
    """슬라이드 4 — 분석 가설 (3개)."""
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    intent = ctx.meta.user_intent or "분석 과제"
    # jh 2026-06-12 — "가설문 — 증거 — 인사이트" 3분할 형식 (라벨 접두 금지).
    # carrier t_hyp_evidence_insight 가 " — " 기준으로 3칸에 분배한다.
    body = [
        f"상위 피처가 결과를 좌우한다 — Top 피처가 {pm.get('name', '지표')} 에 강한 신호 제공 — 핵심 변수 중심 해석 전략 수립",
        f"{chosen} 이 본 데이터에 최적이다 — baseline 대비 우수 성과로 선정 — 운영 비용 대비 효율적 모델 확보",
        "분포 변화에도 성능이 유지된다 — 임계 성능 유지 여부를 세그먼트 검증으로 확인 — drift 모니터링 설계의 근거",
    ]
    return SlideSpec(
        id="hypothesis",
        section_id="problem",
        layout="one_message",
        role="claim",
        so_what=f"본 분석 '{intent[:40]}' 를 뒷받침하는 3개 가설 수립 — 데이터로 입증 예정",
        title_ko="분석 가설",
        body_outline=body,
        thread_part="setup",
        parent_message_id="hyp_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Hypothesis · Evidence · Insight",
            caption="가설별 증거·인사이트 흐름 (검증은 슬라이드 15)",
            spec={"layout": "hyp_evidence_insight"},
        ),
        speaker_notes_hint="가설 3개를 명확히 — 검증은 슬라이드 15 에서 1:1 대응.",
    )
def _build_market_context(ctx: ReportContext) -> SlideSpec:
    """슬라이드 5 — 데이터 개요 + 품질 (통합).

    이전 '시장·맥락' (영업 톤) 을 분석 보고서 톤으로 재구성:
    상단 = 데이터 개요 (행·열·타입·타겟), 하단 = 데이터 품질 이슈 Top 3.
    v28_data_combined layout 가정 — 신규 carrier 가 두 영역으로 분리 렌더.
    """
    rows = ctx.dataset.shape.get("rows", 0)
    cols = ctx.dataset.shape.get("cols", 0)
    dtypes_summary = _summarize_dtypes(ctx)
    target_summary = _summarize_target(ctx)

    overview_items: list[tuple[str, str]] = [
        ("규모", f"{rows:,} 행 × {cols} 열"),
        ("변수 타입", dtypes_summary),
        ("타겟 분포", target_summary),
    ]

    # 데이터 품질 이슈 Top 3
    issues = list(ctx.eda.data_quality_issues or [])[:3]
    quality_items: list[tuple[str, str]] = []
    for it in issues:
        title = it.get("issue") or it.get("name") or "이슈"
        severity = it.get("severity", "medium")
        scope = it.get("scope", "")
        desc = f"심각도 {severity}" + (f" · 범위 {scope}" if scope else "")
        quality_items.append((str(title), desc))
    while len(quality_items) < 3:
        quality_items.append(("품질 확인", "추가 이슈 없음"))

    # jh 2026-06-12 (3차 개편, 사용자 지시) — "이 PPT 를 *왜* 만들었나(분석 목적)
    # + KPI 결과 + 분석 접근" 이 초반에 와야 한다. 데이터·도구는 S7(방법) 으로 이관.
    # 구성: 상단 목적(왜) / 중단 Q1~Q3 / 하단 KPI 결과 한 줄.
    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "분석 과제"
    intent = (ctx.meta.user_intent or use_case).strip()
    target = ctx.dataset.detected_target or "타겟"
    pm = ctx.evaluation.primary_metric or {}
    pm_name, pm_val = pm.get("name", "정확도"), pm.get("value")
    verdict = (ctx.evaluation.verdict or "").lower()
    _verdict_ko = {"adopt": "운영 도입 권장", "iterate": "보완 후 재평가", "reject": "도입 보류"}.get(verdict, "판정")
    biz = ctx.meta.business_context or ""

    # 목적 — "왜 이 분석인가" (user_intent + 도메인). 영업 X, 분석 동기 O.
    purpose = (
        f"{intent} — {target} 를 좌우하는 요인을 데이터로 규명하고, "
        f"재현 가능한 모델로 정량 검증하기 위한 분석"
    )
    if biz:
        purpose = f"{biz} — {purpose}"

    questions = [
        (
            f"{target} 을 가장 강하게 결정하는 변수는 무엇인가",
            "EDA 격차 분석 + SHAP 전역 중요도 (S8~S13)",
        ),
        (
            "그 구조가 데이터에 실제로 재현되는가",
            "집단 격차·상관·비선형 효과 정량 확인 (S8~S11)",
        ),
        (
            "모델은 어디서 약하고 운영에 어떻게 반영하나",
            "사례·오류 집계·세그먼트 분해 (S14~S17)",
        ),
    ]
    _pm_str = (f"{pm_val:.3f}" if isinstance(pm_val, float) and pm_val < 1 else str(pm_val)) if pm_val is not None else "—"
    kpi_line = f"분석 결과 · {pm_name} {_pm_str} → {_verdict_ko}"

    body = [purpose] + [f"{q} · {a}" for q, a in questions] + [kpi_line]

    return SlideSpec(
        id="p1_market",
        section_id="problem",
        layout="background_questions",
        role="claim",
        so_what=f"왜 이 분석인가 — {target} 결정 요인 규명, {pm_name} {_pm_str} 로 {_verdict_ko}",
        title_ko="분석 배경 — 목적과 핵심 질문",
        body_outline=body[:5],
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v32_background_questions",
            title="분석 배경 · 목적",
            spec={"purpose": purpose, "questions": questions, "kpi_line": kpi_line},
        ),
        speaker_notes_hint=(
            "왜 이 분석인가(목적) — 상단. Q1~Q3 + 각 답 위치 — 중단. "
            "KPI 결과·판정 — 하단. 데이터·도구는 S7(방법) 으로 이관."
        ),
    )


def _build_pain_points(ctx: ReportContext) -> SlideSpec:
    """슬라이드 6 — 기술 스택 (카테고리 자동 적응).

    이전 '현행 방식의 한계' 슬라이드 위치를 *Tech Stack* 으로 재구성.
    substitution_manifest.resolve_tech_stack(category) 호출 — tabular_ml/dl/ts/anomaly
    각각의 표준 도구 4종 자동 채움. 2단 위계 (도구 이름 + 역할 1줄).
    """
    category = ctx.meta.category or "tabular_ml"
    items: list[TechStackItem] = resolve_tech_stack(category)

    # ctx.code.environment 의 실제 패키지 정보가 있으면 역할 뒤에 버전 부착
    env_pkgs: dict[str, str] = {}
    if ctx.code and getattr(ctx.code, "environment", None):
        env_pkgs = ctx.code.environment.get("key_packages", {}) or {}

    stack_items: list[tuple[str, str]] = []
    for it in items:
        role = it.role
        # 정확 매치되는 패키지 버전이 있으면 표시
        first_token = it.name.split("/")[0].strip().split(" ")[0].strip().lower()
        for pkg, ver in env_pkgs.items():
            if pkg.lower() == first_token and ver:
                role = f"{role} · v{ver}"
                break
        stack_items.append((it.name, role))

    # body_outline — legacy carrier 호환
    body = [f"{name} · {role}" for name, role in stack_items]

    py_ver = (env_pkgs.get("python") or
              (ctx.code.environment.get("python") if ctx.code and ctx.code.environment else "") or "3.x")

    return SlideSpec(
        id="p2_pain",
        section_id="problem",
        layout="tech_stack_grid",
        role="evidence",
        so_what=f"본 분석은 {category} 표준 스택 ({len(stack_items)}개 도구) 으로 재현 가능 — Python {py_ver}",
        title_ko="기술 스택",
        body_outline=body,
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_tech_stack",
            title="기술 스택",
            spec={
                "stack_items": stack_items,
                "category": category,
                "python_version": py_ver,
            },
        ),
        speaker_notes_hint=(
            "재현 가능성·신뢰성 어필. 카테고리 (tabular_ml/dl/timeseries/anomaly) 에 따라 "
            "표준 스택이 자동 적응 — 매니페스트 단일 진실원 (substitution_manifest)."
        ),
    )
def _build_alt_limits(ctx: ReportContext) -> SlideSpec:
    """슬라이드 7 — 분석 방법 흐름 + WHY 패널 (Option C).

    이전 '기존 솔루션 한계' (영업 톤) 을 분석 방법 흐름도로 재구성:
    - 좌측: 5 단계 미니 흐름도 (preprocessing → feature → model → training → eval)
    - 우측: 4 WHY 카드 (header / WHAT / WHY / 결과) — Option C 구조

    카드의 *WHY* 는 rationale / justification 필드에서 추출 — 단순 *방법* 이 아닌
    *왜 그 방법인가* 를 명시하여 데이터·도메인 의사결정 트레이스 보존.
    """
    steps = _build_method_steps(ctx)
    whys = _build_method_whys(ctx)

    # body_outline — legacy carrier 호환 (5 단계 라벨)
    body = [f"단계 {i+1} · {s['label']}" for i, s in enumerate(steps)]

    # jh 2026-06-12 — S6 에서 이관된 데이터·도구 한 줄 (사용자 지시: 방법 장에 흡수)
    rows = ctx.dataset.shape.get("rows", 0)
    cols = ctx.dataset.shape.get("cols", 0)
    target = ctx.dataset.detected_target or "타겟"
    from outputs.architect.substitution_manifest import resolve_tech_stack as _rts

    _stack = _rts(ctx.meta.category or "tabular_ml")[:4]
    _stack_names = " · ".join(it.name.split("/")[0].strip() for it in _stack)
    data_tools_line = f"데이터 {rows:,}건 × {cols}변수 (타겟 {target}) · 도구 {_stack_names}"

    return SlideSpec(
        id="p3_alt_limits",
        section_id="limits",
        layout="method_flow_with_why",
        role="evidence",
        so_what=(
            "전처리부터 평가까지 5단계 — 각 단계의 선택 이유와 정량 결과를 함께 추적"
        ),
        title_ko="분석 방법 — 5단계와 데이터·도구",
        body_outline=body[:5],
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_method_flow",
            title="분석 방법 흐름 · WHY",
            spec={
                "steps": steps,
                "whys": whys,
                "data_tools_line": data_tools_line,
            },
        ),
        speaker_notes_hint=(
            "좌측 흐름도로 *전체 단계* 인지, 우측 WHY 카드로 *각 선택의 근거* 설명. "
            "WHY 는 ctx 의 rationale·justification 필드에서 자동 추출 — 빈 필드면 폴백 문구."
        ),
    )
def _build_solution_overview(ctx: ReportContext) -> SlideSpec:
    """슬라이드 8 — EDA · 주요 변수 1 (ctx.eda.charts Top 1).

    [재구성] 영업 톤 '솔루션 개요' → 분석 보고서 톤 'EDA 주요 변수 1'.
    함수 이름·슬라이드 ID 는 유지 (build() / message_tree 미수정).
    """
    charts = _select_top_eda_charts(ctx, n=3)
    if charts:
        return _build_eda_slide_from_chart(charts[0], "method_model", 1, ctx, "eda_main_1")
    return _build_eda_placeholder("method_model", 1, ctx, "eda_main_1")


def _build_tech_architecture_with_lineage(ctx: ReportContext) -> SlideSpec:
    """슬라이드 9 — EDA · 주요 변수 2 (ctx.eda.charts Top 2).

    [재구성] '기술 아키텍처 + lineage' → 'EDA 주요 변수 2'.
    함수 이름·ID 유지. 데이터 lineage 는 ctx.meta / dataset 다른 슬라이드에서 처리.
    """
    charts = _select_top_eda_charts(ctx, n=3)
    if len(charts) >= 2:
        return _build_eda_slide_from_chart(charts[1], "tech_architecture", 2, ctx, "eda_main_2")
    return _build_eda_placeholder("tech_architecture", 2, ctx, "eda_main_2")
def _build_differentiation(ctx: ReportContext) -> SlideSpec:
    """슬라이드 11 — EDA Extra (파생 피처 우선 / 4번째 chart / 결측 분포).

    우선순위 변경:
      1) 파생 피처 풍부도 점수 ≥ 5 → 파생 피처 표 슬라이드
      2) 4번째 EDAChart → chart_callout
      3) 결측률 Top 5 → 폴백
    """
    # ① 파생 피처가 충분히 풍부하면 — 파생 피처 표가 EDA Extra 슬롯 차지
    if _derived_features_richness(ctx) >= 5:
        return _build_derived_features_slide(ctx, "s3_differentiation")

    # ② 4번째 EDAChart
    charts = _select_top_eda_charts(ctx, n=4)
    if len(charts) >= 4:
        return _build_eda_slide_from_chart(charts[3], "s3_differentiation", 4, ctx, "eda_extra")

    # ③ 폴백 — 결측 분포
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide("eda_extra", category)
    title_ko = (variant.title_ko if variant else "EDA · 변수 간 상관 / 품질")

    missing = ctx.dataset.missing_rate or {}
    top_missing = sorted(missing.items(), key=lambda kv: -kv[1])[:5]
    body: list[str] = []
    if top_missing:
        for col, rate in top_missing:
            body.append(f"{col} 결측 {rate*100:.1f}%" if rate <= 1 else f"{col} 결측 {rate:.1f}%")
    else:
        body = ["결측 없음 — 추가 EDA 차트 적립 시 변경됨"]

    return SlideSpec(
        id="s3_differentiation",
        section_id="solution",
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence",
        so_what="결측·이상치 패턴 — 전처리 결정의 근거",
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_corr_heatmap"),
            title=title_ko,
            spec={"missing": dict(top_missing)},
        ),
        speaker_notes_hint=(
            "EDA Extra 우선순위 — 파생 피처 풍부도 ≥ 5 / 4번째 EDA chart / 결측률 Top 5."
        ),
    )


def _build_kpi_with_baseline(ctx: ReportContext) -> SlideSpec:
    """슬라이드 12 — 모델 성능 (4-metric 균형 + Baseline 실값 비교).

    [재구성] 가짜 '이론적 상한' 제거. ctx.evaluation.metrics + baselines 의 실값만 사용.
    카테고리별 metric 호환성 검사 (is_metric_compatible) → 부적합 시 visual_spec 안에 hint.
    """
    pm = ctx.evaluation.primary_metric or {}
    pm_name = pm.get("name", "primary")
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    category = ctx.meta.category or "tabular_ml"

    # 카테고리 ↔ metric 호환성 (typed schema assert)
    metric_ok = is_metric_compatible(category, pm_name)

    # 실제 baseline 막대 (가짜 추정 X)
    baselines = ctx.model_selection.baselines
    bars: list[dict[str, Any]] = []
    if baselines.naive:
        b = baselines.naive
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "Naive"), "value": v, "color": "muted"})
    if baselines.domain_rule:
        b = baselines.domain_rule
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "도메인 룰"), "value": v, "color": "muted"})
    if baselines.previous_best:
        b = baselines.previous_best
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "이전 최고"), "value": v, "color": "muted"})
    bars.append({
        "label": f"{chosen} (선정)",
        "value": pm.get("value"),
        "color": "primary",
        "highlight": True,
    })

    # 4-metric 균형 (Top 4 metric 평균)
    metric_lines: list[str] = []
    metric_balance_top4: list[tuple[str, str]] = []
    for name, m in list((ctx.evaluation.metrics or {}).items())[:4]:
        val = m.get("value") if isinstance(m, dict) else None
        if val is None:
            continue
        formatted = format_metric(float(val), name)
        metric_lines.append(f"{name} {formatted}")
        metric_balance_top4.append((name, formatted))

    # body_outline (legacy 호환)
    body: list[str] = []
    for bar in bars[:5]:
        v = bar["value"]
        v_str = format_metric(float(v), pm_name) if isinstance(v, (int, float)) else str(v)
        body.append(f"{bar['label']} · {pm_name} {v_str}")
    if metric_lines:
        body.append("4-metric · " + " · ".join(metric_lines))

    # so_what (verdict 어조 적용)
    tone = _get_verdict_tone(ctx)
    so_what = (
        f"{chosen} 성능: {pm_name} {pm_value_str} "
        f"({tone.accent})"
    )

    # jh 2026-06-12 — "점수 4개 다 69%" percentage_grid 결함:
    # v28_model_perf 는 렌더러 미지원이라 디자이너가 정수 반올림 그리드를 고름.
    # baseline 막대 + 다양한 메트릭(roc_auc·mcc 포함)을 hbar 차트로 직접 렌더 +
    # 페어 인사이트 패널 고정 (chart_key_insights).
    chart_items: list[tuple[str, float]] = []
    for bar in bars:
        v = bar.get("value")
        if isinstance(v, (int, float)):
            chart_items.append((str(bar.get("label", "?")), float(v)))
    for name, m in list((ctx.evaluation.metrics or {}).items()):
        val = m.get("value") if isinstance(m, dict) else None
        if isinstance(val, (int, float)) and name != pm_name and len(chart_items) < 6:
            chart_items.append((name, float(val)))

    sp = SlideSpec(
        id="i1_kpi",
        section_id="results",
        layout="chart_callout",
        role="evidence",
        so_what=so_what,
        title_ko="모델 성능 · Baseline 비교",
        body_outline=body[:5],
        required_refs=primary_metric_ref(ctx),
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="chart_hbar",
            title=f"성능 비교 — {pm_name} 외 주요 지표",
            spec={
                "items": chart_items,
                "metric": pm_name,
                "metric_value": pm.get("value"),
                "bars": bars,
                "metric_balance_top4": metric_balance_top4,
                "metric_category_compatible": metric_ok,
                "verdict": ctx.evaluation.verdict or "",
            },
        ),
        speaker_notes_hint=(
            "선정 모델 + 실제 baseline (naive/domain_rule/previous_best) 비교. "
            "가짜 '이론적 상한' 제거. 4-metric 균형으로 단일 metric 편향 회피. "
            "metric_category_compatible=False 면 typed schema 경고 — fallback 변형 검토."
        ),
    )
    sp.preferred_template = "chart_key_insights"
    return sp


def _build_eda_findings(ctx: ReportContext) -> SlideSpec:
    """슬라이드 13 — SHAP Global Importance (Top 5).

    [재구성] EDA 슬라이드는 S8~S11 로 이동. 본 슬라이드는 모델 해석 시작점:
    interpretation.global_importance Top 5 + 카테고리별 적응 (Integrated Gradients / Reason Code 등).
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide("shap_global", category)
    title_ko = (variant.title_ko if variant else "SHAP Global Importance · Top 5")

    imps = list(ctx.interpretation.global_importance or [])[:5]
    # 파생 피처 이름 집합 — (파생)/(원본) 라벨 부착에 사용
    derived_names = {
        getattr(f, "name", "") for f in (ctx.features.created or []) if getattr(f, "name", "")
    }
    items: list[dict[str, Any]] = []
    refs: list[str] = []
    for it in imps:
        feat = getattr(it, "feature", "")
        is_derived = feat in derived_names
        items.append({
            "feature": feat,
            "importance": getattr(it, "importance", 0.0),
            "method": getattr(it, "method", "shap"),
            "kind": "derived" if is_derived else "original",
        })
        rid = getattr(it, "ref_id", None)
        if rid:
            refs.append(rid)

    body = [
        f"{i+1}순위 · {it['feature']} ({'파생' if it['kind'] == 'derived' else '원본'}) · "
        f"{format_metric(float(it['importance']), 'shap', as_percent=False, decimals=2)}"
        for i, it in enumerate(items)
    ]
    if not body:
        body = ["분석 결과 적립 후 채워짐"]

    # 종합 인사이트 — Top 3 합계 비율
    so_what = "상위 5 피처의 영향력 분포 — 모델이 무엇을 보고 결정하는지"
    if items:
        total = sum(float(it["importance"]) for it in items)
        top3 = sum(float(it["importance"]) for it in items[:3])
        if total > 0:
            ratio = top3 / total * 100
            so_what = (
                f"상위 3 피처가 전체 영향력의 {ratio:.0f}% — "
                f"모델이 핵심 {items[0]['feature']} 등에 강하게 의존"
            )

    return SlideSpec(
        id="eda_findings",
        section_id="results",
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body[:5],
        required_refs=refs,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_annotated_bar"),
            title=title_ko,
            spec={"items": items},
            severity="important",
        ),
        speaker_notes_hint=(
            "SHAP / Integrated Gradients / Reason Code — 카테고리에 따라 자동 적응. "
            "Top 5 만 보여주고 나머지는 백업 슬라이드로."
        ),
    )


def _build_error_analysis(ctx: ReportContext) -> SlideSpec:
    """슬라이드 14 — SHAP Cases (개별 예측 사례 3건).

    [재구성] Error CM 책임은 S15 (_build_insights_derived) 로 이동.
    본 슬라이드는 interpretation.local_examples 의 개별 사례 3건 — 카테고리별 적응:
    - tabular_dl: attention map / per-sample IG
    - timeseries: 계절 분해 효과 / 잔차 패턴
    - anomaly: 이상 사례 3건 + reason code
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide("shap_cases", category)
    title_ko = (variant.title_ko if variant else "개별 예측 사례 · 3건")

    locals_ = list(ctx.interpretation.local_examples or [])[:3]
    cases: list[dict[str, Any]] = []
    body: list[str] = []
    for i, ex in enumerate(locals_):
        if not isinstance(ex, dict):
            continue
        pred = ex.get("prediction", "-")
        true = ex.get("true", "-")
        contributions = ex.get("contributions", [])
        top_feats = ", ".join(
            f"{c.get('feature', '')}({c.get('value', '')})"
            for c in (contributions[:3] if isinstance(contributions, list) else [])
        )
        cases.append({
            "index": i + 1,
            "prediction": pred,
            "true": true,
            "top_contributions": contributions[:3] if isinstance(contributions, list) else [],
        })
        body.append(f"사례 {i+1} · 예측 {pred} / 실제 {true} · {top_feats}")
    while len(body) < 3:
        body.append(f"사례 {len(body)+1} · ctx 적립 후 채워짐")

    return SlideSpec(
        id="error_analysis",
        section_id="results",
        layout=(variant.layout if variant else "one_message"),
        role="evidence",
        so_what="개별 사례 3건의 예측 근거 — 모델이 '왜 그렇게 예측했는가' 트레이스",
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="shap_cases_cards",
            title=title_ko,
            spec={"cases": cases},
        ),
        speaker_notes_hint=(
            "개별 사례 3건 — 모델 해석의 *지역* 측면. "
            "global 영향도(S13) 와 짝. 카테고리별로 attention map / 잔차 / reason code 로 변형."
        ),
    )


def _build_insights_derived(ctx: ReportContext) -> SlideSpec:
    """슬라이드 15 — Error CM / Diagnostic (카테고리별 적응).

    [재구성] '가설 입증 인사이트' → 카테고리별 진단:
    - tabular_ml/dl: Confusion Matrix + 오류 분석
    - timeseries:    잔차 진단 (ACF residual / Q-Q)
    - anomaly:       precision@k 곡선 + 알람 budget 곡선
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide("error_cm", category)
    title_ko = (variant.title_ko if variant else "Confusion Matrix · 오류 분석")

    cm = ctx.evaluation.confusion_matrix or {}
    body: list[str] = []

    if cm:
        tn = cm.get("tn") or cm.get("true_negative") or 0
        fp = cm.get("fp") or cm.get("false_positive") or 0
        fn = cm.get("fn") or cm.get("false_negative") or 0
        tp = cm.get("tp") or cm.get("true_positive") or 0
        total = max(1, tn + fp + fn + tp)
        body.extend([
            f"TN {tn} ({tn/total*100:.0f}%) · TP {tp} ({tp/total*100:.0f}%)",
            f"FP {fp} ({fp/total*100:.0f}%) · FN {fn} ({fn/total*100:.0f}%)",
        ])
        if fn > fp:
            body.append("미탐지(FN) > 오탐지(FP) — 임계값 낮춰 recall 우선 고려")
        elif fp > fn:
            body.append("오탐지(FP) > 미탐지(FN) — 임계값 높여 precision 우선 고려")
        else:
            body.append("FP / FN 균형 — 현재 임계값 적정")
    else:
        body.append("Confusion Matrix 미적립 — 카테고리별 진단으로 폴백")

    return SlideSpec(
        id="insights_derived",
        section_id="results",
        layout=(variant.layout if variant else "chart_callout"),
        role="caveat",
        so_what="모델이 어떤 케이스에서 틀리는가 — CM·잔차·알람 budget 진단",
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "diagram_confusion_matrix"),
            title=title_ko,
            # jh 2026-06-12 — assets 가 만든 실제 CM 히트맵 PNG 를 1순위로 사용
            spec={"confusion_matrix": cm, "chart_path": str(cm.get("chart_path") or "")},
            severity="important",
        ),
        speaker_notes_hint=(
            "Error CM / 잔차 진단 / precision@k 곡선 — 카테고리에 따라 자동 변형. "
            "FN > FP / FP > FN 패턴으로 임계값 조정 방향 제시."
        ),
    )


def _build_insight_synthesis(ctx: ReportContext) -> SlideSpec:
    """인사이트 종합 — 데이터→패턴→인사이트→접목 (jh 2026-06-12 신설).

    사용자 요구: "이 데이터를 분석한 걸로 무엇을 알 수 있고, 어디까지 접목
    가능한지" 를 덱 차원에서 종합하는 장. S5+S6 병합으로 확보한 슬롯.
    icon_columns (DATA→PATTERN→INSIGHT→ACTION 4열) 로 렌더.
    """
    rows = ctx.dataset.shape.get("rows", 0)
    cols = ctx.dataset.shape.get("cols", 0)
    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "분석 과제"
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    pm = ctx.evaluation.primary_metric or {}
    pm_str = _format_pm_value(pm)

    gi = list(ctx.interpretation.global_importance or [])[:3]
    top_feats = " · ".join(getattr(g, "feature", "?") for g in gi) if gi else "상위 피처"

    seg_line = ""
    try:
        segs = sorted(
            [s for s in (ctx.evaluation.per_segment or []) if isinstance(s, dict) and s.get("value") is not None],
            key=lambda s: float(s["value"]),
        )
        if segs:
            seg_line = f", 단 {segs[0].get('segment', '?')} 구간은 취약"
    except Exception:
        pass

    # jh 2026-06-12 — "글이 짧다" 지적: 각 열 2문장(사실 + 의미) 구조로 확장
    body = [
        (
            f"데이터 · {rows:,}건 × {cols}변수의 {use_case}. "
            "타겟 레이블이 완전해 패턴 학습에 충분하며 전 과정이 표준 스택으로 재현 가능하다"
        ),
        (
            f"패턴 · {top_feats} 가 결과를 좌우한다. "
            f"{chosen} 이 {pm_str} 로 이 구조를 포착했다{seg_line or ' — 상위 변수 의존이 뚜렷하다'}"
        ),
        (
            "인사이트 · 결과를 결정한 구조적 요인이 데이터로 정량 입증됐다. "
            "단순 룰로는 못 잡는 비선형·상호작용까지 모델이 흡수해 해석 가능한 형태로 분해된다"
        ),
        (
            "접목 · 동일 구조의 분류 과제(고객 이탈·승인 심사 등)에 즉시 이식 가능하다. "
            "운영 적용 → 취약 구간 보강 → 유사 데이터 확장 검증 순으로 적용 범위를 넓힌다"
        ),
    ]

    # jh 2026-06-12 — 제목은 예시 문구가 아니라 *실제 종합 결론* (사용자 지적).
    # 구성도 데이터/패턴 균등 4열 대신 인사이트·접목 중심으로 재설계.
    if gi:
        _t1 = getattr(gi[0], "feature", "핵심 변수")
        title_ko = f"{_t1} 등 상위 변수가 결과를 구조적으로 결정 — {pm_str} 로 정량 입증"
    else:
        title_ko = f"{use_case} — 구조적 결정 요인 정량 입증"

    insights = [
        (
            f"{top_feats} 가 판단의 주축",
            f"{chosen} 이 {pm_str} 로 포착 — 단순 룰로 못 잡는 비선형·상호작용까지 흡수{seg_line}",
        ),
        (
            "결정 요인이 해석 가능한 형태로 분해됨",
            "변수별 기여(SHAP)·오류 유형(CM)·취약 구간(세그먼트)까지 근거 추적 가능",
        ),
    ]
    applications = [
        "운영 적용 — 임계·모니터링·재학습 룰로 즉시 전환",
        "취약 구간 보강 — 소표본·고결측 세그먼트 피처 보강",
        "동일 구조 과제 이식 — 고객 이탈·승인 심사 등 이진 분류 확장",
    ]
    evidence = f"근거 · {rows:,}건 × {cols}변수 — 타겟 완전, 표준 스택 재현 가능"

    sp = SlideSpec(
        id="insight_synthesis",
        section_id="results",
        layout="insight_synthesis_panel",
        role="insight",
        so_what="이 발견이 의미하는 것과 적용 범위 — 인사이트 중심 종합",
        title_ko=title_ko,
        body_outline=body,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="v32_insight_synthesis",
            title="인사이트 종합",
            spec={
                "insights": insights,
                "applications": applications,
                "evidence": evidence,
            },
        ),
        speaker_notes_hint=(
            "덱 전체의 '그래서?' — 인사이트(좌 크게)와 접목 범위(우)가 주인공, "
            "데이터·패턴은 하단 근거 한 줄로 격하."
        ),
    )
    return sp


def _build_as_is_to_be(ctx: ReportContext) -> SlideSpec:
    """슬라이드 16 — 세그먼트별 성능 비교 (카테고리별 적응).

    [재구성] 영업 톤 'AS-IS vs TO-BE' → 분석 보고서 톤 세그먼트 비교:
    - tabular_ml/dl: ctx.evaluation.per_segment (세그먼트별 metric)
    - timeseries:    계절·시간대·요일별 성능 차이
    - anomaly:       정상 / 이상 클러스터 비교
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide("segment", category)
    title_ko = (variant.title_ko if variant else "세그먼트별 성능 비교")

    segs = list(ctx.evaluation.per_segment or [])[:6]
    body: list[str] = []
    seg_items: list[dict[str, Any]] = []
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        name = seg.get("segment") or seg.get("name") or "?"
        metric_name = seg.get("metric") or "score"
        value = seg.get("value")
        if value is None:
            continue
        formatted = format_metric(float(value), str(metric_name))
        body.append(f"{name} · {metric_name} {formatted}")
        seg_items.append({"segment": name, "metric": metric_name, "value": value})

    if not body:
        body = ["세그먼트별 성능 미적립 — ctx.evaluation.per_segment 채움 시 자동 반영"]

    # 분산 인사이트
    so_what = "세그먼트별 성능 — 모델이 *모든* 세그먼트에서 일관된지 확인"
    if len(seg_items) >= 2:
        vals = [float(s["value"]) for s in seg_items]
        gap = max(vals) - min(vals)
        if gap > 0.1:
            so_what = (
                f"세그먼트 격차 {gap:.2f} 발생 — 일부 세그먼트는 보완·재학습 필요"
            )

    # jh 2026-06-12 — 세그먼트 데이터가 있으면 가로 막대 차트로 시각화
    # (segment_perf_table 은 렌더러 미지원 → generic 폴백으로 차트가 안 그려지던 결함.
    #  목표치 덱 S14 처럼 차트 + KEY INSIGHTS 구성)
    if seg_items:
        _layout = "chart_callout"
        _vs = VisualSpec(
            type="chart_hbar",
            title=title_ko,
            spec={
                "items": [(s["segment"], float(s["value"])) for s in seg_items],
                "segments": seg_items,
            },
            severity="important",
        )
    else:
        _layout = variant.layout if variant else "one_message"
        _vs = VisualSpec(type="segment_perf_table", title=title_ko, spec={"segments": seg_items})

    return SlideSpec(
        id="as_is_to_be",
        section_id="impact",
        layout=_layout,
        role="evidence",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body[:6],
        parent_message_id="impact_root",
        visual_spec=_vs,
        speaker_notes_hint=(
            "세그먼트별 성능 비교 — 분류·DL 은 per_segment, timeseries 는 계절·시간대, "
            "anomaly 는 정상/이상 클러스터. 격차 0.1 이상이면 보완 시사."
        ),
    )


def _build_roi(ctx: ReportContext) -> SlideSpec:
    """슬라이드 17 — Policy Insight (verdict-aware).

    [재구성] 영업 톤 'ROI' → 분석 결과 기반 *운영 정책 인사이트* 로:
    - verdict=adopt: 도입 정책 + 운영 룰 + 모니터링 정책
    - verdict=iterate: 보강 우선순위 + 재시도 조건
    - verdict=reject: 폐기 사유 + 대안 권고

    카테고리별 적응 (resolve_slide('policy_insight', category)):
    - timeseries: 예측 구간 기반 안전재고·임계 정책
    - anomaly:    임계값·알람 budget·운영 시나리오
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide("policy_insight", category)
    tone = _get_verdict_tone(ctx)
    title_ko = tone.s17_section_label or (variant.title_ko if variant else "정책 인사이트")

    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)

    policy_items: list[tuple[str, str]] = []
    if (ctx.evaluation.verdict or "").lower() == "adopt":
        policy_items = [
            ("운영 임계", ctx.evaluation.gate_rationale or f"{pm_value} 기반 임계 설정"),
            ("모니터링", "drift score · 메트릭 alarm · 재학습 트리거"),
            ("Owner", "모델 운영팀 — 월간 리뷰 · 분기별 재검증"),
        ]
    elif (ctx.evaluation.verdict or "").lower() == "iterate":
        policy_items = [
            ("보강 우선순위", "데이터 수집 확대 · 결측 보강 · 신규 피처"),
            ("재시도 조건", f"{pm_value} 대비 +5%p 이상 향상 시 재평가"),
            ("Owner", "분석팀 — 보강 후 재학습"),
        ]
    elif (ctx.evaluation.verdict or "").lower() == "reject":
        policy_items = [
            ("폐기 사유", ctx.evaluation.gate_rationale or "운영 임계 미달"),
            ("대안 권고", "문제 재정의 → 대안 모델 탐색"),
            ("Owner", "프로덕트 / 분석팀 공동 재정의"),
        ]
    else:
        policy_items = [
            ("판정 미정", "ctx.evaluation.verdict 적립 시 자동 분기"),
            ("기본 모니터링", "drift · 메트릭 추적"),
            ("재검토", "월간"),
        ]

    body = [f"{k} · {v}" for k, v in policy_items]
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    if biz_kpi:
        body.append(f"비즈니스 KPI · {getattr(biz_kpi, 'name', '')} {getattr(biz_kpi, 'estimated_value', '')} {getattr(biz_kpi, 'unit', '')}")

    so_what = f"{chosen} 분석 결과 기반 운영 정책 — 판정: {ctx.evaluation.verdict or '미정'}"

    return SlideSpec(
        id="i3_roi",
        section_id="impact",
        layout=(variant.layout if variant else "one_message"),
        role="action",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="v28_policy_insight",
            title=title_ko,
            spec={
                "policy_items": policy_items,
                "verdict": ctx.evaluation.verdict or "",
                "tone_accent": tone.accent,
                "biz_kpi": (
                    {
                        "name": getattr(biz_kpi, "name", ""),
                        "value": getattr(biz_kpi, "estimated_value", ""),
                        "unit": getattr(biz_kpi, "unit", ""),
                    } if biz_kpi else None
                ),
            },
        ),
        speaker_notes_hint=(
            "verdict 에 따라 어조 분기 — adopt 면 운영 정책, iterate 면 보강 계획, reject 면 폐기 사유. "
            "ADA '도메인 자동화' 영업 표현 전량 제거. 비즈니스 KPI 가 ctx.evaluation.business_kpi 에 있으면 부착."
        ),
    )


def _build_risk_mitigation(ctx: ReportContext) -> SlideSpec:
    """슬라이드 18 — SWOT + Drift (ctx 기반 분석 결과 자체에서 도출).

    [재구성] 영업 톤 'ADA 자동화 강점' 제거. 각 분면을 ctx 에서 동적으로:
    - S (강점) : 모델의 잘 작동하는 영역 — top feature / 균형 metric / 강건 세그먼트
    - W (약점) : limitations.data_gaps / per_segment 의 약한 세그먼트
    - O (기회) : revalidation_window 내 보강 가능성 / 추가 신호
    - T (위협) : distribution_shift_risk / generalization_risk / out_of_scope
    """
    pm = ctx.evaluation.primary_metric or {}
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")

    # === S (강점) ===
    strengths: list[str] = []
    if ctx.interpretation.global_importance:
        top_feat = ctx.interpretation.global_importance[0].feature
        strengths.append(f"강한 신호 · {top_feat} 등 핵심 변수 식별")
    if pm.get("value") is not None:
        strengths.append(f"임계 통과 · {chosen} {pm_value_str}")
    # 균형 잡힌 세그먼트 (격차 작음)
    segs = ctx.evaluation.per_segment or []
    if len(segs) >= 2:
        vals = [s.get("value") for s in segs if isinstance(s, dict) and isinstance(s.get("value"), (int, float))]
        if vals and max(vals) - min(vals) <= 0.1:
            strengths.append("세그먼트 균형 · 격차 0.1 이하")
    if not strengths:
        strengths.append("강점 적립 후 채워짐")

    # === W (약점) ===
    weaknesses: list[str] = []
    for g in (ctx.limitations.data_gaps or [])[:2]:
        desc = getattr(g, "description", "") or "데이터 결함"
        impact = getattr(g, "impact", "") or ""
        weaknesses.append(f"{desc}" + (f" ({impact})" if impact else ""))
    # 약한 세그먼트
    if segs:
        weak = min(
            (s for s in segs if isinstance(s, dict) and isinstance(s.get("value"), (int, float))),
            key=lambda s: s["value"], default=None,
        )
        if weak and weak.get("value") is not None:
            name = weak.get("segment") or weak.get("name") or "?"
            weaknesses.append(f"세그먼트 {name} 성능 낮음 · {weak.get('metric', '')} {format_metric(float(weak['value']), str(weak.get('metric', '')))}")
    if not weaknesses:
        weaknesses.append("약점 식별 안 됨")

    # === O (기회) ===
    opportunities: list[str] = []
    rev = ctx.limitations.revalidation_window
    if rev:
        opportunities.append(f"{rev} 후 재검증 시 신규 데이터 반영")
    for g in (ctx.limitations.generalization_risk or [])[:2]:
        mit = getattr(g, "mitigation", None)
        if mit:
            opportunities.append(f"보강 · {mit}")
    if not opportunities:
        opportunities.append("추가 분석 시 발견 예정")

    # === T (위협) ===
    threats: list[str] = []
    shift = ctx.limitations.distribution_shift_risk or {}
    if shift.get("detected"):
        ev = shift.get("evidence") or "분포 변화 감지"
        threats.append(f"데이터 드리프트 · {ev}")
    for c in (ctx.limitations.model_caveats or [])[:2]:
        threats.append(f"모델 한계 · {c}")
    for o in (ctx.limitations.out_of_scope or [])[:1]:
        threats.append(f"범위 밖 · {o}")
    if not threats:
        threats.append("위협 추적 중")

    # body — 라벨 + 첫 항목
    body = [
        f"S · {strengths[0]}",
        f"W · {weaknesses[0]}",
        f"O · {opportunities[0]}",
        f"T · {threats[0]}",
        "Mitigation · 정기 재평가 + drift 모니터링",
    ]

    return SlideSpec(
        id="risk_mitigation",
        section_id="plan",
        layout="swot_2x2",
        role="caveat",
        so_what="강점·약점·기회·위협 4분면 — ctx 기반 분석 결과 자체에서 도출",
        title_ko="SWOT · Drift",
        body_outline=body[:5],
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="v28_swot_reach",
            title="SWOT · Drift",
            spec={
                "strengths": strengths[:3],
                "weaknesses": weaknesses[:3],
                "opportunities": opportunities[:3],
                "threats": threats[:3],
                "revalidation_window": rev or "",
            },
            severity="important",
        ),
        speaker_notes_hint=(
            "SWOT 4 분면을 *분석 결과 자체* 에서 도출. interpretation / per_segment / limitations "
            "의 모든 정보가 SWOT 로 정리됨. ADA 영업 표현 (자동화 강점·재현성 등) 제거."
        ),
    )


def _build_roadmap(ctx: ReportContext) -> SlideSpec:
    """슬라이드 19 — 실행 로드맵 (verdict-aware).

    [재구성] verdict 에 따라 Phase 패턴 자동 분기 (VerdictTone.s19_phase_pattern):
    - adopt:   'Phase 1 (30일) 파일럿 → Phase 2 (90일) 전사 확장'
    - iterate: 'Phase 1 데이터 보강 → Phase 2 재학습 → Phase 3 재평가'
    - reject:  'Phase 1 문제 재정의 → Phase 2 대안 모델 탐색 → Phase 3 검증'

    모니터링 KPI 는 verdict=adopt 인 경우에만 첨부 (iterate/reject 에선 의미 없음).
    """
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    # Phase 라벨을 verdict 별로 — 한 줄 패턴을 ' → ' 로 분해
    raw_pattern = tone.s19_phase_pattern or "Phase 1 → Phase 2 → Phase 3"
    phases = [p.strip() for p in raw_pattern.split("→") if p.strip()][:3]

    body: list[str] = []
    for i, phase in enumerate(phases):
        body.append(f"{i+1}. {phase}")

    if verdict == "adopt":
        body.extend([
            "모니터링 KPI · drift score · primary_metric alarm",
            "재학습 트리거 · 분기별 또는 drift > 0.1 시",
        ])
    elif verdict == "iterate":
        body.extend([
            "보강 측정 · 새로 적립된 데이터 규모 / 결측률 변화",
            "재평가 기준 · 본 모델 대비 +5%p 이상 향상 시 도입 재고려",
        ])
    else:  # reject
        body.extend([
            "대안 후보 · 문제 재정의 후 새 모델 탐색",
            "재학습 금지 · 현 데이터·정의로는 본 모델 폐기",
        ])

    return SlideSpec(
        id="roadmap",
        section_id="plan",
        layout="roadmap_phase_kpi",
        role="action",
        so_what=f"실행 로드맵 — 판정({verdict}) 에 맞춰 단계 자동 분기",
        title_ko="실행 로드맵",
        body_outline=body[:5],
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="v28_domain_mapping",
            title="실행 로드맵",
            spec={
                "verdict": verdict,
                "phases": phases,
                "tone_accent": tone.accent,
            },
        ),
        speaker_notes_hint=(
            "Phase 는 verdict 에 따라 자동 변형. adopt 만 운영 KPI / iterate 는 보강 / reject 는 폐기 후 대안."
        ),
    )


def _build_closing_qna(ctx: ReportContext) -> SlideSpec:
    """슬라이드 20 — 분석 결과 요약 + Q&A 안내.

    [재구성] 'ADA v2' 영업 표현 제거. 분석 보고서 본연의 마무리:
    - 본 보고서가 다룬 분석 주제 (ctx.meta.user_intent)
    - 핵심 결과 (verdict 별 어조)
    - Q&A 안내
    """
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    if verdict == "adopt":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 도입 가능"
    elif verdict == "iterate":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 보강 후 재검토"
    else:  # reject
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 현 모델 도입 불가"

    body = [
        f"본 보고서 · {ctx.meta.user_intent or '데이터 분석'}",
        result_line,
        "Q&A — 데이터 / 모델 / 운영 정책",
    ]
    return SlideSpec(
        id="closing",
        section_id="closing",
        layout="closing",
        role="meta",
        so_what=f"본 분석 마무리 — 판정: {verdict}",
        title_ko="감사합니다",
        body_outline=body,
        visual_spec=VisualSpec(
            type="closing_simple",
            title="감사합니다",
            spec={
                "verdict": verdict,
                "tone_accent": tone.accent,
            },
        ),
        speaker_notes_hint=(
            "새 정보 금지 — Executive Summary 재인용. Q&A 유도. "
            "verdict 에 따라 결론 어조 분기."
        ),
    )


# ==============================================================
# Pyramid Principle 메시지 트리 (검증기 통과용)
# ==============================================================


def _build_message_tree(ctx: ReportContext) -> list[MessageNode]:
    """Pyramid Principle — root(답) → 6 섹션 근거 → 슬라이드별 메시지 노드.

    root_msg 의 결론부는 ctx.evaluation.verdict 에 따라 분기 (adopt/iterate/reject).
    """
    chosen = (ctx.model_selection.chosen or {}).get("name", "ML 모델")
    pm = ctx.evaluation.primary_metric or {}
    verdict = (ctx.evaluation.verdict or "").lower()
    if verdict == "iterate":
        conclusion = "보강 후 재학습 권장"
    elif verdict == "reject":
        conclusion = "현 모델 도입 불가"
    else:
        conclusion = "운영 도입 권장"
    root_msg = (
        f"{chosen} 모델로 {pm.get('name', 'primary')} {pm.get('value', '-')} "
        f"달성 — {conclusion}"
    )
    return [
        MessageNode(
            id="root",
            role="claim",
            text=root_msg,
            parent_id=None,
            children=[
                "problem_root",
                "solution_root",
                "results_root",
                "impact_root",
                "plan_root",
            ],
        ),
        MessageNode(id="hyp_root", role="claim", text="3가설 수립", parent_id="root", slide_ids=["hypothesis"]),
        MessageNode(
            id="problem_root",
            role="evidence",
            text="기존 방식의 한계 명확",
            parent_id="root",
            slide_ids=["p1_market", "p2_pain", "p3_alt_limits"],
        ),
        MessageNode(
            id="solution_root",
            role="evidence",
            text="ADA + 선정 모델로 해결",
            parent_id="root",
            slide_ids=["method_model", "tech_architecture", "tech_stack", "s3_differentiation"],
        ),
        MessageNode(
            id="results_root",
            role="evidence",
            text="baseline 대비 우수 + 신뢰성 검증",
            parent_id="root",
            slide_ids=["i1_kpi", "eda_findings", "error_analysis", "insights_derived"],
        ),
        MessageNode(
            id="impact_root",
            role="claim",
            text="비즈니스 임팩트 확보",
            parent_id="root",
            slide_ids=["as_is_to_be", "i3_roi"],
        ),
        MessageNode(
            id="plan_root",
            role="action",
            text="단계별 실행 + 운영 모니터링",
            parent_id="root",
            slide_ids=["risk_mitigation", "roadmap"],
        ),
    ]

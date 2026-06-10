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
from outputs.architect.substitution_manifest import (
    TechStackItem,
    VerdictTone,
    check_required_ctx_fields,
    is_metric_compatible,
    resolve_slide,
    resolve_tech_stack,
    resolve_verdict_tone,
)
from outputs.context.schema import ReportContext
from outputs.style.text_budget import (
    TextBudget,
    char_budget,
    fit_text,
    format_delta,
    format_metric,
)

SKELETON_NAME = "ML Pitch"


# ==============================================================
# 공통 헬퍼 — verdict / 자동 도메인 라벨
# 본 헬퍼는 ml_pitch 외의 skeleton (dl/ts/anomaly) 에서도 동일 패턴으로 사용 예정.
# ==============================================================


def _get_verdict_tone(ctx: ReportContext) -> VerdictTone:
    """ctx.evaluation.verdict → VerdictTone (미정/미지원 시 adopt 폴백)."""
    v = getattr(ctx.evaluation, "verdict", "") or ""
    return resolve_verdict_tone(v)


def _is_auto_domain(ctx: ReportContext) -> bool:
    """도메인 해석이 *자동 추론* 인지 여부 — True 면 [auto-inferred] 라벨 부착."""
    src = getattr(ctx.domain, "domain_source", "auto") or "auto"
    return src.strip().lower() == "auto"


def _auto_label(text: str, ctx: ReportContext) -> str:
    """자동 추론 도메인 텍스트에 ``[auto-inferred]`` 마커 부착 (인용 면제 표시).

    이미 마커가 있으면 중복 부착하지 않음. 사용자 입력 도메인이면 그대로.
    """
    if not text:
        return text
    if not _is_auto_domain(ctx):
        return text
    marker = "[auto-inferred]"
    if marker in text:
        return text
    return f"{text} {marker}"


# ==============================================================
# 도메인 프로필 — 슬라이드 5 (시장·맥락) · 17 (ROI) 텍스트 적응용
# HJ 2026-06-08: ML 카테고리 5 도메인 (churn / credit / propensity / fraud / generic)
# ==============================================================

_DOMAIN_PROFILES: dict[str, dict[str, Any]] = {
    "churn": {
        "label_ko": "고객 이탈 예측",
        "market_context": "구독·통신·SaaS·금융 고객 행동 데이터 (사용·결제·VOC)",
        "roi": {
            "primary_kpi": "월간 이탈률 감소",
            "primary_unit": "%p",
            "secondary": [
                "이탈 방지 캠페인 ROI — 정확 타겟팅으로 +24%",
                "재가입 비용 절감 — 이탈 후 재유치 대비 1/5 비용",
                "고객 LTV 연장 — 평균 잔존 +N 개월",
            ],
            "fp_cost": "5,000원 (불필요 리텐션 캠페인)",
            "fn_cost": "180,000원/건 (이탈 고객 LTV 손실)",
        },
    },
    "credit_scoring": {
        "label_ko": "신용 평가·스코어링",
        "market_context": "금융·핀테크 대출·여신 신용 데이터 (소득·자산·연체)",
        "roi": {
            "primary_kpi": "부도율 감소 + 승인율 향상",
            "primary_unit": "%p",
            "secondary": [
                "부도 손실 절감 — 정확 예측으로 N%p 감소",
                "승인 자동화 — 분석가 검토 부하 -65%",
                "Compliance — 모델 설명 가능성 (SHAP) 으로 규제 대응",
            ],
            "fp_cost": "이자 수익 손실 (정상 고객 거절)",
            "fn_cost": "부도 손실 (대출 원금 평균 N백만원)",
        },
    },
    "propensity": {
        "label_ko": "구매 성향·전환 예측",
        "market_context": "리테일·이커머스 행동 데이터 (방문·장바구니·이전 구매)",
        "roi": {
            "primary_kpi": "캠페인 전환율 향상",
            "primary_unit": "%p",
            "secondary": [
                "마케팅 ROAS 향상 — 고성향 고객 타겟팅",
                "할인 쿠폰 비용 절감 — Uplift 모델로 증분 효과만 측정",
                "재방문 유도 — Top 5% 우선 채널 노출",
            ],
            "fp_cost": "쿠폰 비용 (저성향 고객 노출)",
            "fn_cost": "기회 손실 (고성향 고객 누락)",
        },
    },
    "fraud_tabular": {
        "label_ko": "거래 사기 (정형 데이터)",
        "market_context": "금융·결제 거래 데이터 (시간·금액·지역·디바이스)",
        "roi": {
            "primary_kpi": "사기 손실 절감",
            "primary_unit": "원/년",
            "secondary": [
                "False alarm 감소 — 정상 거래 차단 ↓, 고객 경험 ↑",
                "분석가 검토 부하 감소 — SHAP Root Cause 자동",
                "신규 사기 패턴 조기 감지 — 정기 재학습",
            ],
            "fp_cost": "2,000원 (불필요 차단·CS 응대)",
            "fn_cost": "280,000원/건 (사기 평균 손실)",
        },
    },
    "generic": {
        "label_ko": "일반 정형 ML 분석",
        "market_context": "정형 데이터 기반 분류·회귀 과제",
        "roi": {
            "primary_kpi": "비즈니스 KPI 개선",
            "primary_unit": "%p",
            "secondary": [
                "운영 효율 향상",
                "분석 자동화로 시간 절감",
                "재현 가능한 의사결정 지원",
            ],
            "fp_cost": "분석 비용",
            "fn_cost": "기회 손실",
        },
    },
}


def _infer_ml_domain(ctx: ReportContext) -> str:
    """ctx 의 도메인·use_case·intent 로부터 ML 도메인 추론."""
    industry = (getattr(ctx.domain, "inferred_industry", "") or "").lower()
    use_case = (getattr(ctx.domain, "inferred_use_case", "") or "").lower()
    intent = (ctx.meta.user_intent or "").lower()
    text = f"{industry} {use_case} {intent}"

    domain_keywords: list[tuple[str, tuple[str, ...]]] = [
        # 구체적인 도메인부터 — 첫 매치가 이김
        ("fraud_tabular", ("사기", "fraud", "이상거래", "money laundering")),
        ("credit_scoring", ("신용", "credit", "여신", "대출", "부도", "스코어링", "scoring")),
        ("churn", ("이탈", "churn", "해지", "retention", "구독", "subscriber")),
        ("propensity", ("구매", "전환", "propensity", "uplift", "캠페인", "마케팅", "marketing")),
    ]
    for domain, keywords in domain_keywords:
        if any(kw in text for kw in keywords):
            return domain
    return "generic"


def _get_domain_profile(ctx: ReportContext) -> dict[str, Any]:
    """현재 ctx 의 도메인 프로필."""
    domain = _infer_ml_domain(ctx)
    return _DOMAIN_PROFILES.get(domain, _DOMAIN_PROFILES["generic"])


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
            _build_market_context(ctx),  # 5. 시장·맥락
            _build_pain_points(ctx),  # 6. 페인 포인트
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


def _format_pm_value(pm: dict[str, Any]) -> str:
    """primary_metric 값을 format_metric 으로 안전 포매팅."""
    name = pm.get("name", "primary")
    raw = pm.get("value")
    if raw is None:
        return "-"
    try:
        return format_metric(float(raw), str(name))
    except (TypeError, ValueError):
        return str(raw)


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
    body = [
        f"H1 · 핵심 변수 영향 · Top 피처가 {pm.get('name', '지표')} 에 강한 신호 제공",
        f"H2 · 모델 적합성 · {chosen} 가 baseline 대비 우수 성과",
        "H3 · 운영 안정성 · 분포 변화 시에도 임계 성능 유지 가능",
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


def _summarize_dtypes(ctx: ReportContext) -> str:
    """dataset.dtypes 의 numeric/categorical/text 카운트 요약."""
    dtypes = ctx.dataset.dtypes or {}
    if not dtypes:
        return "타입 정보 없음"
    num_count = sum(1 for v in dtypes.values() if str(v).lower() in {"int", "int64", "float", "float64", "number", "numeric"})
    cat_count = sum(1 for v in dtypes.values() if str(v).lower() in {"object", "category", "categorical", "str", "string"})
    other = len(dtypes) - num_count - cat_count
    parts = []
    if num_count:
        parts.append(f"수치 {num_count}")
    if cat_count:
        parts.append(f"범주 {cat_count}")
    if other:
        parts.append(f"기타 {other}")
    return " · ".join(parts)


def _summarize_target(ctx: ReportContext) -> str:
    """dataset.detected_target 의 분포 요약.

    분류 — categorical_top[target] 의 클래스별 비율 (Top 3).
    회귀 — numeric_stats[target] 의 mean / std.
    """
    target = ctx.dataset.detected_target
    if not target:
        return "타겟 미감지"
    # 분류 — categorical_top 우선
    cat_top = (ctx.dataset.categorical_top or {}).get(target, [])
    if cat_top:
        # 각 항목: {"value": ..., "count": ...} 또는 (value, count) tuple 가정
        total = sum(_safe_count(it) for it in cat_top) or 1
        parts: list[str] = []
        for it in cat_top[:3]:
            val = _safe_value(it)
            cnt = _safe_count(it)
            parts.append(f"{val} {cnt/total*100:.1f}%")
        return " · ".join(parts) if parts else f"{target} (분포 미산출)"
    # 회귀 — numeric_stats
    num_stats = (ctx.dataset.numeric_stats or {}).get(target, {})
    if num_stats:
        mean = num_stats.get("mean")
        std = num_stats.get("std")
        if mean is not None and std is not None:
            return f"{target} 평균 {mean:.2f} ± {std:.2f}"
    return f"타겟 {target}"


def _safe_value(item: Any) -> str:
    """categorical_top 항목에서 value 안전 추출."""
    if isinstance(item, dict):
        return str(item.get("value", item.get("name", "?")))
    if isinstance(item, (list, tuple)) and len(item) >= 1:
        return str(item[0])
    return str(item)


def _safe_count(item: Any) -> int:
    """categorical_top 항목에서 count 안전 추출."""
    if isinstance(item, dict):
        try:
            return int(item.get("count", item.get("freq", 0)) or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        try:
            return int(item[1])
        except (TypeError, ValueError):
            return 0
    return 0


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

    # body_outline — legacy carrier 호환 (5 lines)
    body = [
        f"규모 · {overview_items[0][1]}",
        f"변수 타입 · {dtypes_summary}",
        f"타겟 분포 · {target_summary}",
        f"품질 이슈 1 · {quality_items[0][0]} ({quality_items[0][1]})",
        f"품질 이슈 2 · {quality_items[1][0]} ({quality_items[1][1]})",
    ]

    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "분석 과제"
    return SlideSpec(
        id="p1_market",
        section_id="problem",
        layout="data_overview_quality_combined",
        role="evidence",
        so_what=f"{rows:,} 행 × {cols} 열 데이터 — {use_case} 분석에 충분한 규모와 품질 확보",
        title_ko="데이터 개요 · 품질",
        body_outline=body,
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_data_combined",
            title="데이터 개요 · 품질",
            spec={
                "overview_items": overview_items,
                "quality_items": quality_items,
            },
        ),
        speaker_notes_hint=(
            "데이터 *규모/타입/타겟* 을 한눈에. 하단은 *발견한 품질 이슈* — "
            "이후 슬라이드에서 어떻게 처리했는지 (전처리·결측 보강) 의 도입부."
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


def _build_method_steps(ctx: ReportContext) -> list[dict[str, str]]:
    """분석 방법 흐름의 5 단계 — 좌측 미니 흐름도 입력.

    각 step: {label, kind} — kind 는 "preprocessing" / "feature" / "model" / "training" / "evaluation"
    """
    steps: list[dict[str, str]] = []
    pp_steps = list(ctx.preprocessing.applied_steps or [])
    if pp_steps:
        steps.append({"label": f"전처리 ({len(pp_steps)}단계)", "kind": "preprocessing"})
    feats = list(ctx.features.created or [])
    if feats:
        steps.append({"label": f"신규 피처 {len(feats)}개", "kind": "feature"})
    chosen_name = (ctx.model_selection.chosen or {}).get("name") or ""
    if chosen_name:
        steps.append({"label": f"모델 {chosen_name}", "kind": "model"})
    if ctx.training.runs:
        steps.append({"label": "학습 · 튜닝", "kind": "training"})
    if ctx.evaluation.primary_metric:
        steps.append({"label": "평가 · 검증", "kind": "evaluation"})
    # 폴백 — ctx 가 빈 경우 (이른 파이프라인 단계) 기본 5 단계
    if not steps:
        steps = [
            {"label": "1 · 전처리", "kind": "preprocessing"},
            {"label": "2 · 피처 엔지니어링", "kind": "feature"},
            {"label": "3 · 모델 선정", "kind": "model"},
            {"label": "4 · 학습", "kind": "training"},
            {"label": "5 · 평가", "kind": "evaluation"},
        ]
    return steps[:5]


def _build_method_whys(ctx: ReportContext) -> list[dict[str, str]]:
    """우측 WHY 카드 4개 — (header, what, why, result).

    header: "단계 N · {라벨}"
    what:   *선택 결과* (큰 글씨)
    why:    *왜 그렇게 했나* (rationale / justification)
    result: *정량 결과* (해당 단계의 결과)
    """
    cards: list[dict[str, str]] = []

    # ① 전처리 — 가장 큰 영향 step 1개
    for ps in (ctx.preprocessing.applied_steps or [])[:1]:
        op = getattr(ps, "op", "") or "전처리"
        scope = ", ".join(getattr(ps, "scope", []) or [])
        rationale = getattr(ps, "rationale", "") or ""
        before = getattr(ps, "before_stats", {}) or {}
        after = getattr(ps, "after_stats", {}) or {}
        what = f"{op}" + (f" · {scope}" if scope else "")
        result = ""
        # 결측률 / 표준편차 변화 추출 (best-effort)
        for key in ("missing_rate", "missing", "std", "mean"):
            if key in before and key in after:
                result = f"{key}: {before[key]} → {after[key]}"
                break
        if not result:
            result = "before / after 통계 적립 완료"
        cards.append({
            "header": f"단계 1 · {op}",
            "what": what,
            "why": rationale or "데이터 분포 보강 — 모델 학습 안정성 향상",
            "result": result,
        })

    # ② 피처 엔지니어링
    feats = list(ctx.features.created or [])
    if feats:
        top = feats[:3]
        names = " · ".join(getattr(f, "name", "") or "" for f in top)
        rationale = next(
            (getattr(f, "rationale", "") for f in top if getattr(f, "rationale", "")),
            "",
        )
        cards.append({
            "header": f"단계 2 · 신규 피처 {len(feats)}개",
            "what": names or f"피처 {len(feats)}개 추가",
            "why": rationale or "비선형·상호작용 신호 포착 — 단일 변수로 못 잡는 패턴",
            "result": f"최종 피처 수 {ctx.features.final_feature_count or len(feats)}",
        })

    # ③ 모델 선정
    chosen = ctx.model_selection.chosen or {}
    chosen_name = chosen.get("name") or ""
    if chosen_name:
        justification = chosen.get("justification") or ""
        candidates = ctx.model_selection.candidates or []
        result_lines: list[str] = []
        for c in candidates[:2]:
            c_name = getattr(c, "name", "")
            c_score = getattr(c, "score", None)
            if c_name and c_score is not None:
                result_lines.append(f"{c_name} {c_score:.3f}")
        result = " / ".join(result_lines) if result_lines else (
            f"후보 {len(candidates)}개 비교 후 선택"
        )
        cards.append({
            "header": "단계 3 · 모델 선정",
            "what": chosen_name,
            "why": justification or "후보 모델 비교 — 본 데이터 특성에 가장 적합",
            "result": result,
        })

    # ④ 검증 방식
    runs = ctx.training.runs or []
    baseline = ctx.model_selection.baselines.naive or {}
    pm = ctx.evaluation.primary_metric or {}
    if runs or pm or baseline:
        split = "80/20 hold-out + Baseline 직접 비교"
        if runs:
            hp = getattr(runs[0], "hyperparameters", {}) or {}
            split = str(hp.get("split", split))
        result = ""
        if baseline and pm:
            b_score = baseline.get("score")
            p_val = pm.get("value")
            if b_score is not None and p_val is not None:
                try:
                    delta = float(p_val) - float(b_score)
                    result = (
                        f"룰 {format_metric(float(b_score), pm.get('name', ''))} → "
                        f"모델 {format_metric(float(p_val), pm.get('name', ''))} "
                        f"({format_delta(delta * 100 if abs(delta) <= 1.5 else delta, unit='%p')})"
                    )
                except (TypeError, ValueError):
                    pass
        cards.append({
            "header": "단계 4 · 검증 방식",
            "what": split,
            "why": "모델의 *추가 가치* 정량화 — Baseline 직접 비교로 향상폭 측정",
            "result": result or "Baseline 비교 완료",
        })

    # 폴백 4개
    while len(cards) < 4:
        i = len(cards) + 1
        cards.append({
            "header": f"단계 {i} · 추가 분석",
            "what": "ctx 적립 후 채워짐",
            "why": "분석 결과 기록 진행 중",
            "result": "-",
        })
    return cards[:4]


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

    return SlideSpec(
        id="p3_alt_limits",
        section_id="limits",
        layout="method_flow_with_why",
        role="evidence",
        so_what=(
            f"5단계 분석 방법 — 각 단계의 *선택 이유* 와 *정량 결과* 를 함께 추적, "
            "재현 가능성 + 의사결정 트레이스 보존"
        ),
        title_ko="분석 방법",
        body_outline=body[:5],
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_method_flow",
            title="분석 방법 흐름 · WHY",
            spec={
                "steps": steps,
                "whys": whys,
            },
        ),
        speaker_notes_hint=(
            "좌측 흐름도로 *전체 단계* 인지, 우측 WHY 카드로 *각 선택의 근거* 설명. "
            "WHY 는 ctx 의 rationale·justification 필드에서 자동 추출 — 빈 필드면 폴백 문구."
        ),
    )


def _select_top_eda_charts(ctx: ReportContext, n: int = 3) -> list[Any]:
    """Top N EDAChart 선정 — severity → finding 길이 → 입력 순서."""
    charts = list(ctx.eda.charts or [])
    if not charts:
        return []
    sev_order = {"critical": 0, "important": 1, "info": 2}
    indexed = [(i, c) for i, c in enumerate(charts)]
    indexed.sort(key=lambda t: (
        sev_order.get(getattr(t[1], "severity", "info"), 2),
        -len(getattr(t[1], "finding", "") or ""),
        t[0],
    ))
    return [c for _, c in indexed[:n]]


def _eda_key_insights(chart: Any, ctx: ReportContext) -> list[str]:
    """EDAChart 의 callouts·numbers·finding 을 KEY INSIGHTS 5줄로 정리.

    포맷 '사실 → 그래서 알 수 있는 것' 페어 — callouts.text 에 \n 으로 페어
    들어있으면 그대로, 아니면 finding 을 마지막 인사이트로 부착.
    """
    insights: list[str] = []
    for callout in (getattr(chart, "callouts", None) or [])[:5]:
        if isinstance(callout, dict):
            text = callout.get("text", "") or ""
        else:
            text = str(callout)
        if text:
            insights.append(_auto_label(text, ctx))
    if not insights:
        for num in (getattr(chart, "numbers", None) or [])[:5]:
            if isinstance(num, dict):
                name = num.get("name", "")
                val = num.get("value", "")
                if name or val:
                    insights.append(f"{name} {val}")
    finding = getattr(chart, "finding", "") or ""
    if finding and finding not in insights:
        insights.append(_auto_label(finding, ctx))
    return insights[:5]


def _build_eda_slide_from_chart(
    chart: Any,
    slide_id: str,
    slide_index: int,
    ctx: ReportContext,
    role_key: str,
) -> SlideSpec:
    """단일 EDAChart → chart_callout SlideSpec.

    substitution_manifest.resolve_slide(role_key, category) 로 title 변형 적응.
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide(role_key, category)

    feature = getattr(chart, "x", None) or getattr(chart, "title_ko", "") or f"Feature {slide_index}"
    title_ko = (variant.title_ko if variant else None) or getattr(chart, "title_ko", "") or f"EDA · {feature}"
    finding = getattr(chart, "finding", "") or ""
    so_what = _auto_label(finding, ctx) if finding else f"{feature} 의 핵심 분포·패턴 발견"

    insights = _eda_key_insights(chart, ctx)
    body = insights if insights else [f"{feature} — 분석 결과 적립 후 채워짐"]

    chart_type = getattr(chart, "chart_type", "") or (
        variant.visual_type if variant else "chart_annotated_bar"
    )
    ref_id = getattr(chart, "ref_id", None)

    return SlideSpec(
        id=slide_id,
        section_id="solution",
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body,
        parent_message_id="solution_root",
        required_refs=[ref_id] if ref_id else [],
        visual_spec=VisualSpec(
            type=chart_type,
            title=title_ko,
            spec={
                "chart_path": getattr(chart, "path", "") or "",
                "x": getattr(chart, "x", None),
                "y": getattr(chart, "y", None),
                "numbers": list(getattr(chart, "numbers", None) or []),
                "callouts": list(getattr(chart, "callouts", None) or []),
                "severity": getattr(chart, "severity", "info"),
            },
        ),
        speaker_notes_hint=(
            f"EDA #{slide_index} — {feature}. finding: {finding[:80]}. "
            "KEY INSIGHTS 는 callouts → numbers → finding 순서로 자동 채워짐."
        ),
    )


def _build_eda_placeholder(
    slide_id: str,
    slide_index: int,
    ctx: ReportContext,
    role_key: str,
) -> SlideSpec:
    """ctx.eda.charts 가 빈 경우의 placeholder — 골격은 유지하되 내용 비움 안내."""
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide(role_key, category)
    title_ko = (variant.title_ko if variant else f"EDA · 슬라이드 {slide_index}")
    return SlideSpec(
        id=slide_id,
        section_id="solution",
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence",
        so_what=f"EDA {slide_index} — 분석 결과 적립 후 채워짐",
        title_ko=title_ko,
        body_outline=["분석 결과 적립 후 채워짐"],
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_annotated_bar"),
            title=title_ko,
            spec={"chart_path": "", "placeholder": True},
        ),
        speaker_notes_hint=f"EDA #{slide_index} placeholder — ctx.eda.charts 적립 시 자동 채워짐.",
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
    """슬라이드 11 — EDA · 변수 간 상관 / 데이터 품질 보조.

    [재구성] '차별화 (PRODUCT/QUALITY/SCALE/TRUST)' 영업 톤 → EDA Extra.
    4번째 EDAChart 가 있으면 그것을, 없으면 데이터 품질 이슈 요약으로.
    """
    charts = _select_top_eda_charts(ctx, n=4)
    if len(charts) >= 4:
        return _build_eda_slide_from_chart(charts[3], "s3_differentiation", 4, ctx, "eda_extra")
    # 4번째 차트 없음 — 데이터 품질·결측 분포로 채움
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
            "EDA Extra — 4번째 차트가 있으면 그것을 사용, 없으면 결측률 Top 5 요약. "
            "이후 슬라이드의 전처리 결정 근거."
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

    return SlideSpec(
        id="i1_kpi",
        section_id="results",
        layout="model_perf_baseline_grouped",
        role="evidence",
        so_what=so_what,
        title_ko="모델 성능 · Baseline 비교",
        body_outline=body[:5],
        required_refs=primary_metric_ref(ctx),
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="v28_model_perf",
            title=f"Baseline 비교 — {pm_name}",
            spec={
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


def _build_eda_findings(ctx: ReportContext) -> SlideSpec:
    """슬라이드 13 — SHAP Global Importance (Top 5).

    [재구성] EDA 슬라이드는 S8~S11 로 이동. 본 슬라이드는 모델 해석 시작점:
    interpretation.global_importance Top 5 + 카테고리별 적응 (Integrated Gradients / Reason Code 등).
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide("shap_global", category)
    title_ko = (variant.title_ko if variant else "SHAP Global Importance · Top 5")

    imps = list(ctx.interpretation.global_importance or [])[:5]
    items: list[dict[str, Any]] = []
    refs: list[str] = []
    for it in imps:
        items.append({
            "feature": getattr(it, "feature", ""),
            "importance": getattr(it, "importance", 0.0),
            "method": getattr(it, "method", "shap"),
        })
        rid = getattr(it, "ref_id", None)
        if rid:
            refs.append(rid)

    body = [
        f"{i+1}순위 · {it['feature']} · {format_metric(float(it['importance']), 'shap', as_percent=False, decimals=2)}"
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
            spec={"confusion_matrix": cm},
            severity="important",
        ),
        speaker_notes_hint=(
            "Error CM / 잔차 진단 / precision@k 곡선 — 카테고리에 따라 자동 변형. "
            "FN > FP / FP > FN 패턴으로 임계값 조정 방향 제시."
        ),
    )


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

    return SlideSpec(
        id="as_is_to_be",
        section_id="impact",
        layout=(variant.layout if variant else "one_message"),
        role="evidence",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body[:6],
        parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="segment_perf_table",
            title=title_ko,
            spec={"segments": seg_items},
        ),
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

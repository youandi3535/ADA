"""outputs.architect.skeletons._common — Skeleton 공통 슬라이드 빌더.

모든 Skeleton 이 공유하는 고정 슬라이드 (Cover/ExecSummary/Agenda/Closing) +
사용자 강제 요구 사항인 **기술스택 + 기술아키텍처 파이프라인** 슬라이드 빌더.
"""

from __future__ import annotations

from typing import Optional

from outputs.architect.plan import (
    SectionSpec,
    SlideSpec,
    VisualSpec,
)
from outputs.context.schema import ReportContext

# ==============================================================
# 고정 5 슬라이드 — 모든 Skeleton 공통
# ==============================================================


def build_cover(ctx: ReportContext) -> SlideSpec:
    """표지 — Cover."""
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "분석 보고서").strip()
    return SlideSpec(
        id="cover",
        section_id="front_matter",
        layout="cover",
        role="meta",
        so_what="",  # 표지에는 So-What 없음
        title_ko=intent[:40],
        body_outline=[
            f"카테고리: {ctx.meta.category}",
            f"데이터셋: {ctx.dataset.dataset_name or '미지정'}",
            f"분류등급: {ctx.meta.classification}",
        ],
        required_refs=[],
        speaker_notes_hint="제목·분석 의도·발표자 소개 + 본 보고서의 핵심 결론 미리보기.",
    )


def build_exec_summary(ctx: ReportContext) -> SlideSpec:
    """Executive Summary — 핵심 3박스 (문제·솔루션·임팩트)."""
    primary = ctx.evaluation.primary_metric or {}
    primary_name = primary.get("name", "primary")
    primary_value = primary.get("value", "-")
    body = [
        f"분석 의도: {ctx.meta.user_intent or '미지정'}",
        f"최적 모델: {ctx.model_selection.chosen.get('name', '-')} / {primary_name} = {primary_value}",
        f"비즈니스 임팩트: {_business_impact_summary(ctx)}",
    ]
    required = []
    if primary.get("ref_id"):
        required.append(primary["ref_id"])
    return SlideSpec(
        id="exec_summary",
        section_id="front_matter",
        layout="kpi_cards_3",
        role="claim",
        so_what=f"본 분석의 결론: {ctx.model_selection.chosen.get('name', '-')} 모델로 {primary_name} {primary_value} 달성",
        title_ko="Executive Summary",
        body_outline=body,
        required_refs=required,
        thread_part="resolution",
        speaker_notes_hint="3박스 카드 — 좌:문제, 중:솔루션, 우:임팩트. 청중에게 결론 먼저.",
    )


def build_agenda(sections_titles: list[str]) -> SlideSpec:
    """Agenda — 섹션 맵."""
    return SlideSpec(
        id="agenda",
        section_id="front_matter",
        layout="agenda",
        role="meta",
        so_what="본 보고서는 5개 섹션 구성으로, 결론부터 근거·실행순으로 전개합니다",
        title_ko="Agenda",
        body_outline=sections_titles,
        speaker_notes_hint="섹션 5개 흐름 안내. 각 섹션 1줄 요약 포함.",
    )


def build_closing(ctx: ReportContext) -> SlideSpec:
    """Closing — 요약 + Q&A."""
    primary = ctx.evaluation.primary_metric or {}
    summary_lines = [
        f"본 분석은 {ctx.meta.category} 카테고리에서 {ctx.model_selection.chosen.get('name', '-')} 모델로 {primary.get('name', '-')} {primary.get('value', '-')} 달성",
        "권고 액션 3건은 본 보고서 권고 섹션 참조",
        f"본 보고서의 한계와 재검증 권고: {ctx.limitations.revalidation_window or '6개월 내 재검증 권장'}",
    ]
    return SlideSpec(
        id="closing",
        section_id="closing",
        layout="closing",
        role="meta",
        so_what="요약 3문장 + Q&A",
        title_ko="Summary & Q&A",
        body_outline=summary_lines,
        speaker_notes_hint="새 정보 금지 — Executive Summary 재인용. Q&A 유도.",
    )


# ==============================================================
# 사용자 강제 — 기술스택 + 기술아키텍처 파이프라인 슬라이드
# ==============================================================


def build_tech_stack_slide(ctx: ReportContext) -> SlideSpec:
    """기술스택 슬라이드 (1장) — 사용 라이브러리·프레임워크·인프라."""
    env = ctx.code.environment or {}
    key_pkgs: dict[str, str] = env.get("key_packages", {}) or {}
    py_ver = env.get("python", "3.x")

    # 카테고리별 대표 스택 강조 (버전 포함)
    cat_stacks = {
        "tabular_ml": ["scikit-learn", "xgboost", "lightgbm", "catboost"],
        "tabular_dl": ["torch", "pytorch-lightning"],
        "timeseries": ["statsmodels", "prophet"],
        "anomaly_detection": ["scikit-learn", "pyod"],
    }
    cat_choices = cat_stacks.get(ctx.meta.category, [])
    spotlight = []
    for p in cat_choices:
        if p in key_pkgs:
            spotlight.append(f"{p} {key_pkgs[p]}")
        else:
            spotlight.append(p)
    if not spotlight:
        spotlight = [f"{k} {v}" for k, v in list(key_pkgs.items())[:4]]
    lines = [
        f"언어 · 런타임 : Python {py_ver}",
        f"분석 라이브러리 : {', '.join(spotlight) if spotlight else '미수집'}",
        f"데이터 · 실험 : pandas {key_pkgs.get('pandas', '')}, numpy {key_pkgs.get('numpy', '')}, MLflow",
        "인프라 : Docker · PostgreSQL · MinIO · Celery · LangGraph",
        "품질 · 관측 : MLflow run + Langfuse trace + Alembic migration",
        "보안 : R-103 PII 마스킹 · code_redactor 14 패턴 · Fernet 암호화",
    ]
    return SlideSpec(
        id="tech_stack",
        section_id="solution",
        layout="comparison_table",
        role="evidence",
        so_what=f"본 분석은 Python {py_ver} 기반 ADA 자동화 스택으로 재현 가능합니다",
        title_ko="기술 스택",
        body_outline=lines,
        visual_spec=VisualSpec(
            type="table_feature_matrix",
            title="기술 스택 구성",
            caption="카테고리별 대표 라이브러리 + 공통 인프라 + 품질·관측 도구",
            spec={"layers": ["언어/런타임", "분석", "데이터", "인프라", "품질·관측"]},
        ),
        speaker_notes_hint="청중이 분석가가 아니어도, 재현 가능성·신뢰성 어필 핵심 슬라이드.",
    )


def build_tech_architecture_slide(ctx: ReportContext) -> SlideSpec:
    """기술 아키텍처 파이프라인 슬라이드 (1장)."""
    # ADA 의 표준 파이프라인 단계
    pipeline_steps = [
        "데이터 업로드 (G1)",
        "Data Profiler (PII + 카테고리 + 도메인)",
        "전처리 (Preprocessing Strategist + Handler)",
        "EDA + 피처 엔지니어링",
        "모델 선정 (G4) + 학습 (Heavy/Light 분기)",
        "평가 (G6) + 해석 (SHAP/PDP)",
        "인사이트 + 보고서 산출 (5종 carrier)",
    ]
    return SlideSpec(
        id="tech_architecture",
        section_id="solution",
        layout="process_flow",
        role="evidence",
        so_what="본 분석은 7단계 파이프라인으로 자동 수행됩니다 (G1~G6 + 산출)",
        title_ko="기술 아키텍처 파이프라인",
        body_outline=pipeline_steps,
        visual_spec=VisualSpec(
            type="diagram_process_linear",
            title="ADA 분석 파이프라인",
            caption="각 단계는 게이트로 사용자 개입 가능 (HITL).",
            spec={"steps": pipeline_steps, "highlight_current_category": ctx.meta.category},
        ),
        speaker_notes_hint="좌→우 단계 박스. 카테고리(시계열/이상탐지/정형ML/DL) 분기 위치 강조.",
    )


def build_combined_tech_slide(ctx: ReportContext) -> SlideSpec:
    """길이 여유 없을 때 — 기술스택 + 기술아키텍처 1장 통합."""
    env = ctx.code.environment or {}
    py_ver = env.get("python", "3.x")
    return SlideSpec(
        id="tech_combined",
        section_id="solution",
        layout="chart_dual",  # 좌 다이어그램 + 우 표 분할
        role="evidence",
        so_what=f"Python {py_ver} ADA 자동화 스택 + 7단계 게이트 파이프라인으로 재현·확장 가능",
        title_ko="기술 스택 · 아키텍처",
        body_outline=[
            "좌: 7단계 분석 파이프라인 (G1~G6 + 산출)",
            "우: 카테고리 대표 라이브러리 + 공통 인프라",
        ],
        visual_spec=VisualSpec(
            type="custom",
            title="기술 스택 · 아키텍처 파이프라인",
            caption="단일 슬라이드 압축 — 상세는 부록 참조",
            spec={
                "left": "diagram_process_linear",
                "right": "table_feature_matrix",
                "pipeline_steps": [
                    "데이터",
                    "프로파일",
                    "전처리",
                    "EDA·피처",
                    "모델 선정·학습",
                    "평가·해석",
                    "보고서 산출",
                ],
            },
        ),
        speaker_notes_hint="여유 없을 때 통합본. 분석가 청중이면 분리 슬라이드 권장.",
    )


def insert_tech_slides(
    section: SectionSpec,
    ctx: ReportContext,
    *,
    space_available: int,
) -> SectionSpec:
    """주어진 섹션에 기술스택·기술아키텍처 슬라이드 강제 삽입.

    Args:
        section: 삽입 대상 섹션 (보통 Solution / Method 섹션).
        ctx: ReportContext.
        space_available: 추가 가능한 슬라이드 칸 수 — 1 이면 통합본, 2+ 이면 분리.

    Returns:
        슬라이드가 추가된 새 SectionSpec.
    """
    if space_available <= 0:
        # 여유 0 — 통합본을 ExecSummary 옆에 삽입은 별도 정책. 여기선 그냥 1장 통합.
        section.slides.append(build_combined_tech_slide(ctx))
        return section
    if space_available == 1:
        section.slides.append(build_combined_tech_slide(ctx))
        return section
    # 2+ 여유 — 분리
    section.slides.append(build_tech_architecture_slide(ctx))
    section.slides.append(build_tech_stack_slide(ctx))
    return section


# ==============================================================
# 내부 헬퍼
# ==============================================================


def _business_impact_summary(ctx: ReportContext) -> str:
    """Executive Summary 의 임팩트 한 줄."""
    if ctx.evaluation.business_kpi:
        first = ctx.evaluation.business_kpi[0]
        return f"{first.name} {first.estimated_value} {first.unit}"
    # 폴백 — primary metric 으로 표현
    primary = ctx.evaluation.primary_metric or {}
    if primary:
        return f"{primary.get('name', '-')} {primary.get('value', '-')} 달성"
    return "추정 불가 — 추가 데이터 필요"


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
    """primary_metric 의 ref_id (있으면 1개) — 모든 Skeleton 이 ExecSummary 에 사용."""
    pm = ctx.evaluation.primary_metric or {}
    rid = pm.get("ref_id")
    return [rid] if rid else []


def eda_top_chart_refs(ctx: ReportContext, top_k: int = 3) -> list[str]:
    """EDA 차트 중 severity=critical/important 우선 top_k 의 ref_id."""
    charts = list(ctx.eda.charts)
    # severity 순위
    rank = {"critical": 0, "important": 1, "info": 2}
    charts.sort(key=lambda c: rank.get(getattr(c, "severity", "info"), 9))
    refs: list[str] = []
    for c in charts:
        rid = getattr(c, "ref_id", None)
        if rid:
            refs.append(rid)
        if len(refs) >= top_k:
            break
    return refs


def build_hypothesis_slide(ctx: ReportContext) -> SlideSpec:
    """가설 슬라이드 — 주제를 뒷받침할 가설 3개 + 검증 방법."""
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    intent = ctx.meta.user_intent or "분석"
    lines = [
        f"H1 · 핵심 변수 영향  ·  Top 피처가 {pm.get('name', '지표')} 에 강한 신호 제공",
        f"H2 · 모델 적합성  ·  {chosen} 가 {ctx.meta.category} 카테고리 baseline 대비 우수",
        "H3 · 운영 안정성  ·  분포 변화 시에도 임계 성능 유지 가능",
    ]
    return SlideSpec(
        id="hypothesis",
        section_id="evidence",
        layout="one_message",
        role="claim",
        so_what=f"본 분석 '{intent[:30]}' 를 뒷받침하는 3개 가설 수립",
        title_ko="분석 가설",
        body_outline=lines,
        thread_part="setup",
        parent_message_id="root",
        visual_spec=VisualSpec(
            type="custom",
            title="Hypothesis · Evidence · Insight",
            caption="가설별 증거·인사이트 흐름",
            spec={"layout": "hyp_evidence_insight"},
        ),
        speaker_notes_hint="가설 3개 설정 — 분석 출발점. 다음 슬라이드에서 각각 증거·인사이트 제시.",
    )


def build_insight_slide(ctx: ReportContext) -> SlideSpec:
    """인사이트 슬라이드 — 가설을 입증한 데이터·해석으로 도출된 핵심 인사이트."""
    pm = ctx.evaluation.primary_metric or {}
    imps = ctx.interpretation.global_importance[:3] if ctx.interpretation.global_importance else []
    chosen = (ctx.model_selection.chosen or {}).get("name", "선정 모델")
    if imps:
        top_feat = imps[0].feature
    else:
        top_feat = "주요 피처"
    lines = [
        f"인사이트 1  ·  {top_feat} 가 결과의 주요 동인 — H1 입증",
        f"인사이트 2  ·  {chosen} 의 {pm.get('name', '지표')} {pm.get('value', '-')} 달성 — H2 입증",
        "인사이트 3  ·  세그먼트별 일관 — H3 부분 입증 (분포 변화 모니터링 권장)",
        "→ 종합  ·  데이터 → 패턴 → 인사이트 → 액션 4단계 도출",
    ]
    return SlideSpec(
        id="insights_derived",
        section_id="evidence",
        layout="one_message_big_number",
        role="claim",
        so_what="가설 3개를 데이터로 입증 — 핵심 인사이트 도출",
        title_ko="가설 입증 인사이트",
        body_outline=lines,
        thread_part="resolution",
        parent_message_id="root",
        visual_spec=VisualSpec(
            type="custom",
            title="인사이트 도출",
            caption="가설 → 증거 → 인사이트 → 액션",
            spec={"layout": "insight_funnel"},
        ),
        speaker_notes_hint="가설 입증 결과 — 데이터→패턴→인사이트→액션 4단계 도출.",
    )


def insert_hypothesis_insight_after_exec(sections: list[SectionSpec], ctx: ReportContext) -> list[SectionSpec]:
    """ExecSummary 직후, 본문 첫 섹션 직전에 가설·인사이트 도입 섹션 삽입.

    Returns updated sections list (in-place modification or new).
    """
    hyp = build_hypothesis_slide(ctx)
    ins = build_insight_slide(ctx)
    intro_section = make_section(
        "hypothesis_intro",
        "Section 0 — 가설 & 인사이트 도입",
        kind="context",
        divider=False,
        slides=[hyp, ins],
    )
    # Insert after front_matter (which contains cover/exec/agenda)
    new_sections = []
    inserted = False
    for sec in sections:
        new_sections.append(sec)
        if sec.id == "front_matter" and not inserted:
            new_sections.append(intro_section)
            inserted = True
    if not inserted:
        # Fallback: prepend
        new_sections.insert(0, intro_section)
    return new_sections

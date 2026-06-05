"""outputs.architect.length_adjuster — ReportPlan 슬라이드 수 조정 (Phase 2).

10~20 hard limit 강제. 고정 5장 (Cover/ExecSummary/Agenda/Closing + 결론·핵심) 은
절대 압축 불가.

알고리즘:
    1. 현재 슬라이드 수 측정.
    2. 하한 미달 → Evidence 섹션 슬라이드 분할 또는 Appendix 추가.
    3. 상한 초과 → 우선순위 낮은 슬라이드부터 통합/제거.
"""

from __future__ import annotations

from outputs.architect.plan import ReportPlan, SlideSpec

# 절대 압축 불가 슬라이드 id 후보 (Skeleton 마다 다를 수 있음)
_PROTECTED_IDS: set[str] = {
    "cover",
    "exec_summary",
    "agenda",
    "closing",
    "conclusion",
    "a_answer",
    "rec_options",
    "root_cause",
    "recommendation",
}

# 압축 시 제거 우선순위 — 위에서부터 제거 후보
_REMOVAL_PRIORITY: tuple[str, ...] = (
    "data_dict",  # Analysis Standard 의 데이터 사전
    "references",  # 참고문헌
    "sensitivity",  # Comparative 민감도
    "e5_interpretation",  # SCQA E-5 해석
    "deep_2",  # Comparative 3번째 심화
    "deep_1",  # Comparative 2번째 심화
    "evidence_h2",  # Diagnostic 가설 2 증거
    "result_eda",  # Analysis result_eda
    "e2_eda_2",  # SCQA EDA 3번째
    "e2_eda_1",  # SCQA EDA 2번째
)


def adjust_length(plan: ReportPlan, *, hard_min: int = 10, hard_max: int = 20) -> ReportPlan:
    """ReportPlan 의 슬라이드 수를 [hard_min, hard_max] 범위로 조정.

    Returns:
        조정된 ReportPlan. 경고는 ``plan.warnings`` 에 누적.
    """
    current = plan.slide_count()

    if current > hard_max:
        plan = _compress(plan, target=hard_max)
        plan.warnings.append(f"length_compressed: {current}→{plan.slide_count()}")
    elif current < hard_min:
        plan = _expand(plan, target=hard_min)
        plan.warnings.append(f"length_expanded: {current}→{plan.slide_count()}")

    plan.slide_count_target = plan.slide_count()
    return plan


# ==============================================================
# 압축 (max 초과)
# ==============================================================


def _compress(plan: ReportPlan, *, target: int) -> ReportPlan:
    """우선순위 순서로 슬라이드 제거."""
    current = plan.slide_count()
    if current <= target:
        return plan

    # 1) 우선순위 리스트의 id 부터 제거
    for rid in _REMOVAL_PRIORITY:
        if plan.slide_count() <= target:
            break
        _remove_slide_by_id(plan, rid)

    # 2) 그래도 초과면 — Evidence 섹션 끝에서부터 1장씩 제거 (protected 제외)
    while plan.slide_count() > target:
        removed = _remove_last_unprotected(plan)
        if not removed:
            plan.warnings.append("compress_failed: only protected slides remain")
            break
    return plan


def _remove_slide_by_id(plan: ReportPlan, slide_id: str) -> bool:
    for sec in plan.sections:
        for i, sl in enumerate(sec.slides):
            if sl.id == slide_id and sl.id not in _PROTECTED_IDS:
                sec.slides.pop(i)
                return True
    return False


def _remove_last_unprotected(plan: ReportPlan) -> bool:
    """뒤에서부터 protected 가 아닌 슬라이드 1개 제거."""
    # closing 섹션은 보호 — 그 앞 섹션부터 역순으로
    for sec in reversed(plan.sections):
        if sec.kind == "closing":
            continue
        for i in range(len(sec.slides) - 1, -1, -1):
            if sec.slides[i].id not in _PROTECTED_IDS:
                sec.slides.pop(i)
                return True
    return False


# ==============================================================
# 확장 (min 미달)
# ==============================================================


def _expand(plan: ReportPlan, *, target: int) -> ReportPlan:
    """본문에 보조 슬라이드 삽입."""
    deficit = target - plan.slide_count()
    if deficit <= 0:
        return plan

    # 1) Evidence 섹션이 있으면 Appendix 슬라이드 추가
    appendix_section = next((s for s in plan.sections if s.kind == "appendix"), None)
    if appendix_section is None:
        # 새 Appendix 섹션 삽입 (Closing 직전)
        from outputs.architect.plan import SectionSpec

        appendix_section = SectionSpec(
            id="appendix",
            title="Appendix",
            kind="appendix",
            divider_required=True,
            short_summary="부록",
        )
        # closing 앞에 삽입
        closing_idx = next(
            (i for i, s in enumerate(plan.sections) if s.kind == "closing"),
            len(plan.sections),
        )
        plan.sections.insert(closing_idx, appendix_section)

    fillers = _make_filler_slides(plan, deficit)
    appendix_section.slides.extend(fillers)
    return plan


def _make_filler_slides(plan: ReportPlan, n: int) -> list[SlideSpec]:
    """n 개 보조 슬라이드 생성 — 방법론·재현·참고 등."""
    templates = [
        SlideSpec(
            id="appendix_methodology",
            section_id="appendix",
            layout="process_flow",
            role="meta",
            so_what="재현 가능한 파이프라인 명세",
            title_ko="Appendix — 방법론",
            body_outline=["전처리·튜닝·평가 단계 명세", "재현 명령 + 환경 정보"],
        ),
        SlideSpec(
            id="appendix_data_dict",
            section_id="appendix",
            layout="appendix_table",
            role="meta",
            so_what="주요 변수 정의·단위",
            title_ko="Appendix — 데이터 사전",
            body_outline=["주요 변수와 단위 정의"],
        ),
        SlideSpec(
            id="appendix_glossary",
            section_id="appendix",
            layout="appendix_table",
            role="meta",
            so_what="용어 사전",
            title_ko="Appendix — 용어 사전",
            body_outline=["본 보고서에 사용된 약어·전문용어"],
        ),
        SlideSpec(
            id="appendix_references",
            section_id="appendix",
            layout="appendix_table",
            role="meta",
            so_what="참고문헌·인용 색인",
            title_ko="Appendix — 참고문헌",
            body_outline=["KB / 외부 인용 모음"],
        ),
    ]
    return templates[:n]

"""outputs.content.qa_anticipator — Q&A 예상 + 백업 슬라이드 (Phase 3, Part 13-3).

각 슬라이드에서 청중이 던질 질문을 예상하고, 상위 5개를 백업 슬라이드 후보로 등록.
PPT 만 — Hide 처리된 슬라이드로 Q&A 시 점프 가능.
"""

from __future__ import annotations

from dataclasses import dataclass

from outputs.architect.plan import SectionSpec, SlideSpec
from outputs.context.schema import ReportContext


@dataclass
class QACandidate:
    question: str = ""
    short_answer: str = ""
    source_slide_id: str = ""
    suggested_backup_id: str = ""
    importance: float = 0.5

    def to_backup_slide(self) -> SlideSpec:
        return SlideSpec(
            id=self.suggested_backup_id or f"backup_{self.source_slide_id}",
            section_id="backup",
            layout="one_message",
            role="evidence",
            so_what=f"Q&A 백업: {self.question}",
            title_ko=f"백업 — {self.question[:30]}",
            body_outline=[self.short_answer],
        )


def anticipate_questions(plan, ctx: ReportContext) -> list[QACandidate]:
    """슬라이드별 예상 질문 → 상위 5개 백업 슬라이드 후보."""
    candidates: list[QACandidate] = []
    for sl in plan.all_slides():
        if sl.role == "meta":
            continue
        for q, a, imp in _per_slide_questions(sl, ctx):
            candidates.append(
                QACandidate(
                    question=q,
                    short_answer=a,
                    source_slide_id=sl.id,
                    suggested_backup_id=f"backup_{sl.id}_{abs(hash(q)) % 1000}",
                    importance=imp,
                )
            )
    # 상위 5개 (importance 기준)
    candidates.sort(key=lambda c: c.importance, reverse=True)
    return candidates[:5]


def attach_backup_section(plan, candidates: list[QACandidate]) -> None:
    """ReportPlan 끝에 (Closing 직전) Hidden Backup 섹션 추가.

    PPT carrier 가 'hidden' 속성으로 표시. 본문 슬라이드 수에는 미포함.
    """
    if not candidates:
        return
    backup_section = SectionSpec(
        id="backup",
        title="Backup (Hidden)",
        kind="appendix",
        divider_required=False,
        short_summary="Q&A 백업",
        slides=[c.to_backup_slide() for c in candidates],
    )
    # backup 슬라이드는 hidden 표시 — speaker_notes_hint 에 마커
    for sl in backup_section.slides:
        sl.speaker_notes_hint = (sl.speaker_notes_hint or "") + "\n[HIDDEN]"
    # closing 앞에 삽입
    closing_idx = next((i for i, s in enumerate(plan.sections) if s.kind == "closing"), len(plan.sections))
    plan.sections.insert(closing_idx, backup_section)


# ==============================================================
# 내부 — role 별 질문 패턴
# ==============================================================


def _per_slide_questions(sl: SlideSpec, ctx: ReportContext) -> list[tuple[str, str, float]]:
    """슬라이드 1장에서 (question, short_answer, importance) 3-튜플 0~3개."""
    role = sl.role
    out: list[tuple[str, str, float]] = []
    if role == "claim":
        pm = ctx.evaluation.primary_metric or {}
        out.append(
            (
                f"{sl.title_ko} 결론의 단일 핵심 근거는?",
                f"{pm.get('name', '-')} = {pm.get('value', '-')} (출처: {pm.get('ref_id', '-')})",
                0.9,
            )
        )
        out.append(
            (
                "반대 가설은 검증했는가?",
                "model_caveats 와 limitations.generalization_risk 참조",
                0.7,
            )
        )
    elif role == "evidence":
        if sl.required_refs:
            out.append(
                (
                    f"이 수치 ({sl.required_refs[0]}) 의 표본·CI는?",
                    "evaluation.metrics 의 ci 필드 또는 dataset.shape 확인",
                    0.8,
                )
            )
        out.append(
            (
                "다른 세그먼트에서도 일관되는가?",
                "evaluation.per_segment 참조 — 미수집 시 추가 분석 권고",
                0.6,
            )
        )
    elif role == "action":
        out.append(
            (
                "실행 비용·일정은?",
                f"limitations.revalidation_window = {ctx.limitations.revalidation_window or '미명시'}",
                0.85,
            )
        )
        out.append(
            (
                "실행 주체는 누구?",
                "risk_register / 권고 슬라이드 의 소유자 컬럼",
                0.7,
            )
        )
    elif role == "caveat":
        out.append(
            (
                "이 한계가 결론에 미치는 영향 크기는?",
                "data_gaps[*].impact 와 model_caveats 비교",
                0.75,
            )
        )
    return out

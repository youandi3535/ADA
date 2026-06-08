"""outputs.content.speaker_notes — 화자 노트 4파트 생성 (Phase 3, Part 13-1).

각 슬라이드에 다음 구조의 화자 노트 자동 생성:

    [화자노트 — 4파트]
    ① 핵심 강조: So-What 1줄 재선언
    ② 데이터 출처: 본 슬라이드 ref_id 와 출처
    ③ 예상 질문 3개 + 짧은 답변 (qa_anticipator 연계)
    ④ 대안 프레이밍: 청중이 다르면 어떻게 말할지 1줄
"""

from __future__ import annotations

from typing import Any

from outputs.architect.plan import SlideSpec
from outputs.context.schema import ReportContext


def generate_speaker_notes(slide: SlideSpec, ctx: ReportContext, profile: dict[str, Any]) -> str:
    """슬라이드별 화자 노트 생성 (의사 모드 — LLM 없이 템플릿)."""
    if slide.role == "meta":
        return slide.speaker_notes_hint or ""

    # ① 핵심 강조
    p1 = f"① 핵심 강조: {slide.so_what}"

    # ② 데이터 출처
    refs = slide.required_refs + slide.data_refs
    if refs:
        sources = []
        for ref in refs[:3]:
            meta = ctx.citations.index.get(ref, {})
            if isinstance(meta, dict):
                sp = meta.get("source_path", ref)
                sources.append(f"{ref} ({sp})")
            else:
                sources.append(ref)
        p2 = f"② 데이터 출처: {' / '.join(sources)}"
    else:
        p2 = "② 데이터 출처: 본 슬라이드는 정성적 — ReportContext meta 인용"

    # ③ 예상 질문 — 슬라이드 role 별 패턴
    p3 = _expected_questions(slide, ctx)

    # ④ 대안 프레이밍
    p4 = _alt_framing(slide, profile)

    return "\n".join([p1, p2, p3, p4])


def _expected_questions(slide: SlideSpec, ctx: ReportContext) -> str:
    """role 별 예상 질문 3개."""
    role = slide.role
    if role == "evidence":
        qs = [
            "이 수치의 표본 크기/CI는?",
            "다른 세그먼트에서도 일관되는가?",
            "출처·재현 가능성은?",
        ]
    elif role == "claim":
        qs = [
            "이 결론을 지지하는 단일 핵심 근거는?",
            "반대 가설은 검증했는가?",
            "이 결론이 깨지는 조건은?",
        ]
    elif role == "action":
        qs = [
            "실행 비용·일정은?",
            "실행 주체와 책임 분배는?",
            "성공 측정 지표는?",
        ]
    elif role == "caveat":
        qs = [
            "한계가 결론에 미치는 영향 크기는?",
            "한계 해소 방안 우선순위는?",
            "잔여 리스크는 누가 관리하는가?",
        ]
    else:
        qs = ["?", "?", "?"]
    return "③ 예상 질문: " + " / ".join(qs)


def _alt_framing(slide: SlideSpec, profile: dict[str, Any]) -> str:
    """청중 변경 시 강조점."""
    emphasis = profile.get("emphasis", []) or ["결론"]
    return f"④ 대안 프레이밍: 다른 청중 시 {emphasis[0]} 대신 다른 측면 강조 가능"


def apply_to_plan(plan, ctx: ReportContext, profile: dict[str, Any]) -> None:
    """ReportPlan 의 모든 슬라이드에 화자 노트 in-place 생성."""
    for sl in plan.all_slides():
        sl.speaker_notes_hint = generate_speaker_notes(sl, ctx, profile)

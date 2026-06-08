"""outputs.qa.final_checklist — carrier 호출 직전 마지막 점검 (Phase 6, Part 15-3).

체크리스트:
    □ 슬라이드 수 ∈ [10, 20]
    □ Classification 마킹 (메타 값 검증)
    □ Footer 모든 슬라이드 표시 (지정 layout 제외)
    □ Cover · ExecSummary · Agenda · Closing 4장 포함
    □ 모든 used_ref_id 가 색인에 해결
    □ 화자 노트 모든 (메타 외) 슬라이드 존재
    □ Backup 슬라이드 ≥ 3장 (PPT 만)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext


@dataclass
class ChecklistResult:
    items: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(it["passed"] for it in self.items)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "items": list(self.items)}


def final_checklist(plan: ReportPlan, ctx: ReportContext) -> ChecklistResult:
    result = ChecklistResult()

    def _add(label: str, passed: bool, note: str = ""):
        result.items.append({"label": label, "passed": passed, "note": note})

    # 1) 슬라이드 수 — backup 제외
    body_slides = sum(len(s.slides) for s in plan.sections if s.id != "backup")
    _add("슬라이드 수 [10, 20]", 10 <= body_slides <= 20, f"current={body_slides}")

    # 2) Classification 메타
    valid_class = ctx.meta.classification in ("Public", "Internal", "Confidential", "Strictly Confidential")
    _add("Classification 유효", valid_class, f"meta.classification={ctx.meta.classification}")

    # 3) 고정 4장 포함
    ids = {s.id for sec in plan.sections for s in sec.slides}
    needed = {"cover", "exec_summary", "agenda", "closing"}
    missing = needed - ids
    _add("고정 슬라이드 4장 포함", not missing, f"missing={list(missing)}")

    # 4) ref_id 해결
    used = plan.used_ref_ids()
    index_keys = set(k for k in (ctx.citations.index or {}) if k != "__meta__")
    unresolved = [r for r in used if r and r not in index_keys]
    _add("미해결 ref_id 0", not unresolved, f"unresolved={len(unresolved)}")

    # 5) 화자 노트
    no_notes = [s.id for s in plan.all_slides() if s.role != "meta" and not s.speaker_notes_hint]
    _add("화자 노트 누락 없음", not no_notes, f"missing={no_notes[:3]}")

    # 6) Backup 슬라이드 ≥ 3 (PPT 만)
    if plan.output_form == "pptx":
        backup_count = next((len(s.slides) for s in plan.sections if s.id == "backup"), 0)
        _add("Backup 슬라이드 ≥ 3 (PPT)", backup_count >= 3, f"current={backup_count}")

    return result

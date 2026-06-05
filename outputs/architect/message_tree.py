"""outputs.architect.message_tree — Pyramid Principle 강제 (Phase 2).

ReportPlan 의 모든 슬라이드가 parent_message_id 를 갖고 root 까지 추적 가능한지 확인.
ExecSummary 가 모든 핵심 결론을 선언하는지 점검.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from outputs.architect.plan import MessageNode, ReportPlan


@dataclass
class MessageTreeReport:
    """Pyramid 자가 검증 결과."""

    total_slides: int = 0
    orphan_slides: list[str] = field(default_factory=list)  # parent_message_id 없는 슬라이드
    unreachable_nodes: list[str] = field(default_factory=list)  # root 까지 도달 못 하는 노드
    exec_summary_coverage: float = 0.0  # ExecSummary 가 selling 한 결론 %

    @property
    def passed(self) -> bool:
        return not self.orphan_slides and not self.unreachable_nodes

    def to_dict(self) -> dict:
        return {
            "total_slides": self.total_slides,
            "orphans": list(self.orphan_slides),
            "unreachable": list(self.unreachable_nodes),
            "exec_summary_coverage": round(self.exec_summary_coverage, 3),
            "passed": self.passed,
        }


def validate_pyramid(plan: ReportPlan) -> MessageTreeReport:
    """ReportPlan 의 메시지 트리 검증.

    - 모든 본문 슬라이드(role != meta) 가 parent_message_id 보유
    - 모든 메시지 노드가 root 까지 도달 가능
    - ExecSummary 슬라이드가 결론 메시지를 선언했는지 (휴리스틱)
    """
    report = MessageTreeReport()

    # 슬라이드 점검
    all_slides = plan.all_slides()
    report.total_slides = len(all_slides)
    for sl in all_slides:
        if sl.role == "meta":
            continue
        if not sl.parent_message_id:
            report.orphan_slides.append(sl.id)

    # 메시지 노드 → 부모 추적
    node_map = {m.id: m for m in plan.message_tree}
    for m in plan.message_tree:
        if not _can_reach_root(m, node_map):
            report.unreachable_nodes.append(m.id)

    # ExecSummary 커버리지 — 본문 슬라이드 so_what 키워드와 ExecSummary body 매칭
    exec_slide = next((s for s in all_slides if s.id == "exec_summary"), None)
    if exec_slide:
        report.exec_summary_coverage = _exec_coverage(exec_slide, all_slides)
    return report


def _can_reach_root(node: MessageNode, node_map: dict[str, MessageNode]) -> bool:
    visited: set[str] = set()
    cur = node
    while cur:
        if cur.id in visited:  # 순환 방어
            return False
        visited.add(cur.id)
        if cur.parent_id is None:
            return True
        cur = node_map.get(cur.parent_id) or None
    return False


def _exec_coverage(exec_slide, all_slides) -> float:
    """ExecSummary body 가 claim role 슬라이드의 so_what 핵심어를 포함하는 비율."""
    body_text = " ".join(exec_slide.body_outline) + " " + exec_slide.so_what
    claim_slides = [s for s in all_slides if s.role == "claim" and s.id != "exec_summary"]
    if not claim_slides:
        return 1.0
    hit = 0
    for s in claim_slides:
        # 키워드 = so_what 의 첫 4 단어
        words = (s.so_what or "").split()[:4]
        if not words:
            continue
        if any(w in body_text for w in words if len(w) >= 2):
            hit += 1
    return hit / len(claim_slides)

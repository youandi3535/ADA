"""outputs.architect.mece_validator — MECE 자가 검증 (Phase 2).

각 섹션 안의 슬라이드 So-What 이 상호 배타 + 집합 완전인지 점검.
LLM 호출은 안 하고 휴리스틱 (단어 중첩 / 길이 / 키워드 분포).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from outputs.architect.plan import ReportPlan


@dataclass
class MeceReport:
    section_id: str = ""
    overlap_pairs: list[tuple[str, str, float]] = field(default_factory=list)  # (id1, id2, score)
    too_few_slides: bool = False
    too_many_slides: bool = False

    def has_issue(self) -> bool:
        return bool(self.overlap_pairs) or self.too_few_slides or self.too_many_slides


@dataclass
class MeceSummary:
    sections: list[MeceReport] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "sections": [
                {
                    "id": s.section_id,
                    "overlap_pairs": list(s.overlap_pairs),
                    "too_few": s.too_few_slides,
                    "too_many": s.too_many_slides,
                }
                for s in self.sections
            ]
        }

    def total_issues(self) -> int:
        return sum(len(s.overlap_pairs) for s in self.sections) + sum(
            1 for s in self.sections if s.too_few_slides or s.too_many_slides
        )


def validate_mece(plan: ReportPlan, *, overlap_threshold: float = 0.5) -> MeceSummary:
    """각 섹션의 슬라이드 So-What 중첩률 점검.

    overlap = (공통 키워드) / (작은 쪽 키워드 수). >= threshold 면 중첩 경고.
    """
    summary = MeceSummary()
    for sec in plan.sections:
        if sec.kind in ("cover", "closing", "appendix"):
            continue
        report = MeceReport(section_id=sec.id)
        # 길이 점검 (Magic Number 3)
        n = len(sec.slides)
        if n > 6:
            report.too_many_slides = True
        if sec.kind == "evidence" and n < 2:
            report.too_few_slides = True
        # 중첩 점검
        keywords = [(s.id, _extract_keywords(s.so_what)) for s in sec.slides if s.so_what]
        for i in range(len(keywords)):
            for j in range(i + 1, len(keywords)):
                id1, k1 = keywords[i]
                id2, k2 = keywords[j]
                if not k1 or not k2:
                    continue
                common = set(k1) & set(k2)
                small = min(len(k1), len(k2))
                score = len(common) / max(1, small)
                if score >= overlap_threshold:
                    report.overlap_pairs.append((id1, id2, round(score, 3)))
        if report.has_issue():
            summary.sections.append(report)
    return summary


def _extract_keywords(text: str) -> list[str]:
    """한국어 So-What → 키워드 (2자 이상 토큰)."""
    if not text:
        return []
    # 간단 토큰화 — 공백 + 구두점 분리
    import re

    tokens = re.split(r"[\s,.!?;:·／/()\[\]]+", text)
    # 의미 있는 토큰만 (2자 이상, 숫자 제외)
    return [t for t in tokens if len(t) >= 2 and not t.replace(".", "").replace("%", "").isdigit()]

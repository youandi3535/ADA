"""outputs.content.so_what_scorer — So-What 6 항목 채점 (Phase 3, Part 10-1).

각 슬라이드의 So-What (상단 1줄 결론) 이 컨설팅 보고서 품질 기준을 통과하는지 검증.

6 항목 (모두 통과해야 합격):
    1. 길이 — 한국어 25~45자
    2. 동사 시작 권장 — 달성/증가/감소/제안/확인 등
    3. 수치 포함 — 최소 1개
    4. 결론성 — 의문문 금지
    5. 일반어 금지 — 다양한·여러·많은 등
    6. 약속 단어 금지 — 최적·완벽·최고

실패 시 SlideContentGenerator 가 LLM retry 또는 placeholder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ==============================================================
# 사전
# ==============================================================

_ACTION_VERBS = (
    "달성",
    "확보",
    "증가",
    "감소",
    "절감",
    "개선",
    "향상",
    "확인",
    "식별",
    "도입",
    "제안",
    "권고",
    "검증",
    "선정",
    "추천",
    "분석",
    "구현",
    "수립",
    "줄이",
    "늘리",
    "높이",
    "낮추",
)

_VAGUE_WORDS = (
    "다양한",
    "여러",
    "많은",
    "어느 정도",
    "대체로",
    "대부분",
    "비교적",
)

_OVERPROMISE_WORDS = (
    "최적",
    "완벽",
    "최고",
    "최선",
    "전무후무",
    "혁신적",
    "획기적",
)

_QUESTION_END = re.compile(r"[?？]\s*$")
_NUMERIC = re.compile(r"\d+(?:[.,]\d+)?%?")


# ==============================================================
# 결과 dataclass
# ==============================================================


@dataclass
class SoWhatScore:
    text: str = ""
    passed: bool = False
    violations: list[str] = field(default_factory=list)
    score: float = 0.0  # 0~1

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "passed": self.passed,
            "violations": list(self.violations),
            "score": self.score,
        }


# ==============================================================
# 공개 API
# ==============================================================


def score_so_what(text: str) -> SoWhatScore:
    """So-What 1줄 채점."""
    text = (text or "").strip()
    violations: list[str] = []

    # 1. 길이
    n = len(text)
    if n < 15:
        violations.append(f"길이 부족 ({n}<15)")
    elif n > 60:
        violations.append(f"길이 초과 ({n}>60)")

    # 2. 동사 시작 (권장만 — 점수 가산)
    # 한국어 동사는 어디서든 등장 가능하므로, action verb 포함 여부로 약식 평가
    has_action_verb = any(v in text for v in _ACTION_VERBS)

    # 3. 수치 포함
    if not _NUMERIC.search(text):
        violations.append("수치 미포함")

    # 4. 결론성 — 의문문 차단
    if _QUESTION_END.search(text):
        violations.append("의문문 종결")

    # 5. 일반어
    for w in _VAGUE_WORDS:
        if w in text:
            violations.append(f"일반어: {w}")
            break

    # 6. 약속 단어
    for w in _OVERPROMISE_WORDS:
        if w in text:
            violations.append(f"약속어: {w}")
            break

    # 점수
    base_score = 1.0 - (len(violations) * 0.18)
    if has_action_verb:
        base_score += 0.05
    base_score = max(0.0, min(1.0, base_score))

    return SoWhatScore(
        text=text,
        passed=len(violations) == 0,
        violations=violations,
        score=round(base_score, 3),
    )


def score_plan_so_whats(plan) -> dict:
    """ReportPlan 전체 슬라이드 So-What 일괄 채점."""
    results = []
    for slide in plan.all_slides():
        if slide.role == "meta":
            continue
        sc = score_so_what(slide.so_what)
        results.append({"slide_id": slide.id, **sc.to_dict()})
    passed = sum(1 for r in results if r["passed"])
    return {
        "total": len(results),
        "passed": passed,
        "fail_rate": round(1 - passed / max(1, len(results)), 3),
        "results": results,
    }

"""agents.gates._intent — user_intent 태그 suffix 멱등 부착 헬퍼.

HJ 2026-06-11 (jh 대행) — G2/G3/G4 가 user_intent 에 "(태그: 값)" 을
중복 체크 없이 덧붙여 gate resume 마다 누적되는 오염 수정
(실측: "(분석 방향: ...)" 6중첩 → S4 가설 슬라이드 오염).

정책: 같은 태그가 이미 있으면 제거 후 새 값으로 교체 (재선택 시 갱신).
"""

from __future__ import annotations

import re

__all__ = ["append_intent_tag"]


def append_intent_tag(base: str | None, tag: str, value: str | None) -> str:
    """``base`` 에 ``(tag: value)`` suffix 를 멱등하게 부착.

    - 동일 tag 의 기존 suffix 는 제거 후 교체 → 누적 방지 + 재선택 반영
    - base 가 비면 ``tag: value`` 형식 (기존 동작 보존)
    - value 가 비면 base 정리만 수행
    """
    base = (base or "").strip()
    value = (value or "").strip()

    # 기존 동일 태그 suffix 제거. 값 내부의 닫는 괄호까지는 비대응 (보수적) —
    # 시스템이 붙이는 suffix 는 본 헬퍼만 거치므로 형식이 일정함.
    pattern = re.compile(r"\s*\(" + re.escape(tag) + r":[^)]*\)")
    base = pattern.sub("", base).strip()
    # base 가 "태그: 값" 단독 형식으로 시작했던 케이스도 정리
    bare = re.compile(r"^" + re.escape(tag) + r":[^(]*$")
    if bare.match(base):
        base = ""

    if not value:
        return base
    if not base:
        return f"{tag}: {value}"
    return f"{base} ({tag}: {value})"

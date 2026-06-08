"""outputs.content.tone_calibrator — 청중별 톤 캘리브레이션 (Phase 3, Part 10-3).

청중에 따라:
    - 종결어미 (~합니다 / ~한다 / ~드립니다)
    - 본문 길이
    - 기술용어 빈도
    - 강조 영역 (결론·임팩트·리스크 vs 방법·데이터·한계)

slide_writer 가 콘텐츠 생성 직후 본 모듈로 후처리.
"""

from __future__ import annotations

import re
from typing import Any

# ==============================================================
# 종결어미 정규화
# ==============================================================


_ENDING_PATTERNS = {
    "합니다": re.compile(r"(?:한다|되어진다|이다)(\.|$|\s)"),
    "한다": re.compile(r"(?:합니다|입니다|됩니다)(\.|$|\s)"),
    "드립니다": re.compile(r"(?:합니다|한다|입니다)(\.|$|\s)"),
}


def calibrate_endings(text: str, target_ending: str) -> str:
    """텍스트의 종결어미를 청중별 목표로 통일.

    target_ending: "합니다" | "한다" | "드립니다"
    """
    if not text:
        return text
    if target_ending == "합니다":
        text = re.sub(r"한다(\.|$|\s)", r"합니다\1", text)
        text = re.sub(r"되어진다(\.|$|\s)", r"됩니다\1", text)
    elif target_ending == "한다":
        text = re.sub(r"합니다(\.|$|\s)", r"한다\1", text)
        text = re.sub(r"됩니다(\.|$|\s)", r"된다\1", text)
        text = re.sub(r"입니다(\.|$|\s)", r"이다\1", text)
    elif target_ending == "드립니다":
        text = re.sub(r"합니다(\.|$|\s)", r"드립니다\1", text)
    return text


def trim_to_max_words(text: str, max_words: int) -> str:
    """본문 길이 제한 (한국어 어절 기준)."""
    if not text:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",.") + " …"


def calibrate_body_outline(body: list[str], profile: dict[str, Any]) -> list[str]:
    """슬라이드 본문 outline 의 톤·길이 조정."""
    ending = profile.get("endings_ko", "합니다")
    max_words = int(profile.get("max_body_words", 70))
    # 불릿 1개당 (max_words / 항목수) 안에 맞추기
    if not body:
        return body
    per_bullet = max(8, max_words // max(1, len(body)))
    out = []
    for line in body:
        adj = calibrate_endings(line, ending)
        adj = trim_to_max_words(adj, per_bullet)
        out.append(adj)
    return out


def calibrate_so_what(text: str, profile: dict[str, Any]) -> str:
    """So-What 어미 통일 (길이는 score 가 별도)."""
    ending = profile.get("endings_ko", "합니다")
    return calibrate_endings(text, ending)

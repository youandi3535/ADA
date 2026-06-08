"""outputs.layouts.md_layouts — Markdown 직렬화 (Phase 4).

layout 토큰 → 마크다운 섹션 구조.
"""

from __future__ import annotations

from outputs.architect.plan import SlideSpec


def slide_to_markdown(slide: SlideSpec) -> str:
    """슬라이드 1개 → 마크다운 문자열."""
    lines: list[str] = []
    # 헤더
    if slide.title_ko:
        lines.append(f"## {slide.title_ko}")
    # So-What 강조
    if slide.so_what:
        lines.append(f"> **{slide.so_what}**")
        lines.append("")
    # 본문 outline → 불릿
    for item in slide.body_outline:
        lines.append(f"- {item}")
    # 비주얼 spec → placeholder
    if slide.visual_spec and slide.visual_spec.type and slide.visual_spec.type != "text_only":
        lines.append("")
        lines.append(f"_[{slide.visual_spec.type}: {slide.visual_spec.title or ''}]_")
    # 화자 노트는 details 블록
    if slide.speaker_notes_hint:
        lines.append("")
        lines.append("<details><summary>화자 노트</summary>")
        lines.append("")
        lines.append(slide.speaker_notes_hint)
        lines.append("")
        lines.append("</details>")
    return "\n".join(lines)

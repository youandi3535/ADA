"""outputs.layouts.pptx_layouts — PPT 매핑 (Phase 4).

layout 토큰 → python-pptx 슬라이드 빌더 helper.
Phase 6 의 pptx_carrier 가 호출.
"""

from __future__ import annotations

from typing import Any

from outputs.layouts.grid import SLIDE_GRID
from outputs.layouts.tokens import get_layout_spec


def slide_box_specs(layout_token: str) -> list[dict[str, Any]]:
    """layout 토큰 → 슬롯별 cm 좌표 리스트.

    각 항목: {"name", "type", "x_cm", "y_cm", "w_cm", "h_cm", "font_role"}
    """
    spec = get_layout_spec(layout_token)
    out: list[dict[str, Any]] = []
    for slot in spec["slots"]:
        col, row, sc, sr = slot["grid"]
        region = SLIDE_GRID.region(col, row, sc, sr)
        out.append(
            {
                "name": slot["name"],
                "type": slot["type"],
                "x_cm": region["x_cm"],
                "y_cm": region["y_cm"],
                "w_cm": region["w_cm"],
                "h_cm": region["h_cm"],
                "font_role": slot.get("font_role"),
            }
        )
    return out


def layout_background(layout_token: str) -> str:
    """layout 의 배경 컬러 키."""
    return get_layout_spec(layout_token).get("bg", "white")


def is_full_bleed(layout_token: str) -> bool:
    return bool(get_layout_spec(layout_token).get("bleed", False))


def shows_header(layout_token: str) -> bool:
    return bool(get_layout_spec(layout_token).get("header", True))


def shows_footer(layout_token: str) -> bool:
    return bool(get_layout_spec(layout_token).get("footer", True))

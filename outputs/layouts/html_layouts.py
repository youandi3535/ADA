"""outputs.layouts.html_layouts — HTML/CSS Grid 매핑 (Phase 4).

layout 토큰 → CSS Grid template area 문자열.
HTML carrier (Phase 6) 가 사용.
"""

from __future__ import annotations

from outputs.layouts.tokens import get_layout_spec


def css_grid_template(layout_token: str) -> dict:
    """layout 토큰 → CSS Grid spec.

    Returns:
        {"grid_template": "...", "areas": {name: area_label}, "slot_meta": [...]}
    """
    spec = get_layout_spec(layout_token)
    # 12x8 grid string 만들기
    grid_cells: list[list[str]] = [["." for _ in range(12)] for _ in range(8)]
    areas_map: dict[str, str] = {}
    for slot in spec["slots"]:
        col, row, sc, sr = slot["grid"]
        label = slot["name"]
        areas_map[label] = label
        for r in range(row, row + sr):
            for c in range(col, col + sc):
                if 0 <= r < 8 and 0 <= c < 12:
                    grid_cells[r][c] = label
    template = "\n".join('"' + " ".join(row) + '"' for row in grid_cells)
    return {
        "grid_template": template,
        "areas": areas_map,
        "slot_meta": list(spec["slots"]),
        "background": spec.get("bg", "white"),
        "header": spec.get("header", True),
        "footer": spec.get("footer", True),
    }

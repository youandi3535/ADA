"""outputs.layouts.pdf_layouts — PDF (reportlab) 매핑 (Phase 4).

layout 토큰 → reportlab Frame 좌표.
A4 (210mm × 297mm) 기준. 슬라이드와 달리 페이지가 세로지만,
PPT 16:9 슬라이드를 가로로 회전하지 않고 위아래 분할로 재구성.
"""

from __future__ import annotations

from typing import Any

from outputs.layouts.tokens import get_layout_spec

A4_PT = (595, 842)  # reportlab points (1pt = 1/72 inch)
MARGIN_PT = 56  # 약 2cm


def page_frames(layout_token: str) -> list[dict[str, Any]]:
    """layout 토큰 → PDF 페이지의 Frame 좌표 (reportlab Frame 사용).

    각 항목: {"name", "type", "x", "y", "w", "h", "font_role"}
    """
    spec = get_layout_spec(layout_token)
    w_total = A4_PT[0] - 2 * MARGIN_PT
    h_total = A4_PT[1] - 2 * MARGIN_PT
    out: list[dict[str, Any]] = []
    for slot in spec["slots"]:
        col, row, sc, sr = slot["grid"]
        x = MARGIN_PT + (col / 12) * w_total
        y = A4_PT[1] - MARGIN_PT - ((row + sr) / 8) * h_total
        w = (sc / 12) * w_total
        h = (sr / 8) * h_total
        out.append(
            {
                "name": slot["name"],
                "type": slot["type"],
                "x": round(x, 1),
                "y": round(y, 1),
                "w": round(w, 1),
                "h": round(h, 1),
                "font_role": slot.get("font_role"),
            }
        )
    return out

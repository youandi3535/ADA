"""outputs.layouts.tokens — 18 layout 토큰 명세 (Phase 4, Part 8-4).

각 토큰은 *영역 분할 + 텍스트 슬롯 + 비주얼 슬롯* 명세 dict.
carrier (pptx/pdf/html/md) 가 토큰 → 형식별 구현으로 변환.

Grid: 12 cols × 8 rows (outputs/layouts/grid.py).
"""

from __future__ import annotations

from typing import Any

# ==============================================================
# 18 layout 토큰 — 영역 분할 spec
# ==============================================================
#
# 각 spec 의 키:
#   slots:      텍스트/비주얼 슬롯 리스트
#               [{type, name, grid: (col, row, span_col, span_row), font_role}]
#   bg:         배경 컬러 키 (palette/semantic) — None 이면 white
#   bleed:      true 면 풀블리드 (마진 무시)
#   header:     true 면 So-What 상단 헤더 표시
#   footer:     true 면 footer 표시
#
# slot type:
#   "so_what"        — 상단 결론 1줄 (slide_so_what 폰트)
#   "title"          — 슬라이드 제목 (section_header 폰트)
#   "body"           — 본문 텍스트
#   "kpi_card"       — KPI 카드 1개 (visuals.cards spec)
#   "chart"          — 차트 1개 (visuals.charts spec)
#   "diagram"        — 다이어그램 1개 (visuals.diagrams spec)
#   "table"          — 표 1개 (visuals.tables spec)
#   "cover_block"    — 표지 전용 (큰 제목 + 메타)
#   "closing_block"  — 마무리 전용 (요약 + Q&A 안내)
#   "agenda_list"    — 섹션 번호·제목 리스트
#   "quote_block"    — 인용 큰 글씨


LAYOUT_SPECS: dict[str, dict[str, Any]] = {
    "cover": {
        "slots": [{"type": "cover_block", "name": "main", "grid": (0, 0, 12, 8), "font_role": "cover_title"}],
        "bg": "white",
        "bleed": True,
        "header": False,
        "footer": True,
    },
    "agenda": {
        "slots": [
            {"type": "title", "name": "title", "grid": (0, 0, 12, 1), "font_role": "section_header"},
            {"type": "agenda_list", "name": "list", "grid": (0, 1, 12, 7), "font_role": "body_strong"},
        ],
        "bg": "white",
        "bleed": False,
        "header": False,
        "footer": True,
    },
    "section_divider": {
        "slots": [{"type": "title", "name": "section", "grid": (0, 0, 12, 8), "font_role": "cover_title"}],
        "bg": "primary",
        "bleed": True,
        "header": False,
        "footer": True,
    },
    "one_message": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "title", "name": "title", "grid": (0, 1, 12, 1), "font_role": "section_header"},
            {"type": "body", "name": "body", "grid": (0, 2, 12, 6), "font_role": "body"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "one_message_big_number": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "kpi_card", "name": "big", "grid": (3, 2, 6, 4), "font_role": "kpi_number"},
            {"type": "body", "name": "caption", "grid": (0, 6, 12, 2), "font_role": "caption"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "chart_callout": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "chart", "name": "chart", "grid": (0, 1, 7, 7), "font_role": None},
            {"type": "body", "name": "callout", "grid": (7, 1, 5, 7), "font_role": "body"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "chart_dual": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "chart", "name": "left", "grid": (0, 1, 6, 6), "font_role": None},
            {"type": "chart", "name": "right", "grid": (6, 1, 6, 6), "font_role": None},
            {"type": "body", "name": "caption", "grid": (0, 7, 12, 1), "font_role": "caption"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "kpi_cards_3": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "kpi_card", "name": "kpi1", "grid": (0, 2, 4, 5), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi2", "grid": (4, 2, 4, 5), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi3", "grid": (8, 2, 4, 5), "font_role": "kpi_number"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "kpi_cards_4": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "kpi_card", "name": "kpi1", "grid": (0, 2, 6, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi2", "grid": (6, 2, 6, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi3", "grid": (0, 5, 6, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi4", "grid": (6, 5, 6, 3), "font_role": "kpi_number"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "kpi_cards_6": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "kpi_card", "name": "kpi1", "grid": (0, 2, 4, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi2", "grid": (4, 2, 4, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi3", "grid": (8, 2, 4, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi4", "grid": (0, 5, 4, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi5", "grid": (4, 5, 4, 3), "font_role": "kpi_number"},
            {"type": "kpi_card", "name": "kpi6", "grid": (8, 5, 4, 3), "font_role": "kpi_number"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "2x2_matrix": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "table", "name": "matrix", "grid": (1, 1, 10, 7), "font_role": "body"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "process_flow": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "diagram", "name": "flow", "grid": (0, 2, 12, 5), "font_role": None},
            {"type": "body", "name": "caption", "grid": (0, 7, 12, 1), "font_role": "caption"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "process_flow_gantt": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "diagram", "name": "gantt", "grid": (0, 2, 12, 6), "font_role": None},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "comparison_table": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "table", "name": "table", "grid": (0, 2, 12, 6), "font_role": "body"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "comparison_before_after": {
        "slots": [
            {"type": "so_what", "name": "so_what", "grid": (0, 0, 12, 1), "font_role": "slide_so_what"},
            {"type": "table", "name": "comparison", "grid": (0, 2, 12, 6), "font_role": "body"},
        ],
        "bg": "white",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "quote": {
        "slots": [
            {"type": "quote_block", "name": "quote", "grid": (1, 2, 10, 4), "font_role": "section_header"},
            {"type": "body", "name": "attribution", "grid": (1, 6, 10, 1), "font_role": "caption"},
        ],
        "bg": "ink_100",
        "bleed": False,
        "header": True,
        "footer": True,
    },
    "appendix_table": {
        "slots": [
            {"type": "title", "name": "title", "grid": (0, 0, 12, 1), "font_role": "section_header"},
            {"type": "table", "name": "data", "grid": (0, 1, 12, 6), "font_role": "footnote"},
            {"type": "body", "name": "source", "grid": (0, 7, 12, 1), "font_role": "footnote"},
        ],
        "bg": "white",
        "bleed": False,
        "header": False,
        "footer": True,
    },
    "closing": {
        "slots": [
            {"type": "closing_block", "name": "main", "grid": (0, 0, 12, 8), "font_role": "section_header"},
        ],
        "bg": "white",
        "bleed": False,
        "header": False,
        "footer": True,
    },
}


def get_layout_spec(token: str) -> dict:
    """layout token → spec. 알 수 없는 토큰은 one_message 폴백."""
    return dict(LAYOUT_SPECS.get(token, LAYOUT_SPECS["one_message"]))


def layout_tokens() -> list[str]:
    return list(LAYOUT_SPECS.keys())

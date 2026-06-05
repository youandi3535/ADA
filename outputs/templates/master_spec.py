"""outputs.templates.master_spec — 카테고리별 마스터 spec (Phase 4).

각 카테고리당 마스터 spec dict:
    palette        — palette.get_palette 결과
    fonts          — typography.TYPOGRAPHY
    icons          — iconography.get_category_icons
    cover_motif    — 표지 비주얼 모티프 (color band / icon / pattern)
    divider_motif  — 섹션 구분 슬라이드 디자인
    accent_shape   — 본문 슬라이드 우상단 액센트 도형
"""

from __future__ import annotations

from typing import Any

from outputs.style.iconography import get_category_icons
from outputs.style.palette import CATEGORY_PALETTE, get_palette
from outputs.style.typography import TYPOGRAPHY


def _build_master(category: str) -> dict[str, Any]:
    palette = get_palette(category)
    return {
        "category": category,
        "label_ko": palette["label_ko"],
        "palette": palette,
        "fonts": dict(TYPOGRAPHY),
        "icons": get_category_icons(category),
        "cover_motif": {
            "type": "diagonal_band",
            "color": palette["primary"],
            "accent_color": palette["accent"],
            "icon": get_category_icons(category)[0],
        },
        "divider_motif": {
            "type": "full_bleed_number",
            "background": palette["primary"],
            "number_color": palette["accent"],
            "text_color": "#FFFFFF",
        },
        "accent_shape": {
            "type": "corner_band",
            "color": palette["primary"],
            "size_cm": 0.6,
            "position": "top_right",
        },
        "footer_style": {
            "rule_color": palette["accent"],
            "rule_height_pt": 1,
        },
    }


MASTER_SPECS: dict[str, dict[str, Any]] = {cat: _build_master(cat) for cat in CATEGORY_PALETTE.keys()}


def get_master_spec(category: str | None) -> dict[str, Any]:
    if not category or category not in MASTER_SPECS:
        return _build_master("tabular_ml")  # 기본 fallback
    return dict(MASTER_SPECS[category])

"""outputs.style.palette — 카테고리·의미 컬러 (Phase 4, Part 8-3).

VisualDNA 가 import 해서 사용. 단일 진실원.
"""

from __future__ import annotations

CATEGORY_PALETTE: dict[str, dict[str, str]] = {
    "tabular_ml": {"primary": "#1308BB", "accent": "#DF14A5", "secondary": "#1A042E", "label_ko": "정형 ML"},
    "tabular_dl": {"primary": "#0891b2", "accent": "#67e8f9", "secondary": "#155e75", "label_ko": "정형 DL"},
    "timeseries": {"primary": "#16a34a", "accent": "#86efac", "secondary": "#15803d", "label_ko": "시계열"},
    "anomaly_detection": {"primary": "#dc2626", "accent": "#fca5a5", "secondary": "#991b1b", "label_ko": "이상 탐지"},
}

DEFAULT_PALETTE: dict[str, str] = {
    "primary": "#4b5563",
    "accent": "#d1d5db",
    "secondary": "#374151",
    "label_ko": "기타",
}

SEMANTIC_COLORS: dict[str, str] = {
    "success": "#16A34A",
    "warning": "#D97706",
    "danger": "#DC2626",
    "info": "#2563EB",
    "ink_900": "#0F172A",
    "ink_700": "#334155",
    "ink_500": "#64748B",
    "ink_300": "#CBD5E1",
    "ink_100": "#F1F5F9",
    "white": "#FFFFFF",
}


def get_palette(category: str | None) -> dict[str, str]:
    if not category:
        return dict(DEFAULT_PALETTE)
    return dict(CATEGORY_PALETTE.get(category, DEFAULT_PALETTE))


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """#RRGGBB → (R, G, B). python-pptx RGBColor 용."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0, 0, 0)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except Exception:
        return (0, 0, 0)

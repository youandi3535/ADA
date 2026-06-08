"""outputs.localization.formatters — 공통 숫자 포맷 (Phase 5)."""

from __future__ import annotations


def format_percent(value: float | int | None, decimals: int = 1) -> str:
    """0.123 → '12.3%' / 12.3 → '12.3%' (1 이상이면 이미 % 단위 가정)."""
    if value is None:
        return "-"
    try:
        v = float(value)
    except Exception:
        return str(value)
    if abs(v) <= 1:
        v *= 100
    return f"{v:.{decimals}f}%"


def format_decimal(value: float | int | None, decimals: int = 3) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{decimals}f}"
    except Exception:
        return str(value)


def format_int_with_commas(value: int | None) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except Exception:
        return str(value)

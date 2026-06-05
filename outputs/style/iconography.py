"""outputs.style.iconography — lucide-icons 매핑 (Phase 4, Part 8-5).

카테고리당 대표 아이콘 6개 사전 매핑. carrier 는 lucide → SVG/PNG 경로 해석.
"""

from __future__ import annotations

_CATEGORY_ICONS: dict[str, list[str]] = {
    "tabular_ml": ["table", "cpu", "bar-chart-3", "git-branch", "target", "shield-check"],
    "tabular_dl": ["layers", "cpu", "network", "git-branch", "target", "shield-check"],
    "timeseries": ["trending-up", "calendar", "activity", "clock", "target", "shield-check"],
    "anomaly_detection": ["alert-triangle", "search", "shield-alert", "filter", "target", "shield-check"],
}

# 일반 아이콘 — 모든 보고서 공통
_COMMON_ICONS: dict[str, str] = {
    "data": "database",
    "code": "code",
    "report": "file-text",
    "kpi": "trending-up",
    "warning": "alert-circle",
    "success": "check-circle-2",
    "user": "users",
    "settings": "settings",
    "calendar": "calendar-days",
    "package": "package",
    "shield": "shield",
}


def get_category_icons(category: str | None) -> list[str]:
    if not category:
        return list(_CATEGORY_ICONS["tabular_ml"])
    return list(_CATEGORY_ICONS.get(category, _CATEGORY_ICONS["tabular_ml"]))


def lucide_icon_name(concept: str) -> str | None:
    """공통 개념 → lucide 아이콘 이름."""
    return _COMMON_ICONS.get(concept.lower())


def icon_url(name: str) -> str:
    """lucide 아이콘 CDN URL (HTML carrier 가 사용)."""
    return f"https://unpkg.com/lucide-static@latest/icons/{name}.svg"

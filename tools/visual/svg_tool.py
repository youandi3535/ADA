"""tools.visual.svg_tool — Lucide SVG 아이콘 → PNG, 색상 동적 적용.

Lucide 아이콘 (1400+, MIT) 을 슬라이드 ID·역할별로 자동 매핑 + 카테고리 색 적용.

흐름:
    1. assets/icons/lucide/<name>.svg 로드
    2. stroke 속성 동적 교체 (Lucide 는 stroke 기반)
    3. cairosvg 로 PNG 변환 (크기 지정 가능)
    4. 결과 PNG 경로 반환 → python-pptx 의 add_picture 로 임베드

cairosvg 미설치 시: SVG 그대로 반환 (PowerPoint 가 SVG 지원, 단 색 변환 안 됨).

HJ 단독 영역.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

# Lucide 아이콘 디렉토리
_ICONS_DIR = Path(__file__).resolve().parents[2] / "assets" / "icons" / "lucide"
_PNG_CACHE = Path(__file__).resolve().parents[2] / "assets" / "cache" / "icon_png"
_PNG_CACHE.mkdir(parents=True, exist_ok=True)

# 슬라이드 ID → Lucide 아이콘 이름 매핑
# 미매칭 시 role 기반 폴백 (claim → target, evidence → bar-chart-3, caveat → alert-triangle)
_ICON_BY_SLIDE_ID: dict[str, str] = {
    "cover": "presentation",
    "exec_summary": "rocket",
    "agenda": "list-checks",
    "hypothesis": "lightbulb",
    "p1_market": "building-2",
    "p2_pain": "alert-triangle",
    "p3_alt_limits": "x-octagon",
    "why_dl": "brain",
    "why_timeseries": "trending-up",
    "why_anomaly": "shield-alert",
    "why_ml": "sparkles",
    "method_model": "settings-2",
    "architecture_deep": "layers",
    "tech_architecture": "network",
    "tech_stack": "code-2",
    "s3_differentiation": "award",
    "i1_kpi": "bar-chart-3",
    "training_dynamics": "activity",
    "eda_findings": "search",
    "error_analysis": "scan-search",
    "score_distribution": "git-fork",
    "forecast_plot": "line-chart",
    "insights_derived": "key",
    "as_is_to_be": "shuffle",
    "i3_roi": "dollar-sign",
    "risk_mitigation": "shield-check",
    "roadmap": "map",
    "closing": "check-circle-2",
}

_ICON_BY_ROLE: dict[str, str] = {
    "claim": "target",
    "evidence": "bar-chart-3",
    "caveat": "alert-triangle",
    "action": "arrow-right-circle",
    "meta": "info",
    "transition": "arrow-right",
}


def svg_icon_path(icon_name: str) -> Optional[Path]:
    """Lucide 아이콘 SVG 파일 경로 반환. 없으면 None."""
    p = _ICONS_DIR / f"{icon_name}.svg"
    return p if p.exists() else None


def icon_for_slide(slide_id: str, role: str = "claim") -> Optional[Path]:
    """슬라이드 ID 우선, 미매칭이면 role 폴백, 둘 다 없으면 None."""
    name = _ICON_BY_SLIDE_ID.get(slide_id) or _ICON_BY_ROLE.get(role)
    if not name:
        return None
    return svg_icon_path(name)


def _recolor_svg_string(svg_text: str, color: str) -> str:
    """SVG 텍스트의 stroke 색상을 동적 교체.

    Lucide 의 SVG 는 stroke="currentColor" 사용 — currentColor → 지정 색.
    fill 도 있으면 함께 교체.
    """
    # currentColor 를 지정 색으로 교체
    svg = svg_text.replace('stroke="currentColor"', f'stroke="{color}"')
    svg = svg.replace('fill="currentColor"', f'fill="{color}"')
    # 명시적 stroke 색이 있으면 그것도 교체 (Lucide 외 일반 SVG)
    svg = re.sub(r'stroke="#[0-9a-fA-F]{3,6}"', f'stroke="{color}"', svg)
    return svg


def svg_to_png_recolored(
    icon_name: str,
    color: str = "#2563eb",
    size_px: int = 128,
) -> Optional[Path]:
    """Lucide SVG 를 지정 색·사이즈 PNG 로 변환 후 캐시 경로 반환.

    cairosvg 미설치 시 None.
    """
    svg_path = svg_icon_path(icon_name)
    if svg_path is None:
        return None

    # 캐시 키
    cache_key = hashlib.md5(f"{icon_name}|{color}|{size_px}".encode()).hexdigest()[:16]
    png_path = _PNG_CACHE / f"{cache_key}.png"
    if png_path.exists():
        return png_path

    try:
        import cairosvg
    except ImportError:
        return None

    svg_text = svg_path.read_text(encoding="utf-8")
    recolored = _recolor_svg_string(svg_text, color)
    try:
        cairosvg.svg2png(
            bytestring=recolored.encode("utf-8"),
            write_to=str(png_path),
            output_width=size_px,
            output_height=size_px,
        )
        return png_path
    except Exception:
        return None


__all__ = [
    "icon_for_slide",
    "svg_icon_path",
    "svg_to_png_recolored",
]

"""tools.visual.illustration_tool — unDraw SVG 일러스트 → PNG, 카테고리 색 동적 매칭.

unDraw (MIT, 무료) 일러스트는 모두 단색 (#6c63ff 보라) 으로 통일되어 있어
ctx.meta.category 별 팔레트로 color swap 가능.

흐름:
    1. assets/illustrations/undraw/<name>.svg 로드
    2. #6c63ff 메인 색상을 카테고리 primary 색으로 교체
    3. cairosvg 로 PNG 변환
    4. 결과 PNG 경로 반환

HJ 단독 영역.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Optional

_ILLUST_DIR = Path(__file__).resolve().parents[2] / "assets" / "illustrations" / "undraw"
_PNG_CACHE = Path(__file__).resolve().parents[2] / "assets" / "cache" / "illust_png"
_PNG_CACHE.mkdir(parents=True, exist_ok=True)

# unDraw 의 기본 메인 색상 (이거를 카테고리 색으로 교체)
UNDRAW_DEFAULT_COLOR = "#6c63ff"

# 슬라이드 ID → unDraw 일러스트 이름 매핑 (큐레이션된 30개)
# unDraw 카탈로그 참조: https://undraw.co/illustrations
_ILLUST_BY_SLIDE_ID: dict[str, str] = {
    "p2_pain": "frustrated",
    "p3_alt_limits": "lost",
    "hypothesis": "creative_thinking",
    "p1_market": "city_life",
    "method_model": "engineering_team",
    "architecture_deep": "server_status",
    "tech_architecture": "cloud_hosting",
    "tech_stack": "programmer",
    "s3_differentiation": "winners",
    "i1_kpi": "growth_analytics",
    "training_dynamics": "progress_indicator",
    "eda_findings": "data_extraction",
    "error_analysis": "investigation",
    "insights_derived": "knowledge",
    "as_is_to_be": "before_dawn",
    "i3_roi": "growth_curve",
    "risk_mitigation": "safety",
    "roadmap": "navigation",
    "closing": "well_done",
    "exec_summary": "presentation",
    "why_dl": "artificial_intelligence",
    "why_timeseries": "calendar",
    "why_anomaly": "security_on",
    "why_ml": "predictive_analytics",
    "forecast_plot": "data_trends",
    "score_distribution": "scientist",
    "score_distribution_alt": "report",
}


def illustration_path(name: str) -> Optional[Path]:
    """unDraw SVG 경로. 없으면 None."""
    p = _ILLUST_DIR / f"{name}.svg"
    return p if p.exists() else None


def illustration_for_slide(slide_id: str) -> Optional[Path]:
    """슬라이드 ID 로 unDraw 일러스트 SVG 경로 반환."""
    name = _ILLUST_BY_SLIDE_ID.get(slide_id)
    if not name:
        return None
    return illustration_path(name)


def _recolor_svg(svg_text: str, new_color: str, default: str = UNDRAW_DEFAULT_COLOR) -> str:
    """unDraw 기본 색을 카테고리 색으로 교체.

    대소문자 무관, 짧은 형식 (#6cf) 도 처리.
    """
    # 명시적 매칭
    svg = svg_text.replace(default, new_color)
    svg = svg.replace(default.upper(), new_color)
    # 짧은 형식 (#6cf — unDraw 에선 잘 안 쓰임)
    svg = re.sub(rf'fill="{default}"', f'fill="{new_color}"', svg, flags=re.IGNORECASE)
    return svg


def recolor_undraw(
    slide_id: str,
    primary_color: str,
    width_px: int = 800,
    height_px: int = 600,
) -> Optional[Path]:
    """슬라이드 ID 의 unDraw 일러스트를 지정 색으로 재컬러링 → PNG.

    Args:
        slide_id: SlideSpec.id
        primary_color: 카테고리 primary hex (예: "#2563eb")
        width_px: PNG 가로 크기
        height_px: PNG 세로 크기

    Returns:
        캐시된 PNG 경로 또는 None.
    """
    svg_path = illustration_for_slide(slide_id)
    if svg_path is None:
        return None

    cache_key = hashlib.md5(f"{slide_id}|{primary_color}|{width_px}x{height_px}".encode()).hexdigest()[:16]
    png_path = _PNG_CACHE / f"{cache_key}.png"
    if png_path.exists():
        return png_path

    try:
        import cairosvg
    except ImportError:
        return None

    svg_text = svg_path.read_text(encoding="utf-8")
    recolored = _recolor_svg(svg_text, primary_color)
    try:
        cairosvg.svg2png(
            bytestring=recolored.encode("utf-8"),
            write_to=str(png_path),
            output_width=width_px,
            output_height=height_px,
        )
        return png_path
    except Exception:
        return None


__all__ = [
    "illustration_for_slide",
    "illustration_path",
    "recolor_undraw",
]

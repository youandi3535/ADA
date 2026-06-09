"""tools.visual — PPT 시각 품질 향상 도구 (CPU 100%, 무료, 무 GPU).

모듈:
    stock_image       : Unsplash·Pexels·Pixabay API + 캐시
    svg_tool          : Lucide SVG → PNG, 색상 동적 적용
    illustration_tool : unDraw SVG → PNG, 카테고리 색 매칭
    font_tool         : Pretendard 폰트 경로·등록

HJ 2026-06-08 — PPT 품질 향상 Phase 1 (GTX 1060 3GB 제약).
"""

from tools.visual.font_tool import (  # noqa: F401
    PRETENDARD_AVAILABLE,
    get_font_name,
)
from tools.visual.illustration_tool import (  # noqa: F401
    illustration_for_slide,
    recolor_undraw,
)
from tools.visual.stock_image import (  # noqa: F401
    fetch_stock_image,
    get_cover_image,
)
from tools.visual.svg_tool import (  # noqa: F401
    icon_for_slide,
    svg_to_png_recolored,
)

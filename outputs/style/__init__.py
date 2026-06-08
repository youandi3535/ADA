"""outputs.style — 디자인 시스템 (Phase 4).

모듈:
    palette.py           — 카테고리·의미 컬러
    typography.py        — Pretendard 타이포 스케일
    iconography.py       — lucide-icons 매핑
    header_footer.py     — 슬라이드 헤더·푸터·페이지 번호
    classification.py    — Public/Internal/Confidential 워터마크
"""

from outputs.style.classification import classification_treatment  # noqa: F401
from outputs.style.iconography import get_category_icons, lucide_icon_name  # noqa: F401
from outputs.style.palette import CATEGORY_PALETTE, SEMANTIC_COLORS, get_palette  # noqa: F401
from outputs.style.typography import TYPOGRAPHY  # noqa: F401

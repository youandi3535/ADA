"""outputs.layouts — 18 layout 토큰 명세 + 그리드 (Phase 4).

각 layout 토큰은 슬라이드 1장의 *영역 분할 + 폰트 + 색* 명세.
carrier 가 형식별로 적용:
    pptx_layouts.py — python-pptx 슬라이드 마스터·텍스트 박스
    pdf_layouts.py  — reportlab Frame·Paragraph
    html_layouts.py — Jinja2 컴포넌트
    md_layouts.py   — markdown 직렬화
"""

from outputs.layouts.grid import SLIDE_GRID, Grid  # noqa: F401
from outputs.layouts.tokens import LAYOUT_SPECS, get_layout_spec  # noqa: F401

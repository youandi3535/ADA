"""outputs.style.typography — Pretendard 타이포 스케일 (Phase 4, Part 8-2)."""

from __future__ import annotations

TYPOGRAPHY: dict[str, dict[str, object]] = {
    "cover_title": {"family": "Pretendard", "size_pt": 54, "weight": 800, "leading": 1.1},
    "slide_so_what": {"family": "Pretendard", "size_pt": 22, "weight": 700, "leading": 1.3},
    "section_header": {"family": "Pretendard", "size_pt": 36, "weight": 700, "leading": 1.2},
    "body": {"family": "Pretendard", "size_pt": 16, "weight": 400, "leading": 1.45},
    "body_strong": {"family": "Pretendard", "size_pt": 16, "weight": 600, "leading": 1.45},
    "caption": {"family": "Pretendard", "size_pt": 11, "weight": 400, "leading": 1.35},
    "footnote": {"family": "Pretendard", "size_pt": 9, "weight": 400, "leading": 1.3},
    "kpi_number": {"family": "Pretendard", "size_pt": 44, "weight": 700, "leading": 1.0},
    "kpi_unit": {"family": "Pretendard", "size_pt": 14, "weight": 500, "leading": 1.0},
    "code": {"family": "JetBrains Mono", "size_pt": 11, "weight": 400, "leading": 1.4},
}

# 폴백 폰트 — Pretendard 미설치 시 시스템 폰트
FALLBACK_KO = ("Pretendard", "Noto Sans KR", "맑은 고딕", "Malgun Gothic", "sans-serif")
FALLBACK_MONO = ("JetBrains Mono", "Consolas", "D2Coding", "monospace")

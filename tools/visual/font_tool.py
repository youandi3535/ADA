"""tools.visual.font_tool — Pretendard 한국어 폰트 경로 관리.

python-pptx 는 OS 의 *시스템 폰트* 만 참조하는 .pptx 를 생성. 폰트 파일 자체는
PowerPoint 가 열 때 사용자 PC 에 폰트가 설치되어 있어야 보임. 따라서:

운영 권고:
    1. 서버: assets/fonts/Pretendard-*.otf 를 /usr/share/fonts/ 에 복사 + fc-cache
    2. 사용자 PC: PowerPoint 로 .pptx 열 때 Pretendard 미설치면 fallback (Malgun Gothic)
    3. .pptx 안에 폰트 임베드는 python-pptx 한계 — Aspose.Slides 상용이면 가능

HJ 단독 영역.
"""

from __future__ import annotations

from pathlib import Path

# Pretendard 폰트 weight 별 매핑
PRETENDARD_WEIGHTS: dict[str, str] = {
    "regular": "Pretendard-Regular.otf",
    "medium": "Pretendard-Medium.otf",
    "semibold": "Pretendard-SemiBold.otf",
    "bold": "Pretendard-Bold.otf",
    "extrabold": "Pretendard-ExtraBold.otf",
}

# 자산 디렉토리
_ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def pretendard_font_path(weight: str = "regular") -> Path | None:
    """Pretendard 폰트 파일 경로 반환. 없으면 None."""
    fname = PRETENDARD_WEIGHTS.get(weight.lower(), PRETENDARD_WEIGHTS["regular"])
    p = _ASSETS_DIR / fname
    return p if p.exists() else None


def is_pretendard_installed() -> bool:
    """시스템에 Pretendard 폰트 파일이 자산 디렉토리에 존재하는지."""
    return any(pretendard_font_path(w) is not None for w in PRETENDARD_WEIGHTS)


# PowerPoint 가 인식할 폰트 이름 — Pretendard 가 설치되어 있으면 그것, 아니면 Malgun Gothic 폴백
PRETENDARD_AVAILABLE = is_pretendard_installed()


def get_font_name(weight: str = "regular") -> str:
    """PPT 슬라이드에서 사용할 폰트 이름 반환.

    Pretendard 자산 존재 + 시스템 설치 가정 → "Pretendard"
    아니면 → "Malgun Gothic" (한국어 폴백)
    """
    if PRETENDARD_AVAILABLE:
        # PowerPoint 가 weight 자동 매핑 — 이름만 "Pretendard"
        return "Pretendard"
    return "Malgun Gothic"


def setup_instructions() -> str:
    """폰트 설치 가이드 (운영 적용용)."""
    return f"""Pretendard 설치 가이드:

1. 자산 다운로드:
   bash scripts/setup_visual_assets.sh

2. 서버 (Linux/Docker) 폰트 시스템 등록:
   sudo cp {_ASSETS_DIR}/Pretendard-*.otf /usr/share/fonts/opentype/
   sudo fc-cache -fv

3. 클라이언트 PC (PowerPoint 사용자):
   {_ASSETS_DIR}/Pretendard-*.otf 더블클릭 → "설치"

4. 미설치 시 폴백: Malgun Gothic (Windows 기본 한국어).
"""


__all__ = [
    "PRETENDARD_AVAILABLE",
    "PRETENDARD_WEIGHTS",
    "get_font_name",
    "is_pretendard_installed",
    "pretendard_font_path",
    "setup_instructions",
]

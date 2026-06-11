"""outputs.carriers.design_hint_helpers — slide._design_hint 활용 헬퍼.

LLMDesigner 가 ``slide._design_hint`` 에 attach 한 디자인 힌트:

    {
        "chosen_template": str,
        "palette_hint": "default" | "warning" | "success" | "monochrome",
        "photo_keyword": str,          # 영문 검색어
        "icon_concept": str,           # 'kpi', 'warning', 'data' 등
        "fallback_reason": str,        # 부족 신호 (빈 문자열이면 좋은 매칭)
        "_source": "llm" | "fallback",
    }

각 draw 함수 시그니처를 *변경하지 않고*, ``getattr(sl, "_design_hint", None)`` 로
읽어서 본 헬퍼들을 호출. 힌트 없으면 기본값.

부족 신호 (fallback_reason 비어있지 않음) 는 카운터에 누적 — 나중에 *어떤 디자인이
부족했는지* 통계로 확인 후 카탈로그 확장에 활용.
"""

from __future__ import annotations

from typing import Any, Optional

from outputs.style.iconography import lucide_icon_name
from outputs.style.palette import SEMANTIC_COLORS

# ==============================================================
# 부족 신호 카운터 (프로세스 단위)
# ==============================================================

_CATALOG_MISS_COUNTER: dict[str, int] = {}


def record_catalog_miss(slide_id: str, reason: str) -> None:
    """LLM 이 *부족함* 신호를 보낸 경우 누적 (process 단위)."""
    if not reason:
        return
    key = f"{slide_id}::{reason[:80]}"
    _CATALOG_MISS_COUNTER[key] = _CATALOG_MISS_COUNTER.get(key, 0) + 1


def catalog_miss_summary() -> list[tuple[str, int]]:
    """누적된 부족 신호 (key, count) 내림차순."""
    return sorted(_CATALOG_MISS_COUNTER.items(), key=lambda kv: -kv[1])


def reset_catalog_miss() -> None:
    """카운터 초기화 (테스트용)."""
    _CATALOG_MISS_COUNTER.clear()


# ==============================================================
# design_hint 접근 헬퍼
# ==============================================================


def get_hint(sl) -> dict[str, Any]:
    """slide 에서 design_hint 추출. 없으면 빈 dict."""
    hint = getattr(sl, "_design_hint", None)
    if isinstance(hint, dict):
        return hint
    return {}


def palette_override(sl, default_palette: dict[str, str]) -> dict[str, str]:
    """LLM 의 palette_hint 에 따라 색 override.

    힌트:
        "default"    — 카테고리 기본 팔레트 그대로
        "warning"    — primary 를 amber/orange 로 (danger 까진 아닌 주의)
        "success"    — primary 를 green 으로 (도입 확정·통과 강조)
        "monochrome" — primary 를 회색 톤으로 (보수적·중립 톤)

    Returns:
        새 팔레트 dict (primary/accent/secondary 키 보장)
    """
    hint = get_hint(sl).get("palette_hint", "default") or "default"
    hint = hint.strip().lower()
    pal = dict(default_palette)

    if hint == "warning":
        pal["primary"] = SEMANTIC_COLORS.get("warning", pal.get("primary", "#D97706"))
        pal["accent"] = "#FCD34D"
        pal["secondary"] = "#92400E"
    elif hint == "success":
        pal["primary"] = SEMANTIC_COLORS.get("success", pal.get("primary", "#16A34A"))
        pal["accent"] = "#86EFAC"
        pal["secondary"] = "#15803D"
    elif hint == "monochrome":
        pal["primary"] = SEMANTIC_COLORS.get("ink_700", "#334155")
        pal["accent"] = SEMANTIC_COLORS.get("ink_300", "#CBD5E1")
        pal["secondary"] = SEMANTIC_COLORS.get("ink_900", "#0F172A")
    # "default" 또는 알 수 없는 값 → 기본 팔레트 유지

    return pal


def photo_keyword(sl, fallback: str = "") -> str:
    """LLM 이 제안한 사진 키워드. 없으면 fallback (보통 슬라이드 ID 기반)."""
    return get_hint(sl).get("photo_keyword", "") or fallback


def icon_name(sl, fallback_concept: str = "") -> str:
    """LLM 의 icon_concept 을 lucide 아이콘 이름으로 변환.

    예:
        hint.icon_concept = "kpi"      → "trending-up"
        hint.icon_concept = "warning"  → "alert-circle"
        없으면 fallback_concept 사용.

    Returns:
        lucide 아이콘 이름 (없으면 빈 문자열)
    """
    concept = get_hint(sl).get("icon_concept", "").strip()
    if concept:
        name = lucide_icon_name(concept)
        if name:
            return name
    if fallback_concept:
        name = lucide_icon_name(fallback_concept)
        if name:
            return name
    return ""


def check_and_log_miss(sl, logger=None) -> bool:
    """slide 의 fallback_reason 검사. 비어있지 않으면 *부족 신호* 로 카운트.

    Args:
        sl: SlideSpec
        logger: 옵션 — 있으면 .info() 호출

    Returns:
        True if catalog miss recorded.
    """
    hint = get_hint(sl)
    reason = (hint.get("fallback_reason") or "").strip()
    if not reason:
        return False
    record_catalog_miss(getattr(sl, "id", "?"), reason)
    if logger is not None:
        try:
            logger.info(
                "design_catalog_miss",
                slide_id=getattr(sl, "id", "?"),
                chosen=hint.get("chosen_template", ""),
                reason=reason,
            )
        except Exception:
            pass
    return True


__all__ = [
    "record_catalog_miss",
    "catalog_miss_summary",
    "reset_catalog_miss",
    "get_hint",
    "palette_override",
    "photo_keyword",
    "icon_name",
    "check_and_log_miss",
]

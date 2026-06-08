"""outputs.localization.korean — 한국어 포맷·종결어미 (Phase 5, Part 12-2).

기능:
    - 만/억/조 단위 자동 변환
    - 통화 (₩ vs 만 원)
    - 날짜 (YYYY-MM-DD / YYYY년 M월 D일)
    - 종결어미 일관성 강제 (~합니다 / ~한다 / ~드립니다)
    - 숫자·명사 띄어쓰기 ("12 건" → "12건")
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

# ==============================================================
# 숫자 단위
# ==============================================================


def format_number_ko(value: int | float | None, *, prefer_unit: bool = True) -> str:
    """1만 미만 그대로, 1만 이상 '1.2만/3.4억/4.5조' 단위.

    Args:
        prefer_unit: True 면 단위 변환, False 면 1,000,000 콤마 포맷.
    """
    if value is None:
        return "-"
    try:
        v = float(value)
    except Exception:
        return str(value)
    if not prefer_unit:
        if abs(v) >= 10000 and v.is_integer():
            return f"{int(v):,}"
        return f"{v:,.2f}" if v % 1 else f"{int(v):,}"
    av = abs(v)
    if av >= 1_0000_0000_0000:  # 1조
        return f"{v / 1_0000_0000_0000:.1f}조"
    if av >= 1_0000_0000:  # 1억
        return f"{v / 1_0000_0000:.1f}억"
    if av >= 10000:  # 1만
        return f"{v / 10000:.1f}만"
    if v.is_integer():
        return f"{int(v):,}"
    return f"{v:.2f}"


# ==============================================================
# 통화
# ==============================================================


def format_currency_ko(value: int | float | None, *, unit: str = "원", use_man: bool = True) -> str:
    """1,200,000원 → '₩1,200,000' or '120만 원'."""
    if value is None:
        return "-"
    try:
        v = float(value)
    except Exception:
        return str(value)
    if use_man and abs(v) >= 10000:
        return f"{format_number_ko(v)} {unit}"
    if v.is_integer():
        return f"₩{int(v):,}"
    return f"₩{v:,.0f}"


# ==============================================================
# 날짜·시간
# ==============================================================


def format_date_ko(value: datetime | str | None, *, style: str = "iso") -> str:
    """'2026-06-05' or '2026년 6월 5일'."""
    if value is None:
        return "-"
    dt = _coerce_dt(value)
    if dt is None:
        return str(value)
    if style == "korean":
        return f"{dt.year}년 {dt.month}월 {dt.day}일"
    return dt.strftime("%Y-%m-%d")


def format_datetime_ko(value: datetime | str | None, *, style: str = "iso") -> str:
    """ISO 또는 한국어."""
    if value is None:
        return "-"
    dt = _coerce_dt(value)
    if dt is None:
        return str(value)
    if style == "korean":
        return f"{dt.year}년 {dt.month}월 {dt.day}일 {dt.hour:02d}:{dt.minute:02d}"
    return dt.strftime("%Y-%m-%d %H:%M")


def _coerce_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            try:
                return datetime.strptime(value[:10], "%Y-%m-%d")
            except Exception:
                return None
    return None


# ==============================================================
# 종결어미 일관성
# ==============================================================

_ENDING_GROUPS = {
    "합니다": ["합니다", "입니다", "됩니다", "옵니다"],
    "한다": ["한다", "이다", "된다", "온다"],
    "드립니다": ["드립니다"],
}


def detect_ending_style(text: str) -> str | None:
    """텍스트의 주요 종결어미 그룹 추정."""
    counts: dict[str, int] = {}
    for group, words in _ENDING_GROUPS.items():
        c = sum(text.count(w) for w in words)
        if c > 0:
            counts[group] = c
    if not counts:
        return None
    return max(counts.keys(), key=lambda g: counts[g])


def enforce_ending_consistency(texts: Iterable[str], target: str) -> list[str]:
    """여러 텍스트의 종결어미를 target 으로 일관 통일.

    수동 변환은 tone_calibrator.calibrate_endings 를 사용; 본 함수는
    *감지·일관성 보고용*. 변환된 리스트 반환.
    """
    from outputs.content.tone_calibrator import calibrate_endings

    return [calibrate_endings(t, target) for t in texts]


# ==============================================================
# 띄어쓰기
# ==============================================================


_NUM_NOUN_SPACE = re.compile(r"(\d+)\s+(건|개|명|회·|회|시간|일|분|초|차|위)")


def fix_number_noun_spacing(text: str) -> str:
    """'12 건' → '12건' (한국어 표준 띄어쓰기)."""
    return _NUM_NOUN_SPACE.sub(r"\1\2", text)

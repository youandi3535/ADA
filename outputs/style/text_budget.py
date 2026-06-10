"""outputs.style.text_budget — 글자 예산 (text budget) 헬퍼.

산출 PPT 의 가장 흔한 회귀:
  1) ctx 에서 가져온 문자열이 박스 폭·높이를 *초과* → mid-word truncation
  2) 짧은 박스에 긴 sentence 가 들어가 *오버플로우* → 다음 박스 침범
  3) 박스에 빈 공간 *낭비* → 위계 무너짐

본 모듈은 *박스 기하 (cm) + 폰트 (pt)* → *글자 예산 (chars)* 환산 + 문장 경계 축약을
한 곳에서 처리. 모든 carrier (PPT/PDF/HTML/MD) 에서 동일 룰 사용 가능.

핵심 원칙:
  - **mid-word truncation 금지** — 한국어 음절 / 영문 단어 경계에서만 자름
  - **문장 경계 우선 축약** — "." / "·" / "—" / "/" / "," 우선 순위로 끊음
  - **줄바꿈 안전** — 박스 폭 기반으로 자동 줄바꿈 위치 추정

사용 예:
    >>> # 박스 5cm × 1.5cm, 11pt 본문
    >>> budget = char_budget(width_cm=5, height_cm=1.5, font_pt=11)
    >>> # → 약 36자 (2줄, 한글 18자/줄)
    >>> shortened = fit_text("긴 문장입니다 ... ", budget)
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

# ==============================================================
# 1) 폰트 → 글자 폭 환산 (한글 1ch vs 영문 1ch)
# ==============================================================

# 폰트 pt 당 한글 음절의 평균 폭 (cm). Malgun Gothic·NanumGothic 기준 실측 근사.
# 12pt → 약 0.42 cm.
_HANGUL_CM_PER_PT = 0.0356

# 폰트 pt 당 영문/숫자 평균 글자 폭 (cm). 한글의 약 0.55 배.
_LATIN_CM_PER_PT = 0.0196

# 행간 (line height) = 폰트 pt × 1.25 (전형값) → cm.
# 1pt ≈ 0.0353 cm.
_LINE_HEIGHT_CM_PER_PT = 0.0441


def _is_wide_char(c: str) -> bool:
    """한글·CJK·전각 기호 등 *2cell* 너비 문자 여부.

    unicodedata.east_asian_width 기준 "W"(Wide)·"F"(Fullwidth) 만 True.
    이모지·일부 기호는 unicodedata 가 'N' 으로 돌려 폭 오차 가능 — 본 함수는
    *글자 예산* 추정 용도이므로 ±10% 는 허용 범위.
    """
    if not c:
        return False
    try:
        return unicodedata.east_asian_width(c) in ("W", "F")
    except Exception:
        return False


def visual_length(text: str) -> float:
    """텍스트의 *시각적* 길이를 한글 음절 단위로 환산.

    한글 1자 = 1.0, 영문/숫자/공백 = 0.55, 전각 기호 = 1.0.
    실제 글자 수(`len`)와 다름 — 박스 fitting 추정에 사용.
    """
    if not text:
        return 0.0
    total = 0.0
    for c in text:
        if _is_wide_char(c):
            total += 1.0
        else:
            total += 0.55
    return total


# ==============================================================
# 2) 박스 기하 → 글자 예산
# ==============================================================


@dataclass(frozen=True)
class TextBudget:
    """박스 한 칸이 담을 수 있는 글자 예산.

    한글 기준의 음절 수를 사용 (영문은 약 1.8 배 더 들어감).
    """

    chars_per_line: int  # 한 줄에 들어가는 한글 음절 추정치
    max_lines: int  # 줄 수 상한 (행간 고려)
    total_chars: int  # chars_per_line × max_lines
    font_pt: float
    width_cm: float
    height_cm: float


def char_budget(
    width_cm: float,
    height_cm: float,
    font_pt: float = 11.0,
    padding_cm: float = 0.2,
    line_spacing: float = 1.25,
) -> TextBudget:
    """박스 기하 + 폰트 → 글자 예산.

    - ``padding_cm`` — 좌·우 (또는 상·하) 한 면 padding (양면 = padding_cm × 2)
    - ``line_spacing`` — 행간 배율. 기본 1.25 (실측 보수치)
    """
    effective_w = max(0.0, width_cm - padding_cm * 2)
    effective_h = max(0.0, height_cm - padding_cm * 2)
    if effective_w <= 0 or effective_h <= 0 or font_pt <= 0:
        return TextBudget(0, 0, 0, font_pt, width_cm, height_cm)

    # 1줄 글자 수 추정 — 한글 기준 폭으로 환산
    char_w = font_pt * _HANGUL_CM_PER_PT
    chars_per_line = max(1, int(effective_w / char_w))

    # 줄 수 = 효과 높이 / (폰트 높이 × line_spacing)
    line_h = font_pt * _LINE_HEIGHT_CM_PER_PT * line_spacing
    max_lines = max(1, int(effective_h / line_h))

    return TextBudget(
        chars_per_line=chars_per_line,
        max_lines=max_lines,
        total_chars=chars_per_line * max_lines,
        font_pt=font_pt,
        width_cm=width_cm,
        height_cm=height_cm,
    )


# ==============================================================
# 3) 문장 경계 축약 — mid-word truncation 금지
# ==============================================================

# 문장 끊기 우선순위 — 앞쪽이 높은 우선순위.
# 한국어·영문 혼용 보고서 톤 기준.
_SENTENCE_DELIMS: tuple[str, ...] = (
    "다. ", "요. ", "음. ", "임. ", ". ",  # 한국어/영문 마침표
    "다.\n", "요.\n", ". \n", ".\n",  # 줄바꿈 직전
    " — ", " · ", " / ", ", ",  # mid-sentence 끊기
    " ",  # 최후 — 단어 경계
)

# 후행에 둘 ellipsis 마커. 한국어 보고서엔 "…" 보다 " 등" 이 자연.
_TRUNCATION_SUFFIX = " 등"


def _find_safe_cut(text: str, max_visual: float) -> int:
    """``text`` 의 ``max_visual`` 이하에서 끊을 *최선의* 인덱스 반환.

    문장 부호 → mid-sentence 끊기 → 단어 경계 → 마지막엔 음절 경계.
    한글 음절 / 영문 단어 *중간* 은 절대 자르지 않음.
    """
    if not text:
        return 0
    if visual_length(text) <= max_visual:
        return len(text)

    # 1) 문장 경계 우선
    for delim in _SENTENCE_DELIMS:
        # 가장 뒤쪽 (가장 많이 담는) 끊을 위치 탐색
        cur = 0
        best = -1
        while True:
            idx = text.find(delim, cur)
            if idx < 0:
                break
            cut = idx + len(delim)
            if visual_length(text[:cut]) <= max_visual:
                best = cut
                cur = cut
            else:
                break
        if best > 0:
            return best

    # 2) 어떤 구분자도 못 찾았으면 — 음절 경계 (한글은 음절 단위, 영문은 단어 단위)
    # 영문/숫자 단어 중간을 안 자르도록 *공백* 단위로만 끊음
    cur = 0
    best = 0
    while cur < len(text):
        # 다음 공백 찾기
        next_space = text.find(" ", cur)
        if next_space < 0:
            # 공백 없음 — 음절 단위로 한 글자씩 (한글 케이스)
            for i in range(len(text), cur, -1):
                if visual_length(text[:i]) <= max_visual:
                    return i
            return cur
        # 공백 까지 포함해 가능한지 시험
        if visual_length(text[: next_space + 1]) <= max_visual:
            best = next_space + 1
            cur = next_space + 1
        else:
            # 공백 직전이라도 들어가나?
            if visual_length(text[:next_space]) <= max_visual:
                return next_space
            return best if best > 0 else cur

    return best


def fit_text(
    text: str,
    budget: TextBudget,
    suffix: Optional[str] = _TRUNCATION_SUFFIX,
) -> str:
    """텍스트를 글자 예산 이내로 *문장 경계* 에서 축약.

    축약 시 ``suffix`` 부착 ("등" 등). ``suffix=None`` 이면 부착 없음.
    예산 이내면 원문 그대로 반환.
    """
    if not text:
        return ""
    total_budget = float(budget.total_chars)
    if total_budget <= 0:
        return text
    if visual_length(text) <= total_budget:
        return text

    # suffix 가 차지하는 폭 만큼 깎고 끊기
    suffix_w = visual_length(suffix or "")
    cut_budget = max(1.0, total_budget - suffix_w)
    cut = _find_safe_cut(text, cut_budget)
    head = text[:cut].rstrip(" ,;·—/")
    if not head:
        # 너무 짧은 예산 — 그래도 한 토큰은 보이게
        return text[:1]
    if suffix:
        return head + suffix
    return head


# ==============================================================
# 4) 줄바꿈 — 박스 폭에 맞춘 자동 wrap
# ==============================================================


def wrap_lines(text: str, chars_per_line: int) -> list[str]:
    """``text`` 를 ``chars_per_line`` (한글 음절 기준) 폭으로 줄 단위 분할.

    문장 부호·공백·음절 경계에서만 끊음. 영문 단어 중간 안 자름.
    """
    if not text or chars_per_line <= 0:
        return [text] if text else []

    lines: list[str] = []
    remaining = text.strip()
    while remaining:
        if visual_length(remaining) <= chars_per_line:
            lines.append(remaining)
            break
        cut = _find_safe_cut(remaining, float(chars_per_line))
        if cut <= 0:
            # 어떻게도 못 끊으면 강제 1자 (안전망)
            cut = 1
        lines.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return lines


# ==============================================================
# 5) 단위 포매터 — 0.693 / 69% / +36% 혼용 방지
# ==============================================================


def format_metric(
    value: float,
    metric_name: str = "",
    *,
    as_percent: Optional[bool] = None,
    decimals: int = 3,
) -> str:
    """metric 값 단일 포매터.

    - ``as_percent=True`` → "69.3%" (0~1 입력 시 자동 ×100)
    - ``as_percent=False`` → "0.693" (소수 유지)
    - ``as_percent=None`` → metric_name 보고 자동 결정 (accuracy/recall 등은 % 로)

    decimals 는 % 표기 시 1~2자리, 소수 표기 시 3자리 디폴트가 일반적.
    """
    name = (metric_name or "").strip().lower()
    pct_names = {"accuracy", "recall", "precision", "f1", "roc_auc", "pr_auc", "coverage"}

    if as_percent is None:
        as_percent = name in pct_names

    if as_percent:
        # 0~1 입력은 ×100, 이미 0~100 범위면 그대로
        pct = value * 100 if abs(value) <= 1.5 else value
        return f"{pct:.{max(1, decimals - 1)}f}%"
    return f"{value:.{decimals}f}"


def format_delta(value: float, *, unit: str = "%p", positive_sign: bool = True) -> str:
    """차이값 포매터 — "+36%p" / "-2.1%p" 등.

    ``unit`` 은 "%p" / "%" / "" 중 택. ``positive_sign=True`` 면 양수에 + 부착.
    """
    sign = "+" if (value > 0 and positive_sign) else ("-" if value < 0 else "")
    return f"{sign}{abs(value):.1f}{unit}"


__all__ = [
    "TextBudget",
    "visual_length",
    "char_budget",
    "fit_text",
    "wrap_lines",
    "format_metric",
    "format_delta",
]

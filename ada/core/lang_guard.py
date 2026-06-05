"""ada.core.lang_guard — 응답 언어 강제 (한국어 only).

qwen2.5:7b 등 다국어 모델은 system_prompt 가 영어이거나 입력에 영문 컬럼명·
중국어 토큰이 섞이면 중국어 한자로 응답하는 경향이 있다. 본 모듈은:

  1. ``KOREAN_FORCE_SUFFIX``  - system_prompt 끝에 붙여 한국어 강제 지시
  2. ``contains_cjk_han(text)`` - CJK 한자(漢字) 포함 여부 (한국어는 한글만 사용)
  3. ``looks_non_korean(text)`` - 한자가 많고 한글이 거의 없으면 비한국어로 간주
  4. ``strip_cjk_han(text)`` - 한자 문자를 제거 (마지막 폴백)

R-103/R-501 과 별개로, 산출물 품질 가드용.
"""

from __future__ import annotations

import re

# ──────────────────────────────────────────────────────────────────────
# system_prompt 끝에 붙이는 한국어 강제 지시
# ──────────────────────────────────────────────────────────────────────
KOREAN_FORCE_SUFFIX = (
    "\n\n[언어 규칙 — 반드시 준수]\n"
    "- 모든 응답은 한국어로만 작성한다. 영어 단어는 고유명사·기술 용어에만 제한적 허용.\n"
    "- 중국어 한자(漢字)·간체자·번체자 사용 금지. 절대로 中文·汉字 출력 금지.\n"
    "- 일본어 가나(かな·カナ) 사용 금지.\n"
    "- 입력 데이터에 영문 컬럼명이 있어도 설명·rationale·title 은 모두 한국어로 쓴다.\n"
    "- 한자 사용시 응답이 거부된다."
)

# 한자(CJK Unified Ideographs) 범위
# - 기본:  U+4E00-U+9FFF
# - 확장A: U+3400-U+4DBF
# - 호환:  U+F900-U+FAFF
# - 부수:  U+2E80-U+2EFF (CJK Radicals Supplement)
_CJK_HAN_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿⺀-⻿]")

# 한글 음절 범위 U+AC00-U+D7A3 (가–힣)
_HANGUL_SYLLABLE_RE = re.compile(r"[가-힣]")


def contains_cjk_han(text: str) -> bool:
    """텍스트에 CJK 한자(漢字) 가 1글자라도 있으면 True."""
    if not text:
        return False
    return bool(_CJK_HAN_RE.search(text))


def count_cjk_han(text: str) -> int:
    """CJK 한자 글자 수."""
    if not text:
        return 0
    return len(_CJK_HAN_RE.findall(text))


def count_hangul(text: str) -> int:
    """한글 음절 글자 수."""
    if not text:
        return 0
    return len(_HANGUL_SYLLABLE_RE.findall(text))


def looks_non_korean(text: str, *, min_hangul: int = 3, max_han: int = 0) -> bool:
    """비한국어 응답으로 판정.

    기본 정책: 한자가 1글자라도 있으면 비한국어 (max_han=0).
    한국어 응답에는 한자가 거의 들어가지 않음. 보수적 판정.
    """
    if not text:
        return False
    han = count_cjk_han(text)
    hangul = count_hangul(text)
    # 한자가 max_han 초과 또는 한글이 너무 적으면 비한국어
    if han > max_han:
        return True
    # 응답이 길고 한글이 거의 없으면 비한국어 (영어 단독 응답 등)
    if len(text) > 30 and hangul < min_hangul:
        return True
    return False


def strip_cjk_han(text: str) -> str:
    """한자를 모두 제거 (마지막 폴백). 의미 손상 가능."""
    if not text:
        return text
    return _CJK_HAN_RE.sub("", text)


def with_korean_guard(system_prompt: str) -> str:
    """system_prompt 에 한국어 강제 suffix 부착."""
    if not system_prompt:
        return KOREAN_FORCE_SUFFIX.strip()
    if "[언어 규칙" in system_prompt:
        return system_prompt  # 이미 부착됨
    return system_prompt.rstrip() + KOREAN_FORCE_SUFFIX

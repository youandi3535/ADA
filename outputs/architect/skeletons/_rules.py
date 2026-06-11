"""ADA PDF 라벨·카드 렌더 유틸 — 하드코딩 룰 강제 시행 모듈.

본 모듈을 통해서만 라벨·카드를 렌더하면 다음 룰이 자동 준수됩니다:

  - [B15 라벨밀착룰]  같은 카드 라벨 행 사이에 빈 줄(<br/><br/>) 없음
  - [B18 평이한언어룰] 화살표(→) 사용 금지 (런타임 체크)
  - [B19 라벨구분자룰] 라벨 콜론 앞뒤 공백 한 칸씩 (`<b>이름 :</b> 내용`)

직접 `<b>label:</b>` 패턴을 손으로 쓰지 마세요. 린트 테스트
`_rules_lint.py` 가 위반을 자동 감지합니다.

룰 카탈로그 단일 진실 출처:
  outputs/ADA_PDF_하드코딩_룰.md
"""
from __future__ import annotations

from typing import Iterable, Tuple

__all__ = ["label", "card", "ArrowInLabelError"]


class ArrowInLabelError(ValueError):
    """[B18 평이한언어룰] 위반 — 라벨/내용에 화살표 사용."""


def label(name: str, content: str) -> str:
    """라벨-내용 한 줄 렌더.

    출력 형식: ``<b>이름 :</b> 내용`` (B19 콜론 앞뒤 공백 보장).
    화살표(→) 발견 시 ArrowInLabelError 발생 (B18 강제).

    Args:
        name: 라벨명 (예: "발견", "전처리", "Next Step").
        content: 라벨 본문 (이미 HTML 태그·서식 포함 가능).

    예시::

        >>> label("발견", "Age 결측 177건(19.87%)")
        '<b>발견 :</b> Age 결측 177건(19.87%)'

        >>> label("표적 개입", "고위험군 → 전수 처리")
        Traceback (most recent call last):
            ...
        _rules.ArrowInLabelError: [B18] ...
    """
    if "→" in name or "→" in content:
        raise ArrowInLabelError(
            f"[B18 평이한언어룰] 화살표(→) 사용 금지. "
            f"풀어쓰세요. name={name!r} content={content!r}"
        )
    return f"<b>{name} :</b> {content}"


def card(items: Iterable[Tuple[str, str]], *, bullet: str = "") -> str:
    """라벨-내용 다행 카드 렌더.

    행 사이 구분자는 단일 ``<br/>`` (B15 라벨밀착룰 — 빈 줄 금지).
    각 행은 ``label()`` 통과 → B18·B19 자동 준수.

    Args:
        items: ``[(라벨, 내용), ...]`` 튜플 시퀀스.
        bullet: 각 행 앞에 붙일 글머리표 (예: "▸"). 빈 문자열이면 생략.

    예시::

        >>> card([("발견", "X"), ("처리", "Y")])
        '<b>발견 :</b> X<br/><b>처리 :</b> Y'

        >>> card([("표적 개입", "X"), ("매출 방어", "Y")], bullet="▸")
        '▸ <b>표적 개입 :</b> X<br/>▸ <b>매출 방어 :</b> Y'
    """
    prefix = f"{bullet} " if bullet else ""
    return "<br/>".join(prefix + label(k, v) for k, v in items)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""룰 인덱스 앵커 자동 동기화 — 제목이 바뀌어도 링크가 안 깨지게.

문제: `ADA_PDF_룰_인덱스.md` 의 룰 링크는 `(ADA_PDF_하드코딩_룰.md#슬러그)` 형식인데,
      슬러그는 헤딩 '제목 텍스트'에서 GitHub 규칙으로 계산된다.
      → 카탈로그에서 룰 제목을 바꾸면 인덱스 링크가 **에러 없이 조용히** 끊긴다.

해결: 룰 **ID(B1·C3 …)** 를 안정 키로 삼는다.
      카탈로그 헤딩(`#### B1. [페이지수룰]`)에서 ID→현재슬러그를 계산하고,
      인덱스 링크의 텍스트 맨 앞 ID 를 보고 슬러그를 현재값으로 자동 교정한다.
      제목을 어떻게 바꾸든 이 스크립트 한 번이면 링크가 다시 맞는다.

사용:
    python -m outputs.dev_sync_rule_anchors           # 교정(인플레이스, .bak 백업)
    python -m outputs.dev_sync_rule_anchors --check   # 검사만 (깨진 링크 있으면 exit 1)

* GitHub / VS Code 마크다운 미리보기 슬러그 규칙 기준.
* 인덱스의 메타(A) 룰은 의도적으로 링크하지 않으므로 '누락'에서 제외(B·C만 점검).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "ADA_PDF_하드코딩_룰.md"
INDEX = HERE / "ADA_PDF_룰_인덱스.md"
CATALOG_NAME = "ADA_PDF_하드코딩_룰.md"

# 카탈로그 헤딩 중 "## ~ #### 로 시작 + 룰ID. " 형태
HEADING_RE = re.compile(r"^#{2,4}\s+([ABC]\d+)\.\s+(.*?)\s*$")
# 인덱스 안의 카탈로그 링크: [텍스트](ADA_PDF_하드코딩_룰.md#슬러그)
LINK_RE = re.compile(r"\[([^\]]+)\]\(" + re.escape(CATALOG_NAME) + r"#([^)]+)\)")
# 링크 텍스트 맨 앞의 룰 ID
ID_RE = re.compile(r"\s*([ABC]\d+)\b")


def gh_slug(text: str) -> str:
    """GitHub(github-slugger) 슬러그: 소문자화 → 문자/숫자/_/-/공백만 유지 → 공백을 -로."""
    s = text.strip().lower()
    kept = [ch for ch in s if ch.isalnum() or ch in "_- "]
    return "".join(kept).replace(" ", "-")


def build_id_to_slug(catalog_text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in catalog_text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            rid, title = m.group(1), m.group(2)
            # 슬러그는 'B1. [페이지수룰]' 전체(번호 포함)에서 계산해야 GitHub와 동일
            mapping[rid] = gh_slug(f"{rid}. {title}")
    return mapping


def _extract_id(link_text: str) -> str | None:
    m = ID_RE.match(link_text)
    return m.group(1) if m else None


def run(check: bool = False) -> int:
    catalog_text = CATALOG.read_text(encoding="utf-8")
    index_text = INDEX.read_text(encoding="utf-8")
    id2slug = build_id_to_slug(catalog_text)

    fixes: list[tuple[str, str, str]] = []   # (id, old, new)
    problems: list[tuple[str, str]] = []     # (id-or-text, reason)

    def repl(mo: re.Match) -> str:
        text, slug = mo.group(1), mo.group(2)
        rid = _extract_id(text)
        if rid is None:
            problems.append((text, "링크 텍스트에서 룰 ID 추출 실패"))
            return mo.group(0)
        if rid not in id2slug:
            problems.append((rid, "카탈로그에 해당 룰 헤딩 없음(고아 링크)"))
            return mo.group(0)
        correct = id2slug[rid]
        if slug != correct:
            fixes.append((rid, slug, correct))
            return f"[{text}]({CATALOG_NAME}#{correct})"
        return mo.group(0)

    new_index = LINK_RE.sub(repl, index_text)

    linked_ids = {_extract_id(m.group(1)) for m in LINK_RE.finditer(index_text)}
    missing = sorted(
        rid for rid in id2slug
        if rid not in linked_ids and rid[0] in "BC"
    )

    print(f"카탈로그 룰 {len(id2slug)}개 · 인덱스 링크 {len(linked_ids)}개")

    if check:
        for rid, old, new in fixes:
            print(f"  ❌ 깨짐 {rid}: #{old} → #{new}")
        for rid, why in problems:
            print(f"  ⚠️ {rid}: {why}")
        if missing:
            print(f"  ℹ️ 인덱스에 링크 없는 B/C 룰: {', '.join(missing)}")
        ok = not fixes and not problems
        print("✅ 모든 앵커 정상" if ok
              else "→ `python -m outputs.dev_sync_rule_anchors` 로 자동 교정하세요")
        return 0 if ok else 1

    if new_index != index_text:
        shutil.copy2(INDEX, str(INDEX) + ".bak")
        INDEX.write_text(new_index, encoding="utf-8")
        print(f"교정 {len(fixes)}건 (백업: {INDEX.name}.bak):")
        for rid, old, new in fixes:
            print(f"  {rid}: #{old} → #{new}")
    else:
        print("변경 없음 — 모든 앵커가 이미 최신입니다.")
    for rid, why in problems:
        print(f"  ⚠️ {rid}: {why}")
    if missing:
        print(f"  ℹ️ 인덱스에 링크 없는 B/C 룰: {', '.join(missing)}")
    return 0


def main() -> None:
    sys.exit(run(check="--check" in sys.argv[1:]))


if __name__ == "__main__":
    main()

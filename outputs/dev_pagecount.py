#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""outputs.dev_pagecount — 보고서 PDF 렌더 + 페이지 수 측정 (20장 수렴 루프용).

`dev_preview3` 로 렌더한 뒤(또는 기존 PDF 를) 페이지 수를 출력한다.
의존성 경량: pypdf → PyPDF2 → raw 바이트(/Type /Page) 폴백 순으로 자동 시도.

사용 (도커: 앞에 `docker exec -it ada-worker-output` 붙임):
    python -m outputs.dev_pagecount titanic            # 타이타닉 렌더 후 페이지수
    python -m outputs.dev_pagecount                      # Telco 렌더 후 페이지수
    python -m outputs.dev_pagecount dump.json            # 실제 덤프 ctx 렌더 후 페이지수
    python -m outputs.dev_pagecount outputs/report_preview3_titanic.pdf   # 기존 PDF 만 카운트

옵션:
    --target N    수렴 목표(기본 20). 결과에 부족/초과 신호 출력.
    --json        결과를 JSON 한 줄로 출력(루프 파싱용).

출력 예:
    [pagecount] PDF = outputs/report_preview3_titanic.pdf
    [pagecount] pages = 18   (size 612.3 KB)   target 20 → 부족 2장 (풍부화 필요)

NY (HJ 위임) 2026-06 — OUT-02 20장 수렴 측정 전용. 진실=호스트 docker 렌더.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def count_pages(pdf_path: str) -> tuple[int, str]:
    """PDF 페이지 수 반환. (n, 방법). 실패 시 (-1, 'fail')."""
    p = Path(pdf_path)
    # 1) pypdf
    try:
        from pypdf import PdfReader  # type: ignore

        return len(PdfReader(str(p)).pages), "pypdf"
    except Exception:
        pass
    # 2) PyPDF2
    try:
        from PyPDF2 import PdfReader  # type: ignore

        return len(PdfReader(str(p)).pages), "PyPDF2"
    except Exception:
        pass
    # 3) raw 폴백 — "/Type /Page" (뒤에 s 없음) 카운트
    data = p.read_bytes()
    pages = re.findall(rb"/Type\s*/Page(?![s])", data)
    if pages:
        return len(pages), "raw:/Type/Page"
    # 4) 페이지 트리 /Count 최대값
    counts = [int(x) for x in re.findall(rb"/Count\s+(\d+)", data)]
    if counts:
        return max(counts), "raw:/Count"
    return -1, "fail"


def _render(topic_or_dump: str | None) -> str:
    """dev_preview3 로 렌더하고 PDF 경로 반환."""
    from outputs import dev_preview3

    argv = ["dev_pagecount"] + ([topic_or_dump] if topic_or_dump else [])
    return dev_preview3.main(argv)


def main(argv: list[str]) -> int:
    args = argv[1:]
    target = 20
    as_json = False
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--target" and i + 1 < len(args):
            target = int(args[i + 1])
            i += 2
            continue
        if a == "--json":
            as_json = True
            i += 1
            continue
        rest.append(a)
        i += 1

    arg1 = rest[0] if rest else None

    # arg1 이 .pdf 면 카운트만, 아니면 렌더(토픽/덤프) 후 카운트
    if arg1 and arg1.lower().endswith(".pdf"):
        pdf = arg1
    else:
        pdf = _render(arg1)

    p = Path(pdf)
    if not p.exists():
        print(f"[pagecount] ERROR: PDF 없음 → {pdf}")
        return 2

    n, how = count_pages(str(p))
    kb = p.stat().st_size / 1024
    if n < 0:
        print(f"[pagecount] ERROR: 페이지 카운트 실패 → {pdf}")
        return 3

    if n == target:
        signal = f"target {target} → OK (수렴)"
    elif n < target:
        signal = f"target {target} → 부족 {target - n}장 (풍부화 필요)"
    else:
        signal = f"target {target} → 초과 {n - target}장 (차등압축 필요)"

    if as_json:
        print(json.dumps({"pdf": str(p), "pages": n, "target": target,
                          "delta": n - target, "method": how, "kb": round(kb, 1)},
                         ensure_ascii=False))
    else:
        print(f"[pagecount] PDF = {p}")
        print(f"[pagecount] pages = {n}   (size {kb:.1f} KB, via {how})")
        print(f"[pagecount] {signal}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

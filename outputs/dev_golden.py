#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""outputs.dev_golden — 구조 골든 테스트 (골든 1단계). 타이타닉 전용.

dev_pagecount(페이지 수 1개만 검사)의 상위 버전.
PDF에서 '구조 지문(structure fingerprint)'을 뽑아 정답지와 비교한다.
  지문 = {pages, sections:[{title, page}], metrics:[{metric, value, page}]}

→ 페이지 수뿐 아니라 섹션 목록·순서·시작페이지·핵심수치가 바뀌면 빨간불.
  (내가 §7만 고쳤는데 §3가 같이 틀어진 부작용을 자동으로 잡아줌)

사용 (도커: 앞에 `docker exec -it ada-worker-output`):
  python -m outputs.dev_golden --bless     # 현재 렌더를 정답지로 저장(최초/의도된 변경 시)
  python -m outputs.dev_golden             # 비교 — 다르면 exit 1 + 무엇이 바뀌었는지 출력
  python -m outputs.dev_golden --show      # 현재 지문만 출력(저장/비교 안 함)
  python -m outputs.dev_golden --pdf <경로>  # 렌더 대신 기존 PDF 사용

  # 2단계 텍스트 골든 (페이지별 문장 비교 — 내용 버그 검출)
  python -m outputs.dev_golden --text --bless   # 페이지 텍스트를 정답지로 저장
  python -m outputs.dev_golden --text           # 텍스트 비교 — 다른 줄을 +/- 로 출력
  python -m outputs.dev_golden --text --show    # 페이지별 추출 텍스트 미리보기

  # 3단계 비주얼 골든 (표지·핵심 페이지 사진 비교 — 레이아웃/폰트 변화 검출)
  python -m outputs.dev_golden --visual --bless        # 기준 이미지 저장(표지·목차)
  python -m outputs.dev_golden --visual                # 사진 비교 — 다른 픽셀 % 출력
  python -m outputs.dev_golden --visual --pages 1,2,5  # 비교 페이지 지정

정답지: outputs/golden/titanic.json   (의도된 변경 후엔 --bless 로 갱신)
NY(HJ 위임) 2026-06 · 타이타닉 전용 · telco 미사용.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden" / "titanic.json"

# "1. 분석 개요", "9.1 재현 정보" 같은 섹션 헤딩
SEC_RE = re.compile(r"^(\d+(?:\.\d+)?)\.?\s+([가-힣A-Za-z][^\n]{0,40})")
# "AUC 0.83", "정확도 81.5%" 같은 핵심 수치
METRIC_RE = re.compile(r"(AUC|정확도|F1|재현율|정밀도)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?%?)")


def _render_titanic() -> str:
    from outputs import dev_preview3
    return dev_preview3.main(["dev_golden", "titanic"])


def _sections_from_lines(lines: list[str], page: int) -> tuple[list, list]:
    secs, mets = [], []
    for ln in lines:
        ln = ln.strip()
        m = SEC_RE.match(ln)
        if m:
            secs.append({"title": (m.group(1) + ". " + m.group(2).strip())[:44], "page": page})
        mm = METRIC_RE.search(ln)
        if mm:
            mets.append({"metric": mm.group(1), "value": mm.group(2), "page": page})
    return secs, mets


def extract_structure(pdf_path: str) -> dict:
    from pypdf import PdfReader

    r = PdfReader(pdf_path)
    pages = len(r.pages)
    sections, metrics = [], []
    for i, p in enumerate(r.pages, 1):
        t = p.extract_text() or ""
        s, m = _sections_from_lines(t.splitlines(), i)
        sections.extend(s)
        metrics.extend(m)
    # 섹션은 번호 첫 등장만 (중복 제거)
    seen, uniq = set(), []
    for s in sections:
        key = s["title"].split()[0]
        if key not in seen:
            seen.add(key)
            uniq.append(s)
    return {"pages": pages, "sections": uniq, "metrics": metrics[:12]}


def diff(golden: dict, cur: dict) -> list[str]:
    out: list[str] = []
    if golden.get("pages") != cur.get("pages"):
        out.append(f"페이지수 {golden.get('pages')} → {cur.get('pages')}")
    g = {s["title"].split()[0]: s for s in golden.get("sections", [])}
    c = {s["title"].split()[0]: s for s in cur.get("sections", [])}
    for k in sorted(set(g) | set(c), key=lambda x: [float(n) for n in x.rstrip('.').split('.')] if x.rstrip('.').replace('.', '').isdigit() else [99]):
        if k not in c:
            out.append(f"섹션 사라짐: {g[k]['title']}")
        elif k not in g:
            out.append(f"섹션 새로 생김: {c[k]['title']}")
        else:
            if g[k]["title"] != c[k]["title"]:
                out.append(f"{k} 제목변경: '{g[k]['title']}' → '{c[k]['title']}'")
            if g[k]["page"] != c[k]["page"]:
                out.append(f"{k} 시작페이지 {g[k]['page']} → {c[k]['page']}")
    gm = {(m["metric"], m["value"]) for m in golden.get("metrics", [])}
    cm = {(m["metric"], m["value"]) for m in cur.get("metrics", [])}
    for x in sorted(gm - cm):
        out.append(f"수치 사라짐: {x[0]} {x[1]}")
    for x in sorted(cm - gm):
        out.append(f"수치 새로 생김: {x[0]} {x[1]}")
    return out


GOLDEN_TEXT = HERE / "golden" / "titanic_text.json"


def _normalize(t: str) -> str:
    """런마다 바뀌는 값(날짜·페이지번호)·공백을 정규화 → 골든 flaky 방지."""
    t = re.sub(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", "<DATE>", t)
    t = re.sub(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일", "<DATE>", t)
    t = re.sub(r"\bp\.?\s*\d+\b", "<PG>", t)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in t.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def extract_text_pages(pdf_path: str) -> list[str]:
    from pypdf import PdfReader

    r = PdfReader(pdf_path)
    return [_normalize(p.extract_text() or "") for p in r.pages]


def diff_text(golden: list[str], cur: list[str]) -> list[str]:
    import difflib

    out: list[str] = []
    if len(golden) != len(cur):
        out.append(f"페이지 수 {len(golden)} → {len(cur)}")
    for i in range(max(len(golden), len(cur))):
        g = golden[i] if i < len(golden) else ""
        c = cur[i] if i < len(cur) else ""
        if g != c:
            raw = difflib.unified_diff(g.splitlines(), c.splitlines(), lineterm="", n=0)
            body = [ln for ln in raw if ln[:1] in "+-" and not ln.startswith(("+++", "---"))][:6]
            out.append(f"p{i + 1} 텍스트 변경:")
            out.extend("    " + ln for ln in body)
    return out


def _main_text(args: list[str]) -> int:
    pdf = args[args.index("--pdf") + 1] if "--pdf" in args else _render_titanic()
    cur = extract_text_pages(pdf)
    if "--show" in args:
        for i, t in enumerate(cur, 1):
            print(f"--- p{i} ---\n{t[:300]}")
        return 0
    if "--bless" in args:
        GOLDEN_TEXT.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_TEXT.write_text(
            json.dumps({"pages": len(cur), "text": cur}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        print(f"[golden-text] 정답지 저장: {GOLDEN_TEXT} ({len(cur)}p)")
        return 0
    if not GOLDEN_TEXT.exists():
        print("[golden-text] 정답지 없음 → 먼저 `--text --bless` 로 저장하세요.")
        return 2
    golden = json.loads(GOLDEN_TEXT.read_text(encoding="utf-8")).get("text", [])
    d = diff_text(golden, cur)
    if not d:
        print(f"[golden-text] ✅ 페이지 텍스트 일치 ({len(cur)}p)")
        return 0
    changed = sum(1 for x in d if x.endswith("변경:") or x.startswith("페이지 수"))
    print(f"[golden-text] ❌ 텍스트 차이 {changed}곳:")
    for x in d:
        print(x if x.startswith("    ") else "  - " + x)
    print("의도된 변경이면 `--text --bless` 로 갱신.")
    return 1


GOLDEN_VISUAL = HERE / "golden" / "visual"
_VIS_PAGES_DEFAULT = [1, 2]   # 표지 + 목차 (시각 골든은 무겁고 flaky → 핵심 페이지만)
_VIS_TOL = 24                 # 픽셀 채널차 허용(폰트 렌더 미세차 무시)
_VIS_FAIL_RATIO = 0.003       # 임계 초과 픽셀 0.3% 넘으면 변경으로 판정


def _rasterize(pdf_path: str, pages: list[int]) -> dict:
    """선택 페이지를 PIL 이미지로. pymupdf → pdf2image 순. 둘 다 없으면 안내."""
    from PIL import Image

    try:
        import fitz  # pymupdf

        doc = fitz.open(pdf_path)
        out = {}
        for n in pages:
            if 1 <= n <= len(doc):
                pix = doc[n - 1].get_pixmap(dpi=110)
                out[n] = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        return out
    except ImportError:
        pass
    try:
        from pdf2image import convert_from_path

        out = {}
        for n in pages:
            pgs = convert_from_path(pdf_path, dpi=110, first_page=n, last_page=n)
            if pgs:
                out[n] = pgs[0].convert("RGB")
        return out
    except Exception:
        pass
    raise RuntimeError("PDF 래스터라이저 없음 — 호스트에 `pip install pymupdf`(권장) 또는 pdf2image+poppler 설치.")


def _img_diff_ratio(a, b) -> float:
    """두 이미지의 '임계 초과 픽셀 비율'. 0=동일, 클수록 다름."""
    from PIL import ImageChops

    a = a.convert("RGB")
    b = b.convert("RGB")
    if a.size != b.size:
        return 1.0  # 크기부터 다르면 명백한 변경
    d = ImageChops.difference(a, b).convert("L")
    over = sum(d.histogram()[_VIS_TOL + 1:])
    return over / float(a.width * a.height)


def _main_visual(args: list[str]) -> int:
    pages = _VIS_PAGES_DEFAULT
    if "--pages" in args:
        pages = [int(x) for x in args[args.index("--pages") + 1].split(",")]
    pdf = args[args.index("--pdf") + 1] if "--pdf" in args else _render_titanic()
    cur = _rasterize(pdf, pages)
    GOLDEN_VISUAL.mkdir(parents=True, exist_ok=True)

    if "--show" in args:
        for n, im in cur.items():
            p = GOLDEN_VISUAL / f"_cur_p{n:02d}.png"
            im.save(p)
            print(f"[golden-visual] 현재 p{n} → {p}")
        return 0

    if "--bless" in args:
        for n, im in cur.items():
            im.save(GOLDEN_VISUAL / f"titanic_p{n:02d}.png")
        print(f"[golden-visual] 기준 이미지 저장: {GOLDEN_VISUAL} (페이지 {pages})")
        return 0

    missing = [n for n in pages if not (GOLDEN_VISUAL / f"titanic_p{n:02d}.png").exists()]
    if missing:
        print(f"[golden-visual] 기준 이미지 없음(p{missing}) → 먼저 `--visual --bless`.")
        return 2

    from PIL import Image, ImageChops

    bad = []
    for n in pages:
        if n not in cur:
            bad.append((n, 1.0))
            continue
        ref = Image.open(GOLDEN_VISUAL / f"titanic_p{n:02d}.png")
        ratio = _img_diff_ratio(ref, cur[n])
        if ratio > _VIS_FAIL_RATIO:
            cur[n].save(GOLDEN_VISUAL / f"_cur_p{n:02d}.png")
            ImageChops.difference(ref.convert("RGB"), cur[n].convert("RGB")).save(
                GOLDEN_VISUAL / f"_diff_p{n:02d}.png"
            )
            bad.append((n, ratio))
    if not bad:
        print(f"[golden-visual] ✅ 시각 일치 (페이지 {pages}, 허용 {_VIS_FAIL_RATIO * 100:.1f}%)")
        return 0
    print(f"[golden-visual] ❌ 시각 변경 {len(bad)}p:")
    for n, r in bad:
        print(f"  - p{n}: 다른 픽셀 {r * 100:.2f}%  (_cur_p{n:02d}.png · _diff_p{n:02d}.png 확인)")
    print("의도된 변경이면 `--visual --bless` 로 기준 갱신.")
    return 1


def main(argv: list[str]) -> int:
    args = argv[1:]
    if "--text" in args:
        return _main_text(args)
    if "--visual" in args:
        return _main_visual(args)
    pdf = args[args.index("--pdf") + 1] if "--pdf" in args else None
    if pdf is None:
        pdf = _render_titanic()
    cur = extract_structure(pdf)

    if "--show" in args:
        print(json.dumps(cur, ensure_ascii=False, indent=2))
        return 0

    if "--bless" in args:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[golden] 정답지 저장: {GOLDEN}  (pages={cur['pages']}, 섹션 {len(cur['sections'])}개)")
        return 0

    if not GOLDEN.exists():
        print("[golden] 정답지 없음 → 먼저 `--bless` 로 저장하세요.")
        return 2
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    d = diff(golden, cur)
    if not d:
        print(f"[golden] ✅ 정답지와 일치 (pages={cur['pages']}, 섹션 {len(cur['sections'])}개)")
        return 0
    print(f"[golden] ❌ 정답지와 {len(d)}건 차이:")
    for x in d:
        print("  -", x)
    print("의도된 변경이면 `--bless` 로 정답지 갱신.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

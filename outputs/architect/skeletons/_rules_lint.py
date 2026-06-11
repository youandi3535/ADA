"""ADA PDF 하드코딩 룰 정적 린트.

`report_skeleton.py` 등 라벨·카드를 렌더하는 파일을 정적으로 스캔해
하드코딩 룰 위반을 감지합니다.

실행::

    python -m outputs.architect.skeletons._rules_lint

또는 코드에서::

    from outputs.architect.skeletons._rules_lint import lint_file
    violations = lint_file("outputs/architect/skeletons/report_skeleton.py")

규칙:
  - [B15] ``<br/><br/><b>`` 패턴 — 같은 카드 라벨 사이 빈 줄
  - [B18] ``<b>...→...:</b>`` 패턴 — 라벨에 화살표
  - [B19] ``<b>...글자:</b>`` 패턴 — 콜론 앞 공백 누락
  - [direct] ``<b>...:</b>`` 직접 사용 — `_rules.label()` 미경유

도커스트링/주석 안의 ❌ ✅ 예시는 의도된 위반 표시이므로 제외합니다.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[3]
TARGETS = [
    REPO_ROOT / "outputs/architect/skeletons/report_skeleton.py",
    REPO_ROOT / "outputs/carriers/pdf_carrier.py",
]


@dataclass
class Violation:
    rule: str
    file: str
    line: int
    text: str


def _is_doc_example(line: str) -> bool:
    """도커스트링 안의 ❌ ✅ 예시 라인은 스캔에서 제외."""
    stripped = line.lstrip()
    return stripped.startswith(("❌", "✅"))


def lint_file(path: str | Path) -> List[Violation]:
    path = Path(path)
    src = path.read_text(encoding="utf-8")
    out: List[Violation] = []

    # B15: <br/><br/><b> — 같은 카드 라벨 사이 빈 줄
    for m in re.finditer(r"<br/><br/><b>", src):
        line_no = src[: m.start()].count("\n") + 1
        line = src.splitlines()[line_no - 1]
        if _is_doc_example(line):
            continue
        out.append(Violation("B15", str(path), line_no, line.strip()[:120]))

    # B19: <b>...글자:</b> — 콜론 앞 공백 누락
    for m in re.finditer(r"<b>([^<{][^<]*?[가-힣A-Za-z0-9\)]):</b>", src):
        line_no = src[: m.start()].count("\n") + 1
        line = src.splitlines()[line_no - 1]
        if _is_doc_example(line):
            continue
        out.append(Violation("B19", str(path), line_no, line.strip()[:120]))

    # B18: <b>...→...:</b> — 라벨에 화살표
    for m in re.finditer(r"<b>[^<]*→[^<]*\s?:</b>", src):
        line_no = src[: m.start()].count("\n") + 1
        line = src.splitlines()[line_no - 1]
        if _is_doc_example(line):
            continue
        out.append(Violation("B18", str(path), line_no, line.strip()[:120]))

    return out


def main() -> int:
    total = 0
    for target in TARGETS:
        violations = lint_file(target)
        if not violations:
            print(f"[OK] {target.name}: 위반 없음")
            continue
        print(f"\n[FAIL] {target.name}: {len(violations)}건 위반")
        for v in violations:
            print(f"  [{v.rule}] {v.file}:{v.line}  {v.text}")
        total += len(violations)
    if total:
        print(f"\n총 {total}건. 규칙은 outputs/ADA_PDF_하드코딩_룰.md 참조.")
        return 1
    print("\n전체 통과.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

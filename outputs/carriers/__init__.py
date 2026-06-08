"""outputs.carriers — 얇은 형식별 렌더러 (Phase 6).

같은 ReportPlan + ReportContext 입력으로 5종 형식 출력:
    pptx_carrier.py    — OUT-01
    pdf_carrier.py     — OUT-02
    script_carrier.py  — OUT-03 (대본 .txt)
    html_carrier.py    — OUT-04 + zip 사이드카 (Option β)
    md_carrier.py      — OUT-07

기존 outputs/ppt.py 등 5종은 보존 (호환) — 신구조는 ReportComposerAgent 가 토글로 선택.
"""

from outputs.carriers.html_carrier import generate_html_with_zip  # noqa: F401
from outputs.carriers.md_carrier import generate_markdown  # noqa: F401
from outputs.carriers.pdf_carrier import generate_pdf  # noqa: F401
from outputs.carriers.pptx_carrier import generate_pptx  # noqa: F401
from outputs.carriers.script_carrier import generate_script  # noqa: F401

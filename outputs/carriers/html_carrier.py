"""outputs.carriers.html_carrier — OUT-04 HTML + zip 사이드카 (Phase 6, Option β).

HTML 1 파일 안에 zip (Companion 코드) 을 data URI 또는 사이드카 파일로 첨부.
"""

from __future__ import annotations

import base64
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext
from outputs.localization.korean import format_date_ko, format_number_ko
from outputs.style.classification import classification_treatment


def generate_html_with_zip(
    plan: ReportPlan,
    ctx: ReportContext,
    output_path: str | Path,
    *,
    embed_zip_as_data_uri: bool = True,
) -> str:
    """HTML 단일 파일 생성. Companion zip 을 data URI 로 임베드.

    Args:
        embed_zip_as_data_uri: True 면 base64 data URI 로 임베드,
            False 면 같은 디렉토리에 `_report_pack.zip` 사이드카 파일 생성.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1) Companion zip 빌드
    zip_bytes = _build_companion_zip(ctx)
    if embed_zip_as_data_uri:
        zip_href = "data:application/zip;base64," + base64.b64encode(zip_bytes).decode("ascii")
    else:
        sidecar = out.with_name(out.stem + "_report_pack.zip")
        sidecar.write_bytes(zip_bytes)
        zip_href = sidecar.name

    # 2) HTML 본문
    html = _render_html(plan, ctx, zip_href=zip_href)
    out.write_text(html, encoding="utf-8")
    return str(out)


def _build_companion_zip(ctx: ReportContext) -> bytes:
    """ReportContext.code 의 files / notebook_cells → zip 바이트."""
    buf = BytesIO()
    with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
        for f in ctx.code.files:
            zf.writestr(f.path or "file.py", f.content or "")
        # notebook .ipynb 생성
        if ctx.code.notebook_cells:
            nb = _cells_to_ipynb(ctx.code.notebook_cells)
            zf.writestr("notebook.ipynb", json.dumps(nb, ensure_ascii=False, indent=2))
        # README 가 없으면 자동 생성
        if not any(f.path == "README.md" for f in ctx.code.files):
            zf.writestr("README.md", f"# Companion\n\n재현 명령: `{ctx.code.reproduce_command}`\n")
    return buf.getvalue()


def _cells_to_ipynb(cells) -> dict[str, Any]:
    """NotebookCell 리스트 → Jupyter .ipynb 구조."""
    ipy_cells = []
    for c in cells:
        if c.cell_type == "markdown":
            ipy_cells.append({"cell_type": "markdown", "metadata": {}, "source": [c.source]})
        else:
            ipy_cells.append(
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": None,
                    "outputs": c.outputs or [],
                    "source": [c.source],
                }
            )
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3"}},
        "cells": ipy_cells,
    }


def _render_html(plan: ReportPlan, ctx: ReportContext, *, zip_href: str) -> str:
    """단일 HTML 페이지 렌더링."""
    intent = ctx.meta.user_intent or "분석 보고서"
    chosen = ctx.model_selection.chosen.get("name", "-")
    pm = ctx.evaluation.primary_metric or {}
    treatment = classification_treatment(ctx.meta.classification)
    palette_primary = _category_color(ctx.meta.category)

    sections_html = []
    for sec in plan.sections:
        if sec.id == "backup":
            continue
        sec_html = [f'<section class="report-section"><h2>{sec.title}</h2>']
        for sl in sec.slides:
            sec_html.append(_slide_html(sl))
        sec_html.append("</section>")
        sections_html.append("\n".join(sec_html))

    html = f"""<!doctype html><html lang="ko"><head>
<meta charset="utf-8">
<title>{intent}</title>
<style>
:root {{ --primary: {palette_primary}; --ink: #0F172A; --muted: #64748B; --accent: #F1F5F9; }}
body {{ font-family: 'Pretendard', 'Noto Sans KR', sans-serif; color: var(--ink); max-width: 1080px; margin: 24px auto; padding: 0 24px; line-height: 1.5; }}
header.cover {{ border-left: 6px solid var(--primary); padding-left: 16px; margin-bottom: 24px; }}
header.cover h1 {{ margin: 0; font-size: 28px; }}
.pill {{ display:inline-block; padding:4px 10px; border-radius:999px; background:var(--primary); color:#fff; font-size:12px; }}
.so-what {{ font-size: 17px; font-weight: 700; color: var(--primary); margin: 8px 0; }}
.slide {{ background: var(--accent); padding: 14px 18px; border-radius: 8px; margin: 12px 0; }}
.slide h3 {{ margin: 0 0 8px 0; font-size: 16px; }}
.slide ul {{ margin: 6px 0; padding-left: 22px; }}
.notes {{ font-size: 12px; color: var(--muted); margin-top: 6px; }}
footer.report-footer {{ border-top: 1px solid #CBD5E1; margin-top: 32px; padding-top: 12px; color: var(--muted); font-size: 12px; display: flex; justify-content: space-between; }}
.classification {{ color: {treatment.get("footer_color", "#334155")}; font-weight: 600; }}
.download-pack a {{ display: inline-block; margin-top: 12px; padding: 10px 18px; background: var(--primary); color: #fff; border-radius: 6px; text-decoration: none; font-weight: 600; }}
.tldr {{ background: #F1F5F9; padding: 12px 18px; border-radius: 8px; margin: 12px 0; }}
</style>
</head><body>

<header class="cover">
  <h1>{intent}</h1>
  <p><span class="pill">{ctx.meta.category}</span> · 모델 <b>{chosen}</b> · {pm.get("name", "지표")} <b>{pm.get("value", "-")}</b></p>
  <p class="notes">생성일 {format_date_ko(ctx.meta.generated_at, style="korean")} · 데이터 {format_number_ko(ctx.dataset.shape.get("rows"))}행</p>
</header>

<div class="tldr">
  <h3>TL;DR</h3>
  <ul>
    <li>{plan.narrative_thread.setup}</li>
    <li>{plan.narrative_thread.conflict}</li>
    <li>{plan.narrative_thread.resolution}</li>
  </ul>
</div>

{chr(10).join(sections_html)}

<div class="download-pack">
  <a href="{zip_href}" download="report_pack.zip">📦 Companion 코드 다운로드 (zip)</a>
  <p class="notes">재현 명령: <code>{ctx.code.reproduce_command}</code></p>
</div>

<footer class="report-footer">
  <span>ADA v2 · {ctx.meta.job_id}</span>
  <span class="classification">{treatment.get("footer_text", "")}</span>
</footer>

</body></html>"""
    return html


def _slide_html(sl) -> str:
    if sl.role == "meta" and sl.layout in ("cover", "agenda", "closing"):
        return ""
    bullets = "".join(f"<li>{b}</li>" for b in sl.body_outline)
    visual = ""
    if sl.visual_spec and sl.visual_spec.type and sl.visual_spec.type != "text_only":
        visual = f'<p class="notes">[{sl.visual_spec.type}: {sl.visual_spec.title or sl.title_ko}]</p>'
    return f"""<div class="slide">
  <h3>{sl.title_ko}</h3>
  <p class="so-what">{sl.so_what}</p>
  <ul>{bullets}</ul>
  {visual}
</div>"""


def _category_color(category: str | None) -> str:
    from outputs.style.palette import get_palette

    return get_palette(category)["primary"]

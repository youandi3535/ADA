"""outputs.carriers.md_carrier — OUT-07 인사이트 마크다운 (Phase 6)."""

from __future__ import annotations

from pathlib import Path

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext
from outputs.layouts.md_layouts import slide_to_markdown
from outputs.localization.korean import format_date_ko, format_number_ko


def generate_markdown(plan: ReportPlan, ctx: ReportContext, output_path: str | Path) -> str:
    """ReportPlan 전체를 마크다운 1파일로 직렬화."""
    lines: list[str] = []
    intent = ctx.meta.user_intent or "분석 보고서"
    chosen = ctx.model_selection.chosen.get("name", "-")
    pm = ctx.evaluation.primary_metric or {}

    # 헤더 메타
    lines.append(f"# {intent}")
    lines.append("")
    lines.append(
        f"> **카테고리** {ctx.meta.category} · **모델** {chosen} · **{pm.get('name', '지표')}** {pm.get('value', '-')}"
    )
    lines.append(f"> 생성일 {format_date_ko(ctx.meta.generated_at or '', style='korean')}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # TL;DR
    if plan.narrative_thread.resolution:
        lines.append("## TL;DR")
        lines.append("")
        lines.append(f"- {plan.narrative_thread.setup}")
        lines.append(f"- {plan.narrative_thread.conflict}")
        lines.append(f"- {plan.narrative_thread.resolution}")
        lines.append("")

    # 섹션 → 슬라이드
    for sec in plan.sections:
        if sec.id == "backup":  # 백업 슬라이드는 마크다운에 미포함
            continue
        lines.append("---")
        lines.append("")
        lines.append(f"# {sec.title}")
        lines.append("")
        for sl in sec.slides:
            lines.append(slide_to_markdown(sl))
            lines.append("")

    # 출처
    lines.append("---")
    lines.append("")
    lines.append("## 데이터 출처")
    lines.append(
        f"- 데이터셋: `{ctx.dataset.dataset_name}` ({format_number_ko(ctx.dataset.shape.get('rows'))}행 × {ctx.dataset.shape.get('cols')}열)"
    )
    if ctx.domain.kb_citations or ctx.domain.web_citations:
        lines.append("- 인용:")
        for c in ctx.domain.kb_citations[:5]:
            lines.append(f"  - KB: {c.title}")
        for c in ctx.domain.web_citations[:5]:
            lines.append(f"  - 외부: {c.title}")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    return str(out)

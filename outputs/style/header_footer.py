"""outputs.style.header_footer — 슬라이드 헤더/푸터 spec (Phase 4, Part 8-6).

ReportPlan 의 슬라이드별 헤더·푸터 표시 spec 생성.
carrier 가 이 spec 을 PPT/PDF/HTML 로 렌더.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from outputs.architect.plan import ReportPlan, SlideSpec
from outputs.context.schema import ReportContext
from outputs.style.classification import classification_treatment


def build_header_footer_spec(
    plan: ReportPlan, ctx: ReportContext, slide: SlideSpec, slide_index: int
) -> dict[str, Any]:
    """단일 슬라이드의 헤더·푸터 spec.

    Returns:
        {"header": {...}, "footer": {...}, "classification": {...}}
    """
    treatment = classification_treatment(ctx.meta.classification)
    section_title = _section_title_for(plan, slide)
    total = plan.slide_count()

    # 표지/마지막 슬라이드는 헤더 생략
    show_header = slide.role != "meta" or slide.layout not in ("cover", "closing", "section_divider")

    header = (
        {
            "show": show_header,
            "section_label": section_title.upper(),
            "page": f"{slide_index + 1} / {total}",
            "color": "#64748B",
        }
        if show_header
        else {"show": False}
    )

    company = (
        ctx.meta.business_context if (ctx.meta.business_context and len(ctx.meta.business_context) < 30) else "ADA"
    )
    report_title_short = (ctx.meta.user_intent or "분석 보고서")[:40]
    footer = {
        "show": slide.layout != "cover",
        "left": f"{company} · {report_title_short}",
        "center": _format_date(ctx.meta.generated_at),
        "right": treatment["footer_text"],
        "right_color": treatment["footer_color"],
        "color": "#64748B",
    }

    return {
        "header": header,
        "footer": footer,
        "classification": treatment,
    }


def _section_title_for(plan: ReportPlan, slide: SlideSpec) -> str:
    for sec in plan.sections:
        if any(s.id == slide.id for s in sec.slides):
            return sec.title
    return ""


def _format_date(iso: str) -> str:
    if not iso:
        return datetime.utcnow().strftime("%Y-%m-%d")
    try:
        return iso[:10]
    except Exception:
        return ""

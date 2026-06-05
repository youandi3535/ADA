"""outputs.governance.classification_marker — 분류 마킹 carrier-agnostic spec (Phase 6).

style.classification 의 treatment + ReportPlan → 슬라이드별 markup spec.
"""

from __future__ import annotations

from typing import Any

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext
from outputs.style.classification import classification_treatment


def apply_classification(plan: ReportPlan, ctx: ReportContext) -> dict[str, Any]:
    """ReportPlan 의 각 슬라이드에 적용할 분류 마킹 spec.

    Returns:
        {"treatment": {...}, "per_slide_overlay": {...}}
    """
    t = classification_treatment(ctx.meta.classification)

    per_slide_overlay: dict[str, dict] = {}
    for s in plan.all_slides():
        overlay = {
            "footer_right": t["footer_text"],
            "footer_color": t["footer_color"],
        }
        if t.get("header_band"):
            overlay["header_band"] = {"color": t.get("header_band_color", "#DC2626"), "height_pt": 4}
        if t.get("watermark"):
            overlay["watermark"] = t["watermark"]
        per_slide_overlay[s.id] = overlay

    return {"treatment": t, "per_slide_overlay": per_slide_overlay}

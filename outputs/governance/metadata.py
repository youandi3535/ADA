"""outputs.governance.metadata — 보고서 메타 블록 (Phase 6, Part 16-1).

표지 우하단 + 마지막 페이지에 표시될 메타 정보 dict 생성.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext


def build_report_metadata(
    plan: ReportPlan,
    ctx: ReportContext,
    *,
    version: str = "v1",
    parent_report_id: str | None = None,
) -> dict[str, Any]:
    """ReportPlan + ReportContext → 메타 블록 dict."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "job_id": ctx.meta.job_id,
        "report_id": str(uuid.uuid4()),
        "version": version,
        "classification": ctx.meta.classification,
        "generated_by": f"ADA v2 / skeleton={plan.skeleton} / audience={plan.audience}",
        "generated_at": now,
        "data_as_of": ctx.meta.generated_at or now,
        "reviewed_by": None,  # 승인 워크플로우가 채움
        "signature_sha256": "",  # signature.sign_report 가 채움
        "parent_report_id": parent_report_id,
        "audience": plan.audience,
        "category": ctx.meta.category,
        "skeleton": plan.skeleton,
        "slide_count": plan.slide_count(),
    }

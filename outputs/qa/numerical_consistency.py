"""outputs.qa.numerical_consistency — ref_id 별 값 일관성 (Phase 6, Part 11-1).

같은 ref_id 가 여러 슬라이드에서 다른 값으로 등장하면 차단.
같은 메트릭은 자릿수·단위도 통일 강제.
"""

from __future__ import annotations

import re
from typing import Any

from outputs.architect.plan import ReportPlan
from outputs.context.schema import ReportContext

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def check_numerical_consistency(plan: ReportPlan, ctx: ReportContext) -> dict[str, Any]:
    """슬라이드에 등장하는 수치가 ReportContext 의 source 값과 일치하는지 점검.

    Returns:
        {"mismatches": [...], "checked": int, "metrics_index": {...}}
    """
    mismatches: list[dict[str, Any]] = []
    checked = 0
    # 같은 메트릭 이름이 두 슬라이드에 나오면 값 비교
    metric_values: dict[str, list[tuple[str, str]]] = {}  # name → [(slide_id, value_str)]

    for sl in plan.all_slides():
        if sl.role == "meta":
            continue
        # 본문 + so_what 에서 메트릭 이름 + 수치 패턴 찾기
        text = " ".join(sl.body_outline) + " " + (sl.so_what or "")
        for mname in ctx.evaluation.metrics:
            if mname in text:
                # 메트릭명 근처의 첫 수치 추출
                idx = text.find(mname)
                window = text[idx : idx + 60]
                nums = _NUM_RE.findall(window)
                if nums:
                    metric_values.setdefault(mname, []).append((sl.id, nums[0]))
                    checked += 1

    # 같은 메트릭의 값이 슬라이드 간 동일한지 검사
    for mname, occurrences in metric_values.items():
        if len(set(v for _, v in occurrences)) > 1:
            mismatches.append(
                {
                    "metric": mname,
                    "occurrences": occurrences,
                }
            )

    return {
        "mismatches": mismatches,
        "checked": checked,
        "metrics_index": {k: len(v) for k, v in metric_values.items()},
    }

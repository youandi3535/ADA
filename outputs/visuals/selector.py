"""outputs.visuals.selector — SlideSpec.visual_spec.type 자동 선정 (Phase 3, Part 9-5).

규칙:
    1. 사용자 제공 도메인 다이어그램 우선
    2. EDA 차트 ref → chart annotation
    3. 다수 metric → kpi_cards 또는 comparison_table
    4. preprocessing steps → process_linear
    5. interpretation importance → annotated_bar
    6. fallback → one_message (텍스트만)
"""

from __future__ import annotations

from outputs.architect.plan import SlideSpec
from outputs.context.schema import ReportContext

# layout → 추천 visual type 매핑
_LAYOUT_VISUAL_HINT: dict[str, str] = {
    "chart_callout": "chart_annotated_bar",
    "chart_dual": "chart_dual",
    "kpi_cards_3": "kpi_cards",
    "kpi_cards_4": "kpi_cards",
    "kpi_cards_6": "kpi_cards",
    "2x2_matrix": "table_2x2_matrix",
    "process_flow": "diagram_process_linear",
    "process_flow_gantt": "diagram_timeline_gantt",
    "comparison_table": "table_feature_matrix",
    "comparison_before_after": "table_before_after",
    "appendix_table": "table_feature_matrix",
    "one_message_big_number": "kpi_single",
}


def select_visual_type(slide: SlideSpec, ctx: ReportContext) -> str:
    """슬라이드 layout + 사용 가능한 데이터로부터 visual.type 선정."""
    # 사용자가 이미 명시한 경우 보존
    if slide.visual_spec and slide.visual_spec.type:
        return slide.visual_spec.type

    # layout 기반 매핑
    hint = _LAYOUT_VISUAL_HINT.get(slide.layout)
    if hint:
        return hint

    # 데이터 풍부도 기반 폴백
    if slide.data_refs:
        for ref in slide.data_refs:
            if ref.startswith("chart::"):
                return "chart_annotated_bar"
            if ref.startswith("metric::"):
                return "kpi_single"

    # text_only fallback 보강 — body_outline 이 있으면 가벼운 표라도
    if slide.body_outline:
        # body 가 "key: value" 패턴이 많으면 표
        kv_count = sum(1 for b in slide.body_outline if ":" in b)
        if kv_count >= 2:
            return "table_feature_matrix"
        # role 별 분기
        if slide.role == "claim":
            return "kpi_single"
        if slide.role == "evidence":
            return "kpi_cards"
        if slide.role in ("action", "caveat"):
            return "table_feature_matrix"

    return "text_only"

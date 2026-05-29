"""agents.handlers.tabular.output_extras — 정형 산출물 추가 (jh 담당)."""

from __future__ import annotations

from typing import Any


def assets(state: Any, ctx: dict[str, Any]) -> dict[str, Any]:
    output_code = ctx.get("output_code", "")
    category = ctx.get("category", getattr(state, "category", ""))
    label = "정형 ML" if category == "tabular_ml" else "정형 DL"

    extras = getattr(state, "category_extras", {}) or {}
    tabular = extras.get("tabular", {})

    charts: list[Any] = []
    tables: list[dict] = []
    text_blocks: list[str] = []

    # 평가 산출물 (ROC / Calibration / Confusion Matrix)
    eval_charts = tabular.get("eval_charts") or []
    charts.extend(eval_charts)

    # EDA 차트
    eda_charts = getattr(state, "eda_charts", None) or []
    if output_code == "OUT-02":
        charts.extend(eda_charts)

    # 메트릭 테이블
    metrics = tabular.get("metrics") or {}
    if metrics:
        rows = [[k, f"{v:.4f}" if isinstance(v, float) else str(v)] for k, v in metrics.items()]
        tables.append({"title": f"{label} 평가 지표", "columns": ["지표", "값"], "rows": rows})

    # 선택 근거 텍스트
    selector_rationale = tabular.get("selector_rationale")
    if selector_rationale:
        text_blocks.append(selector_rationale)

    return {
        "charts": charts,
        "tables": tables,
        "text_blocks": text_blocks,
    }

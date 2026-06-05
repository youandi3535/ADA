"""outputs.visuals.cards — KPI 카드 4 변형 (Phase 3, Part 9-3).

각 함수는 카드 spec dict 반환 — carrier 가 PPT shape / HTML div / PDF Flowable 로 렌더.

4 변형:
    single          — 수치(거대) + 단위 + 캡션
    delta           — 수치 + 증감 (▲▼ + %) + 비교 기간
    vs_baseline     — 본 값 + baseline 값 + 격차
    trend_sparkline — 수치 + 좌측 스파크라인 + 추세
"""

from __future__ import annotations

from typing import Any

from outputs.visuals.visual_dna import VisualDNA

# confidence marker 매핑
_CONFIDENCE_STAR = {
    "high": "★★★",
    "medium": "★★☆",
    "low": "★☆☆",
}


def kpi_single(
    *,
    name: str,
    value: Any,
    unit: str = "",
    caption: str = "",
    confidence: str = "medium",
    ref_id: str | None = None,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """단일 수치 카드."""
    return {
        "type": "kpi_single",
        "name": name,
        "value": value,
        "value_str": _fmt_number(value),
        "unit": unit,
        "caption": caption,
        "confidence_marker": _CONFIDENCE_STAR.get(confidence, "★★☆"),
        "color": (dna.color_for_data(name) if dna else "#2563eb"),
        "ref_id": ref_id,
    }


def kpi_delta(
    *,
    name: str,
    value: Any,
    delta_pct: float | None = None,
    comparison_label: str = "전기 대비",
    unit: str = "",
    caption: str = "",
    confidence: str = "medium",
    ref_id: str | None = None,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """증감 카드."""
    arrow = "▲" if (delta_pct or 0) > 0 else "▼" if (delta_pct or 0) < 0 else "→"
    success = (dna.semantic.get("success") if dna else "#16A34A") or "#16A34A"
    danger = (dna.semantic.get("danger") if dna else "#DC2626") or "#DC2626"
    color = success if (delta_pct or 0) >= 0 else danger
    return {
        "type": "kpi_delta",
        "name": name,
        "value": value,
        "value_str": _fmt_number(value),
        "delta_pct": delta_pct,
        "delta_str": f"{arrow} {abs(delta_pct):.1f}%" if delta_pct is not None else "",
        "delta_color": color,
        "comparison_label": comparison_label,
        "unit": unit,
        "caption": caption,
        "confidence_marker": _CONFIDENCE_STAR.get(confidence, "★★☆"),
        "ref_id": ref_id,
    }


def kpi_vs_baseline(
    *,
    name: str,
    value: Any,
    baseline_value: Any,
    baseline_name: str = "Baseline",
    unit: str = "",
    caption: str = "",
    ref_id: str | None = None,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """본 값 + baseline 비교 카드."""
    try:
        gap = float(value) - float(baseline_value)
        gap_pct = (gap / float(baseline_value) * 100) if float(baseline_value) else None
    except Exception:
        gap = 0.0
        gap_pct = None
    return {
        "type": "kpi_vs_baseline",
        "name": name,
        "value": value,
        "value_str": _fmt_number(value),
        "baseline_value": baseline_value,
        "baseline_str": _fmt_number(baseline_value),
        "baseline_name": baseline_name,
        "gap": gap,
        "gap_pct": gap_pct,
        "gap_str": f"+{gap_pct:.1f}%" if gap_pct and gap_pct > 0 else (f"{gap_pct:.1f}%" if gap_pct else ""),
        "unit": unit,
        "caption": caption,
        "color": (dna.palette.get("primary") if dna else "#2563eb"),
        "ref_id": ref_id,
    }


def kpi_trend_sparkline(
    *,
    name: str,
    value: Any,
    sparkline: list[float],
    unit: str = "",
    caption: str = "",
    ref_id: str | None = None,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """스파크라인 + 수치 카드."""
    trend = (
        "rising"
        if sparkline and sparkline[-1] > sparkline[0]
        else "falling"
        if sparkline and sparkline[-1] < sparkline[0]
        else "stable"
    )
    return {
        "type": "kpi_trend_sparkline",
        "name": name,
        "value": value,
        "value_str": _fmt_number(value),
        "sparkline": list(sparkline)[:30],  # 30 포인트 제한
        "trend": trend,
        "unit": unit,
        "caption": caption,
        "color": (dna.palette.get("primary") if dna else "#2563eb"),
        "ref_id": ref_id,
    }


# ==============================================================
# 내부
# ==============================================================


def _fmt_number(v: Any) -> str:
    """한국어 친화 숫자 포맷.

    - int: 1,000 / 1.2만 / 3.4억
    - float: 0.85 / 12.3%
    """
    if isinstance(v, str):
        return v
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        if abs(v) >= 100_000_000:
            return f"{v / 100_000_000:.1f}억"
        if abs(v) >= 10_000:
            return f"{v / 10_000:.1f}만"
        return f"{v:,}"
    if isinstance(v, float):
        if 0 < abs(v) < 1:
            return f"{v:.3f}"
        if abs(v) < 100:
            return f"{v:.2f}"
        return f"{v:,.1f}"
    return str(v) if v is not None else "-"

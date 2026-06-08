"""outputs.visuals.charts — 8종 차트 annotator pattern (Phase 3, Part 9-2).

원본 EDA 차트는 데이터, 보고서는 **재가공 차트**.
각 함수는 Plotly figure spec (dict) 반환. carrier 가 Plotly → PNG export.

8 패턴:
    callout              — 차트 위 박스 + 화살표
    threshold_line       — 가로/세로 점선 + 라벨
    highlighted_region   — 시계열 이상 구간 음영
    comparison_overlay   — baseline 선 + 본 모델 선
    top_k_marker         — 상위 N 컬러, 나머지 회색
    trend_arrow          — 추세선 + 끝점 화살표
    ci_band              — 신뢰구간 음영
    segment_color        — 세그먼트별 다른 색
"""

from __future__ import annotations

from typing import Any

from outputs.visuals.visual_dna import VisualDNA


def annotated_bar(
    items: list[tuple[str, float]],
    title: str,
    *,
    dna: VisualDNA | None = None,
    so_what_callout: str | None = None,
    top_k_highlight: int = 3,
) -> dict[str, Any]:
    """막대 차트 + Top-K 마커 + 콜아웃.

    Args:
        items: [(label, value)] 정렬되어 있다고 가정 (큰 값 우선).
    """
    labels = [str(i[0]) for i in items]
    values = [float(i[1]) for i in items]
    colors = []
    primary = (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb"
    neutral = (dna.semantic.get("ink_300") if dna else "#CBD5E1") or "#CBD5E1"
    for i in range(len(items)):
        colors.append(primary if i < top_k_highlight else neutral)

    spec: dict[str, Any] = {
        "engine": "plotly",
        "type": "bar",
        "title": title,
        "data": {
            "x": labels,
            "y": values,
            "marker": {"color": colors},
            "type": "bar",
        },
        "layout": {
            "title": title,
            "margin": {"l": 40, "r": 40, "t": 40, "b": 80},
            "xaxis": {"tickangle": -30},
        },
    }
    if so_what_callout:
        spec["annotations"] = [
            {
                "text": so_what_callout,
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 1.08,
                "showarrow": False,
                "font": {"size": 14, "color": "#0F172A"},
            }
        ]
    return spec


def annotated_line(
    series: list[dict[str, Any]],
    title: str,
    *,
    dna: VisualDNA | None = None,
    threshold: float | None = None,
    highlight_regions: list[tuple[float, float]] | None = None,
    trend_label: str | None = None,
) -> dict[str, Any]:
    """선 그래프 + 임계선 + 이상 구간 음영 + 추세 라벨.

    Args:
        series: [{name, x: [...], y: [...]}]
    """
    primary = (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb"
    danger = (dna.semantic.get("danger") if dna else "#DC2626") or "#DC2626"
    traces = []
    for s in series:
        traces.append(
            {
                "x": s.get("x", []),
                "y": s.get("y", []),
                "type": "scatter",
                "mode": "lines",
                "name": s.get("name", "series"),
                "line": {"color": primary, "width": 2},
            }
        )
    spec: dict[str, Any] = {
        "engine": "plotly",
        "type": "line",
        "title": title,
        "data": traces,
        "layout": {"title": title, "shapes": [], "annotations": []},
    }
    if threshold is not None:
        spec["layout"]["shapes"].append(
            {
                "type": "line",
                "xref": "paper",
                "x0": 0,
                "x1": 1,
                "y0": threshold,
                "y1": threshold,
                "line": {"color": danger, "width": 2, "dash": "dash"},
            }
        )
        spec["layout"]["annotations"].append(
            {
                "x": 0.02,
                "y": threshold,
                "xref": "paper",
                "text": f"임계 {threshold}",
                "showarrow": False,
                "font": {"size": 11, "color": danger},
            }
        )
    if highlight_regions:
        for x0, x1 in highlight_regions:
            spec["layout"]["shapes"].append(
                {
                    "type": "rect",
                    "xref": "x",
                    "yref": "paper",
                    "x0": x0,
                    "x1": x1,
                    "y0": 0,
                    "y1": 1,
                    "fillcolor": danger,
                    "opacity": 0.15,
                    "line": {"width": 0},
                }
            )
    if trend_label:
        spec["layout"]["annotations"].append(
            {
                "x": 0.98,
                "y": 0.9,
                "xref": "paper",
                "yref": "paper",
                "text": trend_label,
                "showarrow": False,
                "font": {"size": 12, "color": "#0F172A"},
            }
        )
    return spec


def comparison_overlay(
    baseline: dict[str, Any],
    target: dict[str, Any],
    title: str,
    *,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """baseline 점선 + 본 모델 실선."""
    primary = (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb"
    neutral = (dna.semantic.get("ink_500") if dna else "#64748B") or "#64748B"
    return {
        "engine": "plotly",
        "type": "line_overlay",
        "title": title,
        "data": [
            {
                "x": baseline.get("x", []),
                "y": baseline.get("y", []),
                "type": "scatter",
                "mode": "lines",
                "name": baseline.get("name", "Baseline"),
                "line": {"color": neutral, "dash": "dot", "width": 2},
            },
            {
                "x": target.get("x", []),
                "y": target.get("y", []),
                "type": "scatter",
                "mode": "lines",
                "name": target.get("name", "Target"),
                "line": {"color": primary, "width": 3},
            },
        ],
        "layout": {"title": title, "legend": {"orientation": "h", "y": -0.2}},
    }


def ci_band(
    x: list[Any],
    mean: list[float],
    lower: list[float],
    upper: list[float],
    title: str,
    *,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """신뢰구간 음영 + 평균선."""
    primary = (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb"
    accent = (dna.palette.get("accent") if dna else "#93c5fd") or "#93c5fd"
    return {
        "engine": "plotly",
        "type": "ci_band",
        "title": title,
        "data": [
            {
                "x": x + x[::-1],
                "y": upper + lower[::-1],
                "fill": "toself",
                "fillcolor": accent,
                "opacity": 0.3,
                "line": {"width": 0},
                "showlegend": False,
                "name": "CI",
            },
            {
                "x": x,
                "y": mean,
                "type": "scatter",
                "mode": "lines",
                "name": "Mean",
                "line": {"color": primary, "width": 2},
            },
        ],
        "layout": {"title": title},
    }


def segment_colored(
    points: list[dict[str, Any]],
    title: str,
    *,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """세그먼트별 다른 색 산점도.

    Args:
        points: [{x, y, segment}]
    """
    # 세그먼트별 색 — DNA color_for_data 활용
    segments: dict[str, dict[str, list]] = {}
    for p in points:
        seg = str(p.get("segment", "default"))
        segments.setdefault(seg, {"x": [], "y": []})
        segments[seg]["x"].append(p.get("x"))
        segments[seg]["y"].append(p.get("y"))
    traces = []
    for seg, xy in segments.items():
        color = dna.color_for_data(seg) if dna else "#2563eb"
        traces.append(
            {
                "x": xy["x"],
                "y": xy["y"],
                "type": "scatter",
                "mode": "markers",
                "name": seg,
                "marker": {"color": color, "size": 7},
            }
        )
    return {
        "engine": "plotly",
        "type": "scatter_segments",
        "title": title,
        "data": traces,
        "layout": {"title": title, "legend": {"orientation": "h"}},
    }


def threshold_chart(
    items: list[tuple[str, float]],
    threshold: float,
    title: str,
    *,
    dna: VisualDNA | None = None,
) -> dict[str, Any]:
    """막대 + 가로 임계선."""
    base = annotated_bar(items, title, dna=dna, top_k_highlight=len(items))
    danger = (dna.semantic.get("danger") if dna else "#DC2626") or "#DC2626"
    base["layout"]["shapes"] = [
        {
            "type": "line",
            "xref": "paper",
            "x0": 0,
            "x1": 1,
            "y0": threshold,
            "y1": threshold,
            "line": {"color": danger, "width": 2, "dash": "dash"},
        }
    ]
    base["layout"].setdefault("annotations", []).append(
        {
            "x": 0.02,
            "y": threshold,
            "xref": "paper",
            "yref": "y",
            "text": f"임계 {threshold}",
            "showarrow": False,
            "font": {"size": 11, "color": danger},
        }
    )
    return base


def trend_arrow_chart(
    x: list[Any],
    y: list[float],
    title: str,
    *,
    dna: VisualDNA | None = None,
    delta_label: str | None = None,
) -> dict[str, Any]:
    """추세선 + 끝점 화살표 + 증감 라벨."""
    primary = (dna.palette.get("primary") if dna else "#2563eb") or "#2563eb"
    spec = {
        "engine": "plotly",
        "type": "trend_arrow",
        "title": title,
        "data": [
            {
                "x": x,
                "y": y,
                "type": "scatter",
                "mode": "lines+markers",
                "line": {"color": primary, "width": 3},
                "name": "trend",
            }
        ],
        "layout": {"title": title, "annotations": []},
    }
    if delta_label and x and y:
        spec["layout"]["annotations"].append(
            {
                "x": x[-1],
                "y": y[-1],
                "ax": x[-1],
                "ay": y[-1] + (max(y) - min(y)) * 0.15,
                "axref": "x",
                "ayref": "y",
                "showarrow": True,
                "arrowhead": 3,
                "text": delta_label,
                "font": {"size": 14, "color": primary},
            }
        )
    return spec


def callout_overlay(
    base_chart_spec: dict[str, Any],
    text: str,
    position: tuple[float, float] = (0.5, 0.9),
) -> dict[str, Any]:
    """기존 차트 spec 에 콜아웃 박스 추가."""
    base_chart_spec.setdefault("layout", {}).setdefault("annotations", []).append(
        {
            "x": position[0],
            "y": position[1],
            "xref": "paper",
            "yref": "paper",
            "text": text,
            "showarrow": False,
            "bgcolor": "rgba(255,255,255,0.9)",
            "bordercolor": "#0F172A",
            "borderwidth": 1,
            "borderpad": 6,
            "font": {"size": 13, "color": "#0F172A"},
        }
    )
    return base_chart_spec

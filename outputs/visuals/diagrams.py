"""outputs.visuals.diagrams — 9종 다이어그램 primitive (Phase 3, Part 9-1).

각 primitive 는 spec dict → ``{type, mermaid_or_pyshape, params}`` 반환.
실제 PNG 변환은 Phase 6 carrier (Mermaid → Kroki/CLI 또는 python-pptx shape).

9종:
    architecture_layered  — 시스템 레이어 (Frontend → API → ...)
    process_linear        — 좌→우 단계 박스
    process_branching     — 분기 의사결정 흐름
    swim_lanes            — 역할별 프로세스 (handler vs orchestrator)
    hub_spoke             — 중앙 + 위성
    agent_map             — 격자 에이전트 맵
    tree_diagram          — 가설 트리·의사결정 트리
    funnel                — 데이터 누적
    timeline_gantt        — 로드맵·장애 타임라인
"""

from __future__ import annotations

from typing import Any

# ==============================================================
# 공개 API — 각 primitive 가 spec dict 반환
# ==============================================================


def architecture_layered(
    layers: list[dict[str, Any]],
    title: str = "시스템 아키텍처",
    *,
    primary_color: str = "#2563eb",
) -> dict[str, Any]:
    """레이어드 아키텍처 다이어그램.

    Args:
        layers: [{name, nodes: [str]}] — 위에서 아래로.
    """
    lines = ["flowchart TB"]
    for i, layer in enumerate(layers):
        sub_id = f"L{i}"
        lines.append(f'    subgraph {sub_id}["{layer.get("name", "Layer")}"]')
        for j, node in enumerate(layer.get("nodes", [])):
            lines.append(f'        {sub_id}_{j}["{node}"]')
        lines.append("    end")
    # 레이어 간 연결
    for i in range(len(layers) - 1):
        lines.append(f"    L{i} --> L{i + 1}")
    return {
        "type": "architecture_layered",
        "engine": "mermaid",
        "title": title,
        "mermaid": "\n".join(lines),
        "params": {"primary_color": primary_color},
    }


def process_linear(steps: list[str], title: str = "프로세스", *, highlight_step: int | None = None) -> dict[str, Any]:
    """좌→우 단계 박스 + 화살표."""
    lines = ["flowchart LR"]
    for i, s in enumerate(steps):
        marker = ":::highlight" if highlight_step == i else ""
        lines.append(f'    S{i}["{s}"]{marker}')
    for i in range(len(steps) - 1):
        lines.append(f"    S{i} --> S{i + 1}")
    if highlight_step is not None:
        lines.append("    classDef highlight fill:#FFD86B,stroke:#D97706,color:#0F172A;")
    return {
        "type": "diagram_process_linear",
        "engine": "mermaid",
        "title": title,
        "mermaid": "\n".join(lines),
        "params": {"step_count": len(steps), "highlight_step": highlight_step},
    }


def process_branching(root: str, branches: list[dict[str, Any]], title: str = "분기 흐름") -> dict[str, Any]:
    """분기 의사결정 흐름.

    Args:
        branches: [{condition, target, leaf?: bool}]
    """
    lines = ["flowchart TD", f'    R(("{root}"))']
    for i, b in enumerate(branches):
        node_id = f"B{i}"
        shape = f"{node_id}{{{b.get('target', '')}}}" if not b.get("leaf") else f'{node_id}["{b.get("target", "")}"]'
        lines.append(f"    {shape}")
        lines.append(f"    R -->|{b.get('condition', '조건')}| {node_id}")
    return {
        "type": "diagram_process_branching",
        "engine": "mermaid",
        "title": title,
        "mermaid": "\n".join(lines),
        "params": {"branch_count": len(branches)},
    }


def swim_lanes(lanes: list[dict[str, Any]], title: str = "역할별 흐름") -> dict[str, Any]:
    """역할(lane)별 횡축 프로세스.

    Args:
        lanes: [{role, steps: [str]}]
    """
    # Mermaid 표준 swimlane 미지원 → subgraph 활용
    lines = ["flowchart LR"]
    for i, lane in enumerate(lanes):
        sub_id = f"LN{i}"
        lines.append(f'    subgraph {sub_id}["{lane.get("role", "Role")}"]')
        for j, step in enumerate(lane.get("steps", [])):
            lines.append(f'        {sub_id}_{j}["{step}"]')
        for j in range(len(lane.get("steps", [])) - 1):
            lines.append(f"        {sub_id}_{j} --> {sub_id}_{j + 1}")
        lines.append("    end")
    return {
        "type": "diagram_swim_lanes",
        "engine": "mermaid",
        "title": title,
        "mermaid": "\n".join(lines),
        "params": {"lane_count": len(lanes)},
    }


def hub_spoke(center: str, spokes: list[str], title: str = "허브-스포크") -> dict[str, Any]:
    """중앙 + 위성 노드들."""
    lines = ["flowchart TD", f'    H(("{center}"))']
    for i, s in enumerate(spokes):
        lines.append(f'    S{i}["{s}"]')
        lines.append(f"    H --- S{i}")
    return {
        "type": "diagram_hub_spoke",
        "engine": "mermaid",
        "title": title,
        "mermaid": "\n".join(lines),
        "params": {"spoke_count": len(spokes)},
    }


def agent_map(grid: list[list[str]], title: str = "에이전트 맵") -> dict[str, Any]:
    """격자형 에이전트/모듈 맵.

    Mermaid 로 표현하기 어려워 carrier (PPT) 가 직접 shape 로 그리는 것이 더 좋음.
    여기서는 spec 으로 grid 만 전달.
    """
    return {
        "type": "diagram_agent_map",
        "engine": "shapes",  # PPT shape API 사용 신호
        "title": title,
        "grid": grid,
        "params": {"rows": len(grid), "cols": max(len(r) for r in grid) if grid else 0},
    }


def tree_diagram(root: str, children: list[dict[str, Any]], title: str = "트리") -> dict[str, Any]:
    """가설/의사결정 트리. children 은 재귀 dict.

    Args:
        children: [{label, children?: [...]}]
    """
    lines = ["flowchart TD", f'    R["{root}"]']
    counter = [0]

    def _walk(parent_id: str, items: list[dict[str, Any]]) -> None:
        for item in items:
            counter[0] += 1
            nid = f"N{counter[0]}"
            lines.append(f'    {nid}["{item.get("label", "")}"]')
            lines.append(f"    {parent_id} --> {nid}")
            if item.get("children"):
                _walk(nid, item["children"])

    _walk("R", children)
    return {
        "type": "diagram_tree",
        "engine": "mermaid",
        "title": title,
        "mermaid": "\n".join(lines),
        "params": {"depth": _tree_depth(children)},
    }


def funnel(stages: list[dict[str, Any]], title: str = "퍼널") -> dict[str, Any]:
    """단계별 누적 (1M → 100K → 10K).

    Args:
        stages: [{label, value}]
    """
    return {
        "type": "diagram_funnel",
        "engine": "shapes",  # PPT 사다리꼴 도형
        "title": title,
        "stages": stages,
        "params": {"stage_count": len(stages)},
    }


def timeline_gantt(events: list[dict[str, Any]], title: str = "타임라인") -> dict[str, Any]:
    """간트 차트.

    Args:
        events: [{phase, start_offset_days, duration_days, milestone?: bool}]
    """
    lines = ["gantt", f"    title {title}", "    dateFormat YYYY-MM-DD"]
    base_date = "2026-06-01"
    section_seen = False
    for ev in events:
        if not section_seen:
            lines.append(f"    section {ev.get('phase', 'Phase')}")
            section_seen = True
        if ev.get("milestone"):
            lines.append(
                f"    {ev.get('phase', 'milestone')} :milestone, m{ev.get('start_offset_days', 0)}, {base_date}, 0d"
            )
        else:
            dur = ev.get("duration_days", 14)
            lines.append(f"    {ev.get('phase', 'task')}: t{ev.get('start_offset_days', 0)}, {base_date}, {dur}d")
    return {
        "type": "diagram_timeline_gantt",
        "engine": "mermaid",
        "title": title,
        "mermaid": "\n".join(lines),
        "params": {"event_count": len(events)},
    }


# ==============================================================
# 내부 유틸
# ==============================================================


def _tree_depth(children: list[dict[str, Any]]) -> int:
    if not children:
        return 0
    return 1 + max(_tree_depth(c.get("children", []) or []) for c in children)

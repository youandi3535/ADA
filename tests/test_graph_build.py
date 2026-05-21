"""LangGraph 25 노드 그래프 build 검증."""
from __future__ import annotations

import pytest


def test_graph_builds():
    pytest.importorskip("langgraph")
    from orchestrator.graph import build_graph

    g = build_graph()
    # compile() 결과는 langgraph 버전에 따라 .get_graph().nodes 구조가 다름
    try:
        nodes = list(g.get_graph().nodes)
    except Exception:
        nodes = list(g.nodes) if hasattr(g, "nodes") else []
    assert len(nodes) >= 25

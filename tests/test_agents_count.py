"""27 에이전트 클래스 카운트 검증."""
from __future__ import annotations


def test_all_agent_classes_27():
    from agents.stubs import ALL_AGENT_CLASSES
    assert len(ALL_AGENT_CLASSES) == 27

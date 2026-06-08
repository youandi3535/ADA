"""28 에이전트 클래스 카운트 검증 (HJ 2026-06-08: ReportArchitectAgent 추가)."""

from __future__ import annotations


def test_all_agent_classes_28():
    from agents.stubs import ALL_AGENT_CLASSES

    assert len(ALL_AGENT_CLASSES) == 28

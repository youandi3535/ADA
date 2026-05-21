"""페르소나 27종 자가 검증."""
from __future__ import annotations


def test_personas_count():
    from agents.personas import PERSONAS

    assert len(PERSONAS) == 27


def test_personas_prefix():
    from agents.personas import PERSONAS

    for name, p in PERSONAS.items():
        assert p.startswith("당신은"), f"{name}: must start with 당신은"

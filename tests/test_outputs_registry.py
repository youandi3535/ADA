"""산출물 5종 등록 자가 검증."""
from __future__ import annotations


def test_generator_count():
    from outputs import GENERATORS
    assert set(GENERATORS.keys()) == {"OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"}


def test_generator_codes():
    from outputs import GENERATORS
    for code, cls in GENERATORS.items():
        assert cls.output_code == code

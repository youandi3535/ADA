"""Harness/KB 단위 테스트 (Day09/Day20)."""

from __future__ import annotations


def test_kb_fingerprint_idempotent():
    from ada.error_handler.auto_handler import fingerprint

    a = fingerprint("ConnectionError at 0x7fa12345 in 192.168.1.10")
    b = fingerprint("ConnectionError at 0xff998877 in 10.0.0.5")
    assert a["hash"] == b["hash"]


def test_distill_constants():
    from ada.harness.distiller import CONFIDENCE_CAP, DECAY_DAYS, DECAY_RATE, RETRACT_CONFIDENCE

    assert CONFIDENCE_CAP == 0.95
    assert RETRACT_CONFIDENCE == 0.20
    assert DECAY_DAYS == 60
    assert DECAY_RATE == 0.9

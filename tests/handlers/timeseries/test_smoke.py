"""timeseries 핸들러 스모크 — 8 모듈 임포트 + 등록 확인."""

from __future__ import annotations


def test_handlers_registered():
    import agents.handlers.timeseries  # noqa: F401
    from agents.handlers import HANDLER_REGISTRY

    reg = HANDLER_REGISTRY["timeseries"]
    for cap in ("profile", "plan", "apply", "charts", "score", "evaluate", "g1", "g2"):
        assert cap in reg, f"missing capability {cap} for timeseries"


def test_proposer_g1(ts_state):
    from agents.handlers.timeseries.proposer import g1

    out = g1(ts_state)
    assert len(out) == 3
    assert all("title" in p and "score" in p for p in out)


def test_selector_score(ts_state):
    from agents.handlers.timeseries.selector import score

    ts_state2 = ts_state.with_update(data_profile={"rows": 500})
    result = score(ts_state2, recipes=[])
    assert "top3" in result and len(result["top3"]) == 3

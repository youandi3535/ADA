"""anomaly 핸들러 스모크."""
from __future__ import annotations


def test_handlers_registered():
    from agents.handlers import HANDLER_REGISTRY
    import agents.handlers.anomaly  # noqa: F401

    reg = HANDLER_REGISTRY["anomaly_detection"]
    for cap in ("profile", "plan", "apply", "charts", "score",
                "evaluate", "g1", "g2"):
        assert cap in reg


def test_profiler_outlier(anomaly_state, anomaly_df):
    from agents.handlers.anomaly.profiler import profile
    extra = profile(anomaly_df, anomaly_state)
    assert "outlier_ratios_iqr" in extra
    assert "contamination_estimate" in extra
    assert 0.001 <= extra["contamination_estimate"] <= 0.5


def test_selector_score(anomaly_state):
    from agents.handlers.anomaly.selector import score
    s = anomaly_state.with_update(data_profile={"rows": 2000, "contamination_estimate": 0.05})
    result = score(s, recipes=[])
    assert len(result["top3"]) == 3

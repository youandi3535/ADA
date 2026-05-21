"""tabular 핸들러 스모크 — 2 카테고리(tabular_ml + tabular_dl) 등록 확인."""
from __future__ import annotations


def test_handlers_registered_ml():
    from agents.handlers import HANDLER_REGISTRY
    import agents.handlers.tabular  # noqa: F401

    for cat in ("tabular_ml", "tabular_dl"):
        reg = HANDLER_REGISTRY[cat]
        for cap in ("profile", "plan", "apply", "charts", "score",
                    "evaluate", "g1", "g2"):
            assert cap in reg, f"missing {cap} for {cat}"


def test_profiler_imbalance(tab_state, tab_df):
    from agents.handlers.tabular.profiler import profile
    extra = profile(tab_df, tab_state)
    assert "class_imbalance_ratio" in extra
    assert "cardinality_levels" in extra


def test_selector_dl(tab_state):
    from agents.handlers.tabular.selector import score
    s = tab_state.with_update(category="tabular_dl", data_profile={"rows": 100})
    result = score(s, recipes=[])
    assert "FTTransformer" in result["top3"]

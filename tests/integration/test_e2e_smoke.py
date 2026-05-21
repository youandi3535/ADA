"""E2E 스모크 — Titanic 데이터로 4 카테고리 중 tabular_ml 만 빠르게."""
from __future__ import annotations

import pytest


@pytest.mark.integration
def test_smoke_imports():
    """모든 모듈 임포트 무결성 — Day20 KP7 자동 회귀 게이트."""
    from agents.stubs import ALL_AGENT_CLASSES
    from orchestrator.graph import build_graph
    from orchestrator.runner import celery_app
    from pipelines.factory import PipelineFactory
    from outputs import GENERATORS

    assert len(ALL_AGENT_CLASSES) == 27
    assert PipelineFactory.supported_categories() == [
        "tabular_ml", "tabular_dl", "timeseries", "anomaly_detection",
    ]
    assert set(GENERATORS) == {"OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"}
    assert celery_app.conf.task_routes["ada.pipeline.run"]["queue"] == "pipeline"

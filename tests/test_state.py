"""PipelineState 불변성/직렬화 테스트."""
from __future__ import annotations


def test_state_with_update(pipeline_state_min):
    new = pipeline_state_min.with_update(retry_count=2)
    assert new.retry_count == 2
    assert pipeline_state_min.retry_count == 0  # 원본 불변


def test_state_to_dict(pipeline_state_min):
    d = pipeline_state_min.to_dict()
    assert d["job_id"] == pipeline_state_min.job_id
    assert d["category"] == "tabular_ml"

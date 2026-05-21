"""PipelineFactory — 4 카테고리 지원."""
from __future__ import annotations

import pytest

from pipelines.factory import PipelineFactory


def test_supported_categories():
    cats = PipelineFactory.supported_categories()
    assert set(cats) == {"tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"}


def test_unknown_category_raises():
    with pytest.raises(ValueError):
        PipelineFactory.create("image")  # v2 에서 제거됨

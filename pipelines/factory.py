"""pipelines.factory — 카테고리별 파이프라인 팩토리 (Day04 §4).

4 카테고리만 지원 (v2 스코프). image/nlp 제거.
"""
from __future__ import annotations

from typing import Type

from pipelines.base import BasePipeline


def _lazy_tabular_ml() -> Type[BasePipeline]:
    from pipelines.tabular_ml import TabularMLPipeline
    return TabularMLPipeline


def _lazy_tabular_dl() -> Type[BasePipeline]:
    from pipelines.tabular_dl import TabularDLPipeline
    return TabularDLPipeline


def _lazy_timeseries() -> Type[BasePipeline]:
    from pipelines.timeseries import TimeSeriesPipeline
    return TimeSeriesPipeline


def _lazy_anomaly() -> Type[BasePipeline]:
    from pipelines.anomaly import AnomalyPipeline
    return AnomalyPipeline


PIPELINE_REGISTRY = {
    "tabular_ml": _lazy_tabular_ml,
    "tabular_dl": _lazy_tabular_dl,
    "timeseries": _lazy_timeseries,
    "anomaly_detection": _lazy_anomaly,
}


class PipelineFactory:
    @staticmethod
    def create(category: str) -> BasePipeline:
        if category not in PIPELINE_REGISTRY:
            raise ValueError(
                f"Unknown category: {category}. "
                f"Allowed: {list(PIPELINE_REGISTRY)} (v2 스코프 4종 한정)"
            )
        cls = PIPELINE_REGISTRY[category]()
        return cls()

    @staticmethod
    def supported_categories() -> list[str]:
        return list(PIPELINE_REGISTRY.keys())

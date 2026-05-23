"""ada.observability.metrics — Prometheus 카운터/히스토그램 (Day 1).

핵심 지표:
    - ada_agent_duration_seconds (Histogram, by agent)
    - ada_agent_errors_total     (Counter,   by agent + error_type)
    - ada_jobs_active            (Gauge)
    - ada_llm_tokens_total       (Counter,   by model + direction)
    - ada_kb_citations_total     (Counter,   by source)

prometheus_client 미설치 환경에서는 stub 객체로 silent no-op.
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        generate_latest,
    )

    _PROM_AVAILABLE = True
except Exception:  # pragma: no cover
    _PROM_AVAILABLE = False

    class _NoopMetric:
        def labels(self, *args: Any, **kwargs: Any) -> "_NoopMetric":
            return self

        def inc(self, *a: Any, **k: Any) -> None:
            return None

        def dec(self, *a: Any, **k: Any) -> None:
            return None

        def observe(self, *a: Any, **k: Any) -> None:
            return None

        def set(self, *a: Any, **k: Any) -> None:
            return None

    class CollectorRegistry:  # type: ignore
        pass

    def generate_latest(_reg: Any = None) -> bytes:  # type: ignore
        return b""

    Counter = Gauge = Histogram = _NoopMetric  # type: ignore


# 전용 레지스트리 — 테스트 격리 + Streamlit/FastAPI 동시 마운트 안전
registry = CollectorRegistry() if _PROM_AVAILABLE else None


def _make(metric_cls: Any, name: str, doc: str, labels: tuple[str, ...] = (), **kwargs: Any) -> Any:
    if not _PROM_AVAILABLE:
        return metric_cls()
    return metric_cls(name, doc, list(labels), registry=registry, **kwargs)


# Histogram — 에이전트 실행 시간 (초 단위)
ada_agent_duration_seconds = _make(
    Histogram,
    "ada_agent_duration_seconds",
    "에이전트 1회 실행 소요 시간(초)",
    labels=("agent",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0),
)

# Counter — 에이전트 에러
ada_agent_errors_total = _make(
    Counter,
    "ada_agent_errors_total",
    "에이전트 실행 중 발생한 에러 누적",
    labels=("agent", "error_type"),
)

# Gauge — 진행 중인 job 수
ada_jobs_active = _make(Gauge, "ada_jobs_active", "현재 RUNNING 상태 job 수")

# Counter — LLM 토큰 사용량
ada_llm_tokens_total = _make(
    Counter,
    "ada_llm_tokens_total",
    "LLM 토큰 누적 사용량 (입력+출력 분리)",
    labels=("model", "direction"),
)

# Counter — KB 인용 누적
ada_kb_citations_total = _make(
    Counter,
    "ada_kb_citations_total",
    "RAG KB 인용 누적 (R-501)",
    labels=("source",),
)


# ----- 편의 API ---------------------------------------------------------------
def record_job_start() -> None:
    try:
        ada_jobs_active.inc()
    except Exception:
        pass


def record_job_complete() -> None:
    try:
        ada_jobs_active.dec()
    except Exception:
        pass


def record_agent_run(agent: str, duration_sec: float, error_type: str | None = None) -> None:
    try:
        ada_agent_duration_seconds.labels(agent=agent).observe(duration_sec)
        if error_type:
            ada_agent_errors_total.labels(agent=agent, error_type=error_type).inc()
    except Exception:
        pass


def record_llm_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    try:
        ada_llm_tokens_total.labels(model=model, direction="input").inc(input_tokens)
        ada_llm_tokens_total.labels(model=model, direction="output").inc(output_tokens)
    except Exception:
        pass


def record_kb_citation(source: str = "self_learning_kb") -> None:
    try:
        ada_kb_citations_total.labels(source=source).inc()
    except Exception:
        pass


def render_metrics() -> bytes:
    """Prometheus exposition 포맷 바이트 반환."""
    if not _PROM_AVAILABLE or registry is None:
        return b"# prometheus_client not installed\n"
    return generate_latest(registry)

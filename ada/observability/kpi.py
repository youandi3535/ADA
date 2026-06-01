"""ada.observability.kpi — KPI 자동 측정 코어 (Day 10 HJ).

5종 KPI:
    KP1 — E2E 성공률          (jobs.status SUCCESS / TERMINAL 비율)
    KP2 — 평균 종단 시간(분)   (AgentRun.duration_ms 합 우선, jobs.updated_at 폴백)
    KP5 — API p95 응답시간(ms) (Prometheus ada_agent_duration_seconds_bucket 보간)
    KP9 — KB 적용률            (AgentRun.payload->>'kb_citations' > 0 인 job 비율)
    + 보조: n_jobs_total / n_jobs_terminal / agent_avg_duration_sec

데이터 소스:
    - DB: ada.db.models.{Job, AgentRun}
    - Prometheus: ada.observability.metrics.render_metrics() (in-process)
    - 외부 Prometheus: settings.kpi_prometheus_url (옵션, GET /api/v1/query)

사용 예시:
    from ada.observability.kpi import compute_kpis, parse_window
    async with AsyncSessionLocal() as db:
        result = await compute_kpis(db, since_hours=parse_window("24h"))
        print(result.model_dump_json())

CLI / API 두 진입점 모두 본 모듈 사용 — 단일 진실 원천 (single source of truth).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.models import AgentRun, Job
from ada.observability.metrics import render_metrics

__all__ = [
    "KPIResponse",
    "compute_kpis",
    "parse_window",
    "SUCCESS_STATUSES",
    "TERMINAL_STATUSES",
    "DEFAULT_WINDOW_HOURS",
]

# ---------------------------------------------------------------------------
# 모듈 상수 (Phase 4-1 status 군집 정규화)
# ---------------------------------------------------------------------------

SUCCESS_STATUSES: tuple[str, ...] = ("succeeded", "completed", "ok")
FAILURE_STATUSES: tuple[str, ...] = ("failed", "timeout", "cancelled")
TERMINAL_STATUSES: tuple[str, ...] = SUCCESS_STATUSES + FAILURE_STATUSES
NEUTRAL_STATUSES: tuple[str, ...] = ("pending", "running")

DEFAULT_WINDOW_HOURS = 24
P95_PERCENTILE = 0.95

# Phase 5-3 — outlier 가드 (분)
_OUTLIER_DURATION_MAX_MIN = 720 * 60.0  # 30일 (분)

# ---------------------------------------------------------------------------
# Phase 2-3 — 윈도우 시간 파싱
# ---------------------------------------------------------------------------


def parse_window(value: int | str) -> int:
    """다양한 윈도우 표기를 시간(int) 으로 정규화.

    허용 형식:
        - 정수 (시간): ``24`` → 24
        - "Nh": ``"24h"`` → 24
        - "Nd": ``"7d"`` → 168
        - "Nw": ``"2w"`` → 336

    제한:
        1 <= hours <= 720 (30일)

    예외:
        ValueError — 형식 오류 또는 범위 초과
    """
    if isinstance(value, int):
        hours = value
    elif isinstance(value, str):
        s = value.strip().lower()
        m = re.fullmatch(r"(\d+)\s*([hdw])", s)
        if not m:
            # 순수 정수 문자열도 허용
            if s.isdigit():
                hours = int(s)
            else:
                raise ValueError(f"invalid window format: {value!r} (expected int / Nh / Nd / Nw)")
        else:
            n = int(m.group(1))
            unit = m.group(2)
            hours = {"h": n, "d": n * 24, "w": n * 24 * 7}[unit]
    else:
        raise ValueError(f"invalid window type: {type(value).__name__}")

    if hours < 1 or hours > 720:
        raise ValueError(f"window out of range: {hours}h (1 <= h <= 720)")
    return hours


# ---------------------------------------------------------------------------
# Phase 2-2 — 응답 스키마
# ---------------------------------------------------------------------------


class KPIResponse(BaseModel):
    """KPI 측정 결과 응답 스키마."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "since_hours": 24,
                "measured_at": "2026-06-01T05:00:00+00:00",
                "kp1_e2e_success_rate": 0.92,
                "kp2_avg_duration_min": 12.34,
                "kp5_p95_api_ms": 850.5,
                "kp9_kb_citation_rate": 0.31,
                "n_jobs_total": 50,
                "n_jobs_terminal": 48,
                "agent_avg_duration_sec": 1.234,
                "data_source": {
                    "kp1": "db.jobs (success=44/48)",
                    "kp2": "db.agent_runs.duration_ms",
                    "kp5": "prometheus.in_process_histogram",
                    "kp9": "db.agent_runs.payload.kb_citations",
                },
                "warnings": [],
            }
        }
    )

    since_hours: int = Field(..., description="측정 윈도우 (시간)")
    measured_at: datetime = Field(..., description="측정 시각 (UTC, ISO 8601)")
    kp1_e2e_success_rate: float | None = Field(None, ge=0.0, le=1.0, description="KP1 E2E 성공률 (0.0~1.0)")
    kp2_avg_duration_min: float | None = Field(None, ge=0.0, description="KP2 평균 종단 시간(분)")
    kp5_p95_api_ms: float | None = Field(None, ge=0.0, description="KP5 API p95 응답시간(ms)")
    kp9_kb_citation_rate: float | None = Field(None, ge=0.0, le=1.0, description="KP9 KB 적용률 (0.0~1.0)")
    n_jobs_total: int = Field(0, ge=0, description="윈도우 내 전체 job 수")
    n_jobs_terminal: int = Field(0, ge=0, description="윈도우 내 종료된 job 수")
    agent_avg_duration_sec: float | None = Field(None, ge=0.0, description="에이전트 1회 평균 실행시간(초)")
    data_source: dict[str, str] = Field(default_factory=dict, description="KPI 별 데이터 출처")
    warnings: list[str] = Field(default_factory=list, description="측정 신뢰도 안내")


# ---------------------------------------------------------------------------
# Phase 3-2 — 메인 진입점
# ---------------------------------------------------------------------------


async def compute_kpis(
    db: AsyncSession,
    *,
    since_hours: int = DEFAULT_WINDOW_HOURS,
    include_prometheus: bool = True,
    prometheus_url: str | None = None,
) -> KPIResponse:
    """5종 KPI 일괄 측정.

    Args:
        db: AsyncSession
        since_hours: 측정 윈도우 (시간, 1~720)
        include_prometheus: KP5 측정 여부 (Prometheus 미가용 환경에서 False)
        prometheus_url: 외부 Prometheus 서버 URL (옵션). None 이면 in-process.

    Returns:
        KPIResponse — 각 KPI 값 + data_source + warnings
    """
    since_hours = parse_window(since_hours)
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=since_hours)
    warnings: list[str] = []
    data_source: dict[str, str] = {}

    # ── 1) jobs + agent_runs 일괄 조회 (DB 왕복 최소화) ─────────────────
    jobs = await _fetch_jobs_in_window(db, since, now, warnings)
    job_ids = [j.id for j in jobs]
    agent_runs_by_job: dict[Any, list[AgentRun]] = {}
    if job_ids:
        try:
            agent_runs_by_job = await _fetch_agent_runs(db, job_ids)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"agent_runs_query_failed: {type(e).__name__}")

    n_total = len(jobs)
    terminal_jobs = [j for j in jobs if (j.status or "").strip().lower() in TERMINAL_STATUSES]
    n_terminal = len(terminal_jobs)

    # 종료율 가드 (Phase 8-2)
    if n_total > 0 and (n_total - n_terminal) / n_total > 0.5:
        warnings.append(f"low_termination_rate: {(n_total - n_terminal) / n_total * 100:.1f}% in-flight")

    # ── 2) 각 KPI 계산 (try/except 로 격리) ────────────────────────────
    try:
        kp1, src1 = _calc_kp1(terminal_jobs)
        data_source["kp1"] = src1
    except Exception as e:  # noqa: BLE001
        kp1 = None
        warnings.append(f"kp1_failed: {type(e).__name__}")

    try:
        kp2, src2 = _calc_kp2(terminal_jobs, agent_runs_by_job, warnings)
        data_source["kp2"] = src2
    except Exception as e:  # noqa: BLE001
        kp2 = None
        warnings.append(f"kp2_failed: {type(e).__name__}")

    if include_prometheus:
        try:
            if prometheus_url:
                kp5, src5 = _calc_kp5_remote(prometheus_url)
            else:
                kp5, src5 = _calc_kp5_in_process()
            data_source["kp5"] = src5
        except Exception as e:  # noqa: BLE001
            kp5 = None
            data_source["kp5"] = "prometheus.error"
            warnings.append(f"kp5_failed: {type(e).__name__}")
    else:
        kp5 = None
        data_source["kp5"] = "prometheus.disabled"

    try:
        kp9, src9 = _calc_kp9(terminal_jobs, agent_runs_by_job)
        data_source["kp9"] = src9
    except Exception as e:  # noqa: BLE001
        kp9 = None
        warnings.append(f"kp9_failed: {type(e).__name__}")

    try:
        avg_sec = await _calc_agent_avg(db, since)
    except Exception as e:  # noqa: BLE001
        avg_sec = None
        warnings.append(f"agent_avg_failed: {type(e).__name__}")

    # ── 3) 표본 신뢰도 안내 ───────────────────────────────────────────
    if n_terminal == 0:
        warnings.append("no_terminal_jobs: KPI 계산 불가 (윈도우 내 종료 job 없음)")
    elif n_terminal < 10:
        warnings.append(f"low_sample_size: terminal n={n_terminal}")

    return KPIResponse(
        since_hours=since_hours,
        measured_at=now,
        kp1_e2e_success_rate=kp1,
        kp2_avg_duration_min=kp2,
        kp5_p95_api_ms=kp5,
        kp9_kb_citation_rate=kp9,
        n_jobs_total=n_total,
        n_jobs_terminal=n_terminal,
        agent_avg_duration_sec=avg_sec,
        data_source=data_source,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# region DB helpers
# ---------------------------------------------------------------------------


async def _fetch_jobs_in_window(db: AsyncSession, since: datetime, now: datetime, warnings: list[str]) -> list[Job]:
    """윈도우 내 jobs 조회 + 미래 시각 가드."""
    rows = (await db.scalars(select(Job).where(Job.created_at >= since))).all()
    valid: list[Job] = []
    future_count = 0
    for j in rows:
        if j.created_at and j.created_at > now:
            future_count += 1
            continue
        valid.append(j)
    if future_count > 0:
        warnings.append(f"clock_skew: {future_count} jobs with future created_at excluded")
    return valid


async def _fetch_agent_runs(db: AsyncSession, job_ids: list[Any]) -> dict[Any, list[AgentRun]]:
    """job_id → AgentRun 목록 매핑 (chunk 분할)."""
    out: dict[Any, list[AgentRun]] = {}
    chunk = 5000
    for i in range(0, len(job_ids), chunk):
        ids = job_ids[i : i + chunk]
        rows = (await db.scalars(select(AgentRun).where(AgentRun.job_id.in_(ids)))).all()
        for r in rows:
            out.setdefault(r.job_id, []).append(r)
    return out


async def _calc_agent_avg(db: AsyncSession, since: datetime) -> float | None:
    """AgentRun.duration_ms 평균 (초 단위)."""
    avg = await db.scalar(select(func.avg(AgentRun.duration_ms)).where(AgentRun.created_at >= since))
    if avg is None:
        return None
    return round(float(avg) / 1000.0, 3)


# ---------------------------------------------------------------------------
# region KPI calculators (Phase 4~7)
# ---------------------------------------------------------------------------


def _calc_kp1(terminal_jobs: list[Job]) -> tuple[float | None, str]:
    """KP1 — terminal jobs 중 success 비율."""
    t = len(terminal_jobs)
    if t == 0:
        return None, "db.jobs (terminal n=0)"
    s = sum(1 for j in terminal_jobs if (j.status or "").strip().lower() in SUCCESS_STATUSES)
    rate = round(s / t, 4)
    return rate, f"db.jobs (success={s}/{t})"


def _resolve_duration(
    job: Job, agent_runs: list[AgentRun] | None
) -> tuple[float | None, Literal["agent_runs_sum", "updated_at_diff", "skip"]]:
    """job 별 duration(분) 해석 + 어느 source 썼는지 반환."""
    # 우선순위 1: AgentRun.duration_ms 합
    if agent_runs:
        total_ms = sum(int(r.duration_ms or 0) for r in agent_runs if r.duration_ms is not None)
        if total_ms > 0:
            return round(total_ms / 1000.0 / 60.0, 4), "agent_runs_sum"

    # 우선순위 2: updated_at - created_at
    started = job.created_at
    finished = job.updated_at
    if started and finished:
        sec = (finished - started).total_seconds()
        if sec < 0:
            sec = abs(sec)
        minutes = sec / 60.0
        if minutes > _OUTLIER_DURATION_MAX_MIN:
            return None, "skip"
        return round(minutes, 4), "updated_at_diff"

    return None, "skip"


def _calc_kp2(
    terminal_jobs: list[Job],
    agent_runs_by_job: dict[Any, list[AgentRun]],
    warnings: list[str],
) -> tuple[float | None, str]:
    """KP2 — 평균 종단 시간 (분). AgentRun 합 우선, updated_at 폴백."""
    if not terminal_jobs:
        return None, "db.jobs (terminal n=0)"

    durations: list[float] = []
    sources_count: dict[str, int] = {"agent_runs_sum": 0, "updated_at_diff": 0, "skip": 0}
    for j in terminal_jobs:
        d, src = _resolve_duration(j, agent_runs_by_job.get(j.id))
        sources_count[src] += 1
        if d is not None:
            durations.append(d)

    if sources_count["skip"] > 0:
        warnings.append(f"kp2_skipped: {sources_count['skip']} jobs missing duration")
    if sources_count["agent_runs_sum"] == 0 and sources_count["updated_at_diff"] > 0:
        warnings.append("kp2_fallback_used: all durations from updated_at (agent_runs empty)")

    if not durations:
        return None, "db.jobs (no_duration_available)"

    avg = round(sum(durations) / len(durations), 2)
    n_ar = sources_count["agent_runs_sum"]
    n_ua = sources_count["updated_at_diff"]
    if n_ar > 0 and n_ua > 0:
        src = f"db.mixed (agent_runs={n_ar}, updated_at={n_ua})"
    elif n_ar > 0:
        src = "db.agent_runs.duration_ms"
    else:
        src = "db.jobs.updated_at-created_at"
    return avg, src


def _calc_kp9(
    terminal_jobs: list[Job],
    agent_runs_by_job: dict[Any, list[AgentRun]],
) -> tuple[float | None, str]:
    """KP9 — AgentRun.payload['kb_citations'] > 0 인 job 비율."""
    t = len(terminal_jobs)
    if t == 0:
        return None, "db.jobs (terminal n=0)"

    cited = 0
    for j in terminal_jobs:
        runs = agent_runs_by_job.get(j.id, [])
        total_citations = 0
        for r in runs:
            payload = r.payload
            if not isinstance(payload, dict):
                continue
            try:
                total_citations += int(payload.get("kb_citations", 0) or 0)
            except (TypeError, ValueError):
                continue
        if total_citations > 0:
            cited += 1

    rate = round(cited / t, 4)
    return rate, f"db.agent_runs.payload.kb_citations ({cited}/{t})"


# ---------------------------------------------------------------------------
# region KP5 — Prometheus histogram
# ---------------------------------------------------------------------------

_BUCKET_RE = re.compile(r'ada_agent_duration_seconds_bucket\{[^}]*le="([0-9.eE+-]+|\+Inf)"[^}]*\}\s+([0-9.eE+-]+)')


def _parse_buckets(prom_text: str) -> dict[str, float]:
    """exposition 텍스트에서 le → cumulative count 매핑 추출 (전체 라벨 합산)."""
    by_le: dict[str, float] = {}
    for le, count in _BUCKET_RE.findall(prom_text):
        try:
            by_le[le] = by_le.get(le, 0.0) + float(count)
        except ValueError:
            continue
    return by_le


def _interpolate_p95(buckets: dict[str, float]) -> float | None:
    """누적 histogram bucket 에서 p95 선형 보간 (초 단위)."""
    if not buckets:
        return None

    total = buckets.get("+Inf")
    if total is None:
        total = max(buckets.values()) if buckets else 0.0
    if total <= 0:
        return None
    target = total * P95_PERCENTILE

    # le 를 float 변환 + 정렬 ("+Inf" → inf)
    items = sorted(
        ((float("inf") if le == "+Inf" else float(le), c) for le, c in buckets.items()),
        key=lambda x: x[0],
    )

    prev_le = 0.0
    prev_count = 0.0
    for le, cnt in items:
        if cnt >= target:
            # tail bucket — 보간 불가
            if le == float("inf"):
                return None
            denom = cnt - prev_count
            if denom <= 0:
                return le
            frac = (target - prev_count) / denom
            return prev_le + frac * (le - prev_le)
        prev_le = le if le != float("inf") else prev_le
        prev_count = cnt
    return None


def _calc_kp5_in_process() -> tuple[float | None, str]:
    """in-process registry 의 histogram 에서 p95 (ms)."""
    body = render_metrics()
    text = body.decode("utf-8", errors="ignore")
    if "ada_agent_duration_seconds" not in text:
        return None, "prometheus.unavailable"
    buckets = _parse_buckets(text)
    if not buckets:
        return None, "prometheus.no_buckets"
    p95_sec = _interpolate_p95(buckets)
    if p95_sec is None:
        return None, "prometheus.tail_or_empty"
    return round(p95_sec * 1000.0, 1), "prometheus.in_process_histogram"


def _calc_kp5_remote(url: str, timeout_sec: float = 3.0) -> tuple[float | None, str]:
    """외부 Prometheus 서버 /api/v1/query 호출 → histogram_quantile(0.95) 반환."""
    query = "histogram_quantile(0.95, sum by (le)(rate(ada_agent_duration_seconds_bucket[5m])))"
    full = f"{url.rstrip('/')}/api/v1/query?query={urllib.request.quote(query)}"
    try:
        req = urllib.request.Request(full, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            import json

            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        # in-process 로 폴백
        kp5, _ = _calc_kp5_in_process()
        if kp5 is not None:
            return kp5, "prometheus.in_process_fallback"
        return None, f"prometheus.remote_failed ({type(e).__name__})"

    if data.get("status") != "success":
        return None, "prometheus.remote_no_data"
    results = data.get("data", {}).get("result", [])
    if not results:
        return None, "prometheus.remote_empty"
    try:
        value = float(results[0]["value"][1])
    except (KeyError, IndexError, ValueError):
        return None, "prometheus.remote_parse_error"
    if value != value:  # NaN check
        return None, "prometheus.remote_nan"
    return round(value * 1000.0, 1), f"prometheus.remote ({url})"


# endregion

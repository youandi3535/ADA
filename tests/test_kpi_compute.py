"""Day 10 — ada.observability.kpi 단위 테스트 (HJ).

검증 범위:
    - parse_window: 정수 / "Nh" / "Nd" / "Nw" / 잘못된 입력
    - _calc_kp1: 빈 list / 전부 성공 / 전부 실패 / 혼합
    - _calc_kp2: AgentRun 합 / updated_at 폴백 / 둘 다 없음
    - _calc_kp9: payload['kb_citations'] 0/1/N
    - _interpolate_p95: 보간 정확도 / tail / 단일 bucket
    - _parse_buckets: 정규식 매칭
    - KPIResponse 스키마 검증
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

_job_seq = itertools.count(1)


def _make_job(status: str, *, created_at: datetime | None = None, updated_at: datetime | None = None):
    """가짜 Job 객체."""
    return SimpleNamespace(
        id=f"job-{next(_job_seq)}",
        status=status,
        created_at=created_at or datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
        updated_at=updated_at or datetime(2026, 6, 1, 0, 12, tzinfo=timezone.utc),
    )


def _make_agent_run(job_id: str, duration_ms: int, payload: dict | None = None):
    return SimpleNamespace(
        job_id=job_id,
        duration_ms=duration_ms,
        payload=payload,
    )


# ----- 1) parse_window -------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (24, 24),
        (1, 1),
        (720, 720),
        ("24", 24),
        ("24h", 24),
        ("7d", 168),
        ("2w", 336),
        ("1H", 1),
        (" 24h ", 24),
    ],
)
def test_parse_window_valid(value, expected):
    from ada.observability.kpi import parse_window

    assert parse_window(value) == expected


@pytest.mark.parametrize("value", ["", "invalid", "5x", "0h", "1000h", 0, 721, -1, 60.5, None, "60m"])
def test_parse_window_invalid(value):
    from ada.observability.kpi import parse_window

    with pytest.raises((ValueError, TypeError)):
        parse_window(value)


# ----- 2) _calc_kp1 ----------------------------------------------------------


def test_calc_kp1_empty():
    from ada.observability.kpi import _calc_kp1

    rate, src = _calc_kp1([])
    assert rate is None
    assert "n=0" in src


def test_calc_kp1_all_success():
    from ada.observability.kpi import _calc_kp1

    jobs = [_make_job("succeeded"), _make_job("completed"), _make_job("ok")]
    rate, src = _calc_kp1(jobs)
    assert rate == 1.0
    assert "3/3" in src


def test_calc_kp1_all_fail():
    from ada.observability.kpi import _calc_kp1

    jobs = [_make_job("failed"), _make_job("timeout"), _make_job("cancelled")]
    rate, src = _calc_kp1(jobs)
    assert rate == 0.0


def test_calc_kp1_mixed():
    from ada.observability.kpi import _calc_kp1

    jobs = [_make_job("succeeded")] * 3 + [_make_job("failed")] * 1
    rate, src = _calc_kp1(jobs)
    assert rate == 0.75


def test_calc_kp1_case_insensitive():
    from ada.observability.kpi import _calc_kp1

    jobs = [_make_job("SUCCEEDED"), _make_job("Completed"), _make_job("OK"), _make_job("FAILED")]
    rate, _ = _calc_kp1(jobs)
    assert rate == 0.75


def test_calc_kp1_null_status():
    from ada.observability.kpi import _calc_kp1

    j = _make_job("succeeded")
    j.status = None
    rate, _ = _calc_kp1([j])
    # null status 는 SUCCESS 도 아니지만 함수 호출자는 이미 TERMINAL 필터한 가정
    # 함수 자체는 null 가드만 보장
    assert rate == 0.0


# ----- 3) _calc_kp2 ----------------------------------------------------------


def test_calc_kp2_empty():
    from ada.observability.kpi import _calc_kp2

    rate, src = _calc_kp2([], {}, [])
    assert rate is None


def test_calc_kp2_agent_runs_sum():
    from ada.observability.kpi import _calc_kp2

    job = _make_job("succeeded")
    runs = [
        _make_agent_run(job.id, 60_000),  # 1분
        _make_agent_run(job.id, 120_000),  # 2분
    ]
    warnings = []
    avg, src = _calc_kp2([job], {job.id: runs}, warnings)
    assert avg == 3.0  # 1+2 = 3분
    assert "agent_runs" in src


def test_calc_kp2_fallback_updated_at():
    from ada.observability.kpi import _calc_kp2

    created = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 6, 1, 0, 10, tzinfo=timezone.utc)
    job = _make_job("succeeded", created_at=created, updated_at=finished)
    warnings = []
    avg, src = _calc_kp2([job], {}, warnings)
    assert avg == 10.0
    assert "updated_at" in src


def test_calc_kp2_mixed():
    from ada.observability.kpi import _calc_kp2

    j1 = _make_job(
        "succeeded",
        created_at=datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 1, 0, 10, tzinfo=timezone.utc),
    )
    j2 = _make_job("completed")
    runs2 = [_make_agent_run(j2.id, 300_000)]  # 5분
    warnings = []
    avg, src = _calc_kp2([j1, j2], {j2.id: runs2}, warnings)
    # j1 = 10분, j2 = 5분 → 평균 7.5
    assert avg == 7.5
    assert "mixed" in src


# ----- 4) _calc_kp9 ----------------------------------------------------------


def test_calc_kp9_empty():
    from ada.observability.kpi import _calc_kp9

    rate, _ = _calc_kp9([], {})
    assert rate is None


def test_calc_kp9_all_zero():
    from ada.observability.kpi import _calc_kp9

    jobs = [_make_job("succeeded") for _ in range(3)]
    runs = {j.id: [_make_agent_run(j.id, 1000, payload={"kb_citations": 0})] for j in jobs}
    rate, _ = _calc_kp9(jobs, runs)
    assert rate == 0.0


def test_calc_kp9_all_cited():
    from ada.observability.kpi import _calc_kp9

    jobs = [_make_job("succeeded") for _ in range(3)]
    runs = {j.id: [_make_agent_run(j.id, 1000, payload={"kb_citations": 5})] for j in jobs}
    rate, _ = _calc_kp9(jobs, runs)
    assert rate == 1.0


def test_calc_kp9_partial():
    from ada.observability.kpi import _calc_kp9

    jobs = [_make_job("succeeded") for _ in range(4)]
    runs = {
        jobs[0].id: [_make_agent_run(jobs[0].id, 1000, payload={"kb_citations": 2})],
        jobs[1].id: [_make_agent_run(jobs[1].id, 1000, payload={})],
        jobs[2].id: [_make_agent_run(jobs[2].id, 1000, payload=None)],
        jobs[3].id: [_make_agent_run(jobs[3].id, 1000, payload={"kb_citations": "invalid"})],
    }
    rate, _ = _calc_kp9(jobs, runs)
    assert rate == 0.25  # 1 cited / 4 total


def test_calc_kp9_accumulates_across_runs():
    from ada.observability.kpi import _calc_kp9

    job = _make_job("succeeded")
    runs = [
        _make_agent_run(job.id, 1000, payload={"kb_citations": 0}),
        _make_agent_run(job.id, 1000, payload={"kb_citations": 3}),
    ]
    rate, _ = _calc_kp9([job], {job.id: runs})
    assert rate == 1.0


# ----- 5) _parse_buckets + _interpolate_p95 ----------------------------------


def test_parse_buckets_basic():
    from ada.observability.kpi import _parse_buckets

    text = "\n".join(
        [
            'ada_agent_duration_seconds_bucket{agent="X",le="0.1"} 50',
            'ada_agent_duration_seconds_bucket{agent="X",le="0.5"} 90',
            'ada_agent_duration_seconds_bucket{agent="X",le="+Inf"} 100',
        ]
    )
    b = _parse_buckets(text)
    assert b == {"0.1": 50.0, "0.5": 90.0, "+Inf": 100.0}


def test_parse_buckets_multi_agent_sums():
    from ada.observability.kpi import _parse_buckets

    text = "\n".join(
        [
            'ada_agent_duration_seconds_bucket{agent="X",le="0.1"} 10',
            'ada_agent_duration_seconds_bucket{agent="Y",le="0.1"} 20',
            'ada_agent_duration_seconds_bucket{agent="X",le="+Inf"} 30',
            'ada_agent_duration_seconds_bucket{agent="Y",le="+Inf"} 40',
        ]
    )
    b = _parse_buckets(text)
    assert b["0.1"] == 30.0
    assert b["+Inf"] == 70.0


def test_interpolate_p95_basic():
    from ada.observability.kpi import _interpolate_p95

    # total=100, target=95 → cnt=95 at le=1.0 → p95 = 1.0
    buckets = {"0.1": 50.0, "0.5": 90.0, "1.0": 95.0, "5.0": 100.0, "+Inf": 100.0}
    p = _interpolate_p95(buckets)
    assert p is not None
    assert 0.5 < p <= 1.0


def test_interpolate_p95_tail():
    from ada.observability.kpi import _interpolate_p95

    # target 이 +Inf 안에만 들어가면 None
    buckets = {"0.1": 0.0, "+Inf": 100.0}
    p = _interpolate_p95(buckets)
    assert p is None


def test_interpolate_p95_empty():
    from ada.observability.kpi import _interpolate_p95

    assert _interpolate_p95({}) is None
    assert _interpolate_p95({"+Inf": 0.0}) is None


# ----- 6) KPIResponse 스키마 -----------------------------------------------


def test_kpi_response_schema_validates():
    from ada.observability.kpi import KPIResponse

    r = KPIResponse(
        since_hours=24,
        measured_at=datetime.now(timezone.utc),
        kp1_e2e_success_rate=0.92,
        kp2_avg_duration_min=12.5,
        kp5_p95_api_ms=850.0,
        kp9_kb_citation_rate=0.3,
        n_jobs_total=10,
        n_jobs_terminal=8,
        agent_avg_duration_sec=1.2,
    )
    assert r.kp1_e2e_success_rate == 0.92
    assert r.n_jobs_total == 10


def test_kpi_response_rejects_out_of_range():
    from pydantic import ValidationError

    from ada.observability.kpi import KPIResponse

    with pytest.raises(ValidationError):
        KPIResponse(
            since_hours=24,
            measured_at=datetime.now(timezone.utc),
            kp1_e2e_success_rate=1.5,  # > 1.0
        )


def test_kpi_response_nullable_kpis():
    from ada.observability.kpi import KPIResponse

    r = KPIResponse(
        since_hours=24,
        measured_at=datetime.now(timezone.utc),
        kp1_e2e_success_rate=None,
        kp9_kb_citation_rate=None,
    )
    assert r.kp1_e2e_success_rate is None
    assert r.n_jobs_total == 0


# ----- 7) compute_kpis 통합 (mock DB) ----------------------------------------


class _MockSession:
    """compute_kpis 가 호출하는 최소 인터페이스 stub."""

    def __init__(self, jobs, agent_runs_by_job, avg_ms=None):
        self.jobs = jobs
        self.agent_runs_by_job = agent_runs_by_job
        self.avg_ms = avg_ms
        self._call_count = 0

    async def scalars(self, query):
        self._call_count += 1
        # 첫 호출 = jobs select, 두번째 = agent_runs select
        if self._call_count == 1:
            return _MockResult(self.jobs)
        # agent_runs IN (...)
        all_runs = []
        for runs in self.agent_runs_by_job.values():
            all_runs.extend(runs)
        return _MockResult(all_runs)

    async def scalar(self, query):
        return self.avg_ms


class _MockResult:
    def __init__(self, items):
        self.items = items

    def all(self):
        return self.items


@pytest.mark.asyncio
async def test_compute_kpis_empty_db():
    from ada.observability.kpi import compute_kpis

    session = _MockSession(jobs=[], agent_runs_by_job={})
    r = await compute_kpis(session, since_hours=24, include_prometheus=False)
    assert r.n_jobs_total == 0
    assert r.kp1_e2e_success_rate is None
    assert any("no_terminal_jobs" in w for w in r.warnings)


@pytest.mark.asyncio
async def test_compute_kpis_basic():
    from ada.observability.kpi import compute_kpis

    jobs = [_make_job("succeeded"), _make_job("succeeded"), _make_job("failed")]
    runs = {
        jobs[0].id: [_make_agent_run(jobs[0].id, 60_000, payload={"kb_citations": 1})],
        jobs[1].id: [_make_agent_run(jobs[1].id, 120_000, payload={"kb_citations": 0})],
    }
    session = _MockSession(jobs=jobs, agent_runs_by_job=runs, avg_ms=1500.0)
    r = await compute_kpis(session, since_hours=24, include_prometheus=False)
    assert r.n_jobs_total == 3
    assert r.n_jobs_terminal == 3
    assert r.kp1_e2e_success_rate == round(2 / 3, 4)
    assert r.kp9_kb_citation_rate == round(1 / 3, 4)
    assert r.agent_avg_duration_sec == 1.5

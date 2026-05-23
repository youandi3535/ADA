"""scripts/kpi_measure.py — Day 10 KPI 측정 (HJ).

5종 KPI 측정 + JSON 결과 출력:
    KP1 — E2E 성공률 (최근 24h 완료 job 중 status=succeeded 비율)
    KP2 — 평균 종단 시간 (분)
    KP5 — API p95 응답 시간 (Prometheus 메트릭에서, 없으면 N/A)
    KP9 — KB 인용률 (KB 인용 ≥1 인 job 비율)
    KP_AGENT_AVG_DURATION — 에이전트 평균 실행 시간 (보조)

사용:
    python scripts/kpi_measure.py            # stdout JSON
    python scripts/kpi_measure.py --since 24 # 최근 24 시간
    python scripts/kpi_measure.py --json     # JSON only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from typing import Any


async def _measure_async(since_hours: int) -> dict[str, Any]:
    """DB + Prometheus 에서 KPI 계산."""
    result: dict[str, Any] = {
        "since_hours": since_hours,
        "measured_at": datetime.utcnow().isoformat() + "Z",
        "KP1_e2e_success_rate": None,
        "KP2_avg_duration_min": None,
        "KP5_p95_api_ms": None,
        "KP9_kb_citation_rate": None,
        "KP_AGENT_AVG_DURATION_SEC": None,
        "n_jobs": 0,
    }
    since = datetime.utcnow() - timedelta(hours=since_hours)

    try:
        from sqlalchemy import func, select

        from ada.db.models import AgentRun, Job
        from ada.db.session import AsyncSessionLocal
    except Exception as e:
        result["error"] = f"db_import_failed: {e}"
        return result

    try:
        async with AsyncSessionLocal() as s:
            # n_jobs + KP1 + KP2
            q = select(Job).where(Job.created_at >= since)
            jobs = (await s.scalars(q)).all()
            result["n_jobs"] = len(jobs)
            if jobs:
                succeeded = [j for j in jobs if (j.status or "").lower() in ("succeeded", "completed", "ok")]
                result["KP1_e2e_success_rate"] = round(len(succeeded) / len(jobs), 4)

                # KP2 — completed 가 시간 컬럼 있다고 가정
                durations: list[float] = []
                for j in jobs:
                    started = getattr(j, "started_at", None) or getattr(j, "created_at", None)
                    finished = getattr(j, "finished_at", None) or getattr(j, "updated_at", None)
                    if started and finished:
                        durations.append((finished - started).total_seconds() / 60.0)
                if durations:
                    result["KP2_avg_duration_min"] = round(sum(durations) / len(durations), 2)

                # KP9 — kb_citations 컬럼 있는 경우
                cited = [j for j in jobs if getattr(j, "kb_citation_count", None) and j.kb_citation_count > 0]
                # fallback: state 의 kb_citations 컬럼이 없으면 None
                if hasattr(Job, "kb_citation_count"):
                    result["KP9_kb_citation_rate"] = round(len(cited) / len(jobs), 4)

            # KP_AGENT_AVG_DURATION — agent_runs.duration_ms 평균
            try:
                avg = await s.scalar(select(func.avg(AgentRun.duration_ms)).where(AgentRun.started_at >= since))
                if avg is not None:
                    result["KP_AGENT_AVG_DURATION_SEC"] = round(float(avg) / 1000.0, 3)
            except Exception:
                pass
    except Exception as e:
        result["error"] = f"db_query_failed: {e}"

    # KP5 — Prometheus exposition 텍스트에서 추출
    try:
        from ada.observability.metrics import render_metrics

        body = render_metrics().decode("utf-8", errors="ignore")
        # 간단한 파서 — ada_agent_duration_seconds_bucket{...,le="..."} 분포에서 p95 근사
        p95 = _approximate_p95(body)
        if p95 is not None:
            result["KP5_p95_api_ms"] = round(p95 * 1000.0, 1)
    except Exception:
        pass

    return result


def _approximate_p95(prom_text: str) -> float | None:
    """Prometheus histogram 텍스트에서 ada_agent_duration_seconds 의 p95 근사."""
    import re

    bucket_rows = re.findall(
        r'ada_agent_duration_seconds_bucket\{[^}]*le="([0-9.+e-]+|\+Inf)"[^}]*\}\s+([\d.]+)',
        prom_text,
    )
    if not bucket_rows:
        return None
    # le → count 매핑 (모든 라벨 통합)
    by_le: dict[str, float] = {}
    for le, count in bucket_rows:
        by_le[le] = by_le.get(le, 0.0) + float(count)
    if not by_le:
        return None
    total = by_le.get("+Inf", max(by_le.values()))
    if total <= 0:
        return None
    target = total * 0.95
    # le 를 float 정렬
    items = sorted(
        ((float("inf") if le == "+Inf" else float(le), c) for le, c in by_le.items()),
        key=lambda x: x[0],
    )
    for le, cnt in items:
        if cnt >= target:
            return None if le == float("inf") else le
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="ADA v2 KPI 측정")
    parser.add_argument("--since", type=int, default=24, help="최근 N 시간 (기본 24)")
    parser.add_argument("--json", action="store_true", help="JSON 만 출력")
    args = parser.parse_args()

    try:
        res = asyncio.run(_measure_async(args.since))
    except Exception as e:
        res = {"error": str(e)}

    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())

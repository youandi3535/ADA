"""scripts/kpi_measure.py — Day 10 KPI 측정 CLI (HJ).

5종 KPI 측정 → JSON 출력. 계산 로직은 ``ada.observability.kpi`` 모듈 위임.

사용:
    python scripts/kpi_measure.py            # stdout JSON (pretty)
    python scripts/kpi_measure.py --since 24 # 최근 24 시간
    python scripts/kpi_measure.py --json     # JSON 만 (압축)
    python scripts/kpi_measure.py --since 7d # 7일

옵션:
    --since N|"Nh"|"Nd"|"Nw"   윈도우 (기본 24시간)
    --json                      compact JSON 출력
    --no-prometheus             KP5 측정 건너뛰기

출력 키 (백워드 호환):
    KP1_e2e_success_rate, KP2_avg_duration_min, KP5_p95_api_ms,
    KP9_kb_citation_rate, KP_AGENT_AVG_DURATION_SEC,
    n_jobs, since_hours, measured_at, data_source, warnings
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

# scripts/ 디렉토리에서 직접 실행 시 repo root를 sys.path에 추가
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


async def _measure_async(since_hours: int, include_prometheus: bool) -> dict[str, Any]:
    """ada.observability.kpi.compute_kpis 호출 + 백워드 호환 키로 변환."""
    try:
        from ada.db.session import AsyncSessionLocal
        from ada.observability.kpi import compute_kpis
    except Exception as e:  # noqa: BLE001
        return _empty_result(since_hours, error=f"import_failed: {e}")

    try:
        async with AsyncSessionLocal() as db:
            kpi = await compute_kpis(db, since_hours=since_hours, include_prometheus=include_prometheus)
    except Exception as e:  # noqa: BLE001
        return _empty_result(since_hours, error=f"db_query_failed: {e}")

    return _to_legacy_dict(kpi)


def _empty_result(since_hours: int, *, error: str) -> dict[str, Any]:
    """DB 연결 실패 등으로 측정 불가 시 폴백 JSON (테스트 호환)."""
    from datetime import datetime, timezone

    return {
        "since_hours": since_hours,
        "measured_at": datetime.now(timezone.utc).isoformat(),
        "KP1_e2e_success_rate": None,
        "KP2_avg_duration_min": None,
        "KP5_p95_api_ms": None,
        "KP9_kb_citation_rate": None,
        "KP_AGENT_AVG_DURATION_SEC": None,
        "n_jobs": 0,
        "n_jobs_total": 0,
        "n_jobs_terminal": 0,
        "data_source": {},
        "warnings": [error],
        "error": error,
    }


def _to_legacy_dict(kpi: Any) -> dict[str, Any]:
    """KPIResponse → 백워드 호환 (UPPER_CASE) dict."""
    return {
        "since_hours": kpi.since_hours,
        "measured_at": kpi.measured_at.isoformat(),
        "KP1_e2e_success_rate": kpi.kp1_e2e_success_rate,
        "KP2_avg_duration_min": kpi.kp2_avg_duration_min,
        "KP5_p95_api_ms": kpi.kp5_p95_api_ms,
        "KP9_kb_citation_rate": kpi.kp9_kb_citation_rate,
        "KP_AGENT_AVG_DURATION_SEC": kpi.agent_avg_duration_sec,
        "n_jobs": kpi.n_jobs_total,
        "n_jobs_total": kpi.n_jobs_total,
        "n_jobs_terminal": kpi.n_jobs_terminal,
        "data_source": kpi.data_source,
        "warnings": kpi.warnings,
    }


# ---------------------------------------------------------------------------
# 백워드 호환 — 기존 코드 / 테스트가 import 하던 함수
# ---------------------------------------------------------------------------


def _approximate_p95(prom_text: str) -> float | None:
    """Prometheus exposition 텍스트에서 ada_agent_duration_seconds 의 p95(초) 근사.

    백워드 호환: tests/test_day10_kpi.py 가 본 함수를 직접 import.
    내부 구현은 ada.observability.kpi 로 위임.
    """
    from ada.observability.kpi import _interpolate_p95, _parse_buckets

    buckets = _parse_buckets(prom_text)
    if not buckets:
        return None
    return _interpolate_p95(buckets)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_since(value: str) -> int:
    """--since 인자 파싱 (정수 또는 "Nh"/"Nd"/"Nw")."""
    from ada.observability.kpi import parse_window

    try:
        return parse_window(value)
    except ValueError:
        # int 폴백 (argparse 가 str 로 받음)
        return parse_window(int(value))


def main() -> int:
    parser = argparse.ArgumentParser(description="ADA v2 KPI 측정")
    parser.add_argument(
        "--since",
        type=str,
        default="24",
        help="윈도우 (시간 또는 '7d'/'2w', 기본 24)",
    )
    parser.add_argument("--json", action="store_true", help="compact JSON 출력")
    parser.add_argument(
        "--no-prometheus",
        action="store_true",
        help="KP5 측정 건너뛰기 (Prometheus 미가용 환경)",
    )
    args = parser.parse_args()

    try:
        since_hours = _parse_since(args.since)
    except (ValueError, TypeError) as e:
        print(json.dumps({"error": f"invalid --since: {e}"}, ensure_ascii=False))
        return 2

    try:
        res = asyncio.run(_measure_async(since_hours, include_prometheus=not args.no_prometheus))
    except Exception as e:  # noqa: BLE001
        res = _empty_result(since_hours, error=str(e))

    if args.json:
        print(json.dumps(res, ensure_ascii=False))
    else:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())

"""Day 10 — KPI 측정 스크립트 + Streamlit KPI 위젯 (정적 검증).

DoD:
    - scripts/kpi_measure.py 가 --since/--json 인자 받고 JSON 출력
    - p95 근사 함수가 Prometheus exposition text 에서 값 추출
    - frontend/app.py 가 KPI 5종 컬럼을 노출하는지 (정적 grep)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(__file__))


# ----- 1) scripts/kpi_measure.py 실행 가능 + JSON 출력 ---------------------------
def test_kpi_script_runs_json():
    p = os.path.join(REPO, "scripts", "kpi_measure.py")
    assert os.path.isfile(p)
    r = subprocess.run(
        [sys.executable, p, "--since", "1", "--json"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=REPO,
    )
    # DB 연결 실패해도 JSON 형태로 결과 + error 반환해야 함
    assert r.stdout.strip(), f"stdout empty. stderr={r.stderr}"
    data = json.loads(r.stdout.strip())
    # 5종 KPI 키 존재 (값은 None 일 수 있음)
    for k in (
        "KP1_e2e_success_rate",
        "KP2_avg_duration_min",
        "KP5_p95_api_ms",
        "KP9_kb_citation_rate",
        "KP_AGENT_AVG_DURATION_SEC",
    ):
        assert k in data, f"missing KPI key: {k}"
    assert "since_hours" in data
    assert "measured_at" in data


# ----- 2) p95 근사 함수가 histogram 텍스트에서 값 추출 -----------------------------
def test_approximate_p95_from_prometheus():
    # 직접 import
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    try:
        from kpi_measure import _approximate_p95
    finally:
        sys.path.pop(0)

    # 합성 exposition — 90% 가 le=0.5 안에, 95% 가 le=1.0 안에
    text = "\n".join(
        [
            'ada_agent_duration_seconds_bucket{agent="X",le="0.1"} 50',
            'ada_agent_duration_seconds_bucket{agent="X",le="0.5"} 90',
            'ada_agent_duration_seconds_bucket{agent="X",le="1.0"} 95',
            'ada_agent_duration_seconds_bucket{agent="X",le="5.0"} 100',
            'ada_agent_duration_seconds_bucket{agent="X",le="+Inf"} 100',
        ]
    )
    p95 = _approximate_p95(text)
    assert p95 is not None
    # p95 가 1.0 또는 5.0 범위 안 (target=95 → 첫 cnt>=95 le = 1.0)
    assert p95 == 1.0, f"got {p95}"


# ----- 3) frontend/app.py 에 KPI 위젯 코드 존재 (정적 grep) ------------------------
def test_frontend_has_kpi_widget():
    p = os.path.join(REPO, "frontend", "app.py")
    src = open(p, encoding="utf-8").read()
    # 5개 KPI 메트릭이 표시 코드에 있는지
    assert "KP1 E2E 성공률" in src
    assert "KP2 평균 종단" in src
    assert "KP5 p95" in src
    assert "KP9 KB 적용률" in src
    # 5번째 탭 등록
    assert "tab5" in src
    assert "KPI 대시보드" in src


# ----- 4) kpi_measure.py — 도움말 잘 나옴 ---------------------------------------
def test_kpi_script_help():
    p = os.path.join(REPO, "scripts", "kpi_measure.py")
    r = subprocess.run([sys.executable, p, "--help"], capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert "--since" in r.stdout
    assert "--json" in r.stdout

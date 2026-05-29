"""tests/handlers/anomaly/test_e2e.py — Day 10 anomaly E2E (NY 단독).

5 시나리오(C1~C4 + 엣지) × 전체 LangGraph 무인 구동. docker 스택(MinIO·Redis·
Postgres) 전제 → 스택 없으면 skip. 로직은 scripts/demo/anomaly_demo.py 재사용.
"""

from __future__ import annotations

import importlib.util
import pathlib
import time

import pytest

SCENARIOS = ["S1", "S2", "S3", "S4", "S5"]
LABELLED = ["S2", "S4"]  # 라벨 有 → AUC 측정 기대
BUDGET_SEC = 300.0  # ★ DoD: 5분


# ── 스택 가용성 (없으면 E2E 전체 skip) ─────────────────────────────────
def _stack_available() -> bool:
    """MinIO 연결 가능 여부 — 단위 CI(스택 미가동)에선 E2E skip."""
    try:
        from tools.minio_tool import get_minio_client

        get_minio_client().list_objects("uploads/demo/")
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _stack_available(), reason="MinIO 미가동 → E2E skip (MemorySaver 라 Postgres·Redis 불요)"),
]


# ── 데모 모듈 동적 로드 (scripts 패키징 가정 회피) ─────────────────────
@pytest.fixture(scope="module")
def demo():
    root = pathlib.Path(__file__).resolve().parents[3]  # tests/handlers/anomaly → repo root
    path = root / "scripts" / "demo" / "anomaly_demo.py"
    spec = importlib.util.spec_from_file_location("anomaly_demo", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader, f"데모 로드 실패: {path}"
    spec.loader.exec_module(mod)
    return mod


# ── 5 시나리오 1회 실행 + 캐시 (E2E 비싸므로 모듈당 1회) ────────────────
@pytest.fixture(scope="module")
def e2e_results(demo):
    t0 = time.time()
    out = {}
    for sid in SCENARIOS:
        try:
            out[sid] = demo.run_scenario(sid)
        except Exception as e:  # noqa: BLE001 — 시나리오 격리, 아래 assert 가 잡음
            out[sid] = {
                "scenario": sid,
                "error": f"{type(e).__name__}: {e}",
                "out04_path": None,
                "top_n_rows": 0,
                "auc": None,
            }
    out["_total_sec"] = time.time() - t0
    return out


# ── #1 A — 완주 + top-N (★ DoD) ────────────────────────────────────────
@pytest.mark.parametrize("sid", SCENARIOS)
def test_scenario_completes(e2e_results, sid):
    r = e2e_results[sid]
    assert r.get("error") is None, f"{sid} 파이프라인 에러: {r.get('error')}"
    assert r.get("out04_path"), f"{sid} OUT-04 미생성"
    assert r.get("top_n_rows", 0) >= 1, f"{sid} top-N 테이블 비어있음"


# ── #2 B — 라벨 시나리오 AUC ───────────────────────────────────────────
@pytest.mark.parametrize("sid", LABELLED)
def test_labelled_scenarios_report_auc(e2e_results, sid):
    r = e2e_results[sid]
    assert r.get("error") is None, f"{sid} 에러: {r.get('error')}"
    assert r.get("auc") is not None, f"{sid} 라벨 시나리오인데 AUC None (Day7 라벨 경로 점검)"


# ── #3 C — 5분 budget (★ DoD) ──────────────────────────────────────────
def test_five_scenarios_within_budget(e2e_results):
    total = e2e_results["_total_sec"]
    assert total < BUDGET_SEC, f"5분 budget 초과: {total:.0f}s > {BUDGET_SEC:.0f}s"


# ── #4 D — 전체 격리(이음매 런타임) ────────────────────────────────────
def test_no_unhandled_error(e2e_results):
    failed = [sid for sid in SCENARIOS if e2e_results[sid].get("error")]
    assert not failed, f"실패 시나리오: {failed}"

"""tests/handlers/timeseries/test_e2e.py - timeseries E2E demo 검증 (cs-day10).

설계도 cs-day10_design.md §6 검증 항목:
  1. 5개 시나리오 각각 OUT-04 에 forecast_chart / decomposition 키 존재
  2. 롤백(R1/R2/R3) 경로가 최소 한 번 이상 동작
  3. 엣지 입력(상수 시계열·날짜축 없음)에도 예외로 죽지 않음
  4. 전체 실행 5분(300s) 이내

원칙: 기존 핸들러는 수정하지 않고 demo 스크립트(scripts/demo/timeseries_demo.py)만 조립 검증.
statsmodels 미설치 환경(CI 최소 deps)에서는 자동 skip.
"""

from __future__ import annotations

import time

import pytest

# statsmodels 없으면 전체 모듈 skip (CI 최소 deps 환경 보호)
pytest.importorskip("statsmodels")
pytest.importorskip("sklearn")

from scripts.demo import timeseries_demo as demo  # noqa: E402


# ════════════════════════════════════════════════════════════════════
# fixtures
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def all_results():
    """5개 시나리오 전체를 한 번 실행하고 결과를 모듈 전역으로 재사용."""
    demo._VERBOSE = False
    results = {}
    t0 = time.time()
    for sc in demo.SCENARIOS:
        results[sc.sid] = demo.run_scenario(sc)
    elapsed = time.time() - t0
    return {"results": results, "elapsed": elapsed}


# ════════════════════════════════════════════════════════════════════
# 1. OUT-04 키 검증 (설계도 §6-1)
# ════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sid", ["S1", "S2", "S3", "S4", "S5"])
def test_scenario_produces_out04_keys(all_results, sid):
    """각 시나리오 OUT-04 에 forecast_chart / decomposition 키가 존재."""
    res = all_results["results"][sid]
    assert res.status in ("ok", "naive_fallback"), f"{sid} 비정상 종료: {res.note}"
    assert res.out04, f"{sid} OUT-04 비어있음"
    assert "forecast_chart" in res.out04, f"{sid} forecast_chart 누락"
    assert "decomposition" in res.out04, f"{sid} decomposition 누락"
    assert res.out04.get("code") == "OUT-04"


@pytest.mark.parametrize("sid", ["S1", "S2", "S3", "S5"])
def test_forecast_chart_has_prediction(all_results, sid):
    """forecast 시나리오는 예측값/실측값이 채워져 있어야 한다."""
    fc = all_results["results"][sid].out04["forecast_chart"]
    assert len(fc["y_pred_val"]) > 0
    assert len(fc["y_val_actual"]) > 0
    assert len(fc["y_pred_val"]) == len(fc["y_val_actual"])


# ════════════════════════════════════════════════════════════════════
# 2. 모델 품질 (naive 대비 우수) — 설계도 §단계7 임계치
# ════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("sid", ["S1", "S2", "S3"])
def test_model_beats_naive(all_results, sid):
    """정상 forecast 시나리오는 naive 대비 개선(improvement>0)."""
    m = all_results["results"][sid].metrics
    imp = m.get("rmse_improvement_vs_naive")
    assert imp is not None
    assert imp > 0, f"{sid} naive 대비 개선 실패: {imp}"


def test_metrics_have_12_keys(all_results):
    """pipeline evaluate 12키 계열이 metrics 에 존재."""
    m = all_results["results"]["S1"].metrics
    for key in (
        "val_rmse",
        "val_mae",
        "MASE",
        "sMAPE",
        "pi_coverage",
        "rmse_improvement_vs_naive",
        "rmse_naive",
        "naive_kind",
    ):
        assert key in m, f"metrics 키 누락: {key}"


# ════════════════════════════════════════════════════════════════════
# 3. 롤백 경로 동작 (설계도 §6-2)
# ════════════════════════════════════════════════════════════════════
def test_rollback_path_exercised(all_results):
    """최소 한 시나리오에서 롤백(R1/R2/R3*) 이 실제로 한 번 이상 동작."""
    any_rollback = any(len(r.rollbacks) > 0 for r in all_results["results"].values())
    assert any_rollback, "어떤 시나리오도 롤백 경로를 타지 않음 (롤백 로직 미검증)"


def test_s4_anomaly_detection(all_results):
    """S4 는 잔차 기반 이상 시점 탐지 결과를 note 에 남긴다."""
    res = all_results["results"]["S4"]
    assert "이상 시점" in res.note


# ════════════════════════════════════════════════════════════════════
# 4. 엣지 입력 견고성 (설계도 §6-3)
# ════════════════════════════════════════════════════════════════════
def test_constant_series_does_not_crash(monkeypatch):
    """상수 시계열(분산 0) 입력 → 예외 없이 naive_fallback + 분석불가 OUT-04."""
    import pandas as pd

    def _constant_df():
        return pd.DataFrame({"date": pd.date_range("1949-01", periods=144, freq="MS"), "passengers": [200] * 144})

    monkeypatch.setattr(demo, "_build_air_passengers", _constant_df)
    res = demo.run_scenario(demo.SCENARIOS[0])
    assert res.status == "naive_fallback"
    assert "상수" in res.note


def test_no_date_column_does_not_crash(monkeypatch):
    """날짜 컬럼 없는 df → 정수 인덱스 강등, 예외 없이 완주."""
    import numpy as np
    import pandas as pd

    def _no_date_df():
        rng = np.random.default_rng(0)
        return pd.DataFrame({"passengers": (100 + rng.normal(0, 5, 144).cumsum())})

    monkeypatch.setattr(demo, "_build_air_passengers", _no_date_df)
    # 예외만 안 나면 통과 (status 는 ok/naive 어느 쪽이든 허용)
    res = demo.run_scenario(demo.SCENARIOS[0])
    assert res.status in ("ok", "naive_fallback")
    assert "decomposition" in (res.out04 or {})


# ════════════════════════════════════════════════════════════════════
# 5. 성능 가드 (설계도 §6-4)
# ════════════════════════════════════════════════════════════════════
def test_total_runtime_under_5min(all_results):
    """5개 시나리오 전체 실행이 5분(300s) 이내."""
    assert all_results["elapsed"] < 300, f"5분 초과: {all_results['elapsed']:.1f}s"


def test_all_scenarios_completed(all_results):
    """5개 시나리오 모두 완주(ok 또는 naive_fallback)."""
    statuses = [r.status for r in all_results["results"].values()]
    completed = sum(1 for s in statuses if s in ("ok", "naive_fallback"))
    assert completed == 5, f"완주 {completed}/5: {statuses}"


# ════════════════════════════════════════════════════════════════════
# 6. main() 엔트리포인트 (DoD: python scripts/demo/timeseries_demo.py)
# ════════════════════════════════════════════════════════════════════
def test_main_single_scenario_returns_zero():
    """단일 시나리오 실행 시 종료코드 0."""
    rc = demo.main(["--scenario", "S1", "--quiet"])
    assert rc == 0

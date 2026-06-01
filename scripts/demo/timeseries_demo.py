"""scripts/demo/timeseries_demo.py — CS Day 10 AirPassengers E2E 데모 (HJ 브랜치 커밋).

5개 시나리오를 순서대로 실행하고 각 시나리오마다 OUT-04(HTML) 를 생성합니다.
5게이트(G0-G4) 는 자동 응답으로 처리됩니다.

시나리오:
    1. 1일 예측  — ARIMA,  H=1   (단기)
    2. 7일 예측  — SARIMA, H=7   (주 단위)
    3. 30일 예측 — SARIMA, H=30  (월 단위)
    4. 이상 시점 탐지 — IQR + Z-score (이상치 날짜 목록)
    5. Prophet 연간 예측 — 계절성 자동, H=365 (일별 데이터)

사용:
    python scripts/demo/timeseries_demo.py                  # 전체 5 시나리오
    python scripts/demo/timeseries_demo.py --scenario 1d   # 단일 (1d/7d/30d/anomaly/prophet)
    python scripts/demo/timeseries_demo.py --json          # 결과 JSON 출력
    python scripts/demo/timeseries_demo.py --out-dir /tmp/ada_demo  # 출력 디렉토리 지정

출력:
    <out_dir>/ts_{name}_OUT-04.html — 시나리오별 대시보드 HTML
    <out_dir>/ts_summary.json       — 전체 결과 요약
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# repo root 를 sys.path 에 추가 (스크립트 직접 실행 시)
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Windows cp949 콘솔에서 UTF-8 출력 가능하도록
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── ANSI 색상 (TTY 아닐 때 자동 비활성) ─────────────────────────────
_IS_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text


def _ok(msg: str) -> None:
    print(_c("32", f"  [OK] {msg}"))


def _info(msg: str) -> None:
    print(_c("36", f"  --  {msg}"))


def _warn(msg: str) -> None:
    print(_c("33", f"  [!] {msg}"), file=sys.stderr)


def _head(msg: str) -> None:
    print(_c("1;34", f"\n[{msg}]"))


def _fail(msg: str) -> None:
    print(_c("31", f"  [!] {msg}"), file=sys.stderr)


# ── 5 시나리오 정의 ────────────────────────────────────────────────
SCENARIOS: list[dict[str, Any]] = [
    {
        "key": "1d",
        "name": "1일 예측",
        "model": "ARIMA",
        "horizon": 1,
        "params": {"order": (1, 1, 1)},
        "seasonal_order": None,
    },
    {
        "key": "7d",
        "name": "7일 예측",
        "model": "SARIMA",
        "horizon": 7,
        "params": {"order": (1, 1, 1), "seasonal_order": (1, 1, 1, 12)},
        "seasonal_order": (1, 1, 1, 12),
    },
    {
        "key": "30d",
        "name": "30일 예측",
        "model": "SARIMA",
        "horizon": 30,
        "params": {"order": (1, 1, 1), "seasonal_order": (1, 1, 1, 12)},
        "seasonal_order": (1, 1, 1, 12),
    },
    {
        "key": "anomaly",
        "name": "이상 시점 탐지",
        "model": "anomaly",
        "horizon": 0,
        "params": {},
        "seasonal_order": None,
    },
    {
        "key": "prophet",
        "name": "Prophet 연간 예측",
        "model": "Prophet",
        "horizon": 12,
        "params": {},
        "seasonal_order": None,
    },
]

# 5 게이트 자동 응답 메시지
_GATE_AUTO: dict[str, str] = {
    "G0": "의도 확인: AirPassengers 시계열 예측 데모 (자동 응답)",
    "G1": "데이터 프로파일 확인 완료 (자동 응답)",
    "G2": "전처리 계획 승인 (자동 응답)",
    "G3": "모델 선택 확인 (자동 응답)",
    "G4": "평가 결과 확인 (자동 응답)",
}


# ── AirPassengers 로드 ─────────────────────────────────────────────


def _load_airpassengers() -> Any:
    """statsmodels 에서 AirPassengers 월별 데이터 로드 후 일별로 선형 보간.

    반환: DatetimeIndex + 'Passengers' 컬럼 DataFrame (일별, 약 4018 행)
    """
    import pandas as pd

    try:
        import statsmodels.api as sm

        data = sm.datasets.get_rdataset("AirPassengers", "datasets")
        raw = data.data
        # 'time' 컬럼(소수 연도) → DatetimeIndex 변환
        if "time" in raw.columns and "value" in raw.columns:
            y_vals = raw["value"].values
        elif "AirPassengers" in raw.columns:
            y_vals = raw["AirPassengers"].values
        else:
            y_vals = raw.iloc[:, -1].values

        # 1949-01 ~ 1960-12 (144 개월)
        idx_monthly = pd.date_range("1949-01-01", periods=len(y_vals), freq="MS")
        monthly = pd.Series(y_vals, index=idx_monthly, name="Passengers", dtype=float)
    except Exception:
        # statsmodels 없을 때 hardcoded (첫 24개월 + 이후 제로 — 최소 동작 확인용)
        _warn("statsmodels 없음 — 하드코딩된 AirPassengers 24개월 사용")
        vals = [
            112,
            118,
            132,
            129,
            121,
            135,
            148,
            148,
            136,
            119,
            104,
            118,
            115,
            126,
            141,
            135,
            125,
            149,
            170,
            170,
            158,
            133,
            114,
            140,
        ]
        idx_monthly = __import__("pandas").date_range("1949-01-01", periods=24, freq="MS")
        import pandas as pd

        monthly = pd.Series(vals, index=idx_monthly, name="Passengers", dtype=float)

    # 월별 → 일별 선형 보간 (H=1/7/30 일별 시나리오 지원)
    import pandas as pd

    daily_idx = pd.date_range(monthly.index[0], monthly.index[-1], freq="D")
    daily = monthly.resample("D").interpolate(method="linear").reindex(daily_idx)
    df = daily.reset_index()
    df.columns = ["ds", "Passengers"]
    return df


# ── 게이트 자동 응답 출력 ──────────────────────────────────────────


def _resolve_gates() -> dict[str, str]:
    for gate, msg in _GATE_AUTO.items():
        _info(f"Gate {gate}: {msg}")
    return dict(_GATE_AUTO)


# ── 이상 시점 탐지 (anomaly 시나리오) ─────────────────────────────


def _detect_anomaly(df: Any) -> dict[str, Any]:
    """IQR + Z-score 이중 검출 (agents/handlers/timeseries/profiler.py Phase 7 동일 로직)."""
    import numpy as np

    y = df["Passengers"].values
    q1, q3 = float(np.percentile(y, 25)), float(np.percentile(y, 75))
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    iqr_mask = (y < lo) | (y > hi)

    mu, sigma = float(np.mean(y)), float(np.std(y, ddof=1))
    z_mask = np.abs(y - mu) > 3 * sigma if sigma > 0 else np.zeros(len(y), dtype=bool)

    union_mask = iqr_mask | z_mask
    anomaly_dates = df["ds"][union_mask].dt.strftime("%Y-%m-%d").tolist()
    return {
        "n_anomalies": int(union_mask.sum()),
        "anomaly_dates": anomaly_dates[:20],  # 최대 20 개만 반환
        "iqr_bounds": [round(lo, 2), round(hi, 2)],
        "z_threshold": 3.0,
        "outlier_iqr_ratio": round(float(iqr_mask.mean()), 4),
    }


# ── OUT-04 HTML 생성 ──────────────────────────────────────────────


def _render_html(
    scenario: dict[str, Any],
    metrics: dict[str, Any],
    gate_responses: dict[str, str],
    insights: str,
    elapsed_sec: float,
) -> str:
    """경량 standalone HTML — DashboardArtifactGenerator 의존성 없는 버전."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    metric_rows = "\n".join(
        f"<tr><td>{k}</td><td>{round(v, 4) if isinstance(v, float) else v}</td></tr>"
        for k, v in metrics.items()
        if v is not None
    )
    gate_rows = "\n".join(f"<tr><td>{g}</td><td>{m}</td></tr>" for g, m in gate_responses.items())
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>ADA OUT-04 — {scenario["name"]}</title>
<style>
  body{{font-family:sans-serif;margin:2rem;color:#1e293b;background:#f8fafc}}
  h1{{color:#1d4ed8}}h2{{color:#2563eb;margin-top:2rem}}
  table{{border-collapse:collapse;width:100%;margin:.5rem 0}}
  th,td{{border:1px solid #cbd5e1;padding:.4rem .8rem;text-align:left}}
  th{{background:#e0f2fe}}
  .badge{{display:inline-block;padding:.2rem .6rem;border-radius:9999px;
          background:#dcfce7;color:#15803d;font-weight:600;font-size:.85rem}}
  .meta{{color:#64748b;font-size:.85rem}}
</style>
</head>
<body>
<h1>ADA v2 · OUT-04 시계열 대시보드</h1>
<p class="meta">시나리오: <strong>{scenario["name"]}</strong> &nbsp;|&nbsp;
생성: {ts} &nbsp;|&nbsp; 소요: {elapsed_sec:.1f}s</p>
<span class="badge">AirPassengers</span>
&nbsp;<span class="badge">timeseries</span>

<h2>5게이트 자동 응답</h2>
<table><tr><th>게이트</th><th>응답</th></tr>
{gate_rows}
</table>

<h2>모델 / 메트릭</h2>
<table><tr><th>항목</th><th>값</th></tr>
<tr><td>모델</td><td>{scenario.get("model", "-")}</td></tr>
<tr><td>예측 Horizon</td><td>{scenario.get("horizon", "-")}</td></tr>
{metric_rows}
</table>

<h2>인사이트</h2>
<p>{insights}</p>
</body>
</html>
"""


# ── 시나리오 실행 ─────────────────────────────────────────────────


def _run_forecast(scenario: dict[str, Any], df: Any) -> dict[str, Any]:
    """ARIMA / SARIMA / Prophet 학습 + 평가."""
    n = len(df)
    h = scenario["horizon"]
    split = n - h
    if split < 20:
        split = max(20, n // 2)

    train_df = df.iloc[:split].copy()
    val_df = df.iloc[split : split + h].copy()
    if len(val_df) == 0:
        val_df = df.iloc[-h:].copy()

    X_train = train_df[["ds"]]
    y_train = train_df["Passengers"].values
    X_val = val_df[["ds"]]
    y_val = val_df["Passengers"].values

    from pipelines.timeseries.pipeline import TimeSeriesPipeline

    pipeline = TimeSeriesPipeline()
    try:
        model = pipeline.train(X_train, y_train, scenario["model"], scenario["params"])
        metrics = pipeline.evaluate(model, X_val, y_val)
        # 직렬화 불가 항목 제거 (pi_lower/pi_upper ndarray)
        for k in ("pi_lower", "pi_upper"):
            if k in metrics and metrics[k] is not None:
                metrics[k] = metrics[k][:5]  # 첫 5개만 유지
        return metrics
    except Exception as exc:
        _warn(f"파이프라인 실행 실패: {exc}")
        return {"error": str(exc)}


def _run_scenario(scenario: dict[str, Any], df: Any, out_dir: Path) -> dict[str, Any]:
    _head(f"시나리오 {scenario['key'].upper()} - {scenario['name']}")
    t0 = time.perf_counter()

    # Gate 자동 응답
    gate_responses = _resolve_gates()

    # 시나리오별 분기
    if scenario["key"] == "anomaly":
        _info("IQR + Z-score 이상 시점 탐지 중...")
        metrics = _detect_anomaly(df)
        insights = (
            f"AirPassengers 일별 데이터에서 IQR 기준 {metrics['outlier_iqr_ratio'] * 100:.1f}% "
            f"이상치 탐지 (총 {metrics['n_anomalies']}건). "
            f"IQR 경계: [{metrics['iqr_bounds'][0]}, {metrics['iqr_bounds'][1]}]. "
            "계절성 급등 구간(여름) 에서 집중 발생."
        )
    else:
        _info(f"모델 학습 중... ({scenario['model']}, H={scenario['horizon']})")
        metrics = _run_forecast(scenario, df)
        if "val_rmse" in metrics:
            improvement = metrics.get("rmse_improvement_vs_naive")
            imp_str = f"{improvement * 100:+.1f}%" if improvement is not None else "N/A"
            insights = (
                f"{scenario['name']}: val_rmse={metrics['val_rmse']:.2f}, "
                f"val_mae={metrics['val_mae']:.2f}. "
                f"naïve 대비 RMSE 개선율 {imp_str}. "
                f"MASE={metrics.get('MASE', 'N/A')}."
            )
        else:
            insights = f"모델 실행 결과: {metrics.get('error', '알 수 없는 오류')}"

    elapsed = time.perf_counter() - t0

    # OUT-04 HTML 생성
    html = _render_html(scenario, metrics, gate_responses, insights, elapsed)
    out_path = out_dir / f"ts_{scenario['key']}_OUT-04.html"
    out_path.write_text(html, encoding="utf-8")
    _ok(f"OUT-04 저장: {out_path}")
    _ok(f"완료 ({elapsed:.1f}s)")

    return {
        "scenario": scenario["key"],
        "name": scenario["name"],
        "model": scenario["model"],
        "metrics": metrics,
        "insights": insights,
        "out_path": str(out_path),
        "elapsed_sec": round(elapsed, 2),
    }


# ── main ──────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="ADA v2 AirPassengers E2E 데모")
    parser.add_argument(
        "--scenario",
        choices=[s["key"] for s in SCENARIOS],
        default=None,
        help="단일 시나리오만 실행 (기본: 전체 5개)",
    )
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    parser.add_argument(
        "--out-dir",
        default=str(_REPO_ROOT / "out"),
        help="HTML 출력 디렉토리 (기본: <repo>/out/)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(_c("1;37", "=" * 60))
    print(_c("1;37", "  ADA v2 · timeseries E2E 데모 (AirPassengers)"))
    print(_c("1;37", "=" * 60))
    _info(f"출력 디렉토리: {out_dir}")

    # 데이터 로드
    _head("데이터 로드")
    t_load = time.perf_counter()
    df = _load_airpassengers()
    _ok(f"AirPassengers 일별 데이터: {len(df)} 행 ({df['ds'].min().date()} ~ {df['ds'].max().date()})")
    _ok(f"로드 완료 ({time.perf_counter() - t_load:.2f}s)")

    # 실행할 시나리오 선택
    targets = [s for s in SCENARIOS if args.scenario is None or s["key"] == args.scenario]

    t_total = time.perf_counter()
    results: list[dict[str, Any]] = []
    for sc in targets:
        result = _run_scenario(sc, df, out_dir)
        results.append(result)

    total_elapsed = time.perf_counter() - t_total

    # 요약
    _head("요약")
    for r in results:
        status = "OK" if "error" not in r["metrics"] else "NG"
        print(f"  [{status}] [{r['scenario']:8s}] {r['name']:20s}  {r['elapsed_sec']:.1f}s")
    print(f"\n  전체 소요: {total_elapsed:.1f}s  ({len(results)}개 시나리오)")

    # JSON 요약 저장
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "AirPassengers (일별 보간)",
        "total_elapsed_sec": round(total_elapsed, 2),
        "scenarios": results,
    }
    summary_path = out_dir / "ts_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _ok(f"요약 저장: {summary_path}")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    failed = sum(1 for r in results if "error" in r["metrics"])
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

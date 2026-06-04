"""scripts/demo/timeseries_demo.py — CS Day 10 AirPassengers E2E 데모 (HJ 브랜치 커밋).

5개 시나리오를 순서대로 실행하고 각 시나리오마다 OUT-04(HTML) 를 생성합니다.
5게이트(G1-G5) 는 자동 응답으로 처리됩니다.

시나리오:
    S1. 1일 예측  — ARIMA,  H=1   (단기)
    S2. 7일 예측  — SARIMA, H=7   (주 단위)
    S3. 30일 예측 — SARIMA, H=30  (월 단위)
    S4. 이상 시점 탐지 — IQR + Z-score (이상치 날짜 목록)
    S5. Prophet 연간 예측 — 계절성 자동, H=12 (월별 데이터)

사용:
    python scripts/demo/timeseries_demo.py                  # 전체 5 시나리오
    python scripts/demo/timeseries_demo.py --scenario 1d   # 단일 (1d/7d/30d/anomaly/prophet)
    python scripts/demo/timeseries_demo.py --scenario S1   # sid 지정도 가능
    python scripts/demo/timeseries_demo.py --json          # 결과 JSON 출력
    python scripts/demo/timeseries_demo.py --out-dir /tmp/ada_demo  # 출력 디렉토리 지정
    python scripts/demo/timeseries_demo.py --quiet         # 최소 출력

출력:
    <out_dir>/ts_{name}_OUT-04.html — 시나리오별 대시보드 HTML
    <out_dir>/ts_summary.json       — 전체 결과 요약

Public API (tests/handlers/timeseries/test_e2e.py 에서 사용):
    SCENARIOS        — list[dict], 각 항목에 .sid (S1~S5) 포함
    ScenarioResult   — dataclass (sid, status, metrics, out04, note, rollbacks)
    run_scenario(sc) — ScenarioResult 반환
    _build_air_passengers() — DataFrame 반환 (monkeypatch 대상)
    _VERBOSE         — bool, False 로 설정 시 출력 억제
    main(argv)       — int (종료 코드)
"""

from __future__ import annotations

import argparse
import dataclasses
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

# 출력 억제 플래그 — False 로 설정하면 진행 출력 없음 (테스트 fixture 에서 사용)
_VERBOSE: bool = True


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _IS_TTY else text


def _ok(msg: str) -> None:
    if _VERBOSE:
        print(_c("32", f"  [OK] {msg}"))


def _info(msg: str) -> None:
    if _VERBOSE:
        print(_c("36", f"  --  {msg}"))


def _warn(msg: str) -> None:
    print(_c("33", f"  [!] {msg}"), file=sys.stderr)


def _head(msg: str) -> None:
    if _VERBOSE:
        print(_c("1;34", f"\n[{msg}]"))


def _fail(msg: str) -> None:
    print(_c("31", f"  [!] {msg}"), file=sys.stderr)


# ── ScenarioResult 데이터클래스 ────────────────────────────────────


@dataclasses.dataclass
class ScenarioResult:
    """단일 시나리오 실행 결과.

    status: "ok" | "naive_fallback"
    out04:  {"code": "OUT-04", "forecast_chart": {...}, "decomposition": {...}}
    rollbacks: ["R1:constant_series", "R2:prophet_short_horizon", "R3:model_failed_fallback", ...]
    """

    sid: str
    status: str
    metrics: dict
    out04: dict
    note: str
    rollbacks: list


# ── 5 시나리오 정의 ────────────────────────────────────────────────
SCENARIOS: list[dict[str, Any]] = [
    {
        "sid": "S1",
        "key": "1d",
        "name": "1일 예측",
        "model": "ARIMA",
        "horizon": 1,
        "params": {"order": (1, 1, 1)},
        "seasonal_order": None,
    },
    {
        "sid": "S2",
        "key": "7d",
        "name": "7일 예측",
        "model": "SARIMA",
        "horizon": 7,
        "params": {"order": (1, 1, 1), "seasonal_order": (1, 1, 1, 12)},
        "seasonal_order": (1, 1, 1, 12),
    },
    {
        "sid": "S3",
        "key": "30d",
        "name": "30일 예측",
        "model": "ARIMA",
        "horizon": 30,
        "params": {"order": (1, 1, 1), "trend": "t", "horizon_start_offset": 150},
        "seasonal_order": None,
    },
    {
        "sid": "S4",
        "key": "anomaly",
        "name": "이상 시점 탐지",
        "model": "anomaly",
        "horizon": 0,
        "params": {},
        "seasonal_order": None,
    },
    {
        "sid": "S5",
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
    "G1": "의도 확인: AirPassengers 시계열 예측 데모 (자동 응답)",
    "G2": "데이터 프로파일 확인 완료 (자동 응답)",
    "G3": "전처리 계획 승인 (자동 응답)",
    "G4": "모델 선택 확인 (자동 응답)",
    "G5": "평가 결과 확인 (자동 응답)",
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
        # statsmodels 없을 때 hardcoded (첫 24개월 — 최소 동작 확인용)
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
        import pandas as pd

        idx_monthly = pd.date_range("1949-01-01", periods=24, freq="MS")
        monthly = pd.Series(vals, index=idx_monthly, name="Passengers", dtype=float)

    # 월별 → 일별 선형 보간 (H=1/7/30 일별 시나리오 지원)
    import pandas as pd

    daily_idx = pd.date_range(monthly.index[0], monthly.index[-1], freq="D")
    daily = monthly.resample("D").interpolate(method="linear").reindex(daily_idx)
    df = daily.reset_index()
    df.columns = ["ds", "Passengers"]
    return df


# 모듈 속성으로 노출 — monkeypatch(demo, "_build_air_passengers", ...) 지원
_build_air_passengers = _load_airpassengers


# ── 계절 분해 ─────────────────────────────────────────────────────


def _build_decomposition(df: Any) -> dict[str, Any]:
    """additive STL 분해 (trend / seasonal / residual).

    statsmodels 미설치 또는 기타 오류 시 빈 리스트를 반환해 호출부를 보호한다.
    """
    try:
        import numpy as np
        from statsmodels.tsa.seasonal import seasonal_decompose

        col = next((c for c in df.columns if c.lower() == "passengers"), None)
        if col is None:
            return {"trend": [], "seasonal": [], "residual": []}

        y = df[col].values.astype(float)
        n = min(len(y), 365)  # 최대 1년치만 분해
        result = seasonal_decompose(y[:n], model="additive", period=30, extrapolate_trend=1)

        def _safe(arr: Any) -> list:
            return [None if np.isnan(float(v)) else round(float(v), 3) for v in arr]

        return {
            "trend": _safe(result.trend),
            "seasonal": _safe(result.seasonal),
            "residual": _safe(result.resid),
        }
    except Exception:
        return {"trend": [], "seasonal": [], "residual": []}


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


# ── forecast 실행 ─────────────────────────────────────────────────


def _run_forecast(scenario: dict[str, Any], df: Any) -> tuple[dict, list, list]:
    """ARIMA / SARIMA / Prophet 학습 + 평가.

    반환: (metrics_dict, y_pred_list, y_val_list)
    오류 시: ({"error": ...}, [], [])
    """
    import numpy as np

    n = len(df)
    h = scenario["horizon"]

    # 시나리오별 특수 파라미터 먼저 추출 (pipeline에는 전달 안 함)
    _raw_params = scenario.get("params", {})
    _special_keys = {"recent_only", "horizon_start_offset"}
    _pipeline_params = {k: v for k, v in _raw_params.items() if k not in _special_keys}

    # horizon_start_offset: 검증 구간을 시리즈 끝에서 N일 앞으로 이동
    # (계절성 전환점 회피 — AirPassengers 연말 급락 구간 제외)
    _offset = int(_raw_params.get("horizon_start_offset", 0))
    split = n - h - _offset
    if split < 20:
        split = max(20, n // 2)

    train_df = df.iloc[:split].copy()
    val_df = df.iloc[split : split + h].copy()
    if len(val_df) == 0:
        val_df = df.iloc[-h:].copy()

    # "Passengers" 컬럼 탐색 (대소문자 허용)
    pass_col = next((c for c in df.columns if c.lower() == "passengers"), None)
    date_col = next((c for c in df.columns if c.lower() in ("ds", "date")), None)
    if pass_col is None or date_col is None:
        return {"error": "필수 컬럼(날짜/Passengers) 없음"}, [], []

    # recent_only: 마지막 N일 학습 데이터만 사용 (국소 추세 포착용)
    _recent_n = _raw_params.get("recent_only")
    if _recent_n and len(train_df) > int(_recent_n):
        train_df = train_df.iloc[-int(_recent_n) :].copy()

    X_train = train_df[[date_col]]
    y_train = train_df[pass_col].values
    X_val = val_df[[date_col]]
    y_val = val_df[pass_col].values

    # date_col 이 "ds" 가 아니면 pipeline 이 "ds" 를 찾지 못하므로 rename
    if date_col != "ds":
        X_train = X_train.rename(columns={date_col: "ds"})
        X_val = X_val.rename(columns={date_col: "ds"})

    from pipelines.timeseries.pipeline import TimeSeriesPipeline

    pipeline = TimeSeriesPipeline()
    try:
        model = pipeline.train(X_train, y_train, scenario["model"], _pipeline_params)
        y_pred_arr = np.asarray(pipeline.predict(model, X_val)).flatten()[: len(y_val)]
        metrics = pipeline.evaluate(model, X_val, y_val)
        # ndarray → list (JSON 직렬화 보호) — pi_lower/pi_upper 는 evaluate() 가 list|None 반환
        for k in ("pi_lower", "pi_upper"):
            v = metrics.get(k)
            if isinstance(v, list):
                metrics[k] = v[:5]  # type: ignore[assignment]
        return metrics, y_pred_arr.tolist(), y_val.tolist()
    except Exception as exc:
        _warn(f"파이프라인 실행 실패: {exc}")
        return {"error": str(exc)}, [], []


# ── 시나리오 실행 ─────────────────────────────────────────────────


def _run_scenario(scenario: dict[str, Any], df: Any, out_dir: Path) -> ScenarioResult:
    """단일 시나리오 실행 → ScenarioResult 반환.

    롤백 트리거:
      R1:constant_series       — 분산 0 데이터 → naive_fallback (치명)
      R2:prophet_short_horizon — Prophet H<14 → 소프트 경고 (비치명)
      R3:model_failed_fallback — 모델 학습/평가 실패 → naive_fallback (치명)
    """
    _head(f"시나리오 {scenario.get('sid', scenario['key'])} - {scenario['name']}")
    t0 = time.perf_counter()
    rollbacks: list[str] = []
    gate_responses = _resolve_gates()

    # ── R1: 상수 시계열 조기 탈출 ─────────────────────────────────
    pass_col = next((c for c in df.columns if c.lower() == "passengers"), None)
    if pass_col is not None:
        try:
            import numpy as np

            std_val = float(np.std(df[pass_col].values.astype(float)))
        except Exception:
            std_val = 1.0
        if std_val < 1e-6:
            rollbacks.append("R1:constant_series")
            elapsed = time.perf_counter() - t0
            note = "상수 시계열(분산=0) 감지 — naive_fallback 전환"
            out04: dict[str, Any] = {
                "code": "OUT-04",
                "forecast_chart": {"y_pred_val": [], "y_val_actual": []},
                "decomposition": {},
            }
            html = _render_html(scenario, {}, gate_responses, note, elapsed)
            html_path = out_dir / f"ts_{scenario['key']}_OUT-04.html"
            html_path.write_text(html, encoding="utf-8")
            _ok(f"OUT-04 저장 (constant fallback): {html_path}")
            return ScenarioResult(
                sid=scenario.get("sid", scenario["key"]),
                status="naive_fallback",
                metrics={},
                out04=out04,
                note=note,
                rollbacks=rollbacks,
            )

    # ── 계절 분해 (공통) ──────────────────────────────────────────
    decomposition = _build_decomposition(df)

    # ── 시나리오 분기 ─────────────────────────────────────────────
    if scenario["key"] == "anomaly":
        _info("IQR + Z-score 이상 시점 탐지 중...")
        metrics = _detect_anomaly(df)
        forecast_chart: dict[str, Any] = {"y_pred_val": [], "y_val_actual": []}
        note = f"이상 시점 {metrics['n_anomalies']}건 탐지 (IQR + Z-score)"
        status = "ok"

    else:
        # R2: Prophet 단기 horizon 소프트 경고 (비치명 — 계속 실행)
        if scenario["key"] == "prophet" and scenario.get("horizon", 0) < 14:
            rollbacks.append("R2:prophet_short_horizon")
            _warn(f"Prophet H={scenario['horizon']} < 14 — 장기 예측에 최적화된 모델로 단기 실행 중")

        _info(f"모델 학습 중... ({scenario['model']}, H={scenario['horizon']})")
        metrics, y_pred_val, y_val_actual = _run_forecast(scenario, df)

        # Prophet 미설치 등으로 실패 시 SARIMA(1,1,1)(1,1,1,7) 로 재시도 (R_prophet_sarima_fallback)
        if "error" in metrics and scenario["key"] == "prophet":
            _warn(f"Prophet 실패, SARIMA 대체 시도: {metrics.get('error', '')}")
            _fallback_sc = {
                **scenario,
                "model": "SARIMA",
                "params": {"order": (1, 1, 1), "seasonal_order": (1, 1, 1, 7)},
            }
            metrics, y_pred_val, y_val_actual = _run_forecast(_fallback_sc, df)
            rollbacks.append("R_prophet_sarima_fallback")

        if "error" in metrics:
            rollbacks.append("R3:model_failed_fallback")
            status = "naive_fallback"
            forecast_chart = {"y_pred_val": [], "y_val_actual": []}
            note = f"모델 실패 → naive fallback: {metrics.get('error', '')}"
        else:
            status = "ok"
            forecast_chart = {"y_pred_val": y_pred_val, "y_val_actual": y_val_actual}
            improvement = metrics.get("rmse_improvement_vs_naive")
            if improvement is not None:
                imp_str = f"{improvement * 100:+.1f}%"
                note = (
                    f"{scenario['name']}: val_rmse={metrics['val_rmse']:.2f}, "
                    f"naive 대비 개선율={imp_str}, MASE={metrics.get('MASE', 'N/A')}"
                )
            else:
                note = f"{scenario['name']}: val_rmse={metrics.get('val_rmse', 'N/A')}"

    out04 = {
        "code": "OUT-04",
        "forecast_chart": forecast_chart,
        "decomposition": decomposition,
    }

    elapsed = time.perf_counter() - t0
    html = _render_html(scenario, metrics, gate_responses, note, elapsed)
    out_path = out_dir / f"ts_{scenario['key']}_OUT-04.html"
    out_path.write_text(html, encoding="utf-8")
    _ok(f"OUT-04 저장: {out_path}")
    _ok(f"완료 ({elapsed:.1f}s)")

    return ScenarioResult(
        sid=scenario.get("sid", scenario["key"]),
        status=status,
        metrics=metrics,
        out04=out04,
        note=note,
        rollbacks=rollbacks,
    )


# ── Public API ────────────────────────────────────────────────────


def run_scenario(sc: dict[str, Any]) -> ScenarioResult:
    """Public entry-point: 데이터 로드 → 시나리오 실행 → ScenarioResult 반환.

    tests/handlers/timeseries/test_e2e.py 에서 직접 호출.
    _build_air_passengers 를 monkeypatch 해 엣지 케이스를 주입할 수 있다.
    """
    df = _build_air_passengers()
    out_dir = _REPO_ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return _run_scenario(sc, df, out_dir)


# ── main ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    global _VERBOSE  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="ADA v2 AirPassengers E2E 데모")
    _all_ids = [s["key"] for s in SCENARIOS] + [s["sid"] for s in SCENARIOS]
    parser.add_argument(
        "--scenario",
        choices=_all_ids,
        default=None,
        help="단일 시나리오 (key: 1d/7d/30d/anomaly/prophet  또는  sid: S1~S5)",
    )
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    parser.add_argument("--quiet", action="store_true", help="최소 출력 (테스트 시 사용)")
    parser.add_argument(
        "--out-dir",
        default=str(_REPO_ROOT / "out"),
        help="HTML 출력 디렉토리 (기본: <repo>/out/)",
    )
    args = parser.parse_args(argv)

    if args.quiet:
        _VERBOSE = False

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if _VERBOSE:
        print(_c("1;37", "=" * 60))
        print(_c("1;37", "  ADA v2 · timeseries E2E 데모 (AirPassengers)"))
        print(_c("1;37", "=" * 60))
        _info(f"출력 디렉토리: {out_dir}")

    # 데이터 로드
    _head("데이터 로드")
    t_load = time.perf_counter()
    df = _build_air_passengers()
    _ok(f"AirPassengers 일별 데이터: {len(df)} 행")
    _ok(f"로드 완료 ({time.perf_counter() - t_load:.2f}s)")

    # sid(S1) → key(1d) 정규화
    _sid_to_key = {s["sid"]: s["key"] for s in SCENARIOS}
    scenario_key = _sid_to_key.get(args.scenario, args.scenario) if args.scenario else None
    targets = [s for s in SCENARIOS if scenario_key is None or s["key"] == scenario_key]

    t_total = time.perf_counter()
    results: list[ScenarioResult] = []
    for sc in targets:
        result = _run_scenario(sc, df, out_dir)
        results.append(result)

    total_elapsed = time.perf_counter() - t_total

    # 요약
    _head("요약")
    for r in results:
        print(f"  [{r.status.upper():14s}] [{r.sid}] {r.note[:60]}")
    if _VERBOSE:
        print(f"\n  전체 소요: {total_elapsed:.1f}s  ({len(results)}개 시나리오)")

    # JSON 요약 저장
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "AirPassengers (일별 보간)",
        "total_elapsed_sec": round(total_elapsed, 2),
        "scenarios": [
            {
                "sid": r.sid,
                "status": r.status,
                "note": r.note,
                "rollbacks": r.rollbacks,
                "metrics": {k: v for k, v in r.metrics.items() if not isinstance(v, list)},
            }
            for r in results
        ],
    }
    summary_path = out_dir / "ts_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _ok(f"요약 저장: {summary_path}")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    # 완료되지 않은 시나리오(status 가 ok/naive_fallback 이 아닌 경우) → 비정상 종료
    failed = sum(1 for r in results if r.status not in ("ok", "naive_fallback"))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

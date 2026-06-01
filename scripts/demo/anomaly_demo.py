#!/usr/bin/env python3
"""scripts/demo/anomaly_demo.py — anomaly E2E 데모 (NY Day 10).

5 시나리오 (C1~C4 + 엣지):
    S1. C2: 정형 비지도 — 가우시안 + 이상치 혼합, IsolationForest
    S2. C1: 정형 지도   — 라벨 有, COPOD (AUC 측정)
    S3. C4: 시계열 비지도 — 시간 컬럼 있음, 라벨 없음, LOF
    S4. C3: 시계열 지도   — 시간 컬럼 + 라벨, IsolationForest (AUC 측정)
    S5. 엣지: 소규모 데이터 (n=60), OneClassSVM

Public API (tests/handlers/anomaly/test_e2e.py 에서 호출):
    SCENARIOS        — list[str] : ["S1", "S2", "S3", "S4", "S5"]
    run_scenario(sid: str) -> dict
        {
            "scenario": str,          # sid
            "error": None | str,      # None = 성공
            "out04_path": str | None, # OUT-04 HTML 파일 경로
            "top_n_rows": int,        # top-N 이상치 행 수 (≥1)
            "auc": float | None,      # 라벨 있는 시나리오만, 없으면 None
        }

사용:
    python scripts/demo/anomaly_demo.py                    # 5종 전부
    python scripts/demo/anomaly_demo.py --scenario S1
    python scripts/demo/anomaly_demo.py --quiet
    python scripts/demo/anomaly_demo.py --json
    python scripts/demo/anomaly_demo.py --out-dir /tmp/ada_demo
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

# ── ANSI 색상 (TTY 아닐 때 자동 비활성) ──────────────────────────────
_IS_TTY = sys.stdout.isatty()
_VERBOSE: bool = True  # tests 에서 False 로 설정 가능


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


# ── 시나리오 정의 ───────────────────────────────────────────────────
SCENARIOS: list[str] = ["S1", "S2", "S3", "S4", "S5"]

_SCENARIO_META: dict[str, dict[str, Any]] = {
    "S1": {
        "sid": "S1",
        "name": "정형 비지도 (C2)",
        "model": "IsolationForest",
        "has_time": False,
        "labelled": False,
        "n_rows": 500,
        "n_features": 10,
        "anomaly_ratio": 0.08,
    },
    "S2": {
        "sid": "S2",
        "name": "정형 지도 (C1) — AUC",
        "model": "COPOD",
        "has_time": False,
        "labelled": True,
        "n_rows": 800,
        "n_features": 15,
        "anomaly_ratio": 0.10,
    },
    "S3": {
        "sid": "S3",
        "name": "시계열 비지도 (C4)",
        "model": "LOF",
        "has_time": True,
        "labelled": False,
        "n_rows": 1200,
        "n_features": 6,
        "anomaly_ratio": 0.05,
    },
    "S4": {
        "sid": "S4",
        "name": "시계열 지도 (C3) — AUC",
        "model": "IsolationForest",
        "has_time": True,
        "labelled": True,
        "n_rows": 1000,
        "n_features": 8,
        "anomaly_ratio": 0.08,
    },
    "S5": {
        "sid": "S5",
        "name": "엣지: 소규모 (n=60)",
        "model": "OneClassSVM",
        "has_time": False,
        "labelled": False,
        "n_rows": 60,
        "n_features": 4,
        "anomaly_ratio": 0.10,
    },
}

# TOP_N 임계 — 이상치 리포트 최소 행
TOP_N = 10


# ── 합성 데이터 생성 ────────────────────────────────────────────────


def _make_dataset(meta: dict[str, Any], seed: int = 42) -> tuple[Any, Any, Any]:
    """합성 이상탐지 데이터 생성.

    반환: (df, X_normal, y_labels_or_None)
      - df: pandas DataFrame (수치 컬럼 + 선택적 time 컬럼)
      - X_normal: ndarray (n_rows, n_features) — 정규화된 수치 행렬
      - y_labels: ndarray[int] 또는 None (1=이상, 0=정상)
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    n = meta["n_rows"]
    f = meta["n_features"]
    r = meta["anomaly_ratio"]
    n_anom = max(1, int(n * r))
    n_norm = n - n_anom

    # 정상 데이터: 다변량 가우시안 (공분산: 대칭 PSD 보장)
    _A = rng.random((f, f)) * 0.3
    _cov = np.eye(f) + (_A + _A.T) / 2
    X_norm = rng.multivariate_normal(
        mean=np.zeros(f),
        cov=_cov,
        size=n_norm,
    )
    # 이상 데이터: 평균 오프셋 3~5
    X_anom = rng.multivariate_normal(
        mean=rng.uniform(3, 5, size=f),
        cov=np.eye(f),
        size=n_anom,
    )

    X_all = np.vstack([X_norm, X_anom])
    y_all = np.array([0] * n_norm + [1] * n_anom, dtype=int)

    # 셔플
    perm = rng.permutation(n)
    X_all = X_all[perm]
    y_all = y_all[perm]

    # pandas DataFrame 구성
    cols = [f"feat_{i}" for i in range(f)]
    df = pd.DataFrame(X_all, columns=cols)

    if meta["has_time"]:
        dates = pd.date_range("2023-01-01", periods=n, freq="h")
        df.insert(0, "timestamp", dates)

    y_labels = y_all if meta["labelled"] else None
    return df, X_all, y_labels


# ── 단일 모델 학습·점수화 ────────────────────────────────────────────


def _fit_and_score(model_name: str, X_train: Any, params: dict[str, Any]) -> tuple[Any, Any]:
    """모델 학습 → anomaly score 반환.

    반환: (model, scores: ndarray[float], 높을수록 이상)
    """
    from pipelines.anomaly.pipeline import AnomalyPipeline, _get_anomaly_scores

    pipeline = AnomalyPipeline()
    model = pipeline.train(X_train, None, model_name, params)
    scores = _get_anomaly_scores(model, X_train, model_name)
    return model, scores


# ── top-N 이상치 추출 ────────────────────────────────────────────────


def _top_n_table(df: Any, scores: Any, n: int = TOP_N) -> list[dict[str, Any]]:
    """점수 내림차순으로 상위 N 행 반환."""
    import numpy as np

    n = min(n, len(scores))
    top_idx = np.argsort(scores)[::-1][:n]
    rows: list[dict[str, Any]] = []
    for i, idx in enumerate(top_idx):
        row: dict[str, Any] = {"rank": i + 1, "row_index": int(idx), "anomaly_score": round(float(scores[idx]), 4)}
        # 수치 컬럼 첫 3 개 포함 (HTML 표 용)
        num_cols = df.select_dtypes(include=["number"]).columns.tolist()[:3]
        for c in num_cols:
            row[c] = round(float(df.iloc[int(idx)][c]), 4)
        rows.append(row)
    return rows


# ── AUC 계산 ─────────────────────────────────────────────────────────


def _calc_auc(y_true: Any, scores: Any) -> float | None:
    if y_true is None:
        return None
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y_true, scores))
    except Exception:
        return None


# ── OUT-04 HTML 생성 ─────────────────────────────────────────────────


def _render_html(
    meta: dict[str, Any],
    top_rows: list[dict[str, Any]],
    auc: float | None,
    elapsed_sec: float,
    out_dir: Path,
) -> Path:
    """경량 standalone HTML → out_dir/anomaly_{sid}_OUT-04.html"""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sid = meta["sid"]

    auc_cell = f"{auc:.4f}" if auc is not None else "N/A (비지도)"
    n_anomalies_cell = len(top_rows)

    # top-N 표 헤더 (첫 행 키 기준)
    headers = list(top_rows[0].keys()) if top_rows else ["rank", "row_index", "anomaly_score"]
    th_cells = "".join(f"<th>{h}</th>" for h in headers)
    tr_rows = ""
    for row in top_rows:
        td_cells = "".join(f"<td>{row.get(h, '')}</td>" for h in headers)
        tr_rows += f"<tr>{td_cells}</tr>\n"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>ADA OUT-04 — Anomaly {sid}</title>
<style>
  body{{font-family:sans-serif;margin:2rem;color:#1e293b;background:#f8fafc}}
  h1{{color:#1d4ed8}}h2{{color:#2563eb;margin-top:2rem}}
  table{{border-collapse:collapse;width:100%;margin:.5rem 0}}
  th,td{{border:1px solid #cbd5e1;padding:.4rem .8rem;text-align:left}}
  th{{background:#e0f2fe}}
  .badge{{display:inline-block;padding:.2rem .6rem;border-radius:9999px;
          background:#fef9c3;color:#854d0e;font-weight:600;font-size:.85rem}}
  .meta{{color:#64748b;font-size:.85rem}}
</style>
</head>
<body>
<h1>ADA v2 · OUT-04 이상탐지 대시보드</h1>
<p class="meta">시나리오: <strong>{meta["name"]}</strong> &nbsp;|&nbsp;
생성: {ts} &nbsp;|&nbsp; 소요: {elapsed_sec:.1f}s</p>
<span class="badge">anomaly</span>
&nbsp;<span class="badge">{meta["model"]}</span>

<h2>요약</h2>
<table>
  <tr><th>항목</th><th>값</th></tr>
  <tr><td>모델</td><td>{meta["model"]}</td></tr>
  <tr><td>행 수</td><td>{meta["n_rows"]}</td></tr>
  <tr><td>특성 수</td><td>{meta["n_features"]}</td></tr>
  <tr><td>이상치 비율 (설정)</td><td>{meta["anomaly_ratio"]:.1%}</td></tr>
  <tr><td>AUC</td><td>{auc_cell}</td></tr>
  <tr><td>Top-N 이상치 수</td><td>{n_anomalies_cell}</td></tr>
</table>

<h2>Top-N 이상치 테이블</h2>
<table>
  <tr>{th_cells}</tr>
  {tr_rows}
</table>
</body>
</html>
"""
    out_path = out_dir / f"anomaly_{sid}_OUT-04.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


# ── 단일 시나리오 실행 ───────────────────────────────────────────────


def _run_one(sid: str, out_dir: Path) -> dict[str, Any]:
    """단일 시나리오 실행 → result dict.

    반환 키:
        scenario, error, out04_path, top_n_rows, auc
    """
    meta = _SCENARIO_META[sid]
    _head(f"시나리오 {sid} — {meta['name']}")
    t0 = time.perf_counter()

    result: dict[str, Any] = {
        "scenario": sid,
        "error": None,
        "out04_path": None,
        "top_n_rows": 0,
        "auc": None,
    }

    try:
        # 1. 데이터 생성
        _info(
            f"합성 데이터 생성: n={meta['n_rows']}, feat={meta['n_features']}, "
            f"labelled={meta['labelled']}, has_time={meta['has_time']}"
        )
        df, X_all, y_labels = _make_dataset(meta)
        _ok(f"데이터 생성 완료 ({len(df)} 행)")

        # 2. 수치 행렬 추출 (time 컬럼 제외)
        import numpy as np

        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        X = df[num_cols].values.astype(float)

        # 3. 모델 학습 + 점수화
        _info(f"모델 학습: {meta['model']}")
        params: dict[str, Any] = {"contamination": meta["anomaly_ratio"]}
        _model, scores = _fit_and_score(meta["model"], X, params)
        _ok("학습 완료")

        # 4. AUC (라벨 있는 시나리오만)
        auc = _calc_auc(y_labels, scores)
        result["auc"] = auc
        if auc is not None:
            _ok(f"AUC = {auc:.4f}")

        # 5. Top-N 이상치 추출
        top_rows = _top_n_table(df, scores, n=TOP_N)
        result["top_n_rows"] = len(top_rows)
        _ok(f"Top-N 이상치 {len(top_rows)} 행")

        # 6. OUT-04 HTML 생성
        elapsed = time.perf_counter() - t0
        out_path = _render_html(meta, top_rows, auc, elapsed, out_dir)
        result["out04_path"] = str(out_path)
        _ok(f"OUT-04 저장: {out_path}")

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        _warn(f"시나리오 {sid} 실패: {result['error']}")

    elapsed_total = time.perf_counter() - t0
    _ok(f"완료 ({elapsed_total:.1f}s)")
    return result


# ── Public API ────────────────────────────────────────────────────────


def run_scenario(sid: str) -> dict[str, Any]:
    """Public entry-point: tests/handlers/anomaly/test_e2e.py 에서 직접 호출.

    sid: "S1" ~ "S5"
    반환: {"scenario", "error", "out04_path", "top_n_rows", "auc"}
    """
    if sid not in _SCENARIO_META:
        return {
            "scenario": sid,
            "error": f"Unknown scenario: {sid}",
            "out04_path": None,
            "top_n_rows": 0,
            "auc": None,
        }
    out_dir = _REPO_ROOT / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    return _run_one(sid, out_dir)


# ── main ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    global _VERBOSE  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="ADA v2 anomaly E2E 데모 (Day 10 NY)")
    parser.add_argument(
        "--scenario",
        choices=SCENARIOS,
        default=None,
        help="단일 시나리오 (S1~S5), 생략 시 전체",
    )
    parser.add_argument("--quiet", action="store_true", help="최소 출력 (테스트 시 사용)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
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

    targets = [args.scenario] if args.scenario else SCENARIOS

    if _VERBOSE:
        print(_c("1;37", "=" * 60))
        print(_c("1;37", "  ADA v2 · anomaly E2E 데모"))
        print(_c("1;37", "=" * 60))
        print(_c("36", f"  출력 디렉토리: {out_dir}"))

    t_total = time.perf_counter()
    results: list[dict[str, Any]] = []
    for sid in targets:
        r = run_scenario(sid)
        results.append(r)

    total_elapsed = time.perf_counter() - t_total

    # 요약 출력
    _head("요약")
    n_pass = 0
    for r in results:
        status = "PASS" if r.get("error") is None else "FAIL"
        if r.get("error") is None:
            n_pass += 1
        auc_str = f"AUC={r['auc']:.4f}" if r.get("auc") is not None else "AUC=N/A"
        line = f"  [{status:4s}] [{r['scenario']}] top_n={r['top_n_rows']} {auc_str}"
        if _VERBOSE:
            print(line)
        if r.get("error"):
            _warn(f"  {r['scenario']} ERROR: {r['error']}")

    if _VERBOSE:
        print(f"\n  전체 소요: {total_elapsed:.1f}s  ({len(results)}개 시나리오)")
        print(f"  결과: {n_pass}/{len(results)} PASS")

    # JSON 요약 저장
    summary = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "total_elapsed_sec": round(total_elapsed, 2),
        "scenarios": results,
    }
    summary_path = out_dir / "anomaly_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if _VERBOSE:
        _ok(f"요약 저장: {summary_path}")

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0 if n_pass == len(results) and results else 1


if __name__ == "__main__":
    sys.exit(main())

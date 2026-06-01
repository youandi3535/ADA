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
    python scripts/demo/anomaly_demo.py                    # 5종 전부 (standalone)
    python scripts/demo/anomaly_demo.py --scenario S1
    python scripts/demo/anomaly_demo.py --quiet
    python scripts/demo/anomaly_demo.py --json
    python scripts/demo/anomaly_demo.py --out-dir /tmp/ada_demo
    python scripts/demo/anomaly_demo.py --e2e              # LangGraph E2E 모드 (docker 스택 필요)
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

# 라벨 있는 시나리오 (AUC 측정 대상)
LABELLED = {"S2", "S4"}

# ── E2E 게이트 자동응답 (--e2e 모드 전용) ────────────────────────────
# 5 게이트: G1 방향 · G2 방법론 · G3 모델전략 · G4 best_model · G5 출력.
GATE_AUTO: dict[str, dict[str, Any]] = {
    "G1": {"accept": True, "choice_index": 0},
    "G2": {"accept": True, "choice_index": 0},
    "G3": {"accept": True, "choice_index": 0},
    "G4": {"requires_finetune": False},
    "G5": {"accept": True, "output_codes": ["OUT-04"]},
}


# ── 합성 데이터 생성 (standalone 모드) ──────────────────────────────


def _make_dataset(meta: dict[str, Any], seed: int = 42) -> tuple[Any, Any, Any]:
    """합성 이상탐지 데이터 생성.

    반환: (df, X_normal, y_labels_or_None)
    """
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    n = meta["n_rows"]
    f = meta["n_features"]
    r = meta["anomaly_ratio"]
    n_anom = max(1, int(n * r))
    n_norm = n - n_anom

    _A = rng.random((f, f)) * 0.3
    _cov = np.eye(f) + (_A + _A.T) / 2
    X_norm = rng.multivariate_normal(mean=np.zeros(f), cov=_cov, size=n_norm)
    X_anom = rng.multivariate_normal(mean=rng.uniform(3, 5, size=f), cov=np.eye(f), size=n_anom)

    X_all = np.vstack([X_norm, X_anom])
    y_all = np.array([0] * n_norm + [1] * n_anom, dtype=int)

    perm = rng.permutation(n)
    X_all = X_all[perm]
    y_all = y_all[perm]

    cols = [f"feat_{i}" for i in range(f)]
    df = pd.DataFrame(X_all, columns=cols)

    if meta["has_time"]:
        dates = pd.date_range("2023-01-01", periods=n, freq="h")
        df.insert(0, "timestamp", dates)

    y_labels = y_all if meta["labelled"] else None
    return df, X_all, y_labels


# ── E2E 모드용 시나리오별 합성 데이터 빌더 ────────────────────────────


def build_scenario(scenario_id: str) -> tuple[Any, str | None]:
    """E2E 모드: (df, target_column) 반환. C1~C4 + 엣지."""
    import numpy as np
    import pandas as pd

    if scenario_id == "S1":
        r = np.random.default_rng(1)
        df = pd.DataFrame(
            {
                "amount": np.concatenate([r.normal(100, 10, 950), r.normal(500, 60, 50)]),
                "freq": np.concatenate([r.normal(5, 1, 950), r.normal(22, 5, 50)]),
            }
        )
        return df, None
    if scenario_id == "S2":
        r = np.random.default_rng(2)
        n0, n1 = 950, 50
        df = pd.DataFrame(
            {
                "amount": np.concatenate([r.normal(100, 10, n0), r.normal(500, 60, n1)]),
                "freq": np.concatenate([r.normal(5, 1, n0), r.normal(22, 5, n1)]),
                "is_anomaly": np.concatenate([np.zeros(n0, int), np.ones(n1, int)]),
            }
        )
        return df.sample(frac=1, random_state=2).reset_index(drop=True), "is_anomaly"
    if scenario_id == "S3":
        r = np.random.default_rng(3)
        n = 1000
        ts = pd.date_range("2026-01-01", periods=n, freq="h")
        val = np.sin(np.arange(n) / 24 * 2 * np.pi) * 10 + r.normal(0, 1, n)
        val[500:510] += 30
        return pd.DataFrame({"timestamp": ts, "value": val}), None
    if scenario_id == "S4":
        r = np.random.default_rng(4)
        n = 1000
        ts = pd.date_range("2026-01-01", periods=n, freq="h")
        val = np.sin(np.arange(n) / 24 * 2 * np.pi) * 10 + r.normal(0, 1, n)
        lab = np.zeros(n, int)
        val[500:510] += 30
        lab[500:510] = 1
        return pd.DataFrame({"timestamp": ts, "value": val, "is_anomaly": lab}), "is_anomaly"
    if scenario_id == "S5":
        r = np.random.default_rng(5)
        n0, n1 = 600, 400
        df = pd.DataFrame(
            {
                "amount": np.concatenate([r.normal(100, 10, n0), r.normal(300, 80, n1)]),
                "freq": np.concatenate([r.normal(5, 1, n0), r.normal(15, 6, n1)]),
            }
        )
        return df, None
    raise ValueError(f"unknown scenario: {scenario_id}")


# ── 단일 모델 학습·점수화 (standalone 모드) ──────────────────────────


def _fit_and_score(model_name: str, X_train: Any, params: dict[str, Any]) -> tuple[Any, Any]:
    from pipelines.anomaly.pipeline import AnomalyPipeline, _get_anomaly_scores

    pipeline = AnomalyPipeline()
    model = pipeline.train(X_train, None, model_name, params)
    scores = _get_anomaly_scores(model, X_train, model_name)
    return model, scores


# ── top-N 이상치 추출 ────────────────────────────────────────────────


def _top_n_table(df: Any, scores: Any, n: int = TOP_N) -> list[dict[str, Any]]:
    import numpy as np

    n = min(n, len(scores))
    top_idx = np.argsort(scores)[::-1][:n]
    rows: list[dict[str, Any]] = []
    for i, idx in enumerate(top_idx):
        row: dict[str, Any] = {"rank": i + 1, "row_index": int(idx), "anomaly_score": round(float(scores[idx]), 4)}
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
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sid = meta["sid"]

    auc_cell = f"{auc:.4f}" if auc is not None else "N/A (비지도)"
    n_anomalies_cell = len(top_rows)

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


# ── standalone 모드: 단일 시나리오 실행 ──────────────────────────────


def _run_one(sid: str, out_dir: Path) -> dict[str, Any]:
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
        _info(
            f"합성 데이터 생성: n={meta['n_rows']}, feat={meta['n_features']}, "
            f"labelled={meta['labelled']}, has_time={meta['has_time']}"
        )
        df, X_all, y_labels = _make_dataset(meta)
        _ok(f"데이터 생성 완료 ({len(df)} 행)")

        import numpy as np

        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        X = df[num_cols].values.astype(float)

        _info(f"모델 학습: {meta['model']}")
        params: dict[str, Any] = {"contamination": meta["anomaly_ratio"]}
        _model, scores = _fit_and_score(meta["model"], X, params)
        _ok("학습 완료")

        auc = _calc_auc(y_labels, scores)
        result["auc"] = auc
        if auc is not None:
            _ok(f"AUC = {auc:.4f}")

        top_rows = _top_n_table(df, scores, n=TOP_N)
        result["top_n_rows"] = len(top_rows)
        _ok(f"Top-N 이상치 {len(top_rows)} 행")

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


# ── Public API (standalone 모드) ──────────────────────────────────────


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


# ── E2E 모드 전용 헬퍼 (docker 스택 필요) ────────────────────────────


def _upload_dataset(df: Any, scenario_id: str) -> str:
    from tools.minio_tool import get_minio_client

    file_id = f"uploads/demo/{scenario_id.lower()}.csv"
    get_minio_client().save_dataframe(df, file_id, fmt="csv")
    return file_id


async def _run_pipeline_e2e(file_id: str, target_column: str | None, job_id: str) -> Any:
    from ada.core.state import PipelineState
    from orchestrator.graph import build_graph

    try:
        from langgraph.checkpoint.memory import MemorySaver
    except Exception:
        from langgraph.checkpoint import MemorySaver  # type: ignore

    graph = build_graph(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": job_id}}
    state = PipelineState(
        job_id=job_id,
        file_id=file_id,
        category="anomaly_detection",
        target_column=target_column,
        user_intent="이상 탐지 데모",
    )

    await graph.ainvoke(state, config=config)
    for _ in range(12):
        snap = await graph.aget_state(config)
        if not snap.next:
            break
        cur = snap.values
        gate = cur.get("current_gate") if isinstance(cur, dict) else getattr(cur, "current_gate", None)
        existing = cur.get("gate_responses") if isinstance(cur, dict) else cur.gate_responses
        responses = dict(existing or {})
        if gate:
            responses[gate] = {**responses.get(gate, {}), "user_choice": GATE_AUTO.get(gate, {"accept": True})}
        await graph.aupdate_state(config, {"gate_responses": responses, "current_gate": None})
        await graph.ainvoke(None, config=config)

    snap = await graph.aget_state(config)
    vals = snap.values
    return PipelineState(**vals) if isinstance(vals, dict) else vals


def run_scenario_e2e(sid: str) -> dict[str, Any]:
    """E2E 모드 시나리오 실행 (docker 스택 필요).

    반환 형식은 run_scenario() 와 동일 (+ "elapsed_sec", "eval_passed").
    """
    import asyncio
    import uuid

    t0 = time.time()
    result: dict[str, Any] = {
        "scenario": sid,
        "error": None,
        "out04_path": None,
        "top_n_rows": 0,
        "auc": None,
    }
    try:
        df, target = build_scenario(sid)
        job_id = str(uuid.uuid4())
        file_id = _upload_dataset(df, sid)
        final = asyncio.run(_run_pipeline_e2e(file_id, target, job_id))

        from agents.handlers import get_handler
        from outputs import GENERATORS

        gen = GENERATORS["OUT-04"](job_id=job_id)
        out04 = gen.generate(
            insights=getattr(final, "insights", "") or "",
            best_model=getattr(final, "best_model", {}) or {},
            eda_charts=getattr(final, "eda_charts", []) or [],
            category=final.category,
            user_intent=final.user_intent,
            eval_result=getattr(final, "eval_result", None),
            state=final,
        )
        assets_fn = get_handler(final.category, "assets") or get_handler(final.category, "build")
        ctx = {"output_code": "OUT-04", "category": final.category}
        assets = assets_fn(final, ctx) if assets_fn else {}
        tables = (assets or {}).get("tables") or []
        top_n = tables[0] if tables else None

        eval_result = getattr(final, "eval_result", None) or {}
        result.update(
            {
                "out04_path": out04,
                "top_n_rows": len(top_n["rows"]) if top_n else 0,
                "auc": eval_result.get("auc") or (eval_result.get("metrics") or {}).get("val_auc"),
                "error": getattr(final, "error", None),
                "elapsed_sec": round(time.time() - t0, 1),
                "eval_passed": eval_result.get("passed"),
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        _warn(f"E2E 시나리오 {sid} 실패: {result['error']}")
    return result


# ── main ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    global _VERBOSE  # noqa: PLW0603

    parser = argparse.ArgumentParser(description="ADA v2 anomaly E2E 데모 (Day 10 NY)")
    parser.add_argument("--scenario", choices=SCENARIOS, default=None, help="단일 시나리오 (S1~S5), 생략 시 전체")
    parser.add_argument("--quiet", action="store_true", help="최소 출력 (테스트 시 사용)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    parser.add_argument("--out-dir", default=str(_REPO_ROOT / "out"), help="HTML 출력 디렉토리")
    parser.add_argument("--e2e", action="store_true", help="LangGraph E2E 모드 (docker 스택 필요)")
    parser.add_argument("--budget", type=float, default=300.0, help="E2E 모드 총 시간 예산(초)")
    args = parser.parse_args(argv)

    if args.quiet:
        _VERBOSE = False

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    targets = [args.scenario] if args.scenario else SCENARIOS

    if _VERBOSE:
        mode_label = "E2E (LangGraph)" if args.e2e else "standalone"
        print(_c("1;37", "=" * 60))
        print(_c("1;37", f"  ADA v2 · anomaly 데모 [{mode_label}]"))
        print(_c("1;37", "=" * 60))
        print(_c("36", f"  출력 디렉토리: {out_dir}"))

    t_total = time.perf_counter()
    results: list[dict[str, Any]] = []
    for sid in targets:
        if args.e2e:
            r = run_scenario_e2e(sid)
        else:
            r = run_scenario(sid)
        results.append(r)

    total_elapsed = time.perf_counter() - t_total

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

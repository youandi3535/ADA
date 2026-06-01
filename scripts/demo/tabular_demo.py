#!/usr/bin/env python3
"""tabular E2E 데모 — Titanic·Iris·Adult 3 시나리오 콘솔 시연 (Day 10 jh).

사용:
  python scripts/demo/tabular_demo.py                       # 3종 전부, RandomForest
  python scripts/demo/tabular_demo.py --scenario titanic
  python scripts/demo/tabular_demo.py --model LightGBM       # 다른 모델 시연
  python scripts/demo/tabular_demo.py --real                 # 실데이터 fetch 시도(실패 시 합성)
  python scripts/demo/tabular_demo.py --out                  # OUT-04 자산 경로 출력

엔진(load_scenario/run_scenario)은 tests/handlers/tabular/test_e2e.py 와 공유한다(중복 제거).
전부 PASS → exit 0, 하나라도 실패 → exit 1.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time

# 리포 루트를 import path 에 추가(스크립트 단독 실행 대비)
_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.handlers.tabular.test_e2e import load_scenario, run_scenario  # noqa: E402

_LABEL = {"titanic": "Titanic", "iris": "Iris", "adult": "Adult"}
_TASK_DISP = {"titanic": "classification", "iris": "multiclass", "adult": "regression"}


def render_header() -> str:
    return (
        f"{'시나리오':<10} {'task':<14} {'model':<13} {'metric':<8} {'value':>6} {'임계':>5}  {'결과':<5} {'시간':>6}"
    )


def render_row(r: dict) -> str:
    res = "PASS" if r["passed"] else "FAIL"
    return (
        f"{_LABEL[r['name']]:<10} {_TASK_DISP[r['name']]:<14} {r['model']:<13} "
        f"{r['metric_key']:<8} {r['value']:>6.3f} {r['threshold']:>5.2f}  "
        f"{res:<5} {r['elapsed_s']:>5.1f}s"
    )


def maybe_emit_out04(name: str) -> list[str]:
    """--out: OUT-04 용 자산 경로(있으면) 출력. 핸들러 미구현/실패 시 빈 목록."""
    try:
        from ada.core.state import PipelineState
        from agents.handlers import get_handler

        df, target, task = load_scenario(name)
        state = PipelineState(
            job_id="demo",
            file_id=f"memory://{name}",
            category="tabular_ml",
            target_column=target,
            task=task,
        )
        out: list[str] = []
        charts_fn = get_handler("tabular_ml", "charts")
        if charts_fn:
            out += list(charts_fn(df, state) or [])
        assets_fn = get_handler("tabular_ml", "assets")
        if assets_fn:
            out += list((assets_fn(state) or {}).get("extra_charts", []))
        return out
    except Exception as exc:  # 데모는 자산 실패로 죽지 않는다
        print(f"   (OUT-04 자산 생략: {type(exc).__name__})")
        return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="tabular E2E 데모 (Day 10 jh)")
    ap.add_argument("--scenario", choices=["all", "titanic", "iris", "adult"], default="all")
    ap.add_argument(
        "--model",
        choices=["RandomForest", "LightGBM", "XGBoost", "CatBoost"],
        default="RandomForest",
    )
    ap.add_argument("--real", action="store_true", help="실데이터 fetch 시도(실패 시 합성)")
    ap.add_argument("--out", action="store_true", help="OUT-04 자산 경로 출력")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args(argv)

    names = ["titanic", "iris", "adult"] if args.scenario == "all" else [args.scenario]

    print("=" * 80)
    print(f"  ADA tabular E2E 데모 · model={args.model} · real={args.real}")
    print("=" * 80)
    print(render_header())
    print("-" * 80)

    results: list[dict] = []
    t0 = time.perf_counter()
    for name in names:
        try:
            r = run_scenario(name, model=args.model, real=args.real, seed=args.seed)
        except Exception as exc:
            print(f"{_LABEL[name]:<10} ERROR: {type(exc).__name__}: {exc}")
            results.append({"name": name, "passed": False})
            continue
        print(render_row(r))
        if args.out:
            for p in maybe_emit_out04(name):
                print(f"   └ OUT-04: {p}")
        results.append(r)

    total = time.perf_counter() - t0
    n_pass = sum(1 for r in results if r.get("passed"))
    budget = "≤ 5분" if total <= 300 else "⚠ 5분 초과"
    print("-" * 80)
    print(f"합계: {n_pass}/{len(results)} PASS · {total:.1f}s ({budget})")
    print("=" * 80)
    return 0 if n_pass == len(results) and results else 1


if __name__ == "__main__":
    raise SystemExit(main())

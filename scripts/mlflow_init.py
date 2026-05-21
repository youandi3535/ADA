"""
scripts/mlflow_init.py  -  MLflow 4개 실험 초기화 (v2 스코프)

사용:
    docker compose --profile core run --rm api python scripts/mlflow_init.py

만들어지는 실험 (Day02 v2 §6 + 2026-05-18 스코프 축소):
    ada-tabular-ml, ada-tabular-dl, ada-timeseries, ada-anomaly

⚠ image / nlp 카테고리는 v2 스코프 축소(메모리 ada_scope_decision) 로 제거됨.
"""

from __future__ import annotations

import os
import sys

import mlflow

EXPERIMENTS = [
    "ada-tabular-ml",
    "ada-tabular-dl",
    "ada-timeseries",
    "ada-anomaly",
]


def main() -> int:
    tracking_uri = os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    mlflow.set_tracking_uri(tracking_uri)

    client = mlflow.tracking.MlflowClient()
    existing = {e.name for e in client.search_experiments()}

    for name in EXPERIMENTS:
        if name in existing:
            print(f"[skip] experiment exists: {name}")
            continue
        exp_id = client.create_experiment(name=name)
        print(f"[ok]   created experiment:  {name}  (id={exp_id})")

    print(f"[done] MLflow bootstrap complete ({len(EXPERIMENTS)} experiments).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

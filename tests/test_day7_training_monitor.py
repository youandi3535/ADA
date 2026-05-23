"""Day 7 — TrainingMonitorAgent 본격화.

DoD (3 합성 케이스):
    1) NaN/Inf in all models → error_recovery
    2) 3 epoch 연속 val 하락 → error_recovery
    3) 학습 시간 초과 → error_recovery
    + 메모리 80% 초과는 warning (학습 진행)
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta

import pytest

from ada.core.state import PipelineState


def _state(**kwargs):
    base = dict(
        job_id="00000000-0000-0000-0000-000000000001",
        file_id="f.csv",
        category="tabular_ml",
        target_column="y",
        trained_models=[],
    )
    base.update(kwargs)
    return PipelineState(**base)


# ----- 1) NaN/Inf in all models -------------------------------------------------
def test_nan_inf_all_models_triggers_recovery():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(
        trained_models=[
            {"model_name": "RandomForest", "metrics": {"val_f1": float("nan")}},
            {"model_name": "XGBoost", "metrics": {"val_f1": float("inf")}},
        ]
    )
    out = asyncio.run(TrainingMonitorAgent()(s))
    assert out.next_agent == "error_recovery"
    assert "NaN/Inf" in (out.error or "")
    assert len(out.training_warnings) >= 2


# ----- 2) 3 epoch 연속 val_f1 하락 → error_recovery -----------------------------
def test_diverging_val_metric_triggers_recovery():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(
        trained_models=[
            {
                "model_name": "RandomForest",
                "metrics": {"val_f1": 0.5},
                "val_history": [{"val_f1": 0.8}, {"val_f1": 0.7}, {"val_f1": 0.6}, {"val_f1": 0.5}],
            },
            {
                "model_name": "XGBoost",
                "metrics": {"val_f1": 0.4},
                "val_history": [{"val_f1": 0.9}, {"val_f1": 0.7}, {"val_f1": 0.5}, {"val_f1": 0.4}],
            },
        ]
    )
    out = asyncio.run(TrainingMonitorAgent()(s))
    assert out.next_agent == "error_recovery"
    assert "발산" in (out.error or "")


# ----- 3) 학습 시간 초과 → error_recovery --------------------------------------
def test_timeout_triggers_recovery():
    from agents.training_monitor import TrainingMonitorAgent

    # 1 분 타임아웃에 started_at 을 2 시간 전으로 설정
    s = _state(
        trained_models=[{"model_name": "X", "metrics": {"val_f1": 0.5}}],
        started_at=datetime.utcnow() - timedelta(hours=2),
    )
    agent = TrainingMonitorAgent(timeout_min=1)
    out = asyncio.run(agent(s))
    assert out.next_agent == "error_recovery"
    assert "타임아웃" in (out.error or "")
    assert any("타임아웃" in w for w in out.training_warnings)


# ----- 4) 정상 (warning 없음) → metrics_aggregator ----------------------------
def test_healthy_run_passes_to_aggregator():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(
        trained_models=[
            {
                "model_name": "X",
                "metrics": {"val_f1": 0.85},
                "val_history": [{"val_f1": 0.8}, {"val_f1": 0.83}, {"val_f1": 0.85}],
            },
        ]
    )
    out = asyncio.run(TrainingMonitorAgent()(s))
    assert out.next_agent == "metrics_aggregator"


# ----- 5) 메모리 경고 — fail 안 함 ----------------------------------------------
def test_memory_warning_is_non_fatal(monkeypatch):
    from agents import training_monitor as tm
    from agents.training_monitor import TrainingMonitorAgent

    monkeypatch.setattr(tm, "_memory_percent", lambda: 90.0)
    s = _state(trained_models=[{"model_name": "X", "metrics": {"val_f1": 0.85}}])
    out = asyncio.run(TrainingMonitorAgent(memory_warn_pct=80.0)(s))
    assert out.next_agent == "metrics_aggregator"  # fail 아님
    assert any("메모리" in w for w in out.training_warnings)


# ----- 6) 일부만 NaN 인 경우 — fail 안 하고 warning 만 적재 ----------------------
def test_partial_nan_records_warning_only():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(
        trained_models=[
            {"model_name": "X", "metrics": {"val_f1": 0.85}},
            {"model_name": "Y", "metrics": {"val_f1": float("nan")}},
        ]
    )
    out = asyncio.run(TrainingMonitorAgent()(s))
    assert out.next_agent == "metrics_aggregator"
    assert any("NaN/Inf" in w for w in out.training_warnings)

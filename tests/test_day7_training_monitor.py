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


# ─── Day 7 V3 보강 테스트 (T-7 ~ T-13) ──────────────────────────────────────


# ----- T-7) 한 모델 다중 NaN — 다른 정상 모델 존재 → recovery 안 됨 ---------------
#         (모델 단위 카운트 false-positive 회귀 방지)
def test_one_model_multiple_nan_does_not_trigger_recovery():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(
        trained_models=[
            {
                "model_name": "Broken",
                "metrics": {"val_f1": float("nan"), "val_accuracy": float("nan")},
            },
            {"model_name": "Healthy", "metrics": {"val_f1": 0.85}},
        ]
    )
    out = asyncio.run(TrainingMonitorAgent()(s))
    # 모델 2개 중 NaN 모델 1개뿐 → fatal 아님
    assert out.next_agent == "metrics_aggregator"
    assert any("NaN/Inf" in w for w in out.training_warnings)


# ----- T-8) 일부 모델만 발산 — 다른 정상 모델 존재 → recovery 안 됨 --------------
def test_partial_models_diverging_does_not_trigger_recovery():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(
        trained_models=[
            {
                "model_name": "Diverging",
                "metrics": {"val_f1": 0.4},
                "val_history": [{"val_f1": 0.8}, {"val_f1": 0.6}, {"val_f1": 0.5}, {"val_f1": 0.4}],
            },
            {
                "model_name": "Healthy",
                "metrics": {"val_f1": 0.85},
                "val_history": [{"val_f1": 0.8}, {"val_f1": 0.83}, {"val_f1": 0.85}],
            },
        ]
    )
    out = asyncio.run(TrainingMonitorAgent()(s))
    assert out.next_agent == "metrics_aggregator"
    assert any("발산" in w for w in out.training_warnings)


# ----- T-9) trained_models 가 빈 리스트 → 정상 통과 -----------------------------
def test_empty_trained_models_passes():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(trained_models=[])
    out = asyncio.run(TrainingMonitorAgent()(s))
    assert out.next_agent == "metrics_aggregator"


# ----- T-10) started_at = None → timeout 체크 skip, 정상 통과 -------------------
def test_started_at_none_skips_timeout():
    from agents.training_monitor import TrainingMonitorAgent

    # PipelineState 는 started_at 을 Optional 로 허용하지 않으므로
    # model_construct 로 validation 을 우회해 None 을 직접 주입한다.
    base = _state(trained_models=[{"model_name": "X", "metrics": {"val_f1": 0.85}}])
    s = PipelineState.model_construct(**{**base.model_dump(), "started_at": None})
    out = asyncio.run(TrainingMonitorAgent(timeout_min=1)(s))
    # started_at 없어도 monitor 가 죽지 않고 정상 분기
    assert out.next_agent == "metrics_aggregator"


# ----- T-11) psutil 미설치 시나리오 — _memory_percent → None 시 graceful --------
def test_psutil_missing_graceful_skip(monkeypatch):
    from agents import training_monitor as tm
    from agents.training_monitor import TrainingMonitorAgent

    monkeypatch.setattr(tm, "_memory_percent", lambda: None)
    s = _state(trained_models=[{"model_name": "X", "metrics": {"val_f1": 0.85}}])
    out = asyncio.run(TrainingMonitorAgent(memory_warn_pct=80.0)(s))
    assert out.next_agent == "metrics_aggregator"
    # 메모리 warning 이 추가되지 않아야 함
    assert not any("메모리" in w for w in out.training_warnings)


# ----- T-12) timeout 임계 미만 (-1초) → 정상 통과 -------------------------------
def test_timeout_below_threshold_passes():
    from agents.training_monitor import TrainingMonitorAgent

    # timeout 10 분, started_at = 9 분 전
    s = _state(
        trained_models=[{"model_name": "X", "metrics": {"val_f1": 0.85}}],
        started_at=datetime.utcnow() - timedelta(minutes=9),
    )
    out = asyncio.run(TrainingMonitorAgent(timeout_min=10)(s))
    assert out.next_agent == "metrics_aggregator"
    assert (out.error or "") == ""


# ----- T-13) LOWER_IS_BETTER 메트릭 단조 상승 (val_loss) → 발산 → recovery -----
def test_lower_is_better_diverging_triggers_recovery():
    from agents.training_monitor import TrainingMonitorAgent

    s = _state(
        trained_models=[
            {
                "model_name": "M1",
                "metrics": {"val_loss": 0.4},
                "val_history": [{"val_loss": 0.1}, {"val_loss": 0.2}, {"val_loss": 0.3}, {"val_loss": 0.4}],
            },
            {
                "model_name": "M2",
                "metrics": {"val_loss": 0.5},
                "val_history": [{"val_loss": 0.2}, {"val_loss": 0.3}, {"val_loss": 0.4}, {"val_loss": 0.5}],
            },
        ]
    )
    out = asyncio.run(TrainingMonitorAgent()(s))
    assert out.next_agent == "error_recovery"
    assert "발산" in (out.error or "")
    assert any("상승" in w for w in out.training_warnings)

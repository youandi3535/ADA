"""agents.training_monitor — TrainingMonitorAgent (Day 7 본격화).

발산 / NaN / 시간 초과 / 메모리 압박 신호를 조기 감지하고,
심각도 따라 warning 적재 또는 next_agent='error_recovery'.

심각도 정책:
    - NaN/Inf 가 전 모델에서 발견되면 → error_recovery
    - val 메트릭이 3 연속 하락 (history 보유 시) → error_recovery
    - 학습 시간 임계치 초과 → error_recovery (config: timeout_min)
    - 메모리 사용률 ≥ 80% → 경고만 (warning) — 학습은 진행 가능

state.training_warnings 에 사람이 읽을 수 있는 한국어 라인 누적.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ada.core.config import settings
from ada.core.state import PipelineState
from agents.base import BaseAgent

# 모델 평가 기준 메트릭 (낮을수록 좋은 메트릭 vs 높을수록 좋은 메트릭)
HIGHER_IS_BETTER: tuple[str, ...] = (
    "val_accuracy",
    "val_f1",
    "val_precision",
    "val_recall",
    "val_roc_auc",
    "val_r2",
    "val_auc",
    "val_pr_at_10",
)
LOWER_IS_BETTER: tuple[str, ...] = ("val_rmse", "val_mae", "val_mape", "val_loss")


# ─── 자료구조 (Day 7 V3 설계도 §5) ──────────────────────────────────────────
class Severity(str, Enum):
    """모니터 결정의 심각도. str 상속 — JSON/log 직렬화 호환."""

    OK = "ok"  # → metrics_aggregator
    WARN = "warning"  # → metrics_aggregator (warning 적재만)
    FATAL = "fatal"  # → error_recovery


@dataclass(frozen=True, slots=True)
class ModelDiagnosis:
    """모델 1개의 진단 결과. has_nan_inf/is_diverging 는 모델 단위 boolean."""

    name: str
    has_nan_inf: bool = False
    is_diverging: bool = False
    messages: tuple[str, ...] = field(default_factory=tuple)


def _memory_percent() -> float | None:
    """현재 프로세스 또는 시스템 메모리 사용률(%) — psutil 없으면 None."""
    try:
        import psutil  # type: ignore

        return float(psutil.virtual_memory().percent)
    except Exception:
        return None


# ─── 순수 함수 (Day 7 V3 설계도 §6) ─────────────────────────────────────────
def _has_nan_inf(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    """metrics 안에 NaN/Inf 값이 있는지. (있음여부, [키=값] 메시지)."""
    msgs: list[str] = []
    for k, v in (metrics or {}).items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue  # str/None/dict 등 → 숫자 아님, skip
        if math.isnan(fv) or math.isinf(fv):
            msgs.append(f"{k}={v}")
    return bool(msgs), msgs


def _extract_history(model: dict[str, Any], target_key: str) -> list[float]:
    """model dict 의 epoch history 리스트에서 target_key 값만 float 리스트로."""
    if not target_key:
        return []
    for field_name in ("val_history", "metrics_history", "epoch_log"):
        hist = model.get(field_name)
        if isinstance(hist, list) and hist:
            out: list[float] = []
            for ep in hist:
                if isinstance(ep, dict) and target_key in ep:
                    try:
                        out.append(float(ep[target_key]))
                    except (TypeError, ValueError):
                        pass  # epoch 1건 결측 — 다음 진행
            return out
    return []


def _is_diverging_v2(
    history: list[float],
    higher_is_better: bool,
    min_len: int = 3,
) -> bool:
    """history 마지막 min_len 개가 단조 악화(higher=하락 / lower=상승)인지.

    평탄(동일값) → False (악화 아님).
    history 길이 < min_len → False (판단 불가).
    """
    if len(history) < min_len:
        return False
    last = history[-min_len:]
    if higher_is_better:
        return all(last[i] > last[i + 1] for i in range(min_len - 1))
    return all(last[i] < last[i + 1] for i in range(min_len - 1))


def _pick_metric_key(metrics: dict[str, Any]) -> tuple[str | None, bool]:
    """metrics 안에서 발산 체크용 키 선정. (키, higher_is_better)."""
    for k in HIGHER_IS_BETTER:
        if k in metrics:
            return k, True
    for k in LOWER_IS_BETTER:
        if k in metrics:
            return k, False
    return None, True  # 키 없음 — 발산 체크 skip


def _elapsed_minutes(started_at: Any) -> float | None:
    """started_at 으로부터 경과 시간(분). datetime 아니거나 None 이면 None."""
    if started_at is None:
        return None
    try:
        from datetime import datetime, timezone

        if started_at.tzinfo is None:
            now = datetime.utcnow()
        else:
            now = datetime.now(timezone.utc)
        elapsed = (now - started_at).total_seconds() / 60.0
        return max(0.0, elapsed)  # 시스템 시계 거꾸로 → 0 클램프
    except (TypeError, AttributeError):
        return None


class TrainingMonitorAgent(BaseAgent):
    uses_llm = False

    def __init__(
        self,
        *args: Any,
        timeout_min: int | None = None,
        memory_warn_pct: float = 80.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        # 기본은 settings.pipeline_timeout_min
        self.timeout_min = timeout_min or settings.pipeline_timeout_min
        self.memory_warn_pct = memory_warn_pct

    async def __call__(self, state: PipelineState) -> PipelineState:
        """Day 7 V3: 모델 단위 카운트 + LOWER_IS_BETTER 발산 + 구조화 로그."""
        async with self.log_agent_run(state):
            warnings: list[str] = list(state.training_warnings)

            # ─── 모델별 진단 루프 (각 모델 1개 → ModelDiagnosis 1개) ──────
            diagnoses: list[ModelDiagnosis] = []
            for m in state.trained_models or []:
                try:
                    diagnoses.append(self._diagnose_model(m))
                except Exception as exc:  # 모니터는 절대 raise 하지 않음
                    name = (m or {}).get("model_name", "?") if isinstance(m, dict) else "?"
                    self.logger.warning(
                        "training_monitor_model_diagnose_failed",
                        model=name,
                        error=str(exc),
                    )
                    diagnoses.append(
                        ModelDiagnosis(
                            name=name,
                            messages=(f"{name}: 진단 실패 ({exc.__class__.__name__})",),
                        )
                    )

            # 사람이 읽을 warning 누적
            for dx in diagnoses:
                warnings.extend(dx.messages)

            # ─── 글로벌 체크 (timeout, memory) ─────────────────────────────
            elapsed_min = _elapsed_minutes(state.started_at)
            mem_pct = _memory_percent()

            nan_models = sum(1 for d in diagnoses if d.has_nan_inf)
            div_models = sum(1 for d in diagnoses if d.is_diverging)
            total = len(diagnoses)

            # ─── 우선순위 게이트 (P1 → P5) ─────────────────────────────────
            # P1: 학습 타임아웃 (가장 시급 — 무한루프 즉시 차단)
            if elapsed_min is not None and elapsed_min > self.timeout_min:
                warnings.append(f"학습 경과 시간 {elapsed_min:.1f}분 — 타임아웃 {self.timeout_min}분 초과")
                self._log_summary(state, Severity.FATAL, "timeout", total, nan_models, div_models, elapsed_min, mem_pct)
                return state.with_update(
                    training_warnings=warnings,
                    error="학습 타임아웃 초과",
                    next_agent="error_recovery",
                )

            # P2: 전 모델 NaN/Inf
            if total > 0 and nan_models >= total:
                self._log_summary(state, Severity.FATAL, "all_nan", total, nan_models, div_models, elapsed_min, mem_pct)
                return state.with_update(
                    training_warnings=warnings,
                    error="모든 학습 모델에서 NaN/Inf",
                    next_agent="error_recovery",
                )

            # P3: 전 모델 발산
            if total > 0 and div_models >= total:
                self._log_summary(
                    state, Severity.FATAL, "all_diverge", total, nan_models, div_models, elapsed_min, mem_pct
                )
                return state.with_update(
                    training_warnings=warnings,
                    error="모든 학습 모델에서 val 메트릭 발산",
                    next_agent="error_recovery",
                )

            # P4: 메모리 임계 — fatal 아님, warning 만 추가
            if mem_pct is not None and mem_pct >= self.memory_warn_pct:
                warnings.append(f"메모리 사용률 {mem_pct:.1f}% — 임계 {self.memory_warn_pct:.0f}% 초과")

            # P5: 정상 통과
            self._log_summary(state, Severity.OK, "ok", total, nan_models, div_models, elapsed_min, mem_pct)
            return state.with_update(
                training_warnings=warnings,
                next_agent="metrics_aggregator",
            )

    # ── 보조 메서드 ────────────────────────────────────────────────────────
    def _diagnose_model(self, model: dict[str, Any]) -> ModelDiagnosis:
        """모델 1개에 대한 진단 (NaN + 발산). 예외는 호출측에서 처리."""
        name = model.get("model_name", "?")
        metrics = model.get("metrics") or {}

        has_nan, nan_msgs = _has_nan_inf(metrics)
        target_key, higher = _pick_metric_key(metrics)
        history = _extract_history(model, target_key) if target_key else []
        is_div = _is_diverging_v2(history, higher_is_better=higher) if target_key else False

        msgs: list[str] = []
        for nm in nan_msgs:
            key = nm.split("=", 1)[0]
            msgs.append(f"{name} 의 {key} 가 NaN/Inf 입니다")
        if is_div and target_key:
            direction = "하락" if higher else "상승"
            msgs.append(f"{name} 의 {target_key} 가 3 epoch 연속 {direction} — 발산 의심")

        return ModelDiagnosis(
            name=name,
            has_nan_inf=has_nan,
            is_diverging=is_div,
            messages=tuple(msgs),
        )

    def _log_summary(
        self,
        state: PipelineState,
        severity: Severity,
        reason: str,
        n_models: int,
        nan_models: int,
        div_models: int,
        elapsed_min: float | None,
        mem_pct: float | None,
    ) -> None:
        """구조화 로그 한 줄 — 운영 시 grep 가능."""
        self.logger.info(
            "training_monitor_summary",
            job_id=state.job_id,
            decision=severity.value,
            reason=reason,
            n_models=n_models,
            nan_models=nan_models,
            div_models=div_models,
            elapsed_min=round(elapsed_min, 2) if elapsed_min is not None else None,
            mem_pct=mem_pct,
        )

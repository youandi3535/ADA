"""agents.gates.model_comparison_reporter — G4 Top-3 학습 결과 비교."""
from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate


class ModelComparisonReporterAgent(BaseGate):
    """G4 — 학습된 모델들의 메트릭 비교표. LLM 호출 없음."""

    gate_code = "G4"
    uses_llm = False

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        # 학습된 모델 그대로 제안으로 변환 (objective_value 내림차순)
        objective_metric = {
            "tabular_ml": "val_f1", "tabular_dl": "val_f1",
            "timeseries": "val_rmse", "anomaly_detection": "val_auc",
        }.get(state.category, "val_f1")
        direction = "min" if objective_metric == "val_rmse" else "max"

        models = list(state.trained_models or [])
        def _key(m: dict[str, Any]) -> float:
            v = (m.get("metrics") or {}).get(objective_metric)
            try:
                return float(v) if v is not None else (1e18 if direction == "min" else -1e18)
            except Exception:
                return -1e18

        models.sort(key=_key, reverse=(direction == "max"))
        proposals: list[dict[str, Any]] = []
        for i, m in enumerate(models[:3], start=1):
            proposals.append({
                "id": i,
                "title": m.get("model_name", "?"),
                "metrics": m.get("metrics") or {},
                "minio_path": m.get("minio_path"),
                "mlflow_run_id": m.get("mlflow_run_id"),
                "model_sha256": m.get("model_sha256"),
                "objective_value": _key(m),
                "rationale": f"{objective_metric} 기준 #{i}",
                "score": 1.0 - 0.15 * (i - 1),
                "requires_finetune": False,
            })
        if not proposals:
            proposals = [{"id": 1, "title": "no trained model",
                          "rationale": "학습 결과 없음", "score": 0.0}]
        return proposals

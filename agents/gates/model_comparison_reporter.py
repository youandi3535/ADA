"""agents.gates.model_comparison_reporter — G4 Top-2 학습 결과 비교 + 커스텀 옵션."""
from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 모델명이나 선택 기준을 직접 입력하세요.",
    "metrics": {},
    "score": None,
    "is_custom": True,
}

_RATIONALE = [
    "학습 결과 최고 성능 모델입니다. 교차 검증 지표 기준 1순위 추천.",
    "안정성과 일반화 균형이 좋은 차선 모델입니다. 과적합 위험이 상대적으로 낮습니다.",
]


class ModelComparisonReporterAgent(BaseGate):
    """G4 — 학습된 모델 Top-2 비교 + 커스텀 옵션. LLM 호출 없음."""

    gate_code = "G4"
    uses_llm = False

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
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
        for i, m in enumerate(models[:2], start=1):
            obj_val = _key(m)
            val_str = f"{obj_val:.4f}" if isinstance(obj_val, float) and abs(obj_val) < 1e17 else "—"
            proposals.append({
                "id": i,
                "title": m.get("model_name", "?"),
                "metrics": m.get("metrics") or {},
                "minio_path": m.get("minio_path"),
                "mlflow_run_id": m.get("mlflow_run_id"),
                "model_sha256": m.get("model_sha256"),
                "objective_value": obj_val,
                "rationale": f"{_RATIONALE[i - 1]} ({objective_metric}: {val_str})",
                "score": 1.0 - 0.15 * (i - 1),
                "requires_finetune": False,
            })
        if not proposals:
            proposals = [{"id": 1, "title": "학습된 모델 없음",
                          "rationale": "학습 결과가 없습니다.", "score": 0.0}]
        return proposals + [_CUSTOM_OPTION]

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        uc = user_choice if isinstance(user_choice, dict) else {}
        custom = uc.get("custom_intent")

        # 커스텀 텍스트: 입력된 모델명이 trained_models 에 있으면 best_model 로 교체
        if isinstance(custom, str) and custom.strip():
            keyword = custom.strip().lower()
            matched = next(
                (m for m in (state.trained_models or [])
                 if keyword in (m.get("model_name") or "").lower()),
                None,
            )
            if matched:
                self.logger.info("g4_custom_model_matched", model=matched.get("model_name"))
                return state.with_update(best_model=matched)
            self.logger.info("g4_custom_no_match", intent=custom.strip()[:80])
            return state

        # 순위 선택: 선택된 proposal → best_model 업데이트
        rank = uc.get("adopted_rank")
        if rank and rank != 0:
            chosen = next((p for p in proposals if p.get("id") == rank), None)
            if chosen and chosen.get("title") and not chosen.get("is_custom"):
                best = {
                    "model_name": chosen["title"],
                    "metrics": chosen.get("metrics") or {},
                    "minio_path": chosen.get("minio_path"),
                    "mlflow_run_id": chosen.get("mlflow_run_id"),
                    "model_sha256": chosen.get("model_sha256"),
                    "objective_value": chosen.get("objective_value"),
                }
                return state.with_update(best_model=best)

        return state

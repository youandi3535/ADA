"""agents.schema_validator — SchemaValidatorAgent (Day05 §2)."""
from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

# v2 4 카테고리만
CATEGORY_RULES: dict[str, dict[str, Any]] = {
    "tabular_ml": {
        "min_rows": 100,
        "max_cols": 1000,
        "requires_target": True,
        "min_target_classes": 2,
    },
    "tabular_dl": {
        "min_rows": 1000,
        "max_cols": 1000,
        "requires_target": True,
    },
    "timeseries": {
        "min_rows": 50,
        "requires_target": True,
        "requires_date_col": True,
    },
    "anomaly_detection": {
        "min_rows": 500,
        "requires_target": False,
    },
}


class SchemaValidatorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            rules = CATEGORY_RULES.get(state.category)
            if rules is None:
                v = {"is_valid": False,
                     "errors": [f"Unsupported category: {state.category}"],
                     "warnings": []}
                return state.with_update(validation=v, next_agent="error_recovery",
                                         error=v["errors"][0])
            v = self._validate(state.data_profile or {}, rules)
            next_agent = "gate_direction" if v["is_valid"] else "error_recovery"
            return state.with_update(
                validation=v,
                next_agent=next_agent,
                error=None if v["is_valid"] else "; ".join(v["errors"]),
            )

    @staticmethod
    def _validate(profile: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []

        rows = int(profile.get("rows", 0))
        cols = int(profile.get("cols", 0))

        if "min_rows" in rules and rows < rules["min_rows"]:
            errors.append(f"행 수 부족: {rows} < {rules['min_rows']}")
        if "max_cols" in rules and cols > rules["max_cols"]:
            errors.append(f"컬럼 수 초과: {cols} > {rules['max_cols']}")

        if rules.get("requires_target") and not profile.get("has_target"):
            errors.append("target_column 지정 필수")

        if rules.get("min_target_classes"):
            cd = profile.get("class_distribution") or {}
            if cd and len(cd) < rules["min_target_classes"]:
                errors.append(
                    f"target 클래스 수 부족: {len(cd)} < {rules['min_target_classes']}"
                )

        if rules.get("requires_date_col") and not profile.get("date_col"):
            errors.append("시계열 카테고리: 날짜 컬럼 필수")

        for col, missing_rate in (profile.get("missing") or {}).items():
            if missing_rate > 0.5:
                warnings.append(f"컬럼 '{col}' 결측률 {missing_rate:.1%} — 제거 권장")

        return {
            "is_valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

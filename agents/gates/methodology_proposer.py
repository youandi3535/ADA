"""agents.gates.methodology_proposer — G2 방법론 제안 (정형ML/정형DL/시계열/이상탐지)."""
from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = """당신은 AutoML 자문가입니다. data_profile + G1 채택안 을 보고
4 후보 방법론(tabular_ml / tabular_dl / timeseries / anomaly_detection) 중
권장 순위 2~3 개를 JSON 배열로 반환합니다. id, title (=methodology code),
rationale, score 포함."""


class MethodologyProposerAgent(BaseGate):
    """G2 — 방법론(카테고리) 권장. 본 게이트가 카테고리 변경을 제안할 수 있다."""

    gate_code = "G2"
    model_name = "claude-sonnet-4-6"

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        payload = {
            "category": state.category,
            "data_profile": state.data_profile,
            "g1_choice": (state.gate_responses or {}).get("G1", {}).get("user_choice"),
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False)[:4000],
                max_tokens=500,
                temperature=0.1,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr:
                return arr[: self.n_proposals]
        except Exception as e:
            self.logger.warning("g2_llm_failed", error=str(e))

        # fallback — 현재 카테고리를 우선 추천
        return [
            {"id": 1, "title": state.category,
             "rationale": "사용자 지정 카테고리 유지", "score": 0.9},
            {"id": 2, "title": "tabular_ml",
             "rationale": "안정적인 정형 ML baseline", "score": 0.6},
        ]

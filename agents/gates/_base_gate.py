"""agents.gates._base_gate — 5 게이트 공통 베이스.

각 게이트는 ``_propose()`` 만 오버라이드한다. 공통 후처리:
  - gate_responses[gate_code] = {"proposals": [...], "awaiting_decision": True}
  - current_gate = gate_code  (LangGraph interrupt_after 가 즉시 멈춤)
"""

from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent


class BaseGate(BaseAgent):
    """게이트 노드 공통 — interrupt-by-name 직전 상태 마킹."""

    #: 'G2' ~ 'G6' — 서브클래스 필수 오버라이드
    gate_code: str = "G?"

    #: 게이트당 제안 개수 (마스터 §3 — 보통 3)
    n_proposals: int = 3

    uses_llm: bool = True

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        """서브클래스 본문. ``[{id, title, rationale, score}, ...]`` 반환."""
        raise NotImplementedError

    def _apply_choice(self, state: PipelineState, user_choice: Any, proposals: list[dict[str, Any]]) -> PipelineState:
        """게이트 재진입 시 사용자 선택을 상태에 반영 (기본: 변화 없음).

        서브클래스가 override 하여 category/target(G2)·outputs(G6) 등을 적용한다.
        """
        return state

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # 이미 사용자 응답이 채워졌으면 — 선택을 상태에 반영하고 통과 (재진입 보호)
            existing = (state.gate_responses or {}).get(self.gate_code, {})
            if existing.get("user_choice") is not None:
                updated = self._apply_choice(state, existing.get("user_choice"), existing.get("proposals") or [])
                return updated.with_update(current_gate=None)

            try:
                proposals = await self._propose(state)
            except Exception as e:
                self.logger.warning("gate_propose_failed", gate=self.gate_code, error=str(e))
                proposals = [{"id": 1, "title": "기본 권장", "rationale": "LLM 실패로 fallback", "score": 0.5}]

            if state.re_loop_count > 0:
                gate_responses = dict(state.gate_responses)
                gate_responses[self.gate_code] = {
                    **(gate_responses.get(self.gate_code) or {}),
                    "proposals": proposals,
                    "awaiting_decision": False,
                    "auto_resolved": True,
                    "auto_resolved_reason": f"re_loop={state.re_loop_count}",
                }
                resolved = list(state.auto_resolved_gates or [])
                if self.gate_code not in resolved:
                    resolved.append(self.gate_code)
                return state.with_update(
                    gate_responses=gate_responses,
                    auto_resolved_gates=resolved,
                    current_gate=None,
                )
            gate_responses = dict(state.gate_responses)
            gate_responses[self.gate_code] = {
                "proposals": proposals,
                "awaiting_decision": True,
                "auto_resolved": False,
            }
            return state.with_update(
                gate_responses=gate_responses,
                current_gate=self.gate_code,
                # next_agent 은 고정 엣지가 처리하므로 None
            )

    def _safe_parse_json_array(self, text: str) -> list[dict[str, Any]]:
        try:
            data = self._parse_json(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "proposals" in data:
                return list(data["proposals"])
        except Exception as e:
            self.logger.warning("gate_json_parse_failed", error=str(e))
        return []

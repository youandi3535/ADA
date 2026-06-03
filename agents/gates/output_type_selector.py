"""agents.gates.output_type_selector — G5 5종 산출물 추천."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = """당신은 의도·청중·메트릭을 보고 5종 산출물 중 적절한 조합을
JSON 으로 추천합니다. 후보 풀(권위): OUT-01(.pptx), OUT-02(.pdf),
OUT-03(.txt 대본), OUT-04(.html 대시보드), OUT-07(.md 인사이트).

응답:
[{"id":1,"title":"OUT-04+OUT-07","outputs":["OUT-04","OUT-07"],
  "rationale":"...","score":0.0~1.0}, ... up to 3]
"""

ALL_OUTPUTS = ["OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"]


class OutputTypeSelectorAgent(BaseGate):
    gate_code = "G5"
    model_name = "claude-sonnet-4-6"

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        # 사용자가 사전에 requested_outputs 를 지정했으면 첫 안으로 채택
        pre = list(state.requested_outputs or [])
        payload = {
            "user_intent": state.user_intent or state.user_question or "",
            "pre_selected": pre,
            "best_model_name": (state.best_model or {}).get("model_name"),
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=600,
                temperature=0.2,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr:
                # outputs 검증 — 5종 풀 안으로만
                for p in arr:
                    p["outputs"] = [o for o in (p.get("outputs") or []) if o in ALL_OUTPUTS]
                return arr[: self.n_proposals]
        except Exception as e:
            self.logger.warning("g5_llm_failed", error=str(e))

        # fallback — 사전 선택 우선 / 청중별 단순 추천
        defaults = [
            {
                "id": 1,
                "title": "발표 패키지",
                "outputs": ["OUT-01", "OUT-03", "OUT-04"],
                "rationale": "임원/실무 발표용 PPT+대본+대시보드",
                "score": 0.8,
            },
            {
                "id": 2,
                "title": "리포트 패키지",
                "outputs": ["OUT-02", "OUT-07"],
                "rationale": "상세 PDF + 인사이트 요약",
                "score": 0.7,
            },
            {
                "id": 3,
                "title": "최소 패키지",
                "outputs": ["OUT-04", "OUT-07"],
                "rationale": "온라인 공유용 대시보드+요약",
                "score": 0.6,
            },
        ]
        if pre:
            defaults.insert(
                0, {"id": 0, "title": "사용자 사전 선택", "outputs": pre, "rationale": "사용자 지정", "score": 1.0}
            )
        return defaults

    def _apply_choice(self, state: PipelineState, user_choice: Any, proposals: list[dict[str, Any]]) -> PipelineState:
        """G5 — 선택된 산출물 조합을 requested_outputs 에 반영 (report_composer 가 사용)."""
        uc = user_choice if isinstance(user_choice, dict) else {}
        outs = uc.get("outputs")
        if not outs:
            rank = uc.get("adopted_rank")
            chosen = None
            if rank is not None and proposals:
                chosen = next((p for p in proposals if p.get("id") == rank), None)
                if chosen is None and isinstance(rank, int) and 1 <= rank <= len(proposals):
                    chosen = proposals[rank - 1]
            if chosen is None and proposals:
                chosen = proposals[0]
            outs = (chosen or {}).get("outputs")
        outs = [o for o in (outs or []) if o in ALL_OUTPUTS]
        if not outs:
            outs = ["OUT-04", "OUT-07"]
        return state.with_update(requested_outputs=outs)

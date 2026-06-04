"""agents.gates.output_type_selector — G6 5종 산출물 전체 제시 (멀티선택)."""

from __future__ import annotations

from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

ALL_OUTPUTS = ["OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07"]

_FIXED_PROPOSALS: list[dict[str, Any]] = [
    {
        "id": 1,
        "title": "PPT 프레젠테이션",
        "outputs": ["OUT-01"],
        "rationale": "핵심 분석 결과를 슬라이드로 요약합니다. 발표·공유에 최적화.",
        "score": None,
    },
    {
        "id": 2,
        "title": "PDF 보고서",
        "outputs": ["OUT-02"],
        "rationale": "상세 분석 내용과 방법론을 완전한 문서로 정리합니다.",
        "score": None,
    },
    {
        "id": 3,
        "title": "발표 대본",
        "outputs": ["OUT-03"],
        "rationale": "발표 시 활용할 스크립트와 해설을 제공합니다.",
        "score": None,
    },
    {
        "id": 4,
        "title": "HTML 대시보드",
        "outputs": ["OUT-04"],
        "rationale": "인터랙티브 차트·필터 기반의 웹 페이지로 결과를 제공합니다.",
        "score": None,
    },
    {
        "id": 5,
        "title": "인사이트 요약",
        "outputs": ["OUT-07"],
        "rationale": "핵심 분석 시사점을 Markdown 문서로 간결하게 정리합니다.",
        "score": None,
    },
]


class OutputTypeSelectorAgent(BaseGate):
    gate_code = "G6"
    uses_llm = False
    n_proposals = 5

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        return list(_FIXED_PROPOSALS)

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        uc = user_choice if isinstance(user_choice, dict) else {}

        # 멀티선택: 프론트에서 직접 OUT 코드 목록을 전송
        outs = uc.get("outputs")
        if isinstance(outs, list) and outs:
            outs = [o for o in outs if o in ALL_OUTPUTS]
            if outs:
                self.logger.info("g5_multiselect", outputs=outs)
                return state.with_update(requested_outputs=outs)

        # 단일 순위 선택 fallback
        rank = uc.get("adopted_rank")
        if rank and rank != 0:
            chosen = next((p for p in proposals if p.get("id") == rank), None)
            if chosen and chosen.get("outputs"):
                return state.with_update(requested_outputs=chosen["outputs"])

        return state.with_update(requested_outputs=["OUT-04", "OUT-07"])

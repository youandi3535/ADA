"""agents.gates.analysis_proposer -- G1 analysis direction gate.

Proposal structure:
  Option 1, 2 : LLM recommendations
  Option 3    : fixed user-custom-input placeholder (is_custom=True)

Frontend sends choice as:
  Custom input  -> {adopted_rank: 0, custom_intent: "text"}
  Select 1 or 2 -> {adopted_rank: 1}  or  {adopted_rank: 2}
"""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import CATEGORIES, PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = (
    "You are a data strategy consultant. "
    "Given the user intent and data profile, propose exactly TWO distinct analysis directions. "
    "(Option 3 is reserved for the user's own custom input -- do NOT generate it.) "
    "Reply with a JSON array of 2 objects only:\n"
    '[{"id": 1, "title": "...", "rationale": "1-2 sentences in Korean", "score": 0.0-1.0}, '
    ' {"id": 2, "title": "...", "rationale": "1-2 sentences in Korean", "score": 0.0-1.0}]'
)

_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 분석 방향을 직접 입력하세요.",
    "score": None,
    "is_custom": True,
}

_FALLBACK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "tabular_ml": [
        {
            "id": 1,
            "title": "분류/회귀 예측",
            "rationale": "타겟 컬럼 기반 지도학습으로 결과를 예측합니다.",
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "피처 중요도 분석",
            "rationale": "예측에 영향을 미치는 주요 변수를 식별합니다.",
            "score": 0.6,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "TabTransformer 학습",
            "rationale": "딥러닝 표현력으로 복잡한 패턴을 학습합니다.",
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "FTTransformer 비교",
            "rationale": "수치형 임베딩 방식으로 성능을 비교합니다.",
            "score": 0.7,
        },
    ],
    "timeseries": [
        {"id": 1, "title": "단기 예측", "rationale": "1~30일 구간의 미래 값을 예측합니다.", "score": 0.8},
        {"id": 2, "title": "이상 시점 탐지", "rationale": "변동성이 비정상적으로 큰 시점을 식별합니다.", "score": 0.6},
    ],
    "anomaly_detection": [
        {"id": 1, "title": "이상치 점수화", "rationale": "샘플별 anomaly score를 산출합니다.", "score": 0.85},
        {"id": 2, "title": "정상 분포 학습", "rationale": "정상 패턴을 학습해 이탈 여부를 판단합니다.", "score": 0.7},
    ],
}


class AnalysisProposerAgent(BaseGate):
    """G1 -- LLM 2 proposals + fixed custom option 3."""

    gate_code = "G1"
    model_name = "claude-opus-4-6"
    n_proposals = 2  # LLM generates 2; option 3 is always _CUSTOM_OPTION

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        payload = {
            "user_intent": state.user_intent or state.user_question or "",
            "data_profile": state.data_profile,
            "category": state.category,
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False)[:4000],
                max_tokens=600,
                temperature=0.3,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr:
                llm_opts = arr[: self.n_proposals]
                for i, opt in enumerate(llm_opts, start=1):
                    opt["id"] = i
                return llm_opts + [_CUSTOM_OPTION]
        except Exception as e:
            self.logger.warning("g1_llm_failed", error=str(e))

        base = _FALLBACK_DEFAULTS.get(
            state.category,
            [{"id": 1, "title": "기본 분석", "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        return list(base) + [_CUSTOM_OPTION]

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        """Apply G1 user selection to state.

        Frontend sends:
          Custom input  -> {adopted_rank: 0, custom_intent: "text"}
          Select 1 or 2 -> {adopted_rank: 1}  or  {adopted_rank: 2}
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        # optional category / target override
        cat = uc.get("category")
        if isinstance(cat, str) and cat in CATEGORIES and cat != state.category:
            updates["category"] = cat

        tgt = uc.get("target_column") or uc.get("target")
        if isinstance(tgt, str) and tgt:
            updates["target_column"] = tgt

        # custom_intent 우선 확인 (adopted_rank=0 + custom_intent 조합)
        custom = uc.get("custom_intent")
        if isinstance(custom, str) and custom.strip():
            updates["user_intent"] = custom.strip()
            self.logger.info("g1_custom_intent_applied", intent=custom.strip()[:120])
        else:
            # adopted_rank 로 선택한 LLM 제안 반영
            rank = uc.get("adopted_rank")
            chosen = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank),
                None,
            )
            if chosen and isinstance(chosen.get("title"), str) and chosen["title"].strip():
                direction = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                updates["user_intent"] = (
                    f"{base} (분석 방향: {direction})".strip() if base else f"분석 방향: {direction}"
                )
                self.logger.info("g1_proposal_adopted", rank=rank, title=direction)

        return state.with_update(**updates) if updates else state

"""agents.gates.analysis_proposer — G1 분석 방향 3안 제시."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import CATEGORIES, PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = """당신은 분석 의도와 데이터 프로파일을 보고
서로 다른 세 갈래의 분석 방향을 제시하는 데이터 전략 컨설턴트입니다.

응답은 JSON 배열만. 각 요소:
{
  "id": 1,
  "title": "예측 모델",
  "rationale": "한국어 1~2문장",
  "score": 0.0~1.0
}
"""


class AnalysisProposerAgent(BaseGate):
    """G1 — 분석 방향 3안 (예: 예측 / 분류 / 군집)."""

    gate_code = "G1"
    model_name = "claude-opus-4-7"

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
                max_tokens=700,
                temperature=0.3,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr:
                return arr[: self.n_proposals]
        except Exception as e:
            self.logger.warning("g1_llm_failed", error=str(e))

        # fallback — 카테고리별 기본 3안
        defaults = {
            "tabular_ml": [
                {"id": 1, "title": "분류/회귀 예측", "rationale": "타겟 컬럼 기반 지도학습", "score": 0.8},
                {"id": 2, "title": "피처 중요도 분석", "rationale": "주요 변수 식별", "score": 0.6},
                {"id": 3, "title": "세그먼트 비교", "rationale": "타겟 분포에 따른 집단 분석", "score": 0.5},
            ],
            "tabular_dl": [
                {"id": 1, "title": "TabTransformer 학습", "rationale": "DL 표현력 활용", "score": 0.8},
                {"id": 2, "title": "FTTransformer 비교", "rationale": "수치형 임베딩 비교", "score": 0.7},
                {"id": 3, "title": "TabPFN zero-shot", "rationale": "소규모 데이터 즉답", "score": 0.6},
            ],
            "timeseries": [
                {"id": 1, "title": "단기 예측", "rationale": "1~30일 forecasting", "score": 0.8},
                {"id": 2, "title": "이상 시점 탐지", "rationale": "변동성 큰 구간 식별", "score": 0.6},
                {"id": 3, "title": "계절성 분해", "rationale": "추세/계절/잔차 분리", "score": 0.5},
            ],
            "anomaly_detection": [
                {"id": 1, "title": "이상치 점수화", "rationale": "샘플별 anomaly score", "score": 0.85},
                {"id": 2, "title": "정상 분포 학습", "rationale": "OneClassSVM/AE 등", "score": 0.7},
                {"id": 3, "title": "Top-N 알림", "rationale": "상위 N 이상치 리포트", "score": 0.6},
            ],
        }
        return defaults.get(state.category, [{"id": 1, "title": "기본 분석", "rationale": "fallback", "score": 0.5}])

    def _apply_choice(self, state: PipelineState, user_choice: Any, proposals: list[dict[str, Any]]) -> PipelineState:
        """G1 — 사용자 선택을 상태에 반영.

        - category/target override (기존)
        - 옵션3 직접 입력(custom_intent) → user_intent 로 사용 (사용자 방향 우선)
        - 추천 채택(adopted_rank) → 선택한 제안의 방향 제목을 user_intent 에 반영
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        cat = uc.get("category")
        if isinstance(cat, str) and cat in CATEGORIES and cat != state.category:
            updates["category"] = cat
        tgt = uc.get("target_column") or uc.get("target")
        if isinstance(tgt, str) and tgt:
            updates["target_column"] = tgt

        custom = uc.get("custom_intent")
        if isinstance(custom, str) and custom.strip():
            # 옵션3 — 사용자가 직접 입력한 분석 방향을 그대로 분석 의도로 채택
            updates["user_intent"] = custom.strip()
        else:
            # 추천 채택 — adopted_rank 로 선택한 제안의 방향을 분석 의도에 반영
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

        return state.with_update(**updates) if updates else state

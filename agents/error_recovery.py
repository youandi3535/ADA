"""agents.error_recovery — ErrorRecoveryAgent (Day13).

6단계 폴백 + 사용자 친절 안내.
"""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

SYSTEM_PROMPT = """당신은 회복 코디네이터로서, 다음 상태를 보고 사용자에게
- 무엇이 잘못됐는지 (1줄)
- 우리가 무엇을 했는지 (1줄)
- 사용자가 무엇을 하면 좋을지 (1~2줄)
JSON 으로 응답합니다.

{ "user_message": "...", "suggested_action": "retry|adjust_input|contact_admin|abort" }
"""


FALLBACKS = [
    "retry_same",  # 1) 동일 설정 재시도
    "downgrade_models",  # 2) 트랜스포머 제외 후 재시도
    "reduce_trials",  # 3) Optuna trial 축소
    "skip_finetune",  # 4) FineTune 건너뜀
    "smaller_sample",  # 5) 데이터 샘플링 축소
    "user_handoff",  # 6) 사용자 개입 요청
]


class ErrorRecoveryAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-opus-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            retry = state.retry_count + 1

            # 1) 폴백 단계 선택
            fb_idx = min(retry - 1, len(FALLBACKS) - 1)
            fallback = FALLBACKS[fb_idx]

            # 2) LLM 친절 안내 (선택)
            user_message = "오류가 발생했습니다. 자동 재시도를 진행합니다."
            try:
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(
                        {
                            "error": state.error,
                            "category": state.category,
                            "retry_count": retry,
                            "fallback": fallback,
                        },
                        ensure_ascii=False,
                    ),
                    max_tokens=300,
                    temperature=0.2,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                user_message = parsed.get("user_message", user_message)
            except Exception:
                pass

            # 3) 폴백 별 next_agent 결정
            if retry >= state.max_retries or fallback == "user_handoff":
                return state.with_update(
                    retry_count=retry,
                    insights=user_message,
                    next_agent="END",
                )

            next_agent = "supervisor"
            # downgrade_models: 모델 후보에서 트랜스포머 계열 제외
            updates: dict[str, Any] = {
                "retry_count": retry,
                "insights": user_message,
                "error": None,
                "next_agent": next_agent,
                # HJ 2026-06-13 — retry=supervisor 재시작(새 분석 사이클)이므로 게이트 자동통과
                #   카운터를 리셋한다. 안 하면 직전 re_loop/baseline_re_loop 잔여로 G2~G4 게이트가
                #   자동통과돼 사용자 선택이 스킵된다.
                "re_loop_count": 0,
                "baseline_re_loop_count": 0,
            }
            if fallback == "downgrade_models" and state.model_candidates:
                transformer = {
                    "TabTransformer",
                    "FTTransformer",
                    "TabPFN",
                    "Informer",
                    "TFT",
                    "PatchTST",
                    "TranAD",
                    "AnomalyTransformer",
                }
                updates["model_candidates"] = [m for m in state.model_candidates if m not in transformer]
            elif fallback == "smaller_sample":
                # supervisor 부터 다시 — 본문 sampling 은 training_executor 가 본다
                updates["max_re_loop"] = 0
            return state.with_update(**updates)

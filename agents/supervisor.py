"""agents.supervisor — SupervisorAgent (Day06 §A).

파이프라인 진입점. 입력 검증 + LLM 태스크 분류 + HITL 재시도 가드.
"""

from __future__ import annotations

import redis as redis_pkg

from ada.core.config import settings
from ada.core.state import PipelineState
from agents.base import BaseAgent

VALID_CATEGORIES = ("tabular_ml", "tabular_dl", "timeseries", "anomaly_detection")

SYSTEM_PROMPT = """당신은 데이터 분석 파이프라인 입력 검증 전문가입니다.
사용자가 제공한 데이터 카테고리, 타겟 컬럼, 자유 질문을 분석하여
task 유형(classification/regression/forecasting/anomaly_detection)을
JSON 만 응답하세요.

응답 형식 (반드시 이 키만 포함):
{
  "task": "classification",
  "reason": "타겟 컬럼이 이진 분류(0/1)",
  "confidence": 0.0~1.0
}
"""


class SupervisorAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # 1) 룰 검증
            ok, errs = self._validate_input(state)
            if not ok:
                return state.with_update(
                    error="; ".join(errs),
                    validation={"is_valid": False, "errors": errs, "warnings": []},
                    next_agent="error_recovery",
                )

            # 2) HITL — 자동 재시도 한도 초과 시 인간 개입
            if state.retry_count >= 2:
                try:
                    r = redis_pkg.Redis.from_url(settings.redis_url)
                    r.set(f"ada:hitl:{state.job_id}", "1", ex=86400)
                except Exception:
                    pass
                return state.with_update(
                    error="최대 자동 재시도 횟수 초과 — 인간 검토 필요",
                    next_agent="error_recovery",
                )

            # 3) LLM 태스크 분류 (선택, 시그널)
            task = state.task or "auto"
            try:
                user_prompt = (
                    f"category: {state.category}\n"
                    f"target_column: {state.target_column}\n"
                    f"user_question: {state.user_question or state.user_intent or ''}"
                )
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_tokens=300,
                    temperature=0.0,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                task = parsed.get("task", task)
            except Exception as e:
                self.logger.warning("supervisor_llm_failed", error=str(e))

            return state.with_update(
                task=task,
                next_agent="intent_elicitor",
            )

    @staticmethod
    def _validate_input(state: PipelineState) -> tuple[bool, list[str]]:
        errs: list[str] = []
        if state.category not in VALID_CATEGORIES:
            errs.append(f"유효하지 않은 카테고리: {state.category}")
        if state.category == "timeseries" and not state.target_column:
            errs.append("timeseries 카테고리는 target_column 필수")
        if not state.file_id:
            errs.append("file_id 누락")
        return len(errs) == 0, errs

"""agents.supervisor — SupervisorAgent (Day06 §A + Day 1 KB 폴백 + 메트릭).

파이프라인 진입점.
    1) 입력 검증
    2) retry >= 1 시 ErrorKB 조회 → 매칭 시 fast-fail (자동 패치 큐) 우회
    3) HITL — retry >= 2 시 인간 개입
    4) LLM 태스크 분류 (시그널)
"""

from __future__ import annotations

from typing import Any

from ada.core.config import settings
from ada.core.state import PipelineState
from ada.observability.metrics import record_kb_citation
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

            # 2) retry >= 1: ErrorKB 조회 → 매칭 있으면 빠른 폴백
            if state.retry_count >= 1 and state.error:
                kb_match = await self._lookup_error_kb(state.error)
                if kb_match is not None:
                    record_kb_citation(source="error_kb")
                    return state.with_update(
                        kb_citations=list(state.kb_citations) + [f"error_kb:{kb_match['hash']}"],
                        next_agent=kb_match.get("recommended_recovery", "error_recovery"),
                    )

            # 3) HITL — 자동 재시도 한도 초과 시 인간 개입
            if state.retry_count >= 2:
                try:
                    import redis.asyncio as aioredis  # noqa: WPS433

                    r = await aioredis.from_url(settings.redis_url)
                    await r.set(f"ada:hitl:{state.job_id}", "1", ex=86400)
                    await r.aclose()
                except Exception:
                    pass
                return state.with_update(
                    error="최대 자동 재시도 횟수 초과 — 인간 검토 필요",
                    next_agent="error_recovery",
                )

            # 4) LLM 태스크 분류 (선택, 시그널)
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

    # ------------------------------------------------------------------
    async def _lookup_error_kb(self, error_message: str) -> dict[str, Any] | None:
        """ErrorKB 에서 동일 fingerprint 조회. 매칭 없으면 None."""
        if self.session is None:
            return None
        try:
            from sqlalchemy import select

            from ada.db.models import ErrorKB
            from ada.error_handler.auto_handler import fingerprint

            fp = fingerprint(error_message)
            kb = await self.session.scalar(select(ErrorKB).where(ErrorKB.error_hash == fp["hash"]))
            if kb is None or (kb.confidence or 0.0) < 0.7:
                return None
            # ErrorKB 의 JSONB 컬럼은 `fingerprint` 이며 `payload` 컬럼은 존재하지 않는다.
            # recommended_recovery 가 저장돼 있지 않으면 기본값 "error_recovery" 사용.
            kb_meta = kb.fingerprint or {}
            return {
                "hash": fp["hash"],
                "kb_id": str(kb.id),
                "confidence": float(kb.confidence or 0.0),
                "recommended_recovery": kb_meta.get("recommended_recovery", "error_recovery"),
            }
        except Exception as e:
            self.logger.warning("error_kb_lookup_failed", error=str(e))
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def _validate_input(state: PipelineState) -> tuple[bool, list[str]]:
        errs: list[str] = []
        # pending/auto 는 data_profiler 가 자동 감지하는 플레이스홀더 → 여기서 거부 금지
        if state.category not in VALID_CATEGORIES and state.category not in ("pending", "auto"):
            errs.append(f"유효하지 않은 카테고리: {state.category}")
        if state.category == "timeseries" and not state.target_column:
            errs.append("timeseries 카테고리는 target_column 필수")
        if not state.file_id:
            errs.append("file_id 누락")
        return len(errs) == 0, errs

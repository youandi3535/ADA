"""agents.auto_error_handler — AutoErrorHandlerAgent.

ADR-006 Phase 1.4 — 그래프 노드 + 데몬 hook 양쪽 지원.

흐름 (그래프 노드로 호출 시):
    1. state.error 가 있으면 FailureLog INSERT (정확한 fingerprint 로)
    2. AutoErrorHandler 호출 (Tier 0~3 폴백)
    3. 결과 action 분류:
       - RESOLVED (auto_kb_match, patch_reused_approved)
         → state.error / error_traceback 클리어 → supervisor 재시도
       - PATCH_QUEUED (Tier 0/2/3 의 패치 큐 적재)
         → state.error 는 유지 (적용 안 됐으니 재시도해도 실패) → error_recovery 로
       - FAILED (noop, debounced, circuit_open)
         → state.error 유지 → error_recovery 로
"""

from __future__ import annotations

import uuid

from ada.core.state import PipelineState
from ada.db.models import FailureLog
from agents.base import BaseAgent

# action 분류 (auto_handler.py 의 반환값 기준)
# Day24: auto_self_learning_match 추가 — SelfLearningKB 시맨틱 매칭도 RESOLVED.
RESOLVED_ACTIONS = frozenset(
    {
        "auto_kb_match",  # Tier 1 ErrorKB 해시 매칭
        "auto_self_learning_match",  # Tier 1.5 SelfLearningKB 시맨틱 매칭
        "patch_reused_approved",  # Tier 1.6 승인된 패치 재사용
    }
)
PATCH_QUEUED_ACTIONS = frozenset({"patch_queued_static", "patch_queued_ollama", "patch_queued"})
# ADR-006 Phase 2-C/D/E: budget_exceeded / patch_rejected_scope 도 graceful degradation
FAILED_ACTIONS = frozenset(
    {
        "noop",
        "debounced",
        "circuit_open",
        "budget_exceeded",
        "patch_rejected_scope",
    }
)

# ADR-006 Phase 2-B: 분류기 단축경로 action
# - TRANSIENT  → supervisor 가 retry 처리 (error 유지)
# - CONFIG     → human-only, error_recovery 로 (error 유지)
# - DATA       → user_message, error_recovery 로 (error 유지)
# - USER_INPUT → 동일
TRANSIENT_ACTIONS = frozenset({"classified_transient"})
HUMAN_REQUIRED_ACTIONS = frozenset(
    {
        "classified_config",
        "classified_data",
        "classified_user_input",
    }
)


class AutoErrorHandlerAgent(BaseAgent):
    """그래프 노드 + 외부 hook 양용."""

    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # session 없거나 error 없으면 그대로 통과
            if self.session is None or not state.error:
                return state

            from ada.error_handler.auto_handler import AutoErrorHandler, fingerprint
            from ada.error_handler.redactor import redact

            try:
                # ADR-006 Phase 2-A: PII / secret 마스킹 (FailureLog 저장 전)
                # state.error 가 사용자 입력에서 유래한 PII 포함 가능 (예: 이메일 / 카드).
                clean_error, error_pii = redact(state.error or "")
                clean_traceback, tb_pii = redact(state.error_traceback or "")
                if error_pii or tb_pii:
                    self.logger.info(
                        "pii_redacted_in_agent",
                        error_types=error_pii,
                        traceback_types=tb_pii,
                    )

                # ADR-006 Phase 1.4 & 1.5: redacted text 로 fingerprint
                fp = fingerprint(clean_error, clean_traceback)

                # job_id 가 str 인 경우 UUID 로 변환
                job_id_val = state.job_id
                if isinstance(job_id_val, str):
                    try:
                        job_id_val = uuid.UUID(job_id_val)  # type: ignore[assignment]
                    except (ValueError, TypeError):
                        job_id_val = None  # type: ignore[assignment]

                fl = FailureLog(
                    job_id=job_id_val,  # type: ignore[arg-type]
                    error_hash=fp["hash"],
                    error_message=clean_error[:2000],
                    stack_trace=clean_traceback[:5000],
                    error_category="auto",
                )
                self.session.add(fl)
                await self.session.flush()

                outcome = await AutoErrorHandler(self.session).handle(fl)
                action = outcome.get("action", "")
                classification = outcome.get("classification")

                # 결과에 따라 state 갱신
                if action in RESOLVED_ACTIONS:
                    # 완전 해결: error 클리어 → graph 가 supervisor 로 라우팅
                    self.logger.info(
                        "auto_resolved",
                        action=action,
                        fingerprint=fp["hash"][:16],
                        kb_id=outcome.get("kb_id"),
                    )
                    return state.with_update(
                        error=None,
                        error_traceback=None,
                        error_fingerprint=fp["hash"],
                        error_classified_as=classification,
                        next_agent="supervisor",
                    )

                # ADR-006 Phase 2-B: 분류 단축경로
                if action in TRANSIENT_ACTIONS:
                    # 일시적 장애 → error 유지하되 supervisor 가 retry 결정.
                    # error_classified_as 마킹 → SupervisorAgent / ErrorRecoveryAgent
                    # 가 보고 retry/backoff 선택 가능.
                    self.logger.info(
                        "transient_classified",
                        fingerprint=fp["hash"][:16],
                    )
                    return state.with_update(
                        error_fingerprint=fp["hash"],
                        error_classified_as=classification,
                    )

                if action in HUMAN_REQUIRED_ACTIONS:
                    # CONFIG/DATA/USER_INPUT → LLM 못 고침. 즉시 사람 안내.
                    self.logger.info(
                        "human_required",
                        classification=classification,
                        fingerprint=fp["hash"][:16],
                    )
                    return state.with_update(
                        error_fingerprint=fp["hash"],
                        error_classified_as=classification,
                    )

                # 그 외 (PATCH_QUEUED / FAILED): error 유지 → error_recovery 로
                self.logger.info(
                    "auto_handler_outcome",
                    action=action,
                    fingerprint=fp["hash"][:16],
                )
                return state.with_update(
                    error_fingerprint=fp["hash"],
                    error_classified_as=classification,
                )

            except Exception as e:
                # AutoErrorHandler 자체가 실패해도 graph 가 죽으면 안 됨.
                # state.error 는 그대로 유지 → graph 가 error_recovery 로 보냄.
                self.logger.warning("auto_error_handler_internal_failure", error=str(e))
                return state

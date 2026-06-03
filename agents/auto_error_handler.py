"""agents.auto_error_handler — AutoErrorHandlerAgent.

ADR-006 Phase 1.4 — 그래프 노드 + 데몬 hook 양쪽 지원.

오류 진입 경로는 두 갈래다:

[경로 A] 그래프 내부 — 에이전트 25개 (이 파일)
    safe_node → state.with_update(error=...) → 조건부 엣지 →
    AutoErrorHandlerAgent.__call__() →
    1. state.error 가 있으면 FailureLog INSERT (정확한 fingerprint 로)
    2. AutoErrorHandler 호출 (Tier 0~3 폴백)
    3. 결과 action 분류:
       - RESOLVED (auto_kb_match, auto_self_learning_match, patch_reused_approved)
         → state.error / error_traceback 클리어 → supervisor 재시도
       - PATCH_QUEUED (Tier 0/2/3 의 패치 큐 적재)
         → state.error 는 유지 → error_recovery 로
       - FAILED (noop, debounced, circuit_open, budget_exceeded 등)
         → state.error 유지 → error_recovery 로

[경로 B] 그래프 외부 — runner / resume / API / state 초기화 실패
    capture_and_handle() (ada/error_handler/auto_handler.py) →
    state 없이 자체 DB 세션 생성 → FailureLog INSERT →
    AutoErrorHandler.handle() (동일 Tier 0~3 폴백)
    두 경로 모두 AutoErrorHandler.handle() 에서 합류한다.
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
        # ── 자동 적용 완료 (코드 수정까지 완료) ──────────────────────────────
        "auto_kb_applied",  # Tier 0/legacy  static fixer diff 자동 적용
        "auto_kb_match",  # 레거시 호환 alias
        "auto_self_learning_match",  # Tier 1  SelfLearningKB 시맨틱 매칭 + 패치 큐
        "patch_reused_approved",  # 재사용 패치 승인 (apply-worker)
        "auto_ollama_applied",  # Tier 2  Ollama diff 자동 적용
        "auto_claude_applied",  # Tier 3  Claude diff 자동 적용
    }
)
PATCH_QUEUED_ACTIONS = frozenset({"patch_queued_static"})
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
            if not state.error:
                return state

            # 그래프 노드로 호출 시 session=None → 자체 세션 생성
            # (build_graph 에서 AutoErrorHandlerAgent() 를 세션 없이 등록하기 때문)
            if self.session is None:
                from ada.db.session import AsyncSessionLocal

                async with AsyncSessionLocal() as _session:
                    return await self._handle(state, _session)
            return await self._handle(state, self.session)

    async def _handle(self, state: PipelineState, session) -> PipelineState:
        """실제 오류 처리 로직 — session 보장된 상태에서만 호출."""
        from ada.error_handler.auto_handler import AutoErrorHandler, fingerprint
        from ada.error_handler.redactor import redact

        try:
            clean_error, error_pii = redact(state.error or "")
            clean_traceback, tb_pii = redact(state.error_traceback or "")
            if error_pii or tb_pii:
                self.logger.info(
                    "pii_redacted_in_agent",
                    error_types=error_pii,
                    traceback_types=tb_pii,
                )

            fp = fingerprint(clean_error, clean_traceback)

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
            session.add(fl)
            await session.flush()

            outcome = await AutoErrorHandler(session).handle(fl)
            await session.commit()
            action = outcome.get("action", "")
            classification = outcome.get("classification")

            if action in RESOLVED_ACTIONS:
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

            if action in TRANSIENT_ACTIONS:
                self.logger.info("transient_classified", fingerprint=fp["hash"][:16])
                return state.with_update(
                    error_fingerprint=fp["hash"],
                    error_classified_as=classification,
                )

            if action in HUMAN_REQUIRED_ACTIONS:
                self.logger.info(
                    "human_required",
                    classification=classification,
                    fingerprint=fp["hash"][:16],
                )
                return state.with_update(
                    error_fingerprint=fp["hash"],
                    error_classified_as=classification,
                )

            self.logger.info("auto_handler_outcome", action=action, fingerprint=fp["hash"][:16])
            return state.with_update(
                error_fingerprint=fp["hash"],
                error_classified_as=classification,
            )

        except Exception as e:
            self.logger.warning("auto_error_handler_internal_failure", error=str(e))
            return state

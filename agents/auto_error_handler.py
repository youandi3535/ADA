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
RESOLVED_ACTIONS = frozenset({"auto_kb_match", "patch_reused_approved"})
PATCH_QUEUED_ACTIONS = frozenset({"patch_queued_static", "patch_queued_ollama", "patch_queued"})
FAILED_ACTIONS = frozenset({"noop", "debounced", "circuit_open"})


class AutoErrorHandlerAgent(BaseAgent):
    """그래프 노드 + 외부 hook 양용."""

    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # session 없거나 error 없으면 그대로 통과
            if self.session is None or not state.error:
                return state

            from ada.error_handler.auto_handler import AutoErrorHandler, fingerprint

            try:
                # ADR-006 Phase 1.4 & 1.5: 정상 fingerprint 사용 ('auto' 하드코딩 제거)
                fp = fingerprint(
                    state.error or "",
                    state.error_traceback or "",
                )

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
                    error_message=(state.error or "")[:2000],
                    stack_trace=(state.error_traceback or "")[:5000],
                    error_category="auto",
                )
                self.session.add(fl)
                await self.session.flush()

                outcome = await AutoErrorHandler(self.session).handle(fl)
                action = outcome.get("action", "")

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
                        next_agent="supervisor",
                    )

                # 그 외 (PATCH_QUEUED / FAILED): error 유지 → error_recovery 로
                self.logger.info(
                    "auto_handler_outcome",
                    action=action,
                    fingerprint=fp["hash"][:16],
                )
                return state.with_update(
                    error_fingerprint=fp["hash"],
                )

            except Exception as e:
                # AutoErrorHandler 자체가 실패해도 graph 가 죽으면 안 됨.
                # state.error 는 그대로 유지 → graph 가 error_recovery 로 보냄.
                self.logger.warning("auto_error_handler_internal_failure", error=str(e))
                return state

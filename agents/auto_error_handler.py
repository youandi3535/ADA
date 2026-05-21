"""agents.auto_error_handler — AutoErrorHandlerAgent (Day16).

데몬으로도, 그래프 외부 hook 으로도 호출 가능.
"""
from __future__ import annotations

from sqlalchemy import select

from ada.core.state import PipelineState
from ada.db.models import FailureLog
from agents.base import BaseAgent


class AutoErrorHandlerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            if self.session is None or not state.error:
                return state
            try:
                fl = FailureLog(
                    job_id=state.job_id,  # type: ignore[arg-type]
                    error_hash="auto",
                    error_message=(state.error or "")[:2000],
                    error_category="auto",
                )
                self.session.add(fl)
                await self.session.flush()

                from ada.error_handler.auto_handler import AutoErrorHandler
                await AutoErrorHandler(self.session).handle(fl)
            except Exception as e:
                self.logger.warning("auto_error_handler_failed", error=str(e))
            return state

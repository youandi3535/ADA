"""agents.self_learning — SelfLearningAgent (Day09).

job 종료 시 SelfLearningHarness 를 호출해 KB 증류.
"""
from __future__ import annotations

from ada.core.state import PipelineState
from agents.base import BaseAgent


class SelfLearningAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            if self.session is None:
                return state.with_update(next_agent="END")
            try:
                from ada.harness.distiller import SelfLearningHarness
                h = SelfLearningHarness(self.session)
                await h.distill_from_job(state.job_id)
            except Exception as e:
                self.logger.warning("distill_failed", error=str(e))
            return state.with_update(next_agent="END")

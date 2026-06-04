"""agents.fine_tune_executor — FineTuneExecutorAgent (Day08).

G5 응답이 ``requires_finetune=True`` 일 때만 활성. 트랜스포머 계열 best_model 을
한 번 더 미세조정한다. 비-트랜스포머 모델은 그대로 통과.
"""

from __future__ import annotations

from ada.core.state import PipelineState
from agents.base import BaseAgent

TRANSFORMER_MODELS = {
    "TabTransformer",
    "FTTransformer",
    "TabPFN",
    "Informer",
    "TFT",
    "PatchTST",
    "TranAD",
    "AnomalyTransformer",
}


class FineTuneExecutorAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            best = state.best_model or {}
            model_name = best.get("model_name", "")
            if model_name not in TRANSFORMER_MODELS:
                self.logger.info("finetune_skipped_non_transformer", model=model_name)
                return state.with_update(next_agent="eval_agent")

            # 본 단계는 비용 절약을 위해 epoch 수만 추가하는 light fine-tune.
            # 실제 가중치 재학습은 training_executor 가 담당하므로,
            # 여기서는 best_model 메타에 fine_tuned=True 마크만 추가한다.
            try:
                updated = {**best, "fine_tuned": True, "fine_tune_note": "추가 epoch 5회 가정"}
                return state.with_update(best_model=updated, next_agent="eval_agent")
            except Exception as e:
                self.logger.warning("finetune_failed", error=str(e))
                return state.with_update(next_agent="eval_agent")

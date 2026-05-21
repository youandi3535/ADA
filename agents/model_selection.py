"""agents.model_selection — Day 0 dispatcher 패턴.

LLM top3 선정 → 실패 시 ``handlers/{cat}/selector.score(state, recipes)`` fallback.
수정 권한: **HJ 단독** (dispatcher).
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ada.core.state import PipelineState
from ada.db.models import SelfLearningKB
from agents.base import BaseAgent
from agents.handlers import get_handler
import agents.handlers.timeseries  # noqa: F401
import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401

SYSTEM_PROMPT = """당신은 AutoML 큐레이터입니다. 입력으로 받은
data_profile, category, recipes 를 종합해 상위 3개 모델 후보를 JSON 으로 반환합니다.

후보 풀(권위):
  tabular_ml : ["RandomForest","XGBoost","LightGBM","CatBoost"]
  tabular_dl : ["TabTransformer","FTTransformer","TabPFN"]
  timeseries : ["ARIMA","SARIMA","Prophet","Informer","TFT","PatchTST"]
  anomaly_detection : ["IsolationForest","LOF","OneClassSVM","AutoEncoder","TranAD","AnomalyTransformer"]

응답:
{"top3":["..."], "rationale":"한국어", "citations":[]}
"""


class ModelSelectionAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            recipes = await self._fetch_recipes(state.category) if self.session else []

            top3: list[str] = []
            rationale = ""
            citations: list[str] = []
            try:
                payload = {
                    "category": state.category,
                    "data_profile": state.data_profile,
                    "recipes": recipes[:5],
                    "n_rows": (state.data_profile or {}).get("rows", 0),
                }
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(payload, ensure_ascii=False),
                    max_tokens=600,
                    temperature=0.1,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                top3 = parsed.get("top3") or []
                rationale = parsed.get("rationale", "")
                citations = parsed.get("citations") or []
            except Exception as e:
                self.logger.warning("model_selection_llm_fallback", error=str(e))

            if not top3:
                handler = get_handler(state.category, "score")
                if handler is not None:
                    try:
                        result = handler(state, recipes)
                        top3 = result.get("top3") or []
                        rationale = result.get("rationale", rationale)
                        citations = result.get("citations") or citations
                    except Exception as e:
                        self.logger.warning("selector_handler_failed",
                                            category=state.category, error=str(e))

            if not top3:
                top3 = ["XGBoost"]
                rationale = "최후 fallback"

            return state.with_update(
                model_candidates=top3,
                kb_citations=list(set(state.kb_citations + citations)),
                next_agent="hyperparameter_tuner",
            )

    async def _fetch_recipes(self, category: str) -> list[dict[str, Any]]:
        try:
            rows = await self.session.scalars(
                select(SelfLearningKB).where(
                    SelfLearningKB.kb_type == "recipe",
                    SelfLearningKB.category == category,
                ).order_by(SelfLearningKB.success_count.desc()).limit(5)
            )
            return [{"hash": r.hash, "payload": r.payload,
                     "success_count": r.success_count} for r in rows]
        except Exception:
            return []

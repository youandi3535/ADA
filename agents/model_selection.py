"""agents.model_selection — ModelSelectionAgent (Day07 §3).

Claude Sonnet 4.6 으로 데이터 프로파일 + 과거 성공 패턴(self_learning_kb 'recipe')
을 종합해 Top-3 모델 후보를 선정한다. 트랜스포머 우선 정책(R-403, v2.2 완화)
도 여기서 결정한다.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ada.core.state import PipelineState
from ada.db.models import SelfLearningKB
from agents.base import BaseAgent

SYSTEM_PROMPT = """당신은 AutoML 큐레이터입니다. 입력으로 받은
- data_profile (행/열/결측/카디널리티/클래스 분포)
- category (tabular_ml | tabular_dl | timeseries | anomaly_detection)
- recipes (과거 성공 레시피 hash + payload 요약)
를 종합해 **상위 3개 모델 후보**를 JSON 으로만 반환합니다.

후보 풀(권위):
  tabular_ml : ["RandomForest","XGBoost","LightGBM","CatBoost"]
  tabular_dl : ["TabTransformer","FTTransformer","TabPFN"]
  timeseries : ["ARIMA","SARIMA","Prophet","Informer","TFT","PatchTST"]
  anomaly_detection : ["IsolationForest","LOF","OneClassSVM","AutoEncoder","TranAD","AnomalyTransformer"]

규칙(R-403 v2.2 완화):
  - 데이터 ≥ 5,000 행 또는 GPU 가용 시 트랜스포머 후보 1개 이상 포함
  - 그 외에는 비-트랜스포머만 추천 가능

응답 형식:
{
  "top3": ["XGBoost","LightGBM","RandomForest"],
  "rationale": "한국어 한 문단",
  "uses_transformer": false,
  "citations": ["kb_hash_or_empty"]
}
"""


class ModelSelectionAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            recipes = await self._fetch_recipes(state.category) if self.session else []
            user_payload = {
                "category": state.category,
                "data_profile": state.data_profile,
                "recipes": recipes[:5],
                "n_rows": (state.data_profile or {}).get("rows", 0),
            }

            top3, rationale, citations = self._fallback_top3(state.category)
            try:
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(user_payload, ensure_ascii=False),
                    max_tokens=600,
                    temperature=0.1,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                top3 = parsed.get("top3", top3) or top3
                rationale = parsed.get("rationale", rationale)
                citations = parsed.get("citations", []) or []
            except Exception as e:
                self.logger.warning("model_selection_llm_fallback", error=str(e))

            return state.with_update(
                model_candidates=top3,
                kb_citations=list(set(state.kb_citations + citations)),
                # G3는 ModelStrategyProposerAgent 소유 — 여기서 덮지 않음
                next_agent="hyperparameter_tuner",
            )

    @staticmethod
    def _fallback_top3(category: str) -> tuple[list[str], str, list[str]]:
        defaults = {
            "tabular_ml":         ["XGBoost", "LightGBM", "RandomForest"],
            "tabular_dl":         ["FTTransformer", "TabTransformer", "TabPFN"],
            "timeseries":         ["Prophet", "SARIMA", "TFT"],
            "anomaly_detection":  ["IsolationForest", "LOF", "AutoEncoder"],
        }
        return defaults.get(category, ["XGBoost"]), "기본 권장 후보", []

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

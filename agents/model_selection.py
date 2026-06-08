"""agents.model_selection — Day 0 dispatcher 패턴.

LLM top3 선정 → 실패 시 ``handlers/{cat}/selector.score(state, recipes)`` fallback.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from ada.db.models import SelfLearningKB
from agents.base import BaseAgent
from agents.handlers import get_handler

_MODEL_FAMILY_MAP: dict[str, str] = {
    # tabular_ml
    "RandomForest": "Ensemble",
    "XGBoost": "GBM",
    "LightGBM": "GBM",
    "CatBoost": "GBM",
    # tabular_dl
    "TabTransformer": "DL",
    "FTTransformer": "DL",
    "TabPFN": "DL",
    # timeseries
    "ARIMA": "Statistical",
    "SARIMA": "Statistical",
    "Prophet": "Statistical",
    "Informer": "DL",
    "TFT": "DL",
    "PatchTST": "DL",
    # anomaly
    "IsolationForest": "Tree",
    "LOF": "Density",
    "OneClassSVM": "SVM",
    "AutoEncoder": "DL",
    "TranAD": "DL",
    "AnomalyTransformer": "DL",
}


def _infer_family(model_name: Any) -> str:
    """모델명 → family 매핑 (Phase 1.4 기여 보조)."""
    name = str(model_name or "")
    return _MODEL_FAMILY_MAP.get(name, "Other")


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
    use_anthropic_api = True

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            recipes = await self._fetch_recipes(state.category) if self.session else []

            top3: list[str] = []
            baselines: list[str] = []
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

            # Day 11 (jh 위임) — selector.score 결과의 baselines 키 추출.
            # LLM 경로는 baselines 를 모르므로, fallback 경로 또는 LLM 성공 시에도
            # 카테고리 핸들러 score() 를 호출해 baselines 만 별도 획득.
            handler = get_handler(state.category, "score")
            if not top3:
                if handler is not None:
                    try:
                        result = handler(state, recipes)
                        top3 = result.get("top3") or []
                        baselines = result.get("baselines") or []
                        rationale = result.get("rationale", rationale)
                        citations = result.get("citations") or citations
                    except Exception as e:
                        self.logger.warning("selector_handler_failed", category=state.category, error=str(e))
            else:
                # LLM 경로 성공 → top3 는 LLM 결과 유지하고 baselines 만 핸들러에서 보조 획득.
                if handler is not None and state.category in ("tabular_ml", "tabular_dl"):
                    try:
                        aux = handler(state, recipes) or {}
                        baselines = aux.get("baselines") or []
                    except Exception:
                        baselines = []

            if not top3:
                top3 = ["XGBoost"]
                rationale = "최후 fallback"

            # Day 11 — KB 인용 시 per-agent 카운터 증가 (KP9 측정 정확도)
            if citations:
                try:
                    from ada.observability.metrics import record_kb_citation

                    for _ in citations:
                        record_kb_citation(source="self_learning_kb")
                except Exception:
                    pass

            # Day 11 (jh 위임) — baselines + top3 합쳐 model_candidates 에 저장.
            # G4 UI 는 top3 만 노출하나 training_executor 는 5개 전부 학습 →
            # evaluator/insight 가 "Dummy 대비 +N 향상" 격차 보고 가능.
            # baseline 이름은 category_extras 메타로도 기록 (evaluator 조회용).
            combined_candidates = (baselines or []) + top3

            # 카테고리별 extras 키 결정 (tabular_ml/tabular_dl → "tabular")
            cat_key = "tabular" if state.category.startswith("tabular") else state.category
            new_extras = dict(state.category_extras or {})
            cat_extras = dict(new_extras.get(cat_key, {}))
            if baselines:
                cat_extras["baseline_model_names"] = list(baselines)
                cat_extras["g4_visible_top3"] = list(top3)  # G4 UI 가 보여줄 진짜 추천 모델
            new_extras[cat_key] = cat_extras

            new_state = state.with_update(
                model_candidates=combined_candidates,
                kb_citations=list(set(state.kb_citations + citations)),
                category_extras=new_extras,
                next_agent="hyperparameter_tuner",
            )

            # Phase 1.4 — ReportContext ⑥ model_selection 적립.
            try:
                candidates_payload = [
                    {"name": str(m), "family": _infer_family(m), "why_tried": rationale or "후보 풀에서 선정"}
                    for m in top3
                ]
                chosen_payload: dict[str, Any] = {}
                if top3:
                    chosen_payload = {
                        "name": str(top3[0]),
                        "family": _infer_family(top3[0]),
                        "justification": rationale or "최우선 후보",
                    }
                new_state = self.contribute_to_context(
                    new_state,
                    "model_selection",
                    {"candidates": candidates_payload, "chosen": chosen_payload},
                )
            except Exception as e:
                self.logger.warning("contribute_model_selection_failed", error=str(e))
            return new_state

    async def _fetch_recipes(self, category: str) -> list[dict[str, Any]]:
        try:
            rows = await self.session.scalars(
                select(SelfLearningKB)
                .where(
                    SelfLearningKB.kb_type == "recipe",
                    SelfLearningKB.category == category,
                )
                .order_by(SelfLearningKB.success_count.desc())
                .limit(5)
            )
            return [{"hash": r.hash, "payload": r.payload, "success_count": r.success_count} for r in rows]
        except Exception:
            return []

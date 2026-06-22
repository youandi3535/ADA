"""agents.model_selection — Day 0 dispatcher 패턴.

LLM top3 선정 → 실패 시 ``handlers/{cat}/selector.score(state, recipes)`` fallback.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import asyncio
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


# HJ 2026-06-11 — G4 모달 라이브 피드용. eda_agent.py 패턴 동일.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


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
    # HJ 2026-06-16 — KB recipes 를 LLM 모델추천에 반영. rag_reader → env ADA_RAG_ENRICH=on 일 때만 활성.
    uses_db_session = True
    rag_reader = True

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # HJ 2026-06-11 — G4 모달 라이브 피드: model_selection 진입 즉시 status publish.
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g4_phase": "model_selection_start",
                    "g4_status": f"카테고리 '{state.category}' 에 적합한 모델 후보 선정 중…",
                },
            )

            recipes = await self._fetch_recipes(state.category) if self.session else []
            handler = get_handler(state.category, "score")

            top3: list[str] = []
            baselines: list[str] = []
            rationale = ""
            citations: list[str] = []

            # HJ 2026-06-13 — LLM top3 선정과 핸들러 score(baselines)를 병렬 실행.
            #   기존: LLM await 후, 성공해도 baselines 위해 handler 를 또 호출(직렬 2회).
            #   두 호출은 서로 독립(LLM=추천 top3, handler=후보 풀 점수+baselines)이라
            #   동시에 돌려도 사용 로직·결과 동일 — 분석 품질 무손실.
            async def _llm_top3() -> Any:
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
                return self._parse_json(raw)

            async def _handler_score() -> Any:
                if handler is None:
                    return None
                return await asyncio.to_thread(handler, state, recipes)

            _llm_res, _handler_res = await asyncio.gather(_llm_top3(), _handler_score(), return_exceptions=True)

            if isinstance(_llm_res, dict):
                top3 = _llm_res.get("top3") or []
                rationale = _llm_res.get("rationale", "")
                citations = _llm_res.get("citations") or []
            elif isinstance(_llm_res, Exception):
                self.logger.warning("model_selection_llm_fallback", error=str(_llm_res))

            _handler_out = _handler_res if isinstance(_handler_res, dict) else None
            if isinstance(_handler_res, Exception):
                self.logger.warning("selector_handler_failed", category=state.category, error=str(_handler_res))

            # Day 11 (jh 위임) — selector.score 결과의 baselines 키 추출.
            if not top3:
                # LLM 실패 → 핸들러 결과를 메인 경로로 사용(top3 + baselines).
                if _handler_out is not None:
                    top3 = _handler_out.get("top3") or []
                    baselines = _handler_out.get("baselines") or []
                    rationale = _handler_out.get("rationale", rationale)
                    citations = _handler_out.get("citations") or citations
            else:
                # LLM 성공 → top3 는 LLM 결과 유지, baselines 만 핸들러에서 보조 획득.
                if _handler_out is not None and state.category in ("tabular_ml", "tabular_dl"):
                    baselines = _handler_out.get("baselines") or []

            if not top3:
                top3 = ["XGBoost"]
                rationale = "최후 fallback"

            # HJ 2026-06-22 — 사용자 지시: tabular_ml 후보 4종(RF/XGBoost/LightGBM/CatBoost)을 항상 전부
            #   후보·학습한다. 기존엔 큐레이터가 top3-of-4 로 1개를 누락해 "넣어둔 모델(예: XGBoost)이
            #   조용히 빠지는" 문제가 있었다. LLM 의 top3 는 '추천 순위'로 앞에 두고, 풀의 나머지를 뒤에
            #   합쳐 전 종을 추천순으로 정렬 → UI 표시·학습 모두 4종 보장. (tabular_dl 등 무거운 카테고리는
            #   기존 top-N 유지 — 여기 풀에 없으면 미적용.)
            _FULL_POOL = {"tabular_ml": ["RandomForest", "XGBoost", "LightGBM", "CatBoost"]}
            _pool = _FULL_POOL.get(state.category)
            if _pool:
                _pool_set = set(_pool)
                _ranked = [m for m in top3 if m in _pool_set]
                top3 = _ranked + [m for m in _pool if m not in _ranked]

            # HJ 2026-06-11 — G4 모달 라이브 피드: top3 모델 + LLM rationale 자연어 인사이트 publish.
            # G2 의 methodology_candidates 와 동일 패턴 — 사용자가 어떤 모델이 왜 선정됐는지 즉시 확인.
            try:
                _g4_model_insights: list[str] = []
                for i, m in enumerate(top3, start=1):
                    fam = _infer_family(str(m))
                    _g4_model_insights.append(f"모델 후보 {i}: {m} (계열: {fam})")
                if rationale:
                    _g4_model_insights.append(f"선정 근거: {str(rationale)[:200]}")
                if baselines:
                    _g4_model_insights.append(f"베이스라인: {', '.join(str(b) for b in baselines[:3])} (비교군)")
                # HJ 2026-06-13 — Claude 윤색은 백그라운드로(critical path 제거) → 튜닝 즉시 전진.
                self._spawn_insight_polish(
                    list(_g4_model_insights),
                    backend="ollama",
                    context="G4 모델 선택",
                    job_id=state.job_id,
                    key="g4_model_insights",
                )
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g4_phase": "model_selection_done",
                        "g4_status": f"모델 후보 {len(top3)}개 선정 완료 — 하이퍼파라미터 튜닝 단계로 이동",
                        "g4_model_insights": list(_g4_model_insights),
                        "g4_top3": [str(m) for m in top3[:5]],
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("g4_model_insights_publish_failed", error=str(e))

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
                    # R-504 — 철회된 레시피 재인용 금지. retract_low_confidence 는
                    # confidence<0.20 KB 의 payload 에 retracted=True 만 달고 confidence 는
                    # 그대로 두므로, confidence 하한(0.20)으로 철회분이 전부 걸러진다.
                    SelfLearningKB.confidence >= 0.20,
                )
                .order_by(SelfLearningKB.success_count.desc())
                .limit(5)
            )
            # payload.retracted=True (수동 철회 등 confidence 와 무관한 케이스) 방어적 제외.
            return [
                {"hash": r.hash, "payload": r.payload, "success_count": r.success_count}
                for r in rows
                if not (isinstance(r.payload, dict) and r.payload.get("retracted"))
            ]
        except Exception:
            return []

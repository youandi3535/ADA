"""agents.gates.model_strategy_proposer — G3 최종 모델 전략."""
from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = """당신은 모델링 아키텍트로서 카테고리·EDA 결과·G2 응답을 보고
'왜 이 모델 전략인가' 를 명확히 설명하는 2~3 개 전략을 JSON 으로 반환합니다.
각 요소: id, title, models(list of model_name), rationale, score."""


class ModelStrategyProposerAgent(BaseGate):
    """G3 — 모델 전략 (예: '경량 ML 3종 비교' vs '트랜스포머 1종 강화')."""

    gate_code = "G3"
    model_name = "claude-opus-4-7"

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        payload = {
            "category": state.category,
            "data_profile_rows": (state.data_profile or {}).get("rows"),
            "data_profile_cols": (state.data_profile or {}).get("cols"),
            "g2_choice": (state.gate_responses or {}).get("G2", {}).get("user_choice"),
            "eda_summary": state.eda_summary,
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False)[:4000],
                max_tokens=700,
                temperature=0.2,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)
            if arr:
                return arr[: self.n_proposals]
        except Exception as e:
            self.logger.warning("g3_llm_failed", error=str(e))

        defaults = {
            "tabular_ml": [
                {"id": 1, "title": "Gradient Boosting 3종",
                 "models": ["XGBoost", "LightGBM", "CatBoost"],
                 "rationale": "Tabular 표준 baseline", "score": 0.85},
                {"id": 2, "title": "Tree 다양화",
                 "models": ["RandomForest", "XGBoost", "LightGBM"],
                 "rationale": "안정성 + 빠른 학습", "score": 0.75},
            ],
            "tabular_dl": [
                {"id": 1, "title": "트랜스포머 3종",
                 "models": ["FTTransformer", "TabTransformer", "TabPFN"],
                 "rationale": "DL 표현력 비교", "score": 0.8},
            ],
            "timeseries": [
                {"id": 1, "title": "통계 + DL 혼합",
                 "models": ["SARIMA", "Prophet", "TFT"],
                 "rationale": "단기/장기 균형", "score": 0.85},
                {"id": 2, "title": "DL 중심",
                 "models": ["TFT", "PatchTST", "Informer"],
                 "rationale": "복잡 패턴 학습", "score": 0.7},
            ],
            "anomaly_detection": [
                {"id": 1, "title": "거리 기반 3종",
                 "models": ["IsolationForest", "LOF", "OneClassSVM"],
                 "rationale": "고전 이상탐지 강건성", "score": 0.85},
                {"id": 2, "title": "DL 강화",
                 "models": ["AutoEncoder", "TranAD", "AnomalyTransformer"],
                 "rationale": "복잡 시계열 이상", "score": 0.7},
            ],
        }
        return defaults.get(state.category, [{"id": 1, "title": "fallback",
                                                "models": ["XGBoost"],
                                                "rationale": "default", "score": 0.5}])

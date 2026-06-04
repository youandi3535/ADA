"""agents.gates.model_strategy_proposer — G3 최종 모델 전략."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = (
    "You are a modeling architect. "
    "Given the data profile, EDA summary, and the G2 methodology chosen by the user, "
    "propose exactly TWO distinct model strategy options. "
    "For each option write a concise Korean rationale of 1-2 sentences: "
    "why this strategy fits the data, and what result the user can expect. Keep it short and clear. "
    "Titles must be in Korean (concise). "
    "Reply with a JSON array of exactly 2 objects, no markdown:\n"
    '[{"id": 1, "title": "한국어 제목", "models": ["Model1", "Model2"], '
    '"rationale": "한국어 1-2문장", "score": 0.0-1.0}, '
    ' {"id": 2, "title": "한국어 제목", "models": ["Model1", "Model2"], '
    '"rationale": "한국어 1-2문장", "score": 0.0-1.0}]'
)

_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 모델 전략이나 사용할 알고리즘을 직접 입력하세요.",
    "models": [],
    "score": None,
    "is_custom": True,
}

_FALLBACK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "tabular_ml": [
        {
            "id": 1,
            "title": "Gradient Boosting 앙상블",
            "models": ["XGBoost", "LightGBM", "CatBoost"],
            "rationale": "정형 데이터에 강한 3종 부스팅 모델을 교차 검증으로 비교해 최고 정확도를 선정합니다.",
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "Tree 계열 다양화",
            "models": ["RandomForest", "XGBoost", "LightGBM"],
            "rationale": "배깅(RandomForest)과 부스팅을 함께 비교해 과적합 위험을 낮추고 안정적인 결과를 확보합니다.",
            "score": 0.75,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "Transformer 계열 비교",
            "models": ["FTTransformer", "TabTransformer", "TabPFN"],
            "rationale": "어텐션 기반 3종 모델로 피처 간 복잡한 상호작용을 학습하고 최적 아키텍처를 자동 선정합니다.",
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "MLP 경량 딥러닝",
            "models": ["ResNet", "MLP", "TabPFN"],
            "rationale": "Transformer 대비 빠른 학습 속도와 간단한 튜닝으로 안정적인 예측 성능을 제공합니다.",
            "score": 0.7,
        },
    ],
    "timeseries": [
        {
            "id": 1,
            "title": "통계 + 딥러닝 혼합",
            "models": ["SARIMA", "Prophet", "TFT"],
            "rationale": "해석 가능한 통계 모델과 딥러닝을 결합해 단기·중기 예측 모두에서 균형 잡힌 성능을 냅니다.",
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "딥러닝 장기 예측",
            "models": ["TFT", "PatchTST", "Informer"],
            "rationale": "Transformer 계열로 긴 시계열 의존성을 학습해 장기 예측에서 높은 정확도를 기대할 수 있습니다.",
            "score": 0.7,
        },
    ],
    "anomaly_detection": [
        {
            "id": 1,
            "title": "고전 이상탐지 앙상블",
            "models": ["IsolationForest", "LOF", "OneClassSVM"],
            "rationale": "3종 모델의 이상 점수를 앙상블해 오탐률을 낮추고 라벨 없이도 임계값을 자동 설정합니다.",
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "딥러닝 재구성 탐지",
            "models": ["AutoEncoder", "TranAD", "AnomalyTransformer"],
            "rationale": "정상 패턴을 학습한 AutoEncoder로 재구성 오차가 큰 샘플을 이상치로 판별합니다.",
            "score": 0.7,
        },
    ],
}


class ModelStrategyProposerAgent(BaseGate):
    """G3 — 모델 전략 (예: '경량 ML 3종 비교' vs '트랜스포머 1종 강화')."""

    gate_code = "G3"
    model_name = "claude-opus-4-6"
    n_proposals = 2

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
                llm_opts = arr[: self.n_proposals]
                for i, opt in enumerate(llm_opts, start=1):
                    opt["id"] = i
                return llm_opts + [_CUSTOM_OPTION]
        except Exception as e:
            self.logger.warning("g3_llm_failed", error=str(e))

        base = _FALLBACK_DEFAULTS.get(
            state.category,
            [{"id": 1, "title": "기본 전략", "models": ["XGBoost"], "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        return list(base) + [_CUSTOM_OPTION]

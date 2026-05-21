"""agents.preprocessing_strategist — PreprocessingStrategistAgent (Day10).

v2 — 이미지/NLP 전처리 제거. 정형/시계열 전처리 계획만 생성.
시간 누설 가드: 시계열은 미래값 누설 방지.
"""
from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

SYSTEM_PROMPT = """당신은 시니어 데이터 엔지니어로서 데이터 프로파일을 보고
전처리 단계를 JSON 으로 설계합니다. 카테고리별 규칙:

- tabular_ml/dl: 결측 처리(median/most_frequent), 카디널리티 50 이상은 target_encoding,
                 그 외는 one-hot. RobustScaler 권장.
- timeseries: 미래값 누설 금지. lag/rolling 만 허용. lag = [1,7,14], rolling=[7,14].
- anomaly_detection: 표준화 + Winsorizing 5%.

응답 형식 (반드시 JSON 만):
{
  "steps": [
    {"name": "impute_numeric", "strategy": "median", "needs_review": false},
    ...
  ],
  "rationale": "한국어 한 문단",
  "leakage_risks": []
}
"""


class PreprocessingStrategistAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            payload = {
                "category": state.category,
                "data_profile": state.data_profile,
                "target_column": state.target_column,
            }
            plan = self._fallback_plan(state.category)
            try:
                raw = await self._call_llm(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=json.dumps(payload, ensure_ascii=False)[:4000],
                    max_tokens=800,
                    temperature=0.1,
                    json_mode=True,
                )
                parsed = self._parse_json(raw)
                plan = parsed.get("steps") or plan
            except Exception as e:
                self.logger.warning("preprocess_llm_fallback", error=str(e))

            return state.with_update(preprocessing_plan=plan,
                                     next_agent="feature_engineer")

    @staticmethod
    def _fallback_plan(category: str) -> list[dict[str, Any]]:
        if category == "timeseries":
            return [
                {"name": "lag_features", "lags": [1, 7, 14], "needs_review": False},
                {"name": "rolling_mean", "windows": [7, 14], "needs_review": False},
            ]
        if category == "anomaly_detection":
            return [
                {"name": "standard_scale", "needs_review": False},
                {"name": "winsorize", "quantile": 0.05, "needs_review": False},
            ]
        return [
            {"name": "impute_numeric", "strategy": "median", "needs_review": False},
            {"name": "impute_categorical", "strategy": "most_frequent", "needs_review": False},
            {"name": "encode_categorical", "method": "one_hot",
             "high_card_threshold": 50, "needs_review": True},
            {"name": "scale_numeric", "method": "robust", "needs_review": False},
        ]

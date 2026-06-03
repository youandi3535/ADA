"""agents.gates.methodology_proposer — G2 방법론 제안 (정형ML/정형DL/시계열/이상탐지)."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = (
    "You are an AutoML strategy consultant. "
    "Given the data profile and the G1 analysis direction chosen by the user, "
    "propose exactly TWO distinct methodology options from: tabular_ml, tabular_dl, timeseries, anomaly_detection. "
    "Option 1 should be the best fit; Option 2 should offer a meaningfully different angle. "
    "For each option, write a detailed Korean rationale of 2-3 sentences that explains: "
    "(1) why this methodology suits the data characteristics, "
    "(2) which specific algorithms or model families would be used, "
    "(3) what concrete insight or result the user can expect. "
    "Titles must be in Korean (concise and descriptive). "
    "Reply with a JSON array of exactly 2 objects, no markdown:\n"
    '[{"id": 1, "title": "한국어 제목", "rationale": "한국어 2-3문장 상세 설명", "score": 0.0-1.0}, '
    ' {"id": 2, "title": "한국어 제목", "rationale": "한국어 2-3문장 상세 설명", "score": 0.0-1.0}]'
)

_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 방법론이나 분석 전략을 직접 입력하세요.",
    "score": None,
    "is_custom": True,
}

_FALLBACK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "tabular_ml": [
        {
            "id": 1,
            "title": "정형 ML 분류/회귀 앙상블",
            "rationale": (
                "타겟 컬럼의 분포와 피처 구성이 정형 ML에 적합하며, "
                "Logistic Regression, Random Forest, XGBoost 등 앙상블 모델을 활용해 높은 예측 정확도를 기대할 수 있습니다. "
                "교차 검증과 하이퍼파라미터 최적화를 통해 안정적이고 해석 가능한 예측 모델을 제공합니다."
            ),
            "score": 0.9,
        },
        {
            "id": 2,
            "title": "SHAP 기반 피처 중요도 분석",
            "rationale": (
                "SHAP 값과 피처 중요도 분석을 결합하여 예측에 영향을 미치는 핵심 변수를 식별합니다. "
                "단순 예측을 넘어 어떤 요인이 결과를 결정하는지 해석 가능한 인사이트를 제공하며, "
                "비즈니스 의사결정에 직접 활용할 수 있는 변수 중요도 리포트를 생성합니다."
            ),
            "score": 0.6,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "TabTransformer 딥러닝 학습",
            "rationale": (
                "범주형 피처가 많은 정형 데이터에 TabTransformer를 적용하여 "
                "어텐션 메커니즘으로 피처 간 복잡한 상호작용을 학습합니다. "
                "기존 트리 기반 모델보다 비선형 패턴을 더 정확하게 포착하며, 대규모 데이터에서 강점을 발휘합니다."
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "FTTransformer 수치 임베딩 비교",
            "rationale": (
                "수치형 피처를 임베딩으로 변환하는 FTTransformer를 사용하여 TabTransformer와 성능을 비교합니다. "
                "두 모델의 교차 검증 결과를 기반으로 최적 아키텍처를 자동 선정하며, "
                "각 모델의 예측 신뢰도와 피처 기여도를 함께 제공합니다."
            ),
            "score": 0.7,
        },
    ],
    "timeseries": [
        {
            "id": 1,
            "title": "단기 시계열 예측 (LSTM/Prophet)",
            "rationale": (
                "시계열 데이터의 추세와 계절성 패턴을 분석하여 Prophet 또는 LSTM 기반 단기 예측 모델을 구축합니다. "
                "1~30일 구간의 미래 값 예측과 신뢰 구간을 함께 제공하며, "
                "계절성·휴일 효과 등 외부 요인을 자동으로 반영합니다."
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "이상 시점 탐지 (변동성 분석)",
            "rationale": (
                "시계열 내 변동성이 비정상적으로 큰 구간을 Isolation Forest와 통계적 기법으로 탐지합니다. "
                "정상 패턴을 학습한 후 이탈 시점과 이상치 구간을 자동으로 표시하며, "
                "원인 피처와 이상 발생 패턴에 대한 해석 리포트를 제공합니다."
            ),
            "score": 0.6,
        },
    ],
    "anomaly_detection": [
        {
            "id": 1,
            "title": "Isolation Forest 이상치 점수화",
            "rationale": (
                "Isolation Forest와 AutoEncoder를 결합하여 샘플별 이상 점수를 산출합니다. "
                "정상/이상 임계값을 자동 설정하고 이상 비율과 핵심 이상 피처를 시각화하며, "
                "실시간 모니터링에 바로 적용 가능한 경량 모델을 제공합니다."
            ),
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "정상 분포 학습 기반 탐지",
            "rationale": (
                "정상 데이터 분포를 학습한 후 분포에서 크게 벗어난 샘플을 이상치로 판별합니다. "
                "One-Class SVM과 GMM을 비교하여 데이터 특성에 맞는 최적 탐지 모델을 자동 선정하며, "
                "각 이상치의 원인 피처와 이상 강도를 함께 리포트합니다."
            ),
            "score": 0.7,
        },
    ],
}


class MethodologyProposerAgent(BaseGate):
    """G2 — 방법론(카테고리) 권장. 본 게이트가 카테고리 변경을 제안할 수 있다."""

    gate_code = "G2"
    model_name = "claude-sonnet-4-6"
    n_proposals = 2  # LLM generates 2; option 3 is always _CUSTOM_OPTION

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        payload = {
            "category": state.category,
            "data_profile": state.data_profile,
            "g1_choice": (state.gate_responses or {}).get("G1", {}).get("user_choice"),
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
            self.logger.warning("g2_llm_failed", error=str(e))

        base = _FALLBACK_DEFAULTS.get(
            state.category,
            [{"id": 1, "title": "기본 분석", "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        return list(base) + [_CUSTOM_OPTION]

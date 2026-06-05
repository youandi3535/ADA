"""agents.gates.model_strategy_proposer — G4 최종 모델 전략."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = (
    "You are a modeling architect. "
    "Given the data profile, EDA summary, and the G3 methodology chosen by the user, "
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
    # HJ-3 (2026-06-05) + DL 제거 — 시계열 ML 전용 (6 SUPPORTED_MODELS 와 정합)
    # 통계 + 베이스라인 + 외생변수 3 옵션. DL (Informer/TFT/PatchTST) 비활성.
    "timeseries": [
        {
            "id": 1,
            "title": "통계 + 베이스라인 (해석성 우선)",
            "models": ["SARIMA", "ETS", "seasonal_naive"],
            "rationale": "해석 가능한 통계 + 기준선 비교로 빠르고 안정적인 예측. 작은~중간 데이터에 최적.",
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "외생변수 회귀 + 검증",
            "models": ["SARIMAX", "ETS", "seasonal_naive"],
            "rationale": (
                "외생변수(공휴일·프로모션 등)를 SARIMAX 회귀에 반영하고 ETS 계절성 모델과 "
                "seasonal_naive 베이스라인을 함께 비교해 모델 우위를 객관적으로 검증합니다."
            ),
            "score": 0.80,
        },
        {
            "id": 3,
            "title": "고전 통계 단일 (안정성 우선)",
            "models": ["ARIMA", "SARIMA", "ETS"],
            "rationale": (
                "해석 가능성과 빠른 학습이 중요한 환경에서 차분/계절 차분/지수평활 3종을 "
                "비교해 가장 안정적인 통계 모델을 선택합니다."
            ),
            "score": 0.75,
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
    """G4 — 모델 전략 (예: '경량 ML 3종 비교' vs '트랜스포머 1종 강화')."""

    gate_code = "G4"
    model_name = "claude-opus-4-6"
    n_proposals = 2

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        payload = {
            "category": state.category,
            "data_profile_rows": (state.data_profile or {}).get("rows"),
            "data_profile_cols": (state.data_profile or {}).get("cols"),
            "g2_choice": (state.gate_responses or {}).get("G3", {}).get("user_choice"),
            "eda_summary": state.eda_summary,
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False, default=str)[:4000],
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
            self.logger.warning("g4_llm_failed", error=str(e))

        base = _FALLBACK_DEFAULTS.get(
            state.category,
            [{"id": 1, "title": "기본 전략", "models": ["XGBoost"], "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        return list(base) + [_CUSTOM_OPTION]

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        """G4 사용자 선택을 state 에 반영.

        프론트 형식:
            - 직접 입력  → {adopted_rank: 0, custom_intent: "text"}
            - 옵션 1/2   → {adopted_rank: 1} or {adopted_rank: 2}

        반영 필드:
            - user_intent           : 선택한 전략 제목 누적
            - model_candidates      : proposal.models 가 있으면 다운스트림 후보로 미리 채움
                                      (model_selection 이 LLM 으로 top3 재선정할 수 있으나
                                       LLM 실패 시 본 값이 fallback 으로 그대로 쓰임)
            - category_extras["g4_strategy"]: 감사·디버깅용 선택 메타데이터
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        custom = uc.get("custom_intent")
        chosen: dict[str, Any] | None = None
        if isinstance(custom, str) and custom.strip():
            chosen = {"title": custom.strip(), "models": [], "is_custom": True}
            updates["user_intent"] = f"{(state.user_intent or '').strip()} (모델 전략: {custom.strip()})".strip()
            self.logger.info("g4_custom_intent_applied", intent=custom.strip()[:120])
        else:
            rank = uc.get("adopted_rank")
            chosen = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank),
                None,
            )
            if chosen and isinstance(chosen.get("title"), str):
                strategy = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                updates["user_intent"] = f"{base} (모델 전략: {strategy})" if base else f"모델 전략: {strategy}"
                self.logger.info(
                    "g4_proposal_adopted",
                    rank=rank,
                    title=strategy,
                    models=chosen.get("models"),
                )

        if chosen:
            models = chosen.get("models") or []
            if isinstance(models, list) and models:
                # 다운스트림 model_selection 이 LLM 으로 다시 정할 수 있지만,
                # 본 값이 미리 채워져 있으면 LLM 실패 시 안전한 fallback 이 된다.
                updates["model_candidates"] = [str(m) for m in models if isinstance(m, str)]
            # category_extras 에 감사용 메타데이터 기록 (R-005 with_update 패턴 유지)
            cat = state.category or "_default"
            extras = dict(state.category_extras or {})
            cat_block = dict(extras.get(cat) or {})
            cat_block["g4_strategy"] = {
                "title": chosen.get("title"),
                "models": chosen.get("models") or [],
                "rationale": chosen.get("rationale", ""),
                "is_custom": bool(chosen.get("is_custom")),
            }
            extras[cat] = cat_block
            updates["category_extras"] = extras

        return state.with_update(**updates) if updates else state

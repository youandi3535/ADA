"""agents.gates.model_strategy_proposer — G4 최종 모델 전략."""

from __future__ import annotations

import json
from typing import Any

from ada.core.lang_guard import looks_non_korean, with_korean_guard
from ada.core.state import PipelineState
from agents.gates._base_gate import BaseGate

SYSTEM_PROMPT = with_korean_guard(
    "당신은 모델링 아키텍트입니다. "
    "데이터 프로파일·EDA 요약·G3 방법론을 보고 서로 다른 모델 전략 2개를 한국어로 제안합니다.\n\n"
    "각 옵션의 rationale 은 한국어 1-2문장: "
    "이 전략이 데이터에 적합한 이유 + 사용자가 기대할 결과.\n"
    "title 은 간결한 한국어. 한자(汉字)·중국어 절대 금지. 모델명(XGBoost 등)만 영문 허용.\n\n"
    "정확히 2개 객체의 JSON 배열만 반환 (마크다운 금지):\n"
    '[{"id": 1, "title": "한국어 제목", "models": ["Model1", "Model2"], '
    '"rationale": "한국어 1-2문장", "score": 0.0-1.0}, '
    ' {"id": 2, "title": "한국어 제목", "models": ["Model1", "Model2"], '
    '"rationale": "한국어 1-2문장", "score": 0.0-1.0}]'
)

KOREAN_RETRY_HINT = (
    "이전 응답에 한자(中文)가 포함되어 거부됩니다. 반드시 한국어로만 다시 작성하세요. 한자·중국어 문장 금지."
)


def _has_non_korean_options(options: list[dict[str, Any]]) -> bool:
    for opt in options:
        if not isinstance(opt, dict):
            continue
        for key in ("title", "rationale"):
            v = opt.get(key)
            if isinstance(v, str) and looks_non_korean(v):
                return True
    return False


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
        user_payload = json.dumps(payload, ensure_ascii=False)[:4000]
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_payload,
                max_tokens=700,
                temperature=0.2,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)

            if arr and _has_non_korean_options(arr):
                self.logger.warning("g4_cjk_detected_retry")
                retry_user = KOREAN_RETRY_HINT + "\n\n다시 작성할 데이터:\n" + user_payload
                try:
                    raw2 = await self._call_llm(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=retry_user,
                        max_tokens=700,
                        temperature=0.2,
                        json_mode=True,
                    )
                    arr2 = self._safe_parse_json_array(raw2)
                    if arr2 and not _has_non_korean_options(arr2):
                        arr = arr2
                    else:
                        self.logger.warning("g4_cjk_persist_after_retry")
                        arr = []
                except Exception as e:
                    self.logger.warning("g4_retry_failed", error=str(e))
                    arr = []

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
            if chosen and isinstance(chosen.get("title"), str) and chosen["title"].strip():
                strategy = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                updates["user_intent"] = f"{base} (모델 전략: {strategy})" if base else f"모델 전략: {strategy}"
                self.logger.info(
                    "g4_proposal_adopted",
                    rank=rank,
                    title=strategy,
                )

        if isinstance(chosen, dict):
            models = chosen.get("models")
            if isinstance(models, list) and models:
                updates["model_candidates"] = [str(m) for m in models if m]
            extras = dict(state.category_extras or {})
            cat_bucket = dict(extras.get(state.category) or {})
            cat_bucket["g4_strategy"] = {
                "title": chosen.get("title"),
                "models": chosen.get("models") or [],
                "is_custom": bool(chosen.get("is_custom")),
            }
            extras[state.category] = cat_bucket
            extras[state.category] = cat_bucket
            updates["category_extras"] = extras

        return state.with_update(**updates) if updates else state

"""agents.gates.methodology_proposer — G3 방법론 제안 (정형ML/정형DL/시계열/이상탐지)."""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import CATEGORIES, PipelineState
from agents.gates._base_gate import BaseGate

_UNSUPERVISED_CATEGORIES: frozenset[str] = frozenset({"anomaly_detection"})

# 방법론 제목/근거 텍스트에서 카테고리를 키워드로 추론하기 위한 사전.
# 우선순위 높음 → 낮음 순서 (anomaly_detection 먼저 검사하지 않으면 timeseries 가 흡수).
_CATEGORY_KEYWORDS_KO: list[tuple[str, list[str]]] = [
    ("anomaly_detection", ["이상탐지", "anomaly", "outlier", "이상치", "이상", "OneClass", "Isolation"]),
    ("timeseries", ["시계열", "예측", "forecast", "time series", "temporal", "SARIMA", "Prophet", "LSTM"]),
    ("tabular_dl", ["딥러닝", "deep learning", "transformer", "FTTransformer", "TabTransformer"]),
    ("tabular_ml", ["정형 ML", "XGBoost", "LightGBM", "RandomForest", "tree", "boosting"]),
]


def _infer_category_from_text(text: str, fallback: str) -> str:
    """proposal title/rationale 키워드로 category 를 추론."""
    t = (text or "").lower()
    for cat, kws in _CATEGORY_KEYWORDS_KO:
        if any(k.lower() in t for k in kws):
            return cat
    return fallback


SYSTEM_PROMPT = (
    "You are an AutoML strategy consultant. "
    "Given the data profile and the G2 analysis direction chosen by the user, "
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
    """G3 — 방법론(카테고리) 권장. 본 게이트가 카테고리 변경을 제안할 수 있다."""

    gate_code = "G3"
    model_name = "claude-sonnet-4-6"
    n_proposals = 2  # LLM generates 2; option 3 is always _CUSTOM_OPTION

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        # G2 선택 제목을 추출 — adopted_rank 숫자 대신 실제 방향 텍스트를 LLM 에 전달
        g1_resp = (state.gate_responses or {}).get("G2", {})
        g1_uc = g1_resp.get("user_choice") or {}
        g1_rank = g1_uc.get("adopted_rank") if isinstance(g1_uc, dict) else None
        g1_props = g1_resp.get("proposals") or []
        g1_chosen = next(
            (p for p in g1_props if isinstance(p, dict) and p.get("id") == g1_rank),
            None,
        )
        payload = {
            "category": state.category,
            "data_profile": state.data_profile,
            "g1_direction": g1_chosen.get("title") if g1_chosen else (state.user_intent or ""),
            "user_intent": state.user_intent,
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
            [{"id": 1, "title": "기본 분석", "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        return list(base) + [_CUSTOM_OPTION]

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        """G3 사용자 선택을 state 에 반영.

        프론트 형식:
            - 직접 입력  → {adopted_rank: 0, custom_intent: "text"}
            - 옵션 1/2   → {adopted_rank: 1} or {adopted_rank: 2}

        반영 필드:
            - user_intent  : 사용자가 본 방법론 선택을 user_intent 에 누적 표기
                            (다음 게이트 LLM 프롬프트가 컨텍스트로 활용)
            - category     : proposal 또는 custom_intent 텍스트에서 키워드 추론
            - target_column: 비지도(anomaly_detection) 로 바뀌면 None
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        # 1) 명시적 category 키 (LLM proposal 이 채워줬을 수도) — 최우선
        explicit_cat = uc.get("category")
        if isinstance(explicit_cat, str) and explicit_cat in CATEGORIES and explicit_cat != state.category:
            updates["category"] = explicit_cat

        # 2) custom_intent — 사용자가 직접 입력
        custom = uc.get("custom_intent")
        if isinstance(custom, str) and custom.strip():
            updates["user_intent"] = f"{(state.user_intent or '').strip()} (방법론: {custom.strip()})".strip()
            if "category" not in updates:
                inferred = _infer_category_from_text(custom, state.category)
                if inferred != state.category:
                    updates["category"] = inferred
            self.logger.info("g3_custom_intent_applied", intent=custom.strip()[:120])
        else:
            # 3) adopted_rank — proposals 에서 선택한 항목
            rank = uc.get("adopted_rank")
            chosen = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank),
                None,
            )
            if chosen and isinstance(chosen.get("title"), str) and chosen["title"].strip():
                method = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                updates["user_intent"] = f"{base} (방법론: {method})" if base else f"방법론: {method}"
                # proposal 에 category 가 들어 있으면 우선 사용
                if "category" not in updates:
                    new_cat = chosen.get("category")
                    if isinstance(new_cat, str) and new_cat in CATEGORIES and new_cat != state.category:
                        updates["category"] = new_cat
                # 그래도 없으면 title/rationale 텍스트로 추론
                if "category" not in updates:
                    blob = method + " " + (chosen.get("rationale") or "")
                    inferred = _infer_category_from_text(blob, state.category)
                    if inferred != state.category:
                        updates["category"] = inferred
                self.logger.info(
                    "g3_proposal_adopted",
                    rank=rank,
                    title=method,
                    category=updates.get("category"),
                )

        # 4) 비지도로 카테고리 바뀐 경우 target_column 무효화
        if updates.get("category") in _UNSUPERVISED_CATEGORIES and state.target_column:
            updates["target_column"] = None

        # 5) HJ-7 (2026-06-05) — chosen_recipe 정식 필드 채움
        # CS evaluator/insight/selector 가 state.chosen_recipe.meta.* 우선 활용.
        # G3 에서 채택한 방법론 정보를 recipe dict 로 직렬화. meta 4 키는 G4(model_strategy)
        # 또는 카테고리별 proposer.g1 에서 보강할 수 있도록 기본 None 채움.
        recipe: dict[str, Any] = {}
        if isinstance(custom, str) and custom.strip():
            recipe = {
                "id": 0,
                "title": custom.strip(),
                "methodology": custom.strip(),
                "is_custom": True,
                "meta": {
                    "variate": None,
                    "forecast_kind": None,
                    "task_kind": None,
                    "horizon_hint": None,
                },
            }
        else:
            rank2 = (user_choice or {}).get("adopted_rank") if isinstance(user_choice, dict) else None
            chosen2 = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank2),
                None,
            )
            if chosen2:
                recipe = {
                    "id": chosen2.get("id"),
                    "title": chosen2.get("title"),
                    "methodology": chosen2.get("title"),
                    "rationale": chosen2.get("rationale", ""),
                    "is_custom": False,
                    "meta": chosen2.get("meta")
                    if isinstance(chosen2.get("meta"), dict)
                    else {
                        "variate": None,
                        "forecast_kind": None,
                        "task_kind": None,
                        "horizon_hint": None,
                    },
                }
        if recipe:
            updates["chosen_recipe"] = recipe
            self.logger.info("g3_chosen_recipe_set", recipe_title=recipe.get("title"))

        return state.with_update(**updates) if updates else state

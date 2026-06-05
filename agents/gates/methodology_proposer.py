"""agents.gates.methodology_proposer — G3 방법론 제안 (정형ML/정형DL/시계열/이상탐지)."""

from __future__ import annotations

import json
from typing import Any

from ada.core.lang_guard import looks_non_korean, with_korean_guard
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


def _has_non_korean_options(options: list[dict[str, Any]]) -> bool:
    """옵션 중 title/rationale 에 한자가 포함된 항목이 있으면 True."""
    for opt in options:
        if not isinstance(opt, dict):
            continue
        for key in ("title", "rationale"):
            v = opt.get(key)
            if isinstance(v, str) and looks_non_korean(v):
                return True
    return False


SYSTEM_PROMPT = with_korean_guard(
    "당신은 AutoML 전략 컨설턴트입니다. "
    "데이터 프로파일과 G2 에서 사용자가 선택한 분석 방향을 보고, "
    "tabular_ml · tabular_dl · timeseries · anomaly_detection 중 서로 다른 방법론 2개를 한국어로 제안합니다.\n\n"
    "Option 1: 가장 적합. Option 2: 의미 있게 다른 각도의 차선책.\n\n"
    "각 옵션의 rationale 은 한국어 2-3문장으로 다음을 모두 설명:\n"
    "  (1) 이 방법론이 데이터 특성에 적합한 이유\n"
    "  (2) 사용할 구체적 알고리즘·모델 패밀리\n"
    "  (3) 사용자가 기대할 수 있는 결과·인사이트\n\n"
    "title 은 간결한 한국어. 한자(汉字)·중국어 절대 금지. 영문 알고리즘명만 허용 (XGBoost 등).\n\n"
    "정확히 2개 객체의 JSON 배열만 반환 (마크다운 금지):\n"
    '[{"id": 1, "title": "한국어 제목", "rationale": "한국어 2-3문장", "score": 0.0-1.0}, '
    ' {"id": 2, "title": "한국어 제목", "rationale": "한국어 2-3문장", "score": 0.0-1.0}]'
)

KOREAN_RETRY_HINT = (
    "이전 응답에 한자(中文)가 포함되어 거부됩니다. 반드시 한국어로만 다시 작성하세요. 한자(漢字·汉字)·중국어 문장 금지."
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
                self.logger.warning("g3_cjk_detected_retry")
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
                        self.logger.warning("g3_cjk_persist_after_retry")
                        arr = []
                except Exception as e:
                    self.logger.warning("g3_retry_failed", error=str(e))
                    arr = []

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
                # 키워드 폴백
                if "category" not in updates:
                    inferred = _infer_category_from_text(method, state.category)
                    if inferred != state.category:
                        updates["category"] = inferred
                # 비지도 카테고리면 target_column 무효화
                if updates.get("category", state.category) in _UNSUPERVISED_CATEGORIES:
                    updates["target_column"] = None
                self.logger.info(
                    "g3_proposal_adopted",
                    rank=rank,
                    title=method,
                    category=updates.get("category"),
                )

        return state.with_update(**updates) if updates else state

"""agents.gates.analysis_proposer -- G2 analysis direction gate.

Proposal structure:
  Option 1, 2 : LLM recommendations
  Option 3    : fixed user-custom-input placeholder (is_custom=True)

Frontend sends choice as:
  Custom input  -> {adopted_rank: 0, custom_intent: "text"}
  Select 1 or 2 -> {adopted_rank: 1}  or  {adopted_rank: 2}
"""

from __future__ import annotations

import json
from typing import Any

from ada.core.lang_guard import looks_non_korean
from ada.core.state import CATEGORIES, PipelineState
from agents.gates._base_gate import BaseGate

# HJ 2026-06-09 G1 단축 U — system_prompt 압축 (1500t → ~500t).
# 핵심 규칙·enum·rationale 형식 모두 유지. 반복 강조·영어 중복 제거.
# rationale 은 사용자 요구대로 6줄 형식 (스크린샷 기준).
SYSTEM_PROMPT = (
    "당신은 데이터 전략 컨설턴트. 사용자 의도+프로파일 보고 서로 다른 분석 방향 2개를 JSON 으로 제안.\n\n"
    "[규칙]\n"
    "- Option 1=가장 확신 높은 방향, Option 2=의미 있게 다른 두 번째 방향.\n"
    "- 두 옵션은 반드시 서로 다른 category.\n"
    "- EDA·시각화는 방향 아님 (단계임).\n"
    "- 한국어만, 한자(漢字·汉字)·중국어 금지.\n"
    "- 카드 1장당 rationale 6줄, 각 줄 12~18자:\n"
    "  • 목표: <분석 목표>\n"
    "  • 방법: <핵심 알고리즘>\n"
    "  • 결과: <산출 인사이트>\n"
    "  • 강점: <강점·차별성>\n"
    "  • 적합: <적합 상황>\n"
    "  • 기대: <기대 효과·지표>\n\n"
    "[각 카드 필드]\n"
    "  id, title(한국어 10~20자), rationale(위 6줄), score(0~1),\n"
    "  category: tabular_ml|tabular_dl|timeseries|anomaly_detection,\n"
    "  approach: supervised_classification|supervised_regression|unsupervised_clustering"
    "|anomaly_detection|time_series_forecasting|supervised_other,\n"
    "  target_column: 지도학습이면 컬럼명, 아니면 null.\n\n"
    "JSON 배열 2개만 반환 (markdown·부연 금지):\n"
    '[{"id":1,"title":"...","rationale":"• 목표: ...\\n• 방법: ...\\n• 결과: ...\\n• 강점: ...\\n• 적합: ...\\n• 기대: ...",'
    '"score":0.85,"category":"tabular_ml","approach":"supervised_classification","target_column":"price"},'
    '{"id":2,...,"category":"anomaly_detection","approach":"unsupervised_clustering","target_column":null}]'
)

# Retry 시 더 강한 한국어 지시
KOREAN_RETRY_HINT = (
    "이전 응답에 한자(中文)가 포함되어 거부됩니다. "
    "반드시 한국어로만 다시 작성하세요. "
    "한자(漢字·汉字)·중국어·영어 문장 금지."
)

_UNSUPERVISED_CATEGORIES: frozenset[str] = frozenset({"anomaly_detection"})

# (category, keywords) — 앞쪽 항목일수록 우선순위 높음
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    (
        "anomaly_detection",
        [
            "클러스터",
            "군집",
            "cluster",
            "비지도",
            "unsupervised",
            "이상탐지",
            "anomaly",
            "outlier",
            "이상치",
        ],
    ),
    ("timeseries", ["시계열", "예측", "forecast", "time series", "temporal"]),
    ("tabular_dl", ["딥러닝", "deep learning", "transformer", "neural", "embedding"]),
]


def _infer_category_from_text(text: str, fallback: str) -> str:
    """title/rationale 키워드로 category 를 추론. 매칭 없으면 fallback 반환."""
    t = text.lower()
    for cat, kws in _CATEGORY_KEYWORDS:
        if any(k in t for k in kws):
            return cat
    return fallback


# 카테고리별 최소 행 수 — schema_validator.CATEGORY_RULES 와 동기화.
# 직접 import 하면 순환 의존 가능성이 있으므로 여기서 독립 선언.
_CATEGORY_MIN_ROWS: dict[str, int] = {
    "tabular_ml": 100,
    "tabular_dl": 1000,
    "timeseries": 50,
    "anomaly_detection": 500,
}


def _category_feasible(category: str, data_profile: dict | None) -> bool:
    """데이터셋이 category 의 최소 요건(행 수·필수 컬럼)을 충족하는지 확인.

    data_profile 이 없거나 rows 정보가 없으면 True 반환(보수적 허용).
    """
    if not data_profile:
        return True
    rows = int(data_profile.get("rows", 0) or 0)
    if rows == 0:
        return True
    # 최소 행 수 검사
    if rows < _CATEGORY_MIN_ROWS.get(category, 0):
        return False
    # timeseries: datetime 컬럼이 없으면 불가
    if category == "timeseries":
        dtypes = data_profile.get("dtypes") or {}
        has_datetime = any("datetime" in str(v).lower() for v in dtypes.values())
        if not has_datetime:
            return False
    return True


_CUSTOM_OPTION: dict[str, Any] = {
    "id": 3,
    "title": "직접 입력",
    "rationale": "원하는 분석 방향을 직접 입력하세요.",
    "score": None,
    "is_custom": True,
}

_FALLBACK_DEFAULTS: dict[str, list[dict[str, Any]]] = {
    "tabular_ml": [
        {
            "id": 1,
            "title": "분류/회귀 예측",
            "rationale": "타겟 컬럼 기반 지도학습으로 결과를 예측합니다.",
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "피처 중요도 분석",
            "rationale": "예측에 영향을 미치는 주요 변수를 식별합니다.",
            "score": 0.6,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "TabTransformer 학습",
            "rationale": "딥러닝 표현력으로 복잡한 패턴을 학습합니다.",
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "FTTransformer 비교",
            "rationale": "수치형 임베딩 방식으로 성능을 비교합니다.",
            "score": 0.7,
        },
    ],
    "timeseries": [
        {"id": 1, "title": "단기 예측", "rationale": "1~30일 구간의 미래 값을 예측합니다.", "score": 0.8},
        {"id": 2, "title": "이상 시점 탐지", "rationale": "변동성이 비정상적으로 큰 시점을 식별합니다.", "score": 0.6},
    ],
    "anomaly_detection": [
        {"id": 1, "title": "이상치 점수화", "rationale": "샘플별 anomaly score를 산출합니다.", "score": 0.85},
        {"id": 2, "title": "정상 분포 학습", "rationale": "정상 패턴을 학습해 이탈 여부를 판단합니다.", "score": 0.7},
    ],
}


class AnalysisProposerAgent(BaseGate):
    """G2 -- LLM 2 proposals + fixed custom option 3."""

    gate_code = "G2"
    model_name = "claude-opus-4-6"
    n_proposals = 2  # LLM generates 2; option 3 is always _CUSTOM_OPTION

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        # HJ 2026-06-09 G1 단축 V — user_payload 압축 (data_profile 전체 → 핵심 필드만).
        # gate_direction 결정에 필요한 정보: 카테고리, target, 컬럼명, dtype, 분포, 도메인 요약.
        # 입력 토큰 ~3000t → ~500t. 입력 처리 시간 -15~20s.
        # sample_rows·numeric_stats 등 무거운 필드는 제외 (gate 결정에 영향 없음).
        dp = state.data_profile or {}
        domain = dp.get("domain_analysis") or {}
        missing = dp.get("missing") or {}
        # missing 5% 초과 컬럼만 (작은 잡음 제거)
        missing_hi = {k: round(float(v), 3) for k, v in missing.items() if isinstance(v, (int, float)) and v > 0.05}

        payload: dict[str, Any] = {
            "user_intent": (state.user_intent or state.user_question or "")[:500],
            "category": state.category,
            "target_column": state.target_column,
            "rows": dp.get("rows"),
            "cols": dp.get("cols"),
            "columns": (dp.get("columns") or [])[:30],
            "dtypes": {k: v for k, v in list((dp.get("dtypes") or {}).items())[:30]},
            "target_dtype": dp.get("target_dtype"),
            "class_distribution": dp.get("class_distribution"),
            "date_col": dp.get("date_col"),
            "missing_hi_cols": missing_hi,
            "domain": domain.get("domain"),
            "dataset_summary": (domain.get("dataset_summary") or "")[:300],
        }
        # 안전 cap — 30MB·컬럼 100 worst case 도 4000자 이내로 들어옴.
        # default=str — class_distribution·target_dtype 등에 numpy 타입 섞여도 TypeError 안 나도록.
        user_payload = json.dumps(payload, ensure_ascii=False, default=str)[:4000]
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_payload,
                # HJ 2026-06-09 — G1 단축: 1500 → 900 → 800.
                # 카드 2개 × rationale 6줄 (typical, worst 8줄). 실측 화면 카드 출력 ~550t.
                # cap 800: 6줄 typical 마진 40%, 8줄 worst (~700t) 마진 14% — P99 cap 미도달.
                # 잘려도 _safe_parse_json_array → _FALLBACK_DEFAULTS 폴백.
                # 추가 단축: -8s.
                max_tokens=800,
                temperature=0.3,
                json_mode=True,
            )
            arr = self._safe_parse_json_array(raw)

            # 한자 감지 → 강한 한국어 지시로 1회 retry
            if arr and self._has_non_korean(arr):
                self.logger.warning("g2_cjk_detected_retry")
                retry_user = KOREAN_RETRY_HINT + "\n\n다시 작성할 데이터:\n" + user_payload
                try:
                    raw2 = await self._call_llm(
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=retry_user,
                        max_tokens=600,
                        temperature=0.2,
                        json_mode=True,
                    )
                    arr2 = self._safe_parse_json_array(raw2)
                    if arr2 and not self._has_non_korean(arr2):
                        arr = arr2
                    elif arr2:
                        # 둘 다 한자 → 폴백 사용 (아래로 fall-through)
                        self.logger.warning("g2_cjk_persist_after_retry")
                        arr = []
                except Exception as e:
                    self.logger.warning("g2_retry_failed", error=str(e))
                    arr = []

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

    @staticmethod
    def _has_non_korean(options: list[dict[str, Any]]) -> bool:
        """옵션의 title/rationale 중 한자가 포함된 항목이 있으면 True."""
        for opt in options:
            if not isinstance(opt, dict):
                continue
            for key in ("title", "rationale"):
                v = opt.get(key)
                if isinstance(v, str) and looks_non_korean(v):
                    return True
        return False

    def _apply_choice(
        self,
        state: PipelineState,
        user_choice: Any,
        proposals: list[dict[str, Any]],
    ) -> PipelineState:
        """Apply G2 user selection to state.

        Frontend sends:
          Custom input  -> {adopted_rank: 0, custom_intent: "text"}
          Select 1 or 2 -> {adopted_rank: 1}  or  {adopted_rank: 2}
        """
        uc = user_choice if isinstance(user_choice, dict) else {}
        updates: dict[str, Any] = {}

        # optional category / target override
        cat = uc.get("category")
        if isinstance(cat, str) and cat in CATEGORIES and cat != state.category:
            updates["category"] = cat

        tgt = uc.get("target_column") or uc.get("target")
        if isinstance(tgt, str) and tgt:
            updates["target_column"] = tgt

        # custom_intent 우선 확인 (adopted_rank=0 + custom_intent 조합)
        custom = uc.get("custom_intent")
        if isinstance(custom, str) and custom.strip():
            updates["user_intent"] = custom.strip()
            # Method B: 키워드 휴리스틱으로 category 추론 (데이터셋 요건 충족 시만)
            if "category" not in updates:
                inferred = _infer_category_from_text(custom.strip(), state.category)
                if inferred != state.category and _category_feasible(inferred, state.data_profile):
                    updates["category"] = inferred
            if updates.get("category") in _UNSUPERVISED_CATEGORIES and "target_column" not in updates:
                updates["target_column"] = None
            self.logger.info("g2_custom_intent_applied", intent=custom.strip()[:120])
        else:
            # adopted_rank 로 선택한 LLM 제안 반영
            rank = uc.get("adopted_rank")
            chosen = next(
                (p for p in (proposals or []) if isinstance(p, dict) and p.get("id") == rank),
                None,
            )
            if chosen and isinstance(chosen.get("title"), str) and chosen["title"].strip():
                direction = chosen["title"].strip()
                base = (state.user_intent or "").strip()
                updates["user_intent"] = (
                    f"{base} (분석 방향: {direction})".strip() if base else f"분석 방향: {direction}"
                )

                # Method A: LLM 이 proposal 에 category 를 채워줬으면 그대로 반영
                if "category" not in updates:
                    new_cat = chosen.get("category")
                    if isinstance(new_cat, str) and new_cat in CATEGORIES and new_cat != state.category:
                        if _category_feasible(new_cat, state.data_profile):
                            updates["category"] = new_cat
                            self.logger.info("g2_category_changed", old=state.category, new=new_cat)
                        else:
                            self.logger.info(
                                "g2_category_change_blocked",
                                reason="min_rows_not_met",
                                blocked_cat=new_cat,
                                kept_cat=state.category,
                            )

                # Method B: LLM 이 category 를 안 채웠을 때 키워드 fallback
                if "category" not in updates:
                    inferred = _infer_category_from_text(direction, state.category)
                    if inferred != state.category and _category_feasible(inferred, state.data_profile):
                        updates["category"] = inferred
                        self.logger.info("g2_category_inferred", direction=direction, category=inferred)

                # 비지도 계열이면 target_column 무효화, 지도학습이면 LLM 제안 target 반영
                if "target_column" not in updates:
                    if updates.get("category", state.category) in _UNSUPERVISED_CATEGORIES:
                        updates["target_column"] = None
                    else:
                        new_tgt = chosen.get("target_column")
                        if isinstance(new_tgt, str) and new_tgt.strip():
                            updates["target_column"] = new_tgt.strip()

                self.logger.info(
                    "g2_proposal_adopted",
                    rank=rank,
                    title=direction,
                    category=updates.get("category"),
                    target_column=updates.get("target_column"),
                )

        self.logger.info(
            "g2_apply_done",
            old_category=state.category,
            new_category=updates.get("category", state.category),
            chosen_has_category=bool(chosen.get("category")) if chosen else False,
        )
        return state.with_update(**updates) if updates else state

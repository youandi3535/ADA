"""agents.gates.methodology_proposer — G3 방법론 제안 (정형ML/정형DL/시계열/이상탐지)."""

from __future__ import annotations

import json
from typing import Any

from ada.core.lang_guard import looks_non_korean
from ada.core.state import CATEGORIES, PipelineState
from agents.gates._base_gate import BaseGate

_UNSUPERVISED_CATEGORIES: frozenset[str] = frozenset({"anomaly_detection"})

# 방법론 제목/근거 텍스트에서 카테고리를 키워드로 추론하기 위한 사전.
# 우선순위 높음 → 낮음 순서 (anomaly_detection 먼저 검사하지 않으면 timeseries 가 흡수).
_CATEGORY_KEYWORDS_KO: list[tuple[str, list[str]]] = [
    (
        "anomaly_detection",
        ["이상탐지", "anomaly", "outlier", "이상치", "OneClass", "Isolation"],
    ),  # "이상" 제거 — "0.85 이상의" 등 일반 용어와 충돌
    (
        "timeseries",
        ["시계열", "forecast", "time series", "temporal", "SARIMA", "Prophet", "LSTM"],
    ),  # "예측" 제거 — 분류 타이틀에도 흔히 등장
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


_CATEGORY_MIN_ROWS: dict[str, int] = {
    "tabular_ml": 100,
    "tabular_dl": 1000,
    "timeseries": 50,
    "anomaly_detection": 500,
}


def _category_feasible(category: str, data_profile: dict | None) -> bool:
    """데이터셋이 category 의 최소 요건(행 수·필수 컬럼)을 충족하는지 확인."""
    if not data_profile:
        return True
    rows = int(data_profile.get("rows", 0) or 0)
    if rows == 0:
        return True
    if rows < _CATEGORY_MIN_ROWS.get(category, 0):
        return False
    if category == "timeseries":
        dtypes = data_profile.get("dtypes") or {}
        has_datetime = any("datetime" in str(v).lower() for v in dtypes.values())
        if not has_datetime:
            return False
    return True


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


SYSTEM_PROMPT = (
    "당신은 AutoML 방법론 전문가. G2 에서 정해진 분석 CATEGORY 는 고정(immutable). "
    "카테고리 재결정 금지 — 그 카테고리 안에서 서로 다른 구체적 방법론 2개만 제안.\n"
    "입력 JSON: locked_category(고정 카테고리), g2_title(G2 선택 방향), "
    "rows·cols·dtypes·target 등 데이터 프로파일, user_intent(사용자 목표).\n\n"
    "## 절대 강제 사항\n"
    "1. 두 옵션 모두 locked_category 안에 머무를 것. 카테고리 점프 금지.\n"
    "   locked_category=tabular_ml 이면 anomaly_detection / timeseries / tabular_dl 안을 절대 제안하지 말 것.\n\n"
    "2. 같은 카테고리 안에서 알고리즘 계열이 명확히 다른 두 안을 낼 것. 카테고리별 허용 분기 축:\n"
    "   - tabular_ml:\n"
    "       Option 1 = 트리 앙상블 (XGBoost / LightGBM / CatBoost / RandomForest 스태킹)\n"
    "       Option 2 = 선형·커널 (Logistic Regression / SVM / Elastic Net) — 해석성 강조\n"
    "   - tabular_dl:\n"
    "       Option 1 = Transformer (TabTransformer / FT-Transformer)\n"
    "       Option 2 = 경량 MLP / TabPFN — 학습 시간·소형 데이터 강점\n"
    "   - timeseries:\n"
    "       Option 1 = 통계 모델 (SARIMA / Prophet) — 해석성·계절성\n"
    "       Option 2 = 딥러닝 (TFT / PatchTST / Informer) — 장기 의존성\n"
    "   - anomaly_detection:\n"
    "       Option 1 = 고전 앙상블 (IsolationForest / LOF / OneClassSVM)\n"
    "       Option 2 = 딥러닝 재구성 (AutoEncoder / TranAD / AnomalyTransformer)\n\n"
    "3. 위 분기 축 외 조합 금지 (예: tabular_ml 인데 한쪽에 이상탐지 끼우기).\n"
    "4. Option 1 score 는 0.80~0.95, Option 2 는 0.60~0.78.\n\n"
    "## rationale 작성 규칙 (6줄 글머리)\n"
    "한국어. 정확히 6줄. 각 줄 '• ' 로 시작, 각 줄 12~18자.\n"
    "  • 목표: 이 방법론으로 달성할 분석 목표\n"
    "  • 방법: 핵심 알고리즘 1~3개\n"
    "  • 결과: 사용자가 얻을 인사이트·지표\n"
    "  • 장점: 이 방법론의 강점·차별성\n"
    "  • 단점: 한계·주의점\n"
    "  • 기대: 기대 효과·성능 지표\n"
    "줄 사이는 반드시 '\\n' 개행. JSON 안에서 "
    '"rationale": "• 목표: ...\\n• 방법: ...\\n• 결과: ...\\n• 장점: ...\\n• 단점: ...\\n• 기대: ..."\n\n'
    "## 출력 (마크다운 금지, JSON array of 2 objects)\n"
    '[{"id":1, "title":"한국어 제목 (계열명 포함)", '
    '"category":"<locked_category 그대로>", '
    '"rationale":"• 목표: ...\\n• 방법: ...\\n• 결과: ...\\n• 장점: ...\\n• 단점: ...\\n• 기대: ...", "score":0.80},\n'
    ' {"id":2, "title":"한국어 제목 (대조 계열)", '
    '"category":"<locked_category 그대로>", '
    '"rationale":"• 목표: ...\\n• 방법: ...\\n• 결과: ...\\n• 장점: ...\\n• 단점: ...\\n• 기대: ...", "score":0.65}]'
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
                "• 목표: 타겟값 고정밀 분류·회귀 예측\n"
                "• 방법: XGBoost·RandomForest 앙상블\n"
                "• 결과: 교차검증 기반 안정적 예측 모델\n"
                "• 장점: 높은 정확도·피처 해석 용이\n"
                "• 단점: 하이퍼파라미터 튜닝 비용 발생\n"
                "• 기대: 견고한 예측 성능·중요도 지표"
            ),
            "score": 0.9,
        },
        {
            "id": 2,
            "title": "SHAP 기반 피처 중요도 분석",
            "rationale": (
                "• 목표: 예측을 좌우하는 핵심 변수 규명\n"
                "• 방법: SHAP 값·피처 중요도 결합\n"
                "• 결과: 변수별 영향도 정량 리포트\n"
                "• 장점: 예측 근거 해석·신뢰 확보\n"
                "• 단점: 계산 비용·해석 전문성 필요\n"
                "• 기대: 의사결정에 쓰는 중요도 인사이트"
            ),
            "score": 0.6,
        },
    ],
    "tabular_dl": [
        {
            "id": 1,
            "title": "TabTransformer 딥러닝 학습",
            "rationale": (
                "• 목표: 복잡한 비선형 패턴 학습\n"
                "• 방법: TabTransformer 어텐션 모델\n"
                "• 결과: 피처 상호작용 반영 예측\n"
                "• 장점: 트리 모델 대비 표현력 우위\n"
                "• 단점: 학습 시간·데이터량 요구\n"
                "• 기대: 대규모 정형 데이터 고성능"
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "FTTransformer 수치 임베딩 비교",
            "rationale": (
                "• 목표: 최적 딥러닝 구조 선정\n"
                "• 방법: FTTransformer 수치 임베딩\n"
                "• 결과: 모델 비교·자동 아키텍처 선정\n"
                "• 장점: 수치형 표현력·기여도 제공\n"
                "• 단점: 튜닝 복잡·자원 소모\n"
                "• 기대: 검증된 최적 모델·신뢰도"
            ),
            "score": 0.7,
        },
    ],
    "timeseries": [
        {
            "id": 1,
            "title": "단기 시계열 예측 (LSTM/Prophet)",
            "rationale": (
                "• 목표: 단기 미래 값 예측\n"
                "• 방법: Prophet·LSTM 예측 모델\n"
                "• 결과: 1~30일 예측값·신뢰구간\n"
                "• 장점: 추세·계절성 자동 반영\n"
                "• 단점: 장기 예측 정확도 한계\n"
                "• 기대: 수요·지표 사전 대응력"
            ),
            "score": 0.8,
        },
        {
            "id": 2,
            "title": "이상 시점 탐지 (변동성 분석)",
            "rationale": (
                "• 목표: 비정상 변동 시점 탐지\n"
                "• 방법: IsolationForest·통계 기법\n"
                "• 결과: 이상 시점·구간 자동 표시\n"
                "• 장점: 정상 패턴 학습 후 이탈 포착\n"
                "• 단점: 임계값 설정 민감성\n"
                "• 기대: 원인 피처·이상 패턴 해석"
            ),
            "score": 0.6,
        },
    ],
    "anomaly_detection": [
        {
            "id": 1,
            "title": "Isolation Forest 이상치 점수화",
            "rationale": (
                "• 목표: 샘플별 이상 점수화\n"
                "• 방법: IsolationForest·AutoEncoder\n"
                "• 결과: 임계값 자동·이상 비율 시각화\n"
                "• 장점: 경량·실시간 모니터링 적합\n"
                "• 단점: 고차원서 성능 저하 가능\n"
                "• 기대: 즉시 적용 가능한 탐지 모델"
            ),
            "score": 0.85,
        },
        {
            "id": 2,
            "title": "정상 분포 학습 기반 탐지",
            "rationale": (
                "• 목표: 정상 분포 이탈 판별\n"
                "• 방법: One-Class SVM·GMM 학습\n"
                "• 결과: 최적 탐지 모델 자동 선정\n"
                "• 장점: 데이터 특성 맞춤 탐지\n"
                "• 단점: 정상 정의·분포 가정 의존\n"
                "• 기대: 이상 강도·원인 피처 리포트"
            ),
            "score": 0.7,
        },
    ],
}


# HJ 2026-06-12 — C′-2: 방법론 후보 선계산 캐시 (prefetch ↔ 노드 공유).
#   Redis Hash ada:g2_method:{job_id}, field = G2 선택 방향 제목, value = {status, category, proposals}.
def _g2_method_cache_key(job_id: str) -> str:
    return f"ada:g2_method:{job_id}"


def _g2_method_cache_get(job_id, title, category):
    """선계산된 방법론 후보 조회. 방향 제목 + category 일치 시에만 반환(데이터 정합)."""
    if not job_id or not title:
        return None
    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings

        r = _redis.Redis.from_url(settings.redis_url)
        raw = r.hget(_g2_method_cache_key(job_id), title)
        if not raw:
            return None
        d = _json.loads(raw)
        if d.get("status") == "done" and d.get("proposals") and d.get("category") == category:
            return d["proposals"]
    except Exception:  # noqa: BLE001
        return None
    return None


def _g2_method_cache_set(job_id, title, category, proposals) -> None:
    if not job_id or not title or not proposals:
        return
    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings

        r = _redis.Redis.from_url(settings.redis_url)
        r.hset(
            _g2_method_cache_key(job_id),
            title,
            _json.dumps(
                {"status": "done", "category": category, "proposals": proposals}, ensure_ascii=False, default=str
            ),
        )
        r.expire(_g2_method_cache_key(job_id), 86400)
    except Exception:  # noqa: BLE001
        pass


class MethodologyProposerAgent(BaseGate):
    """G3 — 방법론(카테고리) 권장. 본 게이트가 카테고리 변경을 제안할 수 있다."""

    gate_code = "G3"
    model_name = "claude-sonnet-4-6"
    n_proposals = 2  # LLM generates 2; option 3 is always _CUSTOM_OPTION

    async def _propose(self, state: PipelineState) -> list[dict[str, Any]]:
        # HJ 2026-06-10 — stage_partial publish (단계 2 long-phase 라이브 피드백)
        def _emit(partial: dict) -> None:
            try:
                from orchestrator.runner import publish_stage_partial as _psp

                _psp(state.job_id, partial)
            except Exception:  # noqa: BLE001
                pass

        # G2 선택 제목을 추출 — adopted_rank 숫자 대신 실제 방향 텍스트를 LLM 에 전달
        g1_resp = (state.gate_responses or {}).get("G2", {})
        g1_uc = g1_resp.get("user_choice") or {}
        g1_rank = g1_uc.get("adopted_rank") if isinstance(g1_uc, dict) else None
        g1_props = g1_resp.get("proposals") or []
        g1_chosen = next(
            (p for p in g1_props if isinstance(p, dict) and p.get("id") == g1_rank),
            None,
        )
        _emit(
            {
                "methodology_status": f"G2 선택 분석: {(g1_chosen or {}).get('title', '미정')[:80]}",
                "methodology_phase": "context",
                "methodology_locked_category": state.category,
            }
        )
        g2_title = g1_chosen.get("title") if g1_chosen else ""
        _emit(
            {
                "methodology_status": f"카테고리 '{state.category}' 에 적합한 방법론 후보를 분석하고 있습니다…",
                "methodology_phase": "llm",
            }
        )
        # HJ 2026-06-12 — C′-2: prefetch 가 주제 선택 중 미리 만든 방법론 후보가 있으면 LLM 스킵(63~87초 절감).
        #   캐시 key = (job_id, 선택 방향 제목, category). 추천 방향+동일 카테고리면 적중,
        #   사용자가 다른 방향/카테고리 선택 시 miss → 그 자리에서 생성(폴백).
        # HJ 2026-06-12 — 병목 진단용 구간 타이밍 로깅 (cache 조회 / LLM 생성 / 전체).
        #   cache_hit  → G3 시점 LLM 미호출(선이동 적중). 병목은 G2 prefetch 쪽.
        #   cache_miss → llm_ms 가 실제 생성 시간. 내부 분해는 base.py 의 ollama_timing 로그 참조.
        import time as _time

        _t0 = _time.perf_counter()
        llm_opts = _g2_method_cache_get(state.job_id, g2_title, state.category)
        _cache_ms = round((_time.perf_counter() - _t0) * 1000, 1)
        if llm_opts:
            self.logger.info(
                "g3_timing",
                phase="cache_hit",
                cache_lookup_ms=_cache_ms,
                llm_ms=0.0,
                total_ms=round((_time.perf_counter() - _t0) * 1000, 1),
            )
        else:
            _t1 = _time.perf_counter()
            llm_opts = await self._generate_for_title(state, g2_title)
            _llm_ms = round((_time.perf_counter() - _t1) * 1000, 1)
            self.logger.info(
                "g3_timing",
                phase="cache_miss_generate",
                cache_lookup_ms=_cache_ms,
                llm_ms=_llm_ms,
                total_ms=round((_time.perf_counter() - _t0) * 1000, 1),
                generated=bool(llm_opts),
            )
            if llm_opts:
                _g2_method_cache_set(state.job_id, g2_title, state.category, llm_opts)

        if llm_opts:
            # 후보를 stage_partial 에도 노출 — 프론트 모달이 곧바로 표시
            _emit(
                {
                    "methodology_status": f"방법론 후보 {len(llm_opts)}개 확정",
                    "methodology_phase": "done",
                    "methodology_candidates": [
                        {
                            "id": o.get("id"),
                            "title": str(o.get("title", ""))[:160],
                            "score": o.get("score"),
                            "rationale": str(o.get("rationale", ""))[:600],
                        }
                        for o in llm_opts
                    ],
                }
            )
            return llm_opts + [_CUSTOM_OPTION]

        base = _FALLBACK_DEFAULTS.get(
            state.category,
            [{"id": 1, "title": "기본 분석", "rationale": "LLM 실패로 기본 제안", "score": 0.5}],
        )
        _emit(
            {
                "methodology_status": f"폴백 방법론 {len(base)}개 적용",
                "methodology_phase": "fallback_applied",
                "methodology_candidates": [
                    {
                        "id": o.get("id"),
                        "title": str(o.get("title", ""))[:160],
                        "score": o.get("score"),
                        "rationale": str(o.get("rationale", ""))[:600],
                    }
                    for o in base
                ],
            }
        )
        return list(base) + [_CUSTOM_OPTION]

    async def _generate_for_title(self, state: PipelineState, g2_title: str) -> list[dict[str, Any]] | None:
        """방법론 후보 LLM 생성 (g2_title 입력). 성공 시 llm_opts(list), 실패/한자 고착 시 None.

        _emit(status publish) 없음 → 노드(_propose)와 prefetch 선계산이 공유. HJ 2026-06-12 C′-2.
        """
        # HJ 2026-06-12 — 입력 토큰 축소(생성 실패 방지). data_profile 통째(≈3200t)는 LLM JSON 생성을
        #   실패시켜 76초 헛돌이를 유발 → gate 결정에 필요한 핵심 필드만 추출(G2 _propose 동일 패턴).
        #   sample_rows·numeric_stats·domain_analysis 전체 등 무거운 필드 제외.
        dp = state.data_profile or {}
        domain = dp.get("domain_analysis") or {}
        payload = {
            "locked_category": state.category,
            "g2_title": g2_title or "",
            "user_intent": (state.user_intent or "")[:500],
            "rows": dp.get("rows"),
            "cols": dp.get("cols"),
            "columns": (dp.get("columns") or [])[:30],
            "dtypes": {k: v for k, v in list((dp.get("dtypes") or {}).items())[:30]},
            "target_column": state.target_column,
            "target_dtype": dp.get("target_dtype"),
            "class_distribution": dp.get("class_distribution"),
            "domain": domain.get("domain"),
            "dataset_summary": (domain.get("dataset_summary") or "")[:300],
        }
        # default=str — numpy/pandas 타입이 섞여도 TypeError 방지
        user_payload = json.dumps(payload, ensure_ascii=False, default=str)[:2500]
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_payload,
                max_tokens=1500,
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
                return llm_opts
        except Exception as e:
            self.logger.warning("g3_llm_failed", error=str(e))
        return None

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
        _DEFAULT_META = {"variate": None, "forecast_kind": None, "task_kind": None, "horizon_hint": None}
        if isinstance(custom, str) and custom.strip():
            # HJ 2026-06-11 (jh 대행) — 멱등 부착 (resume 누적 오염 수정)
            from agents.gates._intent import append_intent_tag

            updates["user_intent"] = append_intent_tag(state.user_intent, "방법론", custom)
            if "category" not in updates:
                inferred = _infer_category_from_text(custom, state.category)
                if inferred != state.category and _category_feasible(inferred, state.data_profile):
                    updates["category"] = inferred
            updates["chosen_recipe"] = {
                "id": 0,
                "title": custom.strip(),
                "methodology": custom.strip(),
                "is_custom": True,
                "meta": dict(_DEFAULT_META),
            }
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
                from agents.gates._intent import append_intent_tag

                updates["user_intent"] = append_intent_tag(base, "방법론", method)
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
                chosen_meta = chosen.get("meta")
                updates["chosen_recipe"] = {
                    "id": chosen.get("id"),
                    "title": method,
                    "methodology": method,
                    "is_custom": False,
                    "meta": dict(chosen_meta) if isinstance(chosen_meta, dict) else dict(_DEFAULT_META),
                }
                self.logger.info(
                    "g3_proposal_adopted",
                    rank=rank,
                    title=method,
                    category=updates.get("category"),
                )

        return state.with_update(**updates) if updates else state

"""agents.preprocessing_strategist — Day 0 dispatcher 패턴.

LLM 으로 plan 시도 → 실패 시 ``handlers/{cat}/preprocessor.plan()`` fallback.
수정 권한: **HJ 단독** (dispatcher).
"""

from __future__ import annotations

import json
from typing import Any

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler


# HJ 2026-06-11 — G3 모달 라이브 피드용. eda_agent.py 패턴 동일.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


# HJ 2026-06-11 — plan step 이름 → 사용자 친화 prefix·설명 매핑.
# G2 의 eda_insights "결측 분석:", "상관관계:" 패턴과 동일. frontend 가 prefix 별 그룹화.
_STEP_PREFIX: dict[str, str] = {
    "impute_numeric": "결측 처리",
    "impute_categorical": "결측 처리",
    "scale_standard": "스케일링",
    "scale_minmax": "스케일링",
    "scale_robust": "스케일링",
    "onehot": "인코딩",
    "ordinal": "인코딩",
    "target_encoding": "인코딩",
    "frequency_encoding": "인코딩",
    "hash": "인코딩",
    "hash_encoding": "인코딩",
    "outlier_clip": "이상치 처리",
    "log_transform": "분포 변환",
    "boxcox": "분포 변환",
    "polynomial_features": "파생 피처",
    "interaction_terms": "파생 피처",
    "binning": "구간화",
    "drop_high_missing": "컬럼 제거",
    "drop_constant": "컬럼 제거",
    "drop_duplicates": "행 제거",
}
_STEP_DESC: dict[str, str] = {
    "impute_numeric": "median/mean imputation",
    "impute_categorical": "mode/상수 imputation",
    "scale_standard": "표준 스케일링 (z-score)",
    "scale_minmax": "MinMax 스케일링 (0-1 범위)",
    "scale_robust": "Robust 스케일링 (IQR 기반)",
    "onehot": "원핫 인코딩 (one-hot)",
    "ordinal": "순서형 인코딩",
    "target_encoding": "타깃 인코딩 (target encoding)",
    "frequency_encoding": "빈도 인코딩",
    "hash": "해시 인코딩",
    "hash_encoding": "해시 인코딩",
    "outlier_clip": "이상치 클리핑 (Winsorize)",
    "log_transform": "로그 변환 (왜도 보정)",
    "boxcox": "Box-Cox 변환",
    "polynomial_features": "다항 피처 (x², xy 조합)",
    "interaction_terms": "교호작용 항 (x1 × x2)",
    "binning": "구간화 (binning)",
    "drop_high_missing": "고결측 컬럼 제거",
    "drop_constant": "상수 컬럼 제거",
}


def _plan_to_insights(plan: list, profile: dict | None) -> list[str]:
    """preprocessing plan 의 각 step 을 사용자 친화 자연어 인사이트로 변환.

    G2 의 eda_insights 와 동일 패턴 — 'prefix: 내용' 형식. frontend 가 prefix 별 그룹화.
    결측 처리 step 에는 결측률 추가, LLM rationale 이 있으면 우선 노출.
    """
    insights: list[str] = []
    miss = (profile or {}).get("missing") or {}
    for step in plan:
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or step.get("op") or "").strip()
        if not name:
            continue
        prefix = _STEP_PREFIX.get(name, "전처리")
        desc = _STEP_DESC.get(name, name)
        strategy = step.get("strategy") or (step.get("params") or {}).get("strategy")
        cols = step.get("columns") or step.get("scope") or []
        rationale = str(step.get("rationale") or "").strip()

        # 컬럼 정보 (4개 이하 나열, 그 외는 개수만)
        col_txt = ""
        if isinstance(cols, list) and cols:
            if len(cols) <= 4:
                col_txt = f" — 대상 컬럼: {', '.join(str(c) for c in cols[:4])}"
            else:
                col_txt = f" — 대상 컬럼 {len(cols)}개"

        # strategy
        strat_txt = f" (전략: {strategy})" if strategy else ""

        # 결측 처리는 결측률 노출
        miss_txt = ""
        if name.startswith("impute") and isinstance(cols, list) and cols:
            rates: list[str] = []
            for c in cols[:3]:
                r = miss.get(str(c))
                if r is not None:
                    try:
                        rates.append(f"'{c}' {float(r) * 100:.1f}%")
                    except (TypeError, ValueError):
                        continue
            if rates:
                miss_txt = f" — 결측률: {', '.join(rates)}"

        # LLM rationale 우선, 없으면 strategy/col 정보
        if rationale and len(rationale) > 5:
            insights.append(f"{prefix}: {desc}{strat_txt}{col_txt} — {rationale[:160]}")
        else:
            insights.append(f"{prefix}: {desc}{strat_txt}{col_txt}{miss_txt}")
    return insights


# HJ 2026-06-13 — G3 전처리 윤색 선계산 캐시 (G2 eda_insights prefetch 패턴 동일).
#   gate_methodology(G3 방법론 화면) 대기 중 worker 가 plan+윤색을 미리 만들어 Redis 에 저장.
#   resume 후 __call__ 이 캐시 히트 시 LLM·윤색을 모두 스킵·즉시 표시 → 품질 보장·0 블록.
def _g3_pre_cache_key(job_id: str) -> str:
    return f"ada:g3_pre:{job_id}"


def _g3_pre_cache_get(job_id, category, target_column):
    """선계산된 plan+윤색 번들 조회. category/target 일치 시에만 반환(데이터 정합)."""
    if not job_id:
        return None
    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings

        r = _redis.Redis.from_url(settings.redis_url)
        raw = r.get(_g3_pre_cache_key(job_id))
        if not raw:
            return None
        d = _json.loads(raw)
        if (
            d.get("status") == "done"
            and d.get("insights")
            and d.get("category") == category
            and d.get("target") == (target_column or None)
        ):
            return d
    except Exception:  # noqa: BLE001
        return None
    return None


def _g3_pre_cache_set(job_id, category, target_column, *, plan, rationale, leakage_risks, insights) -> None:
    if not job_id or not insights:
        return
    try:
        import json as _json

        import redis as _redis

        from ada.core.config import settings

        r = _redis.Redis.from_url(settings.redis_url)
        r.set(
            _g3_pre_cache_key(job_id),
            _json.dumps(
                {
                    "status": "done",
                    "category": category,
                    "target": (target_column or None),
                    "plan": plan,
                    "rationale": rationale,
                    "leakage_risks": leakage_risks,
                    "insights": insights,
                },
                ensure_ascii=False,
                default=str,
            ),
            ex=86400,
        )
    except Exception:  # noqa: BLE001
        pass


SYSTEM_PROMPT = """당신은 시니어 데이터 엔지니어로서 데이터 프로파일을 보고
전처리 단계를 JSON 으로 설계합니다.

응답:
{
  "steps": [
    {"name": "impute_numeric", "strategy": "median", "needs_review": false},
    ...
  ],
  "rationale": "한국어 1문장",
  "leakage_risks": []
}
"""


class PreprocessingStrategistAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-sonnet-4-6"

    async def _generate_plan(self, state: PipelineState) -> tuple[list, str, list]:
        """전처리 plan 생성 (LLM 우선 → 핸들러 폴백). prefetch·본실행 공용.

        입력은 category/data_profile/target 만 의존(방법론 선택과 무관)하므로
        gate_methodology 대기 중 선계산해도 본실행과 동일한 plan 을 얻는다.
        반환: (plan, rationale, leakage_risks).
        """
        plan: list[dict[str, Any]] = []
        rationale: str = ""
        leakage_risks: list = []
        try:
            payload = {
                "category": state.category,
                "data_profile": state.data_profile,
                "target_column": state.target_column,
            }
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False)[:4000],
                max_tokens=800,
                temperature=0.1,
                json_mode=True,
            )
            parsed = self._parse_json(raw)
            plan = parsed.get("steps") or []
            rationale = str(parsed.get("rationale") or "").strip()
            lr = parsed.get("leakage_risks") or []
            leakage_risks = lr if isinstance(lr, list) else []
        except Exception as e:
            self.logger.warning("preprocess_llm_fallback", error=str(e))

        if not plan:
            handler = get_handler(state.category, "plan")
            if handler is not None:
                try:
                    plan = handler(state) or []
                except Exception as e:
                    self.logger.warning("preprocess_handler_failed", category=state.category, error=str(e))
        return plan, rationale, leakage_risks

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # HJ 2026-06-11 — G3 모달 라이브 피드: 진행 시작 즉시 status publish.
            _safe_publish_stage_partial(
                state.job_id,
                {"g3_phase": "preprocessing_strategist_start", "g3_status": "전처리 전략 LLM 호출 중…"},
            )

            # HJ 2026-06-13 — G2 eda_insights prefetch 패턴 이식. gate_methodology(G3 방법론
            #   화면) 대기 중 worker 가 plan+윤색을 선계산(_g3_pre_prefetch_async)해 Redis 에 저장.
            #   캐시 히트면 LLM·윤색(최대 165s)을 모두 스킵하고 완성된 윤색을 즉시 동기 publish →
            #   윤색이 항상 표시(품질 보장)되고 feature_engineer 가 0 블록으로 전진.
            cached = _g3_pre_cache_get(state.job_id, state.category, state.target_column)
            if cached:
                plan = cached.get("plan") or []
                rationale = str(cached.get("rationale") or "")
                leakage_risks = cached.get("leakage_risks") or []
                g3_insights = list(cached.get("insights") or [])
                self.logger.info("g3_pre_cache_hit", n=len(g3_insights), steps=len(plan))
            else:
                # 캐시 미스(빠른 제출·prefetch 미완) — plan 생성 후 윤색은 백그라운드로(critical
                #   path 제거). 규칙기반 g3_insights 즉시 표시, 윤색 완료분은 _dynamic_insights 가
                #   job_id+key="g3_insights" 로 교체 publish(best-effort), 게이트 직전 drain 회수.
                #   윤색은 모달 표시용 설명일 뿐 preprocessing_plan(다음 단계 입력)과 무관.
                plan, rationale, leakage_risks = await self._generate_plan(state)
                g3_insights = _plan_to_insights(plan, state.data_profile or {})
                self._spawn_insight_polish(
                    list(g3_insights),
                    backend="ollama",
                    context="G3 전처리 전략",
                    job_id=state.job_id,
                    key="g3_insights",
                )

            # G2 의 eda_insights 와 동일 패턴 — frontend 가 prefix 별 그룹화. 사용자가 실시간 확인.
            try:
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g3_phase": "preprocessing_strategist_done",
                        "g3_status": f"전처리 전략 수립 완료 (step {len(plan)}개) — 피처 엔지니어링 시작",
                        "g3_insights": g3_insights,
                        "g3_rationale": rationale[:300],
                        "g3_leakage_risks": [str(r)[:200] for r in leakage_risks][:5],
                        "g3_plan_count": len(plan),
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("g3_insights_publish_failed", error=str(e))

            new_state = state.with_update(preprocessing_plan=plan, next_agent="feature_engineer")

            # Phase 1.4 — ReportContext ③ preprocessing 적립.
            # plan 의 각 step 을 PreprocessingStep dict 로 변환. before/after_stats 는
            # feature_engineer 가 실제 적용 시 보강 가능 (현재는 placeholder).
            try:
                applied_steps = [
                    {
                        "op": str(s.get("name") or s.get("op") or ""),
                        "scope": list(s.get("columns") or s.get("scope") or []),
                        "params": {k: v for k, v in s.items() if k not in ("name", "op", "columns", "scope")},
                        "rationale": str(s.get("rationale") or s.get("needs_review", "")),
                        "before_stats": {},
                        "after_stats": {},
                    }
                    for s in plan
                    if isinstance(s, dict)
                ]
                new_state = self.contribute_to_context(
                    new_state,
                    "preprocessing",
                    {"applied_steps": applied_steps},
                )
            except Exception as e:
                self.logger.warning("contribute_preprocessing_failed", error=str(e))
            return new_state

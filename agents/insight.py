"""agents.insight — Day 0 dispatcher + Day 8 가드레일.

카테고리별 프롬프트는 ``handlers/{cat}/insight.{prompt_payload,fallback,SYSTEM_PROMPT}`` 사용.

Day 8 가드:
    (a) 정확한 수치 1개+ (예: 12%, 0.83)
    (b) top3 피처 1개+ (state.eval_result['feature_importance'] 상위 키)
    (c) 3~5 문장
    (d) 한국어 강제 (한글 음절 1자+)

위반 시: 시스템 프롬프트에 수정 요구를 덧붙여 1회 retry. 그래도 실패면 fallback.

수정 권한: HJ 단독 (dispatcher).
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from ada.security.guardrails import insight_must_cite
from agents.base import BaseAgent


# HJ 2026-06-11 — G5 모달 라이브 피드용.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass

CATEGORY_TO_MODULE = {
    "timeseries": "agents.handlers.timeseries.insight",
    "anomaly_detection": "agents.handlers.anomaly.insight",
    "tabular_ml": "agents.handlers.tabular.insight",
    "tabular_dl": "agents.handlers.tabular.insight",
}

GUARD_FAIL_RETRY_PROMPT = (
    "\n\n[수정 요청] 이전 응답이 다음 가드를 위반했습니다: {violations}.\n"
    "반드시 (a) 정확한 수치 1개 이상 포함, (b) 상위 피처 명 1개 이상 인용,\n"
    "(c) 3~5문장 한국어로 답하세요. 다른 형식은 거부됩니다."
)


def _top_features(state: PipelineState) -> list[str]:
    """eval_result 또는 explanations 에서 top3 피처명 추출."""
    sources = (state.eval_result, state.explanations)
    for src in sources:
        if not isinstance(src, dict):
            continue
        fi = src.get("feature_importance") or src.get("top_features") or src.get("importances")
        if isinstance(fi, dict) and fi:
            return [str(k) for k, _ in sorted(fi.items(), key=lambda kv: kv[1], reverse=True)[:3]]
        if isinstance(fi, list) and fi:
            return [str(x.get("name") if isinstance(x, dict) else x) for x in fi[:3]]
    return []


def _metric_names(state: PipelineState) -> list[str]:
    bm = state.best_model or {}
    metrics = bm.get("metrics") or {}
    return list(metrics.keys())


class InsightAgent(BaseAgent):
    uses_llm = True
    model_name = "claude-opus-4-6"
    use_anthropic_api = True

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # HJ 2026-06-11 — G5 모달 라이브 피드: 인사이트 LLM 호출 시작 status.
            _safe_publish_stage_partial(
                state.job_id,
                {
                    "g5_phase": "insight_start",
                    "g5_status": "인사이트 LLM 호출 중 — 한국어 3~5문장 생성",
                },
            )
            mod_name = CATEGORY_TO_MODULE.get(state.category)
            text: str = ""
            mod = None
            try:
                mod = importlib.import_module(mod_name) if mod_name else None
            except Exception as e:
                self.logger.warning("insight_handler_missing", error=str(e))

            system_prompt = (
                getattr(mod, "SYSTEM_PROMPT", "한국어 3~5문장으로 인사이트.")
                if mod
                else ("한국어 3~5문장으로 인사이트. 수치 1개 이상과 상위 피처 1개 이상 반드시 인용.")
            )
            payload_fn = getattr(mod, "prompt_payload", None) if mod else None
            fallback_fn = getattr(mod, "fallback", None) if mod else None
            payload = payload_fn(state) if callable(payload_fn) else {"category": state.category}

            top_feats = _top_features(state)
            metric_names = _metric_names(state)

            # 1) 최초 LLM 호출
            text = await self._call_with_guard(
                system_prompt=system_prompt,
                payload=payload,
                top_feats=top_feats,
                metric_names=metric_names,
            )

            # 2) 가드 검증
            verdict = insight_must_cite(text, metric_names=metric_names, top_features=top_feats)
            self.logger.info(
                "insight_guard_attempt",
                job_id=state.job_id,
                attempt=1,
                passed=verdict["passed"],
                violations=verdict["violations"],
                n_sentences=verdict["n_sentences"],
                text_len=len(text),
            )
            if not verdict["passed"]:
                self.logger.warning("insight_guard_fail_first", violations=verdict["violations"])
                # retry 1회 — 가드 위반 사유를 system prompt 에 덧붙임
                retry_prompt = system_prompt + GUARD_FAIL_RETRY_PROMPT.format(
                    violations=", ".join(verdict["violations"])
                )
                text2 = await self._call_with_guard(
                    system_prompt=retry_prompt,
                    payload=payload,
                    top_feats=top_feats,
                    metric_names=metric_names,
                )
                verdict2 = insight_must_cite(text2, metric_names=metric_names, top_features=top_feats)
                self.logger.info(
                    "insight_guard_attempt",
                    job_id=state.job_id,
                    attempt=2,
                    passed=verdict2["passed"],
                    violations=verdict2["violations"],
                    n_sentences=verdict2["n_sentences"],
                    text_len=len(text2),
                )
                if verdict2["passed"]:
                    text = text2
                else:
                    # 그래도 실패 — fallback 텍스트
                    self.logger.warning("insight_guard_fail_after_retry", violations=verdict2["violations"])
                    if callable(fallback_fn):
                        try:
                            text = fallback_fn(state)
                        except Exception as e:
                            # P3 보강: silent pass → logger.warning
                            self.logger.warning("insight_fallback_failed", error=str(e))
                            text = ""

            if not text:
                text = "이번 분석 결과는 추가 검토가 필요합니다."

            # HJ 2026-06-11 — G5 모달 라이브 피드: 최종 인사이트 자연어 publish.
            # 한국어 3~5 문장을 문장 단위로 분리해 G2 의 eda_insights 처럼 그룹 표시.
            try:
                _sentences = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip() and len(s.strip()) > 5]
                _g5_final_insights = [f"인사이트: {s[:200]}" for s in _sentences[:6]]
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g5_phase": "insight_done",
                        "g5_status": "인사이트 생성 완료 — 산출물 단계로 이동",
                        "g5_final_insights": _g5_final_insights,
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.warning("g5_final_insights_publish_failed", error=str(e))

            # Day 4 — PII reattach (LLM 응답에 토큰이 남았을 가능성 대비)
            try:
                pii_meta = (state.category_extras or {}).get("_pii") or {}
                mapping = pii_meta.get("mapping") or {}
                if mapping:
                    from agents.security_guard import SecurityGuardAgent

                    text = SecurityGuardAgent.reattach_for_user(text, mapping)
            except Exception as e:
                # P3 보강: silent pass → logger.warning (PII 누출 추적용)
                self.logger.warning("insight_pii_reattach_failed", error=str(e))

            new_state = state.with_update(insights=text.strip(), next_agent="gate_outputs")

            # Phase 1.4 — ReportContext ⑨ interpretation 보조 적립.
            # 본격적 SHAP/PDP 는 Explainability agent 가 글로벌 importance 적립.
            # 여기서는 top_feats 와 인사이트 텍스트의 피처별 요약을 간단 저장.
            try:
                per_feature_story: dict[str, str] = {}
                for feat in top_feats[:3]:
                    # 인사이트에서 해당 피처를 포함한 문장만 추출 (best-effort).
                    sents = [s.strip() for s in text.split(".") if feat in s]
                    if sents:
                        per_feature_story[str(feat)] = sents[0][:200]
                if per_feature_story:
                    new_state = self.contribute_to_context(
                        new_state,
                        "interpretation",
                        {"per_feature_story": per_feature_story},
                    )
            except Exception as e:
                self.logger.warning("contribute_interpretation_failed", error=str(e))
            return new_state

    # ------------------------------------------------------------------
    async def _call_with_guard(
        self,
        *,
        system_prompt: str,
        payload: dict[str, Any],
        top_feats: list[str],
        metric_names: list[str],
    ) -> str:
        """LLM 호출 — payload 에 가드 힌트(metric_names/top_feats) 자동 주입."""
        enriched = {
            **payload,
            "_guard": {
                "metric_names": metric_names,
                "top_features": top_feats,
                "sentence_range": [3, 5],
                "language": "ko-KR",
            },
        }
        try:
            return await self._call_llm(
                system_prompt=system_prompt,
                user_prompt=json.dumps(enriched, ensure_ascii=False)[:4500],
                max_tokens=600,
                temperature=0.4,
            )
        except Exception as e:
            self.logger.warning("insight_llm_failed", error=str(e))
            return ""

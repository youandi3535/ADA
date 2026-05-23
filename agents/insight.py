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
    model_name = "claude-opus-4-7"

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
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
                if verdict2["passed"]:
                    text = text2
                else:
                    # 그래도 실패 — fallback 텍스트
                    self.logger.warning("insight_guard_fail_after_retry", violations=verdict2["violations"])
                    if callable(fallback_fn):
                        try:
                            text = fallback_fn(state)
                        except Exception:
                            pass

            if not text:
                text = "이번 분석 결과는 추가 검토가 필요합니다."

            # Day 4 — PII reattach (LLM 응답에 토큰이 남았을 가능성 대비)
            try:
                pii_meta = (state.category_extras or {}).get("_pii") or {}
                mapping = pii_meta.get("mapping") or {}
                if mapping:
                    from agents.security_guard import SecurityGuardAgent

                    text = SecurityGuardAgent.reattach_for_user(text, mapping)
            except Exception:
                pass

            return state.with_update(insights=text.strip(), next_agent="gate_outputs")

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

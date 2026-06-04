"""agents.security_guard — SecurityGuardAgent (Day05 v2 + Day 4 PII 풀 통합).

R-708 indirect prompt injection 가드 + LLM Guard PII anonymize→re-attach.
LLM Guard 미설치 환경에서는 정규표현식 기반 자체 가드 fallback.

Day 4 변경:
    - scan_text() 외에 anonymize_for_llm() / reattach_for_user() 헬퍼 노출
    - __call__ 에서 state.user_intent / user_question 의 PII 를 자동 마스킹
    - 마스킹 매핑은 state.category_extras['_pii']['mapping'] 에 저장
      (InsightAgent / output carrier 가 reattach 시 사용)
"""

from __future__ import annotations

import re
from typing import Any

from ada.core.state import PipelineState
from ada.security.audit import log_event
from agents.base import BaseAgent

INJECTION_PATTERNS = [
    r"ignore (?:previous|prior|all) (?:instructions|directives)",
    r"system prompt",
    r"reveal (?:the )?prompt",
    r"jailbreak",
    r"DAN mode",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
]


class SecurityGuardAgent(BaseAgent):
    """그래프 외부 hook + 그래프 내부 노드 양쪽에서 호출 가능."""

    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            text = state.user_intent or state.user_question or ""
            verdict = self.scan_text(text)
            if not verdict["safe"]:
                # 차단 audit
                if self.session is not None:
                    try:
                        await log_event(
                            self.session,
                            event_type="security",
                            action="prompt_injection_blocked",
                            result="blocked",
                            actor_user_id=state.user_id,
                            details={"reason": verdict["reason"], "preview": text[:200]},
                        )
                    except Exception:
                        pass
                return state.with_update(
                    error=f"보안 가드 차단: {verdict['reason']}",
                    next_agent="error_recovery",
                )

            # Day 4 — PII anonymize: 텍스트의 PII 를 토큰으로 치환하고 매핑 저장
            from ada.security.guardrails import PIIAnonymizer

            # PII anonymizer 의 토큰 할당이 anonymize_text 호출마다 독립이라
            # 같은 PII 가 intent / question 양쪽에 있어도 다른 토큰을 받을 수 있다.
            # → 같은 anonymizer 인스턴스를 재사용해 토큰 카운터 공유 +
            #   mapping 병합 시 동일 토큰이면 값 일치, 다른 토큰이면 둘 다 보존.
            anonymizer = PIIAnonymizer()
            mapped_intent, mapping_intent = anonymizer.anonymize_text(state.user_intent or "")
            mapped_question, mapping_question = anonymizer.anonymize_text(state.user_question or "")
            # 토큰 키 충돌 검사 — 동일 키에 다른 값이 들어 있으면 데이터 손실이므로 경고.
            _conflict_keys = [
                k for k in mapping_intent if k in mapping_question and mapping_intent[k] != mapping_question[k]
            ]
            if _conflict_keys:
                self.logger.warning(
                    "pii_mapping_token_conflict",
                    keys=_conflict_keys[:10],
                    n=len(_conflict_keys),
                )
            mapping = {**mapping_intent, **mapping_question}

            extras = dict(state.category_extras or {})
            if mapping:
                extras["_pii"] = {
                    "mapping": mapping,
                    "redaction": "***",
                    "n_tokens": len(mapping),
                }
                if self.session is not None:
                    try:
                        await log_event(
                            self.session,
                            event_type="security",
                            action="pii_anonymized",
                            result="success",
                            actor_user_id=state.user_id,
                            details={"n_tokens": len(mapping)},
                        )
                    except Exception:
                        pass

            return state.with_update(
                user_intent=mapped_intent or state.user_intent,
                user_question=mapped_question or state.user_question,
                category_extras=extras,
            )

    # ------------------------------------------------------------------
    @staticmethod
    def scan_text(text: str) -> dict[str, Any]:
        """공개 API — FastAPI 미들웨어/Supervisor 에서 직접 호출."""
        if not text:
            return {"safe": True, "reason": "empty"}

        # 1) LLM Guard (R-1002) — 옵션
        try:
            from llm_guard.input_scanners import PromptInjection  # type: ignore

            scanner = PromptInjection()
            _, is_valid, _ = scanner.scan(text)
            if not is_valid:
                return {"safe": False, "reason": "llm_guard_injection"}
        except Exception:
            pass

        # 2) 정규표현식 fallback
        for pat in INJECTION_PATTERNS:
            if re.search(pat, text, re.IGNORECASE):
                return {"safe": False, "reason": f"injection_pattern:{pat}"}

        return {"safe": True, "reason": "ok"}

    @staticmethod
    def detect_pii_columns(df: Any) -> list[str]:
        """업로드 파일 PII 컬럼 자동 감지 (이메일/주민/전화/카드).

        ada.security.guardrails.PIIAnonymizer.detect_pii_columns 와 동일 로직 위임.
        """
        from ada.security.guardrails import PIIAnonymizer

        return PIIAnonymizer().detect_pii_columns(df)

    # ------------------------------------------------------------------
    @staticmethod
    def anonymize_for_llm(df: Any, text: str) -> tuple[Any, str, dict[str, str]]:
        """업로드 데이터프레임 + 텍스트 → 마스킹된 사본 + 매핑."""
        from ada.security.guardrails import PIIAnonymizer

        return PIIAnonymizer().anonymize(df, text)

    @staticmethod
    def reattach_for_user(llm_response: str, mapping: dict[str, str]) -> str:
        """LLM 응답을 사용자에게 노출하기 전 *** 로 최종 마스킹."""
        from ada.security.guardrails import PIIAnonymizer

        return PIIAnonymizer().reattach(llm_response, mapping)

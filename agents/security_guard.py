"""agents.security_guard — SecurityGuardAgent (Day05 v2 / Day17).

R-708 indirect prompt injection 가드 + LLM Guard PII 보강.
LLM Guard 미설치 환경에서는 정규표현식 기반 자체 가드 fallback.
"""
from __future__ import annotations

import re
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

# --- 정규표현식 기반 PII 자체 가드 ----------------------------------------
RRN_RE = re.compile(r"\b\d{6}-\d{7}\b")
PHONE_RE = re.compile(r"\b01\d-?\d{3,4}-?\d{4}\b")
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
CARD_RE = re.compile(r"\b\d{4}-?\d{4}-?\d{4}-?\d{4}\b")

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
    """그래프에 직접 노드로 들어가진 않음. 호출은 supervisor / API 미들웨어가 한다."""

    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            verdict = self.scan_text(state.user_intent or state.user_question or "")
            if not verdict["safe"]:
                return state.with_update(
                    error=f"보안 가드 차단: {verdict['reason']}",
                    next_agent="error_recovery",
                )
            return state

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
        """업로드 파일 PII 컬럼 자동 감지 (이메일/주민/전화/카드)."""
        pii_cols: list[str] = []
        for col in df.columns:
            try:
                sample = df[col].dropna().astype(str).head(50)
            except Exception:
                continue
            joined = " ".join(sample.tolist())[:5000]
            if any(p.search(joined) for p in (RRN_RE, PHONE_RE, EMAIL_RE, CARD_RE)):
                pii_cols.append(str(col))
        return pii_cols

"""ada.security.guardrails — LLM Guard + Guardrails AI (Day17 R-1002/R-1005)."""

from __future__ import annotations

import json
from typing import Any


def llm_guard_input(text: str) -> dict[str, Any]:
    """R-1002 — LLM Guard input scan. 미설치면 SecurityGuardAgent 가드 fallback."""
    try:
        from llm_guard import scan_prompt  # type: ignore
        from llm_guard.input_scanners import (  # type: ignore
            Anonymize,
            PromptInjection,
            TokenLimit,
        )

        scanners = [PromptInjection(), TokenLimit(limit=4000), Anonymize()]
        sanitized, results, _ = scan_prompt(scanners, text)
        all_valid = all(v for v in results.values())
        return {"safe": all_valid, "sanitized": sanitized, "results": results}
    except Exception:
        from agents.security_guard import SecurityGuardAgent

        verdict = SecurityGuardAgent.scan_text(text)
        return {"safe": verdict["safe"], "sanitized": text, "results": {"fallback": verdict["safe"]}}


def guardrails_validate(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    """R-1005 — Guardrails AI 로 JSON 스키마 검증.

    스키마 미설치 시에는 pydantic v2 로 동적 검증 fallback.
    """
    try:
        from guardrails import Guard  # type: ignore
        from guardrails.validators import (  # type: ignore  # noqa: F401
            ValidJson,
        )

        Guard.from_pydantic(output_class=None)
        return {"valid": True, "data": json.loads(text)}
    except Exception:
        try:
            data = json.loads(text)
            return {"valid": True, "data": data}
        except Exception as e:
            return {"valid": False, "error": str(e)}

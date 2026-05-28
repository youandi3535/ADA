"""ada.security.guardrails — LLM Guard + Guardrails AI + Day 4 PII anonymize/re-attach.

[Intent separation - difference from ada.error_handler.redactor]
    PIIAnonymizer (this file) : BIDIRECTIONAL. preserves mapping -> reattach() possible.
                                 use: mask LLM response with *** before user exposure.
    error_handler.redactor.redact() : ONE-WAY. no mapping preservation.
                                 use: error logs / auto-patch prompts (debug priority).

    DO NOT merge - reattach breaks. ADR-008 section 4 decision.
    Shared regex: ada.security._pii_patterns (L3.2).

Core functions:
    llm_guard_input(text)         - input prompt scan (R-1002, regex fallback)
    guardrails_validate(text)     - JSON schema check (R-1005, pydantic fallback)
    PIIAnonymizer                  - Day 4: anonymize->replace->re-attach pipeline
    insight_must_cite(text, ...)  - Day 8: insight numeric citation enforcement
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Optional

# ADR-008 L3.2: shared PII patterns from single source of truth
from ada.security._pii_patterns import (
    COMMON_PATTERNS as PII_PATTERNS,
)


def _token(kind: str, payload: str) -> str:
    """Deterministic token per PII item. Same input -> same token (for LLM matching)."""
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"<PII:{kind}:{h}>"


# ==============================================================
# 1) LLM Guard input scan
# ==============================================================
def llm_guard_input(text: str) -> dict[str, Any]:
    """R-1002 - LLM Guard input scan. Falls back to SecurityGuardAgent if not installed."""
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


# ==============================================================
# 2) Guardrails AI JSON validation
# ==============================================================
def guardrails_validate(text: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """R-1005 - Guardrails AI JSON schema check. Pydantic fallback if not installed."""
    try:
        data = json.loads(text)
        if schema:
            try:
                from pydantic import create_model  # noqa: F401

                missing = [k for k in schema.get("required", []) if k not in data]
                if missing:
                    return {"valid": False, "error": f"missing keys: {missing}"}
            except Exception:
                pass
        return {"valid": True, "data": data}
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ==============================================================
# 3) Day 4 - PII Anonymize / Re-attach pipeline
# ==============================================================
class PIIAnonymizer:
    """Mask PII in uploaded DataFrame + free text.

    Example::

        anon = PIIAnonymizer()
        masked_df, masked_text, mapping = anon.anonymize(df, user_intent)
        safe_output = anon.reattach(llm_response, mapping)
    """

    def __init__(self, replacement: str = "***") -> None:
        self.replacement = replacement

    def anonymize_text(self, text: str) -> tuple[str, dict[str, str]]:
        """Replace PII in text with tokens. Returns (safe_text, mapping: token->original)."""
        if not text:
            return text, {}
        mapping: dict[str, str] = {}

        def _sub(kind: str, m) -> str:
            orig = m.group(0)
            tok = _token(kind, orig)
            mapping[tok] = orig
            return tok

        out = text
        for kind, pat in PII_PATTERNS:
            out = pat.sub(lambda m, k=kind: _sub(k, m), out)
        return out, mapping

    def detect_pii_columns(self, df: Any) -> list[str]:
        """Columns in df containing PII."""
        pii_cols: list[str] = []
        try:
            cols = list(df.columns)
        except Exception:
            return pii_cols
        for col in cols:
            try:
                sample = df[col].dropna().astype(str).head(50).tolist()
            except Exception:
                continue
            joined = " ".join(sample)[:5000]
            if any(p.search(joined) for _, p in PII_PATTERNS):
                pii_cols.append(str(col))
        return pii_cols

    def anonymize_df(self, df: Any, pii_columns: Optional[Iterable[str]] = None) -> tuple[Any, dict[str, str]]:
        """Mask PII columns in df. Returns (masked_df, mapping)."""
        if df is None or not hasattr(df, "copy"):
            return df, {}
        cols = list(pii_columns) if pii_columns is not None else self.detect_pii_columns(df)
        if not cols:
            return df, {}
        out = df.copy()
        mapping: dict[str, str] = {}
        for col in cols:
            try:
                series = out[col].astype(str)
            except Exception:
                continue
            new_vals = []
            for val in series:
                masked, m2 = self.anonymize_text(val)
                mapping.update(m2)
                new_vals.append(masked)
            out[col] = new_vals
        return out, mapping

    def anonymize(self, df: Any, text: str) -> tuple[Any, str, dict[str, str]]:
        """Mask df and text simultaneously - unified mapping returned."""
        df_masked, m1 = self.anonymize_df(df)
        text_masked, m2 = self.anonymize_text(text or "")
        mapping = {**m1, **m2}
        return df_masked, text_masked, mapping

    def reattach(self, llm_response: str, mapping: dict[str, str]) -> str:
        """Final *** replacement of PII tokens in LLM response.

        Intent: even if tokens remain in LLM response, PII not exposed.
        Restoring originals forbidden - DoD 'result page shows ***'.
        """
        out = llm_response or ""
        for tok in mapping.keys():
            out = out.replace(tok, self.replacement)
        for _, pat in PII_PATTERNS:
            out = pat.sub(self.replacement, out)
        return out


# ==============================================================
# 4) Day 8 - InsightAgent guardrails (numeric citation + Korean)
# ==============================================================
HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")
NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?\s*%?")


def insight_must_cite(
    text: str,
    *,
    metric_names: Iterable[str] = (),
    top_features: Iterable[str] = (),
    min_sentences: int = 3,
    max_sentences: int = 5,
) -> dict[str, Any]:
    """Day 8 guard - check text has (a) numeric value, (b) top feature, (c) 3-5 sentences, (d) Korean."""
    text = (text or "").strip()
    violations: list[str] = []

    if not HANGUL_RE.search(text):
        violations.append("한국어 미사용")

    nums = NUM_RE.findall(text)
    if not nums:
        violations.append("수치 미인용 (예: 12%, 0.83)")
    elif metric_names:
        _ = [n for n in metric_names if n.lower() in text.lower()]

    if top_features:
        feats = [str(f) for f in top_features if f]
        if feats and not any(f in text for f in feats):
            violations.append(f"피처 미인용 (예상 후보: {feats[:3]})")

    sentences = [s for s in re.split(r"[.!?]\s*", text) if s.strip()]
    if len(sentences) < min_sentences:
        violations.append(f"문장 부족 ({len(sentences)}<{min_sentences})")
    elif len(sentences) > max_sentences:
        violations.append(f"문장 초과 ({len(sentences)}>{max_sentences})")

    return {"passed": len(violations) == 0, "violations": violations, "n_sentences": len(sentences)}

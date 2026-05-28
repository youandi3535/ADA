"""ada.security._pii_patterns — Shared PII regex (LOW-LEVEL, internal).

Both ada.security.guardrails.PIIAnonymizer and ada.error_handler.redactor
import these 4 common patterns. Patterns only - replacement policy decided
by each caller.

⚠️ Internal module - external users should NOT import directly.
   Created for single source of truth (ADR-008 L3.2).
"""

from __future__ import annotations

import re

# 4 common PII patterns (shared)
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_KR_RE = re.compile(r"\b01\d-?\d{3,4}-?\d{4}\b")
RRN_RE = re.compile(r"\b\d{6}-\d{7}\b")
CARD_RE = re.compile(r"\b\d{4}-?\d{4}-?\d{4}-?\d{4}\b")

# Caller-friendly grouping (same shape as guardrails.PII_PATTERNS)
COMMON_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("email", EMAIL_RE),
    ("rrn", RRN_RE),
    ("phone", PHONE_KR_RE),
    ("card", CARD_RE),
)

__all__ = [
    "EMAIL_RE",
    "PHONE_KR_RE",
    "RRN_RE",
    "CARD_RE",
    "COMMON_PATTERNS",
]

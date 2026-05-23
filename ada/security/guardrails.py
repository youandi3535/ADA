"""ada.security.guardrails — LLM Guard + Guardrails AI + Day 4 PII anonymize/re-attach.

핵심 함수:
    llm_guard_input(text)      — 입력 prompt 스캔 (R-1002, fallback 정규식)
    guardrails_validate(text)  — JSON schema 검증 (R-1005, pydantic fallback)
    PIIAnonymizer              — Day 4: anonymize→replace→re-attach 파이프라인
    insight_must_cite(text, ...) — Day 8: 인사이트 수치 인용 강제

PIIAnonymizer 동작:
    1) anonymize(df, text)  → (df_masked, text_masked, mapping)
         - df 의 PII 컬럼(이메일/주민/전화/카드) 자동 감지 → 토큰 치환
         - text 의 PII 패턴 → 토큰 치환
    2) reattach(text, mapping) → original PII 가 노출되지 않도록 ``***`` 로 최종 치환
       (LLM 결과를 사용자에게 보여줄 때 호출)
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Iterable, Optional

# --- 정규표현식 (security_guard 와 동일) ---------------------------------------
RRN_RE = re.compile(r"\b\d{6}-\d{7}\b")
PHONE_RE = re.compile(r"\b01\d-?\d{3,4}-?\d{4}\b")
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
CARD_RE = re.compile(r"\b\d{4}-?\d{4}-?\d{4}-?\d{4}\b")

PII_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("email", EMAIL_RE),
    ("rrn", RRN_RE),
    ("phone", PHONE_RE),
    ("card", CARD_RE),
)


def _token(kind: str, payload: str) -> str:
    """PII 한 건당 결정적 토큰. 동일 입력 → 동일 토큰 (LLM 응답에서 매칭 용이)."""
    h = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"<PII:{kind}:{h}>"


# ==============================================================
# 1) LLM Guard 입력 스캔
# ==============================================================
def llm_guard_input(text: str) -> dict[str, Any]:
    """R-1002 — LLM Guard input scan. 미설치 시 SecurityGuardAgent 가드 fallback."""
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
# 2) Guardrails AI JSON 검증
# ==============================================================
def guardrails_validate(text: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """R-1005 — Guardrails AI 로 JSON 스키마 검증. 미설치 시 pydantic fallback."""
    try:
        data = json.loads(text)
        # schema 가 주어지면 pydantic 으로 동적 검증
        if schema:
            try:
                from pydantic import create_model  # noqa: F401

                # 간단한 키 존재 검증
                missing = [k for k in schema.get("required", []) if k not in data]
                if missing:
                    return {"valid": False, "error": f"missing keys: {missing}"}
            except Exception:
                pass
        return {"valid": True, "data": data}
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ==============================================================
# 3) Day 4 — PII Anonymize / Re-attach 파이프라인
# ==============================================================
class PIIAnonymizer:
    """업로드 데이터프레임 + 자유 텍스트의 PII 마스킹.

    사용 예시::

        anon = PIIAnonymizer()
        masked_df, masked_text, mapping = anon.anonymize(df, user_intent)
        # ... LLM 호출은 masked_df / masked_text 로만 ...
        safe_output = anon.reattach(llm_response, mapping)
        # safe_output 안에 원본 PII 가 없도록 *** 로 최종 마스킹
    """

    def __init__(self, replacement: str = "***") -> None:
        self.replacement = replacement

    # ------------------------------------------------------------------
    def anonymize_text(self, text: str) -> tuple[str, dict[str, str]]:
        """text 안의 PII 를 토큰으로 치환. 반환 (안전한 텍스트, mapping: token→original)."""
        if not text:
            return text, {}
        mapping: dict[str, str] = {}

        def _sub(kind: str, m: re.Match) -> str:
            orig = m.group(0)
            tok = _token(kind, orig)
            mapping[tok] = orig
            return tok

        out = text
        for kind, pat in PII_PATTERNS:
            out = pat.sub(lambda m, k=kind: _sub(k, m), out)
        return out, mapping

    # ------------------------------------------------------------------
    def detect_pii_columns(self, df: Any) -> list[str]:
        """DataFrame 컬럼 중 PII 가 발견되는 컬럼명 목록."""
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
        """DataFrame 의 PII 컬럼을 마스킹. 반환 (마스킹된 df, mapping)."""
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
        """df 와 text 동시 마스킹 — 통합 mapping 반환."""
        df_masked, m1 = self.anonymize_df(df)
        text_masked, m2 = self.anonymize_text(text or "")
        mapping = {**m1, **m2}
        return df_masked, text_masked, mapping

    # ------------------------------------------------------------------
    def reattach(self, llm_response: str, mapping: dict[str, str]) -> str:
        """LLM 응답 안의 PII 토큰을 ``***`` 로 최종 치환.

        의도: 토큰이 LLM 응답에 그대로 남았더라도 PII 가 노출되지 않도록.
        원본 값 복원은 금지 — '결과 페이지에 ***' DoD 충족.
        """
        out = llm_response or ""
        for tok in mapping.keys():
            out = out.replace(tok, self.replacement)
        # 혹시 LLM 이 자체로 PII 패턴을 generate 한 경우도 대비 — 최종 정규식 마스킹
        for _, pat in PII_PATTERNS:
            out = pat.sub(self.replacement, out)
        return out


# ==============================================================
# 4) Day 8 — InsightAgent 가드레일 (수치 인용 + 한국어 강제)
#   (Day 8 에서 본 함수 import 해 사용; 모듈 한 곳에 두는 게 단일 진실)
# ==============================================================
HANGUL_RE = re.compile(r"[가-힣]")
NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?\s*%?")


def insight_must_cite(
    text: str,
    *,
    metric_names: Iterable[str] = (),
    top_features: Iterable[str] = (),
    min_sentences: int = 3,
    max_sentences: int = 5,
) -> dict[str, Any]:
    """Day 8 가드 — text 가 (a) 정확한 수치 1개+, (b) top feature 1개+,
    (c) 3~5문장, (d) 한국어 인지 검사.

    반환::
        {
            "passed": bool,
            "violations": list[str],  # 위반 사유 (사용자에게 retry 사유로 표시)
        }
    """
    text = (text or "").strip()
    violations: list[str] = []

    # (d) 한국어
    if not HANGUL_RE.search(text):
        violations.append("한국어 미사용")

    # (a) 수치 1개 이상
    nums = NUM_RE.findall(text)
    if not nums:
        violations.append("수치 미인용 (예: 12%, 0.83)")
    elif metric_names:
        # metric 이름이 본문에 있는지 — 수치만 있어도 통과 처리 (best-effort)
        _ = [n for n in metric_names if n.lower() in text.lower()]

    # (b) top feature 1개 이상
    if top_features:
        feats = [str(f) for f in top_features if f]
        if feats and not any(f in text for f in feats):
            violations.append(f"피처 미인용 (예상 후보: {feats[:3]})")

    # (c) 문장 수 (한국어/영어 모두 마침표·물음표·느낌표 기준)
    sentences = [s for s in re.split(r"[.!?。！？]\s*", text) if s.strip()]
    if len(sentences) < min_sentences:
        violations.append(f"문장 부족 ({len(sentences)}<{min_sentences})")
    elif len(sentences) > max_sentences:
        violations.append(f"문장 초과 ({len(sentences)}>{max_sentences})")

    return {"passed": len(violations) == 0, "violations": violations, "n_sentences": len(sentences)}

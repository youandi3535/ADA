"""ada.error_handler.redactor — PII / secret 마스킹 (ADR-006 Phase 2-A).

R-103 (PII 로그 출력 금지) 완전 준수의 핵심.
모든 에러 메시지·스택 트레이스가 다음 단계로 넘어가기 전 통과:

    FailureLog INSERT 전        ← raw 저장 금지
    fingerprint() 입력 전        ← 같은 PII 패턴은 같은 hash
    Ollama 프롬프트 생성 전      ← 로컬 LLM 도 raw PII 보면 안 됨
    Claude CLI 프롬프트 전       ← 외부 API 로 PII 유출 차단
    ErrorKB.error_signature 전   ← KB 영구 저장에 PII 금지

원본은 별도 암호화 컬럼 (failure_logs.raw_error_encrypted, Phase 2-F 마이그)
에 AES-GCM 으로 저장 → KMS 키로 분리 → 디버깅 시에만 복호화.

본 모듈은 외부 의존성 0 (순수 stdlib re).

설계 원칙:
    1. False positive 비용 < False negative 비용
       → 의심스러우면 마스킹. 에러 메시지 디버깅성보다 안전이 우선.
    2. 패턴 순서 = specificity 순
       → 긴 패턴 (RRN, 카드) 먼저, 짧은 패턴 (IP, 숫자) 나중.
    3. 모든 치환은 ``<TAG>`` 형식으로 통일
       → fingerprint 안정성. 추후 토큰 길이 변경에도 hash 영향 0.
    4. ``redact()`` 는 무엇이 마스킹됐는지 type 리스트도 반환
       → audit log 에 "이 에러는 EMAIL/CARD 포함됐었음" 기록.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# =============================================================================
# 정규식 패턴
# =============================================================================

# (compiled_pattern, replacement, type_tag)
# 순서가 매우 중요 — 광역(URL) → specific(카드/토큰) → 일반(이메일/IP).
# 후순위 패턴이 선순위 결과의 잔재를 매칭하지 않도록 신중히 배치.
REDACTION_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # ── 0. URI 시크릿 (다른 패턴들이 부분 매칭하기 전 최우선) ───────────
    # postgresql://user:pass@host:port/db (이메일 패턴이 user:pass@host 를 잡지 않게)
    (
        re.compile(
            r"\b(postgresql|postgres|mysql|mongodb|redis)://[^:\s/]+:[^@\s]+@",
            re.IGNORECASE,
        ),
        r"\1://<USER>:<PASS>@",
        "DB_URL",
    ),
    # ── 1. 결제 / 금융 ───────────────────────────────────────────────────
    # 신용카드 (4-4-4-4, 공백/하이픈 허용)
    (
        re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
        "<CARD>",
        "CARD",
    ),
    # AMEX (15자리, 4-6-5)
    (
        re.compile(r"\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b"),
        "<CARD>",
        "CARD",
    ),
    # 한국 주민번호
    (
        re.compile(r"\b\d{6}-?[1-4]\d{6}\b"),
        "<RRN>",
        "RRN",
    ),
    # 여권번호 (한국 M/S + 8자리)
    (
        re.compile(r"\b[MS]\d{8}\b"),
        "<PASSPORT>",
        "PASSPORT",
    ),
    # ── 2. 시크릿 / 토큰 ────────────────────────────────────────────────
    # JWT
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
        "<JWT>",
        "JWT",
    ),
    # Bearer 토큰
    (
        re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
        "Bearer <TOKEN>",
        "BEARER",
    ),
    # Stripe live/test (sk_live_... / sk_test_... / pk_live_... / rk_live_...)
    # body 에 _ 허용 (예: sk_live_abc123 의 두 번째 _ 까지)
    (
        re.compile(r"\b(sk|pk|rk)_(live|test)_[A-Za-z0-9_]{16,}\b"),
        "<TOKEN>",
        "TOKEN",
    ),
    # GitHub 토큰 (gho_, ghp_, ghs_, ghu_, ghr_)
    (
        re.compile(r"\b(gho|ghp|ghs|ghu|ghr)_[A-Za-z0-9]{16,}\b"),
        "<TOKEN>",
        "TOKEN",
    ),
    # OpenAI / 일반 sk-/pk- (Stripe 외)
    (
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        "<TOKEN>",
        "TOKEN",
    ),
    # Anthropic API 키
    (
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
        "<ANTHROPIC_KEY>",
        "TOKEN",
    ),
    # AWS Access Key ID
    (
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "<AWS_KEY>",
        "AWS_KEY",
    ),
    # AWS Secret (assignment 형태만)
    (
        re.compile(
            r"(aws_secret_access_key|secret_access_key)\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?",
            re.IGNORECASE,
        ),
        r"\1=<AWS_SECRET>",
        "AWS_SECRET",
    ),
    # GCP 서비스 계정 (JSON 안의 private_key)
    (
        re.compile(r'"private_key"\s*:\s*"[^"]+"'),
        '"private_key": "<GCP_PRIVATE_KEY>"',
        "GCP_KEY",
    ),
    # PEM 개인키 블록
    (
        re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----[\s\S]+?-----END (?:RSA |EC |DSA )?PRIVATE KEY-----"),
        "<PRIVATE_KEY_PEM>",
        "PRIVATE_KEY",
    ),
    # password=... / api_key=... / token=... 패턴
    # 핵심: `\b` 대신 negative lookbehind 로 `DB_PASSWORD` 의 PASSWORD 부분도 잡음
    # (`_` 가 regex 의 \b 에서는 word char 라 boundary 가 안 생김).
    (
        re.compile(
            r"(?<![A-Za-z0-9])(password|passwd|pwd|api_key|apikey|api_secret|access_token|refresh_token|secret)"
            r"\s*[=:]\s*['\"]?[^\s'\"&]{6,}['\"]?",
            re.IGNORECASE,
        ),
        r"\1=<SECRET>",
        "SECRET",
    ),
    # ── 3. 연락처 ───────────────────────────────────────────────────────
    # 이메일
    (
        re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
        "<EMAIL>",
        "EMAIL",
    ),
    # 한국 휴대전화
    (
        re.compile(r"\b(?:\+?82[-\s.]?|0)1[016789][-\s.]?\d{3,4}[-\s.]?\d{4}\b"),
        "<PHONE>",
        "PHONE",
    ),
    # 한국 지역번호 일반전화
    (
        re.compile(r"\b(?:\+?82[-\s.]?|0)(?:2|3[1-3]|4[1-4]|5[1-5]|6[1-4]|70)[-\s.]?\d{3,4}[-\s.]?\d{4}\b"),
        "<PHONE>",
        "PHONE",
    ),
    # ── 4. 네트워크 — MAC 먼저 (IPv6 보다 더 specific) ──────────────────
    # MAC 주소 (00:1A:2B:3C:4D:5E 또는 00-1A-...)
    (
        re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b"),
        "<MAC>",
        "MAC",
    ),
    # IPv4 — 일부 마스킹 (subnet 만 유지, 디버깅성)
    # fingerprint 도 partial form 을 정규화하므로 매칭 안정성 OK.
    (
        re.compile(r"\b(\d{1,3})\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        r"\1.x.x.x",
        "IP",
    ),
    # IPv6 (MAC 처리 후)
    (
        re.compile(r"\b([0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}\b"),
        "<IPv6>",
        "IP",
    ),
    # ── 5. 파일 경로의 사용자명 ─────────────────────────────────────────
    # Windows: C:\Users\한정현\... → C:\Users\<USER>\...
    (
        re.compile(r"([A-Z]):[\\/]Users[\\/]([^\\/\s]+)([\\/])"),
        r"\1:\\Users\\<USER>\3",
        "USER_PATH",
    ),
    # Linux: /home/username/...
    (
        re.compile(r"/home/([^/\s]+)/"),
        "/home/<USER>/",
        "USER_PATH",
    ),
    # macOS: /Users/username/...
    (
        re.compile(r"/Users/([^/\s]+)/"),
        "/Users/<USER>/",
        "USER_PATH",
    ),
]


# =============================================================================
# Public API
# =============================================================================


def redact(text: str | None) -> tuple[str, list[str]]:
    """텍스트에서 PII/secret 제거.

    Args:
        text: 마스킹할 문자열. None 이면 빈 문자열 처리.

    Returns:
        (redacted_text, list_of_type_tags_found):
            예: ("user <EMAIL> from <IP>", ["EMAIL", "IP"])
    """
    if not text:
        return "", []

    found: list[str] = []
    redacted = text

    for pattern, replacement, type_tag in REDACTION_PATTERNS:
        new_redacted, n = pattern.subn(replacement, redacted)
        if n > 0:
            # 중복 type 은 set 으로 1번만
            if type_tag not in found:
                found.append(type_tag)
            redacted = new_redacted

    return redacted, found


def redact_dict(data: Any, _depth: int = 0) -> tuple[Any, list[str]]:
    """dict/list 재귀적 마스킹.

    Args:
        data: dict, list, tuple, str 또는 원시 타입.

    Returns:
        (redacted_data_same_type, all_type_tags_found)
    """
    if _depth > 10:  # 무한 재귀 방어
        return data, []

    all_found: list[str] = []

    if isinstance(data, str):
        return redact(data)

    if isinstance(data, dict):
        result: dict = {}
        for k, v in data.items():
            new_v, found = redact_dict(v, _depth + 1)
            for tag in found:
                if tag not in all_found:
                    all_found.append(tag)
            result[k] = new_v
        return result, all_found

    if isinstance(data, (list, tuple)):
        results = []
        for item in data:
            new_item, found = redact_dict(item, _depth + 1)
            for tag in found:
                if tag not in all_found:
                    all_found.append(tag)
            results.append(new_item)
        return (type(data)(results), all_found)

    return data, []


def has_pii(text: str | None) -> bool:
    """빠른 PII 존재 여부 확인 (마스킹 안 함)."""
    if not text:
        return False
    for pattern, _, _ in REDACTION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def redact_keys(keys: Iterable[str]) -> set[str]:
    """주어진 key 이름들 중 시크릿스러운 것 식별.

    config dict 검사 등에 사용:
        if k in redact_keys(config.keys()):
            value = "<REDACTED>"
    """
    secret_indicators = (
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "api_secret",
        "access_key",
        "private_key",
        "auth",
        "credential",
        "key",
    )
    return {k for k in keys if any(ind in k.lower() for ind in secret_indicators)}


__all__ = ["redact", "redact_dict", "has_pii", "redact_keys", "REDACTION_PATTERNS"]

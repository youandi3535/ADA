"""ada.error_handler.classifier — 에러 유형 5종 분류 (ADR-006 Phase 2-B).

분류는 처리 전략을 결정한다:

    TRANSIENT   네트워크/타임아웃/일시적 장애 → LLM 호출 없이 지수 백오프 재시도
    CODE_BUG    Attribute/Type/Name/Import/Syntax → LLM 패치 생성 (Tier 2/3)
    CONFIG      환경변수/시크릿 누락/Vault 오류 → LLM 비용 0, 사람 안내만
    DATA        입력 데이터 스키마/품질 문제 → 사용자에게 데이터 수정 요청
    USER_INPUT  사용자 요청 파라미터 오류 (4xx) → 사용자 친절 안내
    UNKNOWN     매칭 안 됨 → LLM 패치 생성 (보수적 폴백)

핵심 효과:
    - TRANSIENT 의 60% 가 LLM 호출 안 함 → 비용 절감
    - CONFIG 의 100% 가 LLM skip → 사람 개입 빠름 (LLM 이 어차피 못 고침)
    - DATA / USER_INPUT 은 즉시 사용자 안내 → UX 향상

외부 의존성 0 (순수 stdlib re + enum).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import NamedTuple


class ErrorClass(str, Enum):
    """5종 에러 유형 + UNKNOWN."""

    TRANSIENT = "transient"
    CODE_BUG = "code_bug"
    CONFIG = "config"
    DATA = "data"
    USER_INPUT = "user_input"
    UNKNOWN = "unknown"


class HandlingStrategy(str, Enum):
    """ErrorClass → 처리 전략."""

    RETRY_BACKOFF = "retry_with_backoff"  # 1s, 2s, 4s 지수 백오프
    LLM_PATCH = "llm_patch"  # Tier 2/3 폴백 진입
    HUMAN_ONLY = "human_only"  # LLM skip, 사람 개입
    USER_MESSAGE = "user_message"  # 사용자에게 안내


# ErrorClass → HandlingStrategy 매트릭스 (immutable)
HANDLING_STRATEGY: dict[ErrorClass, HandlingStrategy] = {
    ErrorClass.TRANSIENT: HandlingStrategy.RETRY_BACKOFF,
    ErrorClass.CODE_BUG: HandlingStrategy.LLM_PATCH,
    ErrorClass.CONFIG: HandlingStrategy.HUMAN_ONLY,
    ErrorClass.DATA: HandlingStrategy.USER_MESSAGE,
    ErrorClass.USER_INPUT: HandlingStrategy.USER_MESSAGE,
    ErrorClass.UNKNOWN: HandlingStrategy.LLM_PATCH,  # 보수적 — 모르면 LLM
}


# =============================================================================
# 분류 규칙 — 정규식 기반
# =============================================================================

# 우선순위 매트릭스 (높은 순):
#   1. CONFIG  ("환경 설정" 류는 LLM 으로 못 고침, 명확히 분리)
#   2. TRANSIENT  ("재시도하면 풀림" 류)
#   3. DATA  ("데이터 모양/스키마" 류)
#   4. USER_INPUT  ("4xx 입력 오류" 류)
#   5. CODE_BUG  ("진짜 코드 버그" 류 - 가장 일반적, 마지막에)
#   → 어디에도 안 걸리면 UNKNOWN


class _Rule(NamedTuple):
    pattern: re.Pattern
    cls: ErrorClass
    reason: str


CLASSIFIERS: list[_Rule] = [
    # ── CONFIG (1순위: LLM 비용 0) ────────────────────────────────────────
    _Rule(
        re.compile(
            r"(VaultError|VaultUnavailable|hvac\.exceptions|"
            r"KeyError.*[A-Z_]{3,}.*(?:KEY|TOKEN|SECRET|PASSWORD|URL)|"
            r"environment variable.*not set|"
            r"Settings.*(?:not.*set|missing|required)|"
            r"os\.environ\[.*\].*KeyError|"
            r"ANTHROPIC_API_KEY|OPENAI_API_KEY|AWS_.*_KEY)",
            re.IGNORECASE,
        ),
        ErrorClass.CONFIG,
        "환경변수 / Vault / 시크릿 누락",
    ),
    # ── TRANSIENT (2순위: 단순 재시도) ────────────────────────────────────
    _Rule(
        re.compile(
            r"(ConnectionError|ConnectionResetError|ConnectionAbortedError|ConnectionRefusedError|"
            r"TimeoutError|ReadTimeout|WriteTimeout|"
            r"socket\.timeout|asyncio\.TimeoutError|"
            r"TemporaryFailure|TempFailure|"
            r"http.*5\d\d|"  # 5xx HTTP
            r"503 Service Unavailable|502 Bad Gateway|504 Gateway Timeout|"
            r"max retries exceeded|"
            r"network is unreachable|"
            r"Name or service not known|DNS lookup failed|"
            r"Broken pipe|Connection aborted|Connection reset by peer)",
            re.IGNORECASE,
        ),
        ErrorClass.TRANSIENT,
        "네트워크 / 타임아웃 / 일시적 장애",
    ),
    # ── DATA (3순위: 입력 데이터 문제) ────────────────────────────────────
    _Rule(
        re.compile(
            r"(pandas\.errors|EmptyDataError|ParserError|"
            r"MissingColumn|ColumnNotFound|KeyError.*column|"
            r"SchemaError|ValidationError.*schema|"
            r"DType.*mismatch|cannot convert.*to.*dtype|"
            r"All NaN|empty DataFrame|"
            r"InvalidDataFrameError|"
            r"FileNotFoundError.*\.(?:csv|parquet|xlsx|json|txt))",
            re.IGNORECASE,
        ),
        ErrorClass.DATA,
        "입력 데이터 스키마 / 품질 / 파일 누락",
    ),
    # ── USER_INPUT (4순위: 4xx 사용자 오류) ───────────────────────────────
    _Rule(
        re.compile(
            r"(pydantic\.ValidationError|"
            r"HTTPException.*4\d\d|"
            r"400 Bad Request|401 Unauthorized|403 Forbidden|404 Not Found|"
            r"422 Unprocessable Entity|429 Too Many Requests|"
            r"InvalidArgument|InvalidParameter|"
            r"AssertionError.*user|user_choice.*invalid|"
            r"gate_response.*invalid)",
            re.IGNORECASE,
        ),
        ErrorClass.USER_INPUT,
        "사용자 입력 / 4xx 클라이언트 오류",
    ),
    # ── CODE_BUG (5순위: 실제 코드 버그) ──────────────────────────────────
    _Rule(
        re.compile(
            r"(AttributeError|TypeError|NameError|"
            r"ImportError|ModuleNotFoundError|"
            r"SyntaxError|IndentationError|"
            r"NotImplementedError|"
            r"ZeroDivisionError|RecursionError|"
            r"UnboundLocalError|"
            r"object has no attribute|"
            r"takes \d+ positional argument|"
            r"unexpected keyword argument|"
            r"is not subscriptable|"
            r"is not callable)",
            re.IGNORECASE,
        ),
        ErrorClass.CODE_BUG,
        "코드 버그 (Attribute/Type/Name/Import/Syntax/...)",
    ),
]


# =============================================================================
# Public API
# =============================================================================


def classify(error_message: str | None, traceback_text: str | None = None) -> ErrorClass:
    """에러 메시지·트레이스에서 분류.

    Args:
        error_message: 1줄 에러 (예: "ConnectionError: timeout")
        traceback_text: 풀 스택 트레이스. 없어도 OK.

    Returns:
        ErrorClass.{TRANSIENT|CODE_BUG|CONFIG|DATA|USER_INPUT|UNKNOWN}
    """
    if not error_message and not traceback_text:
        return ErrorClass.UNKNOWN

    full = f"{error_message or ''}\n{traceback_text or ''}"
    for rule in CLASSIFIERS:
        if rule.pattern.search(full):
            return rule.cls
    return ErrorClass.UNKNOWN


def classify_with_reason(
    error_message: str | None,
    traceback_text: str | None = None,
) -> tuple[ErrorClass, str]:
    """classify() + 사유 텍스트.

    Returns:
        (ErrorClass, reason_string)
    """
    if not error_message and not traceback_text:
        return ErrorClass.UNKNOWN, "입력 없음"

    full = f"{error_message or ''}\n{traceback_text or ''}"
    for rule in CLASSIFIERS:
        if rule.pattern.search(full):
            return rule.cls, rule.reason
    return ErrorClass.UNKNOWN, "매칭 패턴 없음 - 보수적으로 LLM 폴백"


def get_strategy(cls: ErrorClass) -> HandlingStrategy:
    """분류 → 처리 전략."""
    return HANDLING_STRATEGY.get(cls, HandlingStrategy.LLM_PATCH)


def should_skip_llm(cls: ErrorClass) -> bool:
    """LLM 호출 skip 여부 (비용 절감용).

    True 반환 시 AutoErrorHandler 는 Tier 2/3 진입 안 함.
    """
    return get_strategy(cls) in (
        HandlingStrategy.RETRY_BACKOFF,
        HandlingStrategy.HUMAN_ONLY,
        HandlingStrategy.USER_MESSAGE,
    )


__all__ = [
    "ErrorClass",
    "HandlingStrategy",
    "HANDLING_STRATEGY",
    "classify",
    "classify_with_reason",
    "get_strategy",
    "should_skip_llm",
]

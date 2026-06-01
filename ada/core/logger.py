"""ada.core.logger — structlog JSON 로거.

PII 출력 금지 (R-103). 컨텍스트 자동 바인딩: job_id, agent_name.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from ada.core.config import settings


def _configure_once() -> None:
    """structlog 전역 1회 설정."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        stream=sys.stdout,
        format="%(message)s",
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _pii_redactor,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


# R-103 PII 패턴 — 모듈 로드 시 1회 컴파일 (매 로그 호출마다 재컴파일 방지)
import re as _re

_PII_EMAIL = _re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_PII_RRN = _re.compile(r"\b\d{6}-\d{7}\b")
_PII_PHONE = _re.compile(r"\b01\d-?\d{3,4}-?\d{4}\b")


def _pii_mask(s: str) -> str:
    s = _PII_EMAIL.sub("***@***", s)
    s = _PII_RRN.sub("******-*******", s)
    s = _PII_PHONE.sub("***-****-****", s)
    return s


def _pii_redactor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """R-103 — PII 자동 마스킹.

    이메일/주민번호/전화 패턴 발견 시 마스킹. 운영 PII 보호 1차 가드.
    정규식은 모듈 레벨에서 1회 컴파일된다 (성능).
    """
    for k, v in list(event_dict.items()):
        if isinstance(v, str) and len(v) < 4096:
            event_dict[k] = _pii_mask(v)
    return event_dict


_configure_once()


def get_logger(name: str | None = None) -> Any:
    """팩토리 — agent_name 등 컨텍스트는 ``logger.bind(...)`` 로 추가."""
    return structlog.get_logger(name or "ada")


def bind_context(**kwargs: Any) -> None:
    """contextvars 기반 — 비동기 태스크 내내 자동 전파."""
    structlog.contextvars.bind_contextvars(**kwargs)


def log_agent_run(
    *,
    job_id: str,
    agent_name: str,
    status: str,
    duration_ms: int | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: str | None = None,
) -> None:
    """편의 함수 — Day02 agent_runs 테이블과 1:1 매칭되는 구조 출력."""
    log = get_logger("agent_run").bind(
        job_id=job_id,
        agent_name=agent_name,
    )
    payload = {
        "status": status,
        "duration_ms": duration_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    if error:
        log.error("agent_run", **payload, error=error)
    else:
        log.info("agent_run", **payload)

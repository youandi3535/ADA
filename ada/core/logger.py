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
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _pii_redactor(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """R-103 — PII 자동 마스킹.

    이메일/주민번호 패턴 발견 시 ``***`` 치환. 운영 PII 보호 1차 가드.
    """
    import re

    EMAIL = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    RRN = re.compile(r"\b\d{6}-\d{7}\b")
    PHONE = re.compile(r"\b01\d-?\d{3,4}-?\d{4}\b")

    def _mask(s: str) -> str:
        s = EMAIL.sub("***@***", s)
        s = RRN.sub("******-*******", s)
        s = PHONE.sub("***-****-****", s)
        return s

    for k, v in list(event_dict.items()):
        if isinstance(v, str) and len(v) < 4096:
            event_dict[k] = _mask(v)
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

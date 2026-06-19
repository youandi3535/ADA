"""ada.error_handler.daemon — Day 2 AutoErrorHandler 데몬 로직.

Celery beat 가 30초마다 :func:`scan_new_failures` 를 호출. 이 함수는
auto_handled_by_kb=False AND error_kb_id IS NULL 인 FailureLog 을 모아
:class:`AutoErrorHandler` 에 넘긴다. 처리된 row 는 다음 폴링 시점에
중복 처리되지 않는다 (auto_handled_by_kb 가 True 로 갱신되거나, 패치 큐 적재).

비고:
    - 본 모듈은 sync 진입점(Celery)과 async 본문을 분리.
    - 단일 트랜잭션 안에서 1회 폴 → 결과 dict 반환.
"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import and_, or_, select

from ada.core.logger import get_logger

log = get_logger("error_handler.daemon")

# 1회 폴링당 처리 상한 (백로그 폭주 방지)
MAX_BATCH = 50


async def scan_new_failures_async(session: Any) -> dict[str, Any]:
    """auto_handled_by_kb=False 인 FailureLog 를 batch 단위로 처리.

    반환::

        {"scanned": N, "auto_kb_matched": M, "patches_queued": P, "errors": [...]}
    """
    from ada.db.models import FailureLog
    from ada.error_handler.auto_handler import AutoErrorHandler

    rows = (
        await session.scalars(
            select(FailureLog)
            .where(
                and_(
                    or_(FailureLog.auto_handled_by_kb.is_(False), FailureLog.auto_handled_by_kb.is_(None)),
                    FailureLog.error_kb_id.is_(None),
                    # ★ 이미 분류·시도(Tier 0~3)한 row 는 제외 → 같은 오류 무한 재처리 방지 (HJ 2026-06-19)
                    FailureLog.classified_as.is_(None),
                )
            )
            .order_by(FailureLog.created_at.asc())
            .limit(MAX_BATCH)
        )
    ).all()

    handler = AutoErrorHandler(session)
    result = {
        "scanned": len(rows),
        "auto_kb_matched": 0,
        "patches_queued": 0,
        "errors": [],
    }
    # auto_kb_match 는 레거시 명칭, 현 코드는 Tier 1 SelfLearningKB 매칭 시
    # "auto_self_learning_match" 를 발행한다. 두 액션 모두 KB 자동 해결로 집계.
    _KB_MATCH_ACTIONS = {"auto_kb_match", "auto_self_learning_match"}
    for row in rows:
        try:
            outcome = await handler.handle(row)
            action = outcome.get("action", "")
            if action in _KB_MATCH_ACTIONS:
                result["auto_kb_matched"] += 1
            elif action.startswith("patch"):
                result["patches_queued"] += 1
        except Exception as e:
            result["errors"].append({"failure_log_id": str(row.id), "error": str(e)})
            log.warning("daemon_handle_failed", id=str(row.id), error=str(e))
        finally:
            # ★ 안전망(HJ 2026-06-19): handle 이 분류값을 못 세웠어도(예외 등) 시도한 row 는 마킹.
            #   → 다음 폴에서 제외되어 무한 재처리가 절대 안 생기게 한다.
            if not row.classified_as:
                row.classified_as = "attempted"

    if rows:
        try:
            await session.commit()
        except Exception:
            await session.rollback()

    log.info("scanned_new_failures", **{k: v for k, v in result.items() if k != "errors"})
    return result


def scan_new_failures() -> dict[str, Any]:
    """sync 진입점 — Celery task 에서 호출."""

    async def _do() -> dict[str, Any]:
        from ada.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            return await scan_new_failures_async(s)

    return asyncio.run(_do())

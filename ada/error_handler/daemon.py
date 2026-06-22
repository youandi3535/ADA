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
# HJ 2026-06-22 — 50 → 2. 건당 ~25s(Ollama)·~200MB(임베딩·LLM 버퍼, 자식 재생성 전엔 미해제)라,
#   배치가 클수록 한 scan 의 anon 피크가 비례해 커진다(관측: 5 → 피크 ~1.7GiB). 2 로 줄여 한 scan 의
#   누적을 ~400MB 로 제한 → 피크 anon ~1.1~1.2GiB(2000M 한도의 ~60%)로 바운딩. 백로그는 여러 scan 에
#   걸쳐 점진 소진. (근본은 '오류 재발 자체'를 멈추는 것 — 그게 해결되면 이 배치값은 사실상 무의미.)
MAX_BATCH = 2


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
        # ★ HJ 2026-06-22 — handle() '전에' attempted 로 마킹·즉시 커밋한다.
        #   기존엔 배치 전체를 처리한 뒤 루프 끝에서 한 번만 커밋했는데, 건당 ~25s(Ollama)라 배치가 길면
        #   한 scan 이 수~수십 분 → 도중 중단(time_limit/워커 재시작/OOM)되면 커밋 전이라 처리분이 전부
        #   미마킹 → task_acks_late redeliver 로 같은 row 들이 무한 재처리되는 루프가 발생했다(메모리
        #   1.7GiB 인질의 근본 원인). handle 전에 durable 마킹하면 handle 이 아무리 느리거나 task 가 죽어도
        #   이 row 는 다음 폴에서 반드시 제외된다(expire_on_commit=False 라 커밋 후 row 접근 안전 — session.py).
        row.classified_as = "attempted"
        try:
            await session.commit()
        except Exception:
            await session.rollback()
        try:
            outcome = await handler.handle(row)
            action = outcome.get("action", "")
            if action in _KB_MATCH_ACTIONS:
                result["auto_kb_matched"] += 1
            elif action.startswith("patch"):
                result["patches_queued"] += 1
            # handle() 의 DB 기록(패치 큐·KB 갱신·실제 분류값 덮어쓰기) 영속화
            await session.commit()
        except Exception as e:
            await session.rollback()
            result["errors"].append({"failure_log_id": str(row.id), "error": str(e)})
            log.warning("daemon_handle_failed", id=str(row.id), error=str(e))

    log.info("scanned_new_failures", **{k: v for k, v in result.items() if k != "errors"})
    return result


def scan_new_failures() -> dict[str, Any]:
    """sync 진입점 — Celery task 에서 호출."""

    async def _do() -> dict[str, Any]:
        from ada.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            return await scan_new_failures_async(s)

    return asyncio.run(_do())

"""ada.error_handler.auto_handler — AutoErrorHandler 데몬 (Day16).

흐름:
  1. failure_logs INSERT (또는 PubSub 이벤트) 감지
  2. error_kb 에서 동일 fingerprint 매칭
  3. 매칭이 있으면 자동 처리 (auto_handled_by_kb=True)
  4. 없으면 Claude CLI 사이드카에 패치 요청 → pending_patches 큐 적재
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.breaker import get_breaker
from ada.core.logger import get_logger
from ada.db.models import ErrorKB, FailureLog, PendingPatch

log = get_logger("auto_handler")


def fingerprint(error_message: str, stack: str = "") -> dict[str, str]:
    """오류 시그니처 생성. 동일 패턴은 동일 hash."""
    # 시간/메모리주소/UUID 등은 제거
    clean = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", error_message)
    clean = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>", clean)
    clean = re.sub(r"\d+", "<N>", clean)
    h = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    return {"hash": h, "signature": clean[:500]}


class AutoErrorHandler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def handle(self, log_row: FailureLog) -> dict[str, Any]:
        fp = fingerprint(log_row.error_message or "", log_row.stack_trace or "")
        # 1) KB 매칭
        kb = await self.session.scalar(
            select(ErrorKB).where(ErrorKB.error_hash == fp["hash"])
        )
        if kb and (kb.confidence or 0.0) >= 0.7:
            log_row.auto_handled_by_kb = True
            log_row.error_kb_id = kb.id
            kb.success_count = (kb.success_count or 0) + 1
            await self.session.flush()
            return {"action": "auto_kb_match", "kb_id": str(kb.id)}

        # 2) KB 없거나 신뢰도 낮음 → Claude CLI 사이드카에 패치 요청
        try:
            from ada.error_handler.claude_cli_bridge import ClaudeCLIBridge
            bridge = ClaudeCLIBridge()
            patch = await bridge.request_patch(
                error_signature=fp["signature"],
                stack=log_row.stack_trace or "",
            )
            self.session.add(PendingPatch(
                error_kb_id=(kb.id if kb else None),
                patch_diff=patch.get("diff"),
                test_plan=patch.get("test_plan"),
                confidence=patch.get("confidence", 0.4),
                review_status="pending",
            ))
            await self.session.flush()
            return {"action": "patch_queued", "patch_chars": len(patch.get("diff") or "")}
        except Exception as e:
            log.warning("auto_handler_failed", error=str(e))
            return {"action": "noop", "error": str(e)}

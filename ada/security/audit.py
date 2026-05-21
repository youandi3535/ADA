"""ada.security.audit — security_audit_log 헬퍼 (Day17)."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.models import SecurityAuditLog


async def log_event(
    session: AsyncSession,
    *,
    event_type: str,
    actor_user_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    resource: Optional[str] = None,
    action: Optional[str] = None,
    result: str = "success",
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
) -> None:
    row = SecurityAuditLog(
        event_type=event_type,
        actor_user_id=uuid.UUID(actor_user_id) if actor_user_id else None,
        actor_role=actor_role,
        resource=resource,
        action=action,
        result=result,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details or {},
    )
    session.add(row)
    await session.flush()

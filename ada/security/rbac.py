"""ada.security.rbac — Role-based Access Control (Day17)."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import Depends, HTTPException

from ada.security.jwt import get_current_user

# 역할 권한 매트릭스
PERMISSIONS = {
    "admin":    {"*"},
    "analyst":  {"upload", "pipeline.start", "pipeline.read", "pipeline.resume"},
    "viewer":   {"pipeline.read"},
    "service":  {"*"},
}


def has_perm(role: str, perm: str) -> bool:
    allowed = PERMISSIONS.get(role, set())
    return "*" in allowed or perm in allowed


def require_perm(perm: str) -> Callable:
    async def _dep(user: dict = Depends(get_current_user)) -> dict:
        if not has_perm(user.get("role", ""), perm):
            raise HTTPException(403, detail=f"missing perm: {perm}")
        return user
    return _dep

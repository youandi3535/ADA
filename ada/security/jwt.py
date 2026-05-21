"""ada.security.jwt — JWT 발급/검증 (Day17 R-707)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from ada.core.config import settings

security = HTTPBearer(auto_error=False)


def create_access_token(*, sub: str, role: str = "analyst",
                        expires_minutes: Optional[int] = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_min,
    )
    payload = {"sub": sub, "role": role, "exp": exp,
                "iat": datetime.now(timezone.utc), "iss": "ada"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algo)


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret,
                       algorithms=[settings.jwt_algo, "RS256"])


async def get_current_user(
    request: Request,
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict[str, Any]:
    if creds is None or not creds.credentials:
        raise HTTPException(401, detail="missing bearer")
    try:
        payload = decode_token(creds.credentials)
    except JWTError as e:
        raise HTTPException(401, detail=f"invalid token: {e}")
    return {
        "user_id": payload.get("sub"),
        "role": payload.get("role", "analyst"),
    }

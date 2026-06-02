"""api.routes.auth — 로그인 / 토큰 발급 + 현재 사용자 조회 (Day17 + Day18)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.models import User
from ada.db.session import get_db
from ada.security.jwt import create_access_token, decode_token

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 셀프 가입은 기본 비활성 (운영 보안). 명시적으로 켤 때만 허용.
# 관리자 계정은 DB 시드(ada.db.seeds) 또는 별도 스크립트로 생성한다.
_ALLOW_SELF_REG = os.environ.get("ADA_ALLOW_SELF_REGISTRATION", "false").lower() in ("1", "true", "yes")


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    user = await db.scalar(select(User).where(User.email == req.email))
    if user is None or not user.password_hash:
        raise HTTPException(401, detail="invalid credentials")
    if not pwd_ctx.verify(req.password, user.password_hash):
        raise HTTPException(401, detail="invalid credentials")
    token = create_access_token(sub=str(user.id), role=user.role or "analyst")
    return LoginResponse(access_token=token, role=user.role or "analyst")


@router.post("/register", response_model=LoginResponse)
async def register(req: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    if not _ALLOW_SELF_REG:
        raise HTTPException(
            403,
            detail="self-registration disabled; set ADA_ALLOW_SELF_REGISTRATION=true or ask an admin",
        )
    existing = await db.scalar(select(User).where(User.email == req.email))
    if existing is not None:
        raise HTTPException(409, detail="email exists")
    u = User(
        id=uuid.uuid4(),
        email=req.email,
        password_hash=pwd_ctx.hash(req.password),
        role="analyst",
    )
    db.add(u)
    await db.flush()
    return LoginResponse(
        access_token=create_access_token(sub=str(u.id), role="analyst"),
        role="analyst",
    )


# ----- 현재 사용자 (Day 18 — 사이드바 표시용) -----
class MeResponse(BaseModel):
    user_id: str
    email: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime] = None


def _extract_bearer(authorization: Optional[str]) -> str:
    """`Authorization: Bearer <token>` 헤더에서 토큰 추출."""
    if not authorization:
        raise HTTPException(401, detail="missing authorization header")
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(401, detail="invalid authorization scheme")
    return parts[1]


@router.get("/me", response_model=MeResponse)
async def me(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    """JWT 토큰 → 현재 로그인 사용자 정보 반환.

    동작 원리
    ---------
    1) Authorization 헤더에서 Bearer 토큰 추출
    2) ``decode_token()`` 으로 검증 + 페이로드 파싱 (sub=user_id)
    3) User 테이블 조회 → 비활성/삭제 사용자는 401
    4) 응답 직렬화 (password_hash 등 민감정보 제외)
    """

    token = _extract_bearer(authorization)
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(401, detail="invalid or expired token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(401, detail="token missing sub claim")

    try:
        user_uuid = uuid.UUID(sub)
    except Exception:
        raise HTTPException(401, detail="invalid sub format")

    user = await db.scalar(select(User).where(User.id == user_uuid))
    if user is None or not user.is_active:
        raise HTTPException(401, detail="user not found or inactive")

    return MeResponse(
        user_id=str(user.id),
        email=user.email,
        role=user.role or "analyst",
        is_active=bool(user.is_active),
        last_login_at=user.last_login_at,
    )

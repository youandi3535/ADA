"""api.routes.auth — 로그인 / 토큰 발급 (Day17)."""

from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.models import User
from ada.db.session import get_db
from ada.security.jwt import create_access_token

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

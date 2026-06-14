"""api.routes.auth — 로그인 / 토큰 발급 + 현재 사용자 조회 (Day17 + Day18)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.db.models import OAuthAccount, User
from ada.db.session import get_db
from ada.security.audit import log_event
from ada.security.jwt import create_access_token, decode_token

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_log = get_logger("auth")

# ----- 구글 OAuth 클라이언트 (v1 소셜 로그인) ---------------------------------
# authlib 미설치/등록 실패 환경에서도 기존 /login·/me 가 죽지 않도록 import 가드.
# 등록만 import 시점에 하고, 구글 JWKS 메타데이터는 첫 호출 때 lazy 로 가져온다.
try:
    from authlib.integrations.starlette_client import OAuth, OAuthError

    _oauth: Optional["OAuth"] = OAuth()
    _oauth.register(
        name="google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
except Exception as _e:  # noqa: BLE001 — authlib 미설치 시 구글 로그인만 비활성
    _oauth = None
    OAuthError = Exception  # type: ignore[assignment,misc]
    _log.warning("google_oauth_unavailable", error=str(_e))

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


# =============================================================================
# 구글 OAuth 로그인 (v1) — STEP 5
#
# 흐름 (OIDC Authorization Code):
#   GET /auth/google           → state 발급 + 구글 동의화면으로 리다이렉트
#   GET /auth/google/callback  → code→토큰 교환 + id_token 서명검증(구글 JWKS)
#                                → user 조회/생성/연동 → ADA JWT 발급 → 프론트 복귀
# =============================================================================
def _front_redirect(**params: str) -> RedirectResponse:
    """프론트(Streamlit)로 쿼리파라미터를 붙여 리다이렉트."""
    base = settings.frontend_url.rstrip("/")
    return RedirectResponse(f"{base}/?{urlencode(params)}")


@router.get("/google")
async def google_login(request: Request):
    """구글 동의화면으로 리다이렉트. state/nonce 는 세션 쿠키에 저장된다."""
    if _oauth is None:
        raise HTTPException(503, detail="google oauth unavailable (authlib not installed)")
    if not settings.google_client_id:
        raise HTTPException(503, detail="GOOGLE_CLIENT_ID not set in .env")
    return await _oauth.google.authorize_redirect(request, settings.google_redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, db: AsyncSession = Depends(get_db)):
    """구글 콜백 처리 — 검증/연동/발급 후 프론트로 복귀."""
    if _oauth is None:
        raise HTTPException(503, detail="google oauth unavailable")

    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")

    # 1) code → 토큰 교환 + id_token 서명검증 (authlib 가 구글 JWKS 로 자동 수행)
    try:
        token = await _oauth.google.authorize_access_token(request)
    except OAuthError as e:  # state 불일치·교환 실패 등
        _log.warning("google_oauth_error", error=str(e))
        await log_event(
            db, event_type="login", action="google_oauth", result="failure",
            ip_address=ip, user_agent=ua, details={"reason": "oauth_error"},
        )
        return _front_redirect(auth_error="google_oauth_failed")

    userinfo = token.get("userinfo") or {}
    sub = userinfo.get("sub")
    email = userinfo.get("email")
    if not sub or not email:
        return _front_redirect(auth_error="no_userinfo")

    name = userinfo.get("name")
    email_verified = bool(userinfo.get("email_verified", False))

    # 2) 기존 연동(oauth_accounts) 조회
    acc = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == "google",
            OAuthAccount.provider_account_id == sub,
        )
    )
    if acc is not None:
        user = await db.scalar(select(User).where(User.id == acc.user_id))
    else:
        # 3) 같은 이메일 계정이 있으면 연동 — 단 구글이 이메일 인증한 경우만(계정 탈취 방지)
        user = await db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(
                id=uuid.uuid4(),
                email=email,
                name=name,
                role="analyst",
                is_verified=email_verified,
                password_hash=None,  # 구글 전용 = 비번 없음
            )
            db.add(user)
            await db.flush()
        elif not email_verified:
            return _front_redirect(auth_error="email_not_verified")
        # 4) 연동 레코드 생성
        db.add(
            OAuthAccount(
                id=uuid.uuid4(),
                user_id=user.id,
                provider="google",
                provider_account_id=sub,
                email=email,
            )
        )
        await db.flush()

    # 5) 비활성 계정 차단
    if user is None or not user.is_active:
        await log_event(
            db, event_type="login", action="google_oauth", result="blocked",
            actor_user_id=str(user.id) if user else None,
            ip_address=ip, user_agent=ua, details={"reason": "inactive"},
        )
        return _front_redirect(auth_error="account_inactive")

    # 6) 성공 — 로그인 기록(security_audit_log 재사용) + ADA JWT 발급
    user.last_login_at = datetime.utcnow()
    role = user.role or "analyst"
    await log_event(
        db, event_type="login", action="google_oauth", result="success",
        actor_user_id=str(user.id), actor_role=role,
        ip_address=ip, user_agent=ua, details={"provider": "google"},
    )
    access = create_access_token(sub=str(user.id), role=role)
    return _front_redirect(token=access, role=role, email=user.email)


@router.post("/logout")
async def logout(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """로그아웃 — JWT 는 stateless 라 서버 무효화는 없고, 이력만 기록한다.

    실제 세션 종료는 클라이언트가 토큰을 폐기(삭제)함으로써 이뤄진다.
    """
    actor: Optional[str] = None
    if authorization:
        try:
            payload = decode_token(_extract_bearer(authorization))
            actor = payload.get("sub")
        except Exception:  # noqa: BLE001 — 만료/위조 토큰이어도 로그아웃은 멱등
            actor = None
    await log_event(db, event_type="logout", action="logout", result="success", actor_user_id=actor)
    return {"status": "logged_out"}

"""ada.security.jwt — JWT 발급/검증 (Day17 R-707 + Day 5 RS256 전환).

알고리즘 결정 우선순위 (decode 는 둘 다 허용):
    1) settings.jwt_algo == 'RS256' 이고 Vault 에서 RS 키 로드 성공 → RS256
    2) 그 외 → HS256 (개발 fallback)

키 로드:
    - read_secret('jwt/rs256') → {"private_key": "...PEM...", "public_key": "...PEM..."}
    - Vault 응답 비면 환경변수 JWT_PRIVATE_KEY / JWT_PUBLIC_KEY 시도
    - 그것도 없으면 HS256 으로 강제 fallback
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from ada.core.config import settings
from ada.core.logger import get_logger

_log = get_logger("jwt")
security = HTTPBearer(auto_error=False)


# ----- 키 로드 ----------------------------------------------------------------
@lru_cache(maxsize=1)
def _load_rs_keys() -> dict[str, str]:
    """Vault 또는 환경변수에서 RS256 키 PEM 로드. 실패 시 빈 dict."""
    # 1) Vault
    try:
        from ada.security.vault import read_secret

        v = read_secret("jwt/rs256")
        if v and v.get("private_key") and v.get("public_key"):
            return {"private_key": v["private_key"], "public_key": v["public_key"]}
    except Exception as e:
        _log.warning("vault_rs_key_load_failed", error=str(e))

    # 2) 환경변수 fallback
    priv = os.environ.get("JWT_PRIVATE_KEY", "")
    pub = os.environ.get("JWT_PUBLIC_KEY", "")
    if priv and pub:
        return {"private_key": priv, "public_key": pub}

    return {}


def _effective_algo() -> str:
    """현재 설정 + 키 로드 가능 여부로 결정된 실효 알고리즘."""
    if (settings.jwt_algo or "").upper() == "RS256" and _load_rs_keys().get("private_key"):
        return "RS256"
    return "HS256"


def _sign_key() -> str:
    if _effective_algo() == "RS256":
        return _load_rs_keys()["private_key"]
    return settings.jwt_secret


def _verify_keys() -> tuple[list[str], list[str]]:
    """(허용 알고리즘 목록, 검증 키 후보 목록).

    RS256 가 가능하면 RS256+HS256 모두 허용 (운영 전환 기간 호환).
    """
    rs = _load_rs_keys()
    if rs.get("public_key"):
        return ["RS256", "HS256"], [rs["public_key"], settings.jwt_secret]
    return ["HS256"], [settings.jwt_secret]


# ----- public API -------------------------------------------------------------
def create_access_token(
    *,
    sub: str,
    role: str = "analyst",
    expires_minutes: Optional[int] = None,
) -> str:
    exp = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_min,
    )
    payload = {
        "sub": sub,
        "role": role,
        "exp": exp,
        "iat": datetime.now(timezone.utc),
        "iss": "ada",
    }
    algo = _effective_algo()
    return jwt.encode(payload, _sign_key(), algorithm=algo)


def decode_token(token: str) -> dict[str, Any]:
    """다중 알고리즘 + 다중 키 검증. RS256/HS256 각 키-알고리즘 쌍을 시도."""
    rs = _load_rs_keys()
    # (key, algo) 쌍 — 알고리즘이 키 종류와 맞을 때만 시도해 JWKError 회피.
    pairs: list[tuple[str, str]] = []
    if rs.get("public_key"):
        pairs.append((rs["public_key"], "RS256"))
    pairs.append((settings.jwt_secret, "HS256"))

    last_err: Exception | None = None
    for key, algo in pairs:
        try:
            return jwt.decode(token, key, algorithms=[algo])
        except Exception as e:
            last_err = e
            continue
    raise JWTError(f"decode_failed: {last_err}")


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


def reset_key_cache() -> None:
    """테스트/로테이션 시 호출 — Vault 재로드 강제."""
    _load_rs_keys.cache_clear()

"""Day 5 — RS256 JWT 전환 + Vault 키 로딩.

DoD:
    - JWT_ALGO=RS256 + 키 환경변수 있을 때 RS256 으로 sign/verify
    - HS256 환경에서도 종전대로 동작 (호환성)
    - decode_token 이 두 알고리즘 모두 수용 (운영 전환 기간)
    - keygen 스크립트가 실행 가능 (syntax + 실행 가능 비트)
"""

from __future__ import annotations

import os
import platform
import subprocess

import pytest


def _bash_exe() -> str:
    """플랫폼별 bash 실행 파일 경로.

    Windows: Git Bash 를 우선 사용 (WSL bash 는 ``/c/...`` 경로 비호환).
    Git Bash (MSYS2) 는 인자로 받은 Windows 경로를 자동 변환해줌.
    """
    if platform.system() != "Windows":
        return "bash"
    for cand in (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        r"C:\Program Files\Git\usr\bin\bash.exe",
    ):
        if os.path.exists(cand):
            return cand
    return "bash"


# ----- 1) keygen 스크립트 존재 + 실행 가능 ------------------------------------
def test_keygen_script_exists():
    repo = os.path.dirname(os.path.dirname(__file__))
    p = os.path.join(repo, "scripts", "security", "jwt_keygen.sh")
    assert os.path.isfile(p)
    assert os.access(p, os.X_OK)
    # Windows: Git Bash 직접 호출 (Windows 경로 자동 변환). WSL bash 회피.
    r = subprocess.run(
        [_bash_exe(), "-n", p],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr


# ----- 2) HS256 (개발 기본) — 종전 호환 ---------------------------------------
def test_hs256_roundtrip():
    from ada.security.jwt import create_access_token, decode_token, reset_key_cache

    reset_key_cache()
    # JWT_ALGO 기본 HS256
    os.environ.pop("JWT_PRIVATE_KEY", None)
    os.environ.pop("JWT_PUBLIC_KEY", None)
    tok = create_access_token(sub="user-1", role="analyst")
    decoded = decode_token(tok)
    assert decoded["sub"] == "user-1"
    assert decoded["role"] == "analyst"


# ----- 3) RS256 — 환경변수 키 사용 ---------------------------------------------
def test_rs256_roundtrip_via_env(monkeypatch):
    pytest.importorskip("Crypto")  # python-jose RS256 의존 cryptography
    # 키쌍 생성
    import subprocess as sp
    import tempfile

    workdir = tempfile.mkdtemp()
    repo = os.path.dirname(os.path.dirname(__file__))
    script = os.path.join(repo, "scripts", "security", "jwt_keygen.sh")
    sp.run(["bash", script], cwd=workdir, check=True, capture_output=True)

    with open(os.path.join(workdir, "jwt_private.pem")) as f:
        priv = f.read()
    with open(os.path.join(workdir, "jwt_public.pem")) as f:
        pub = f.read()

    monkeypatch.setenv("JWT_PRIVATE_KEY", priv)
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)
    # settings 캐시 우회 — settings 객체 자체의 jwt_algo 만 override
    from ada.core.config import settings
    from ada.security import jwt as jwt_mod

    monkeypatch.setattr(settings, "jwt_algo", "RS256")
    jwt_mod.reset_key_cache()

    tok = jwt_mod.create_access_token(sub="user-rs", role="admin")
    # RS256 토큰은 헤더에 'alg':'RS256' 박혀있음
    import base64
    import json as _json

    header = _json.loads(base64.urlsafe_b64decode(tok.split(".")[0] + "=="))
    assert header["alg"] == "RS256"

    decoded = jwt_mod.decode_token(tok)
    assert decoded["sub"] == "user-rs"
    assert decoded["role"] == "admin"


# ----- 4) decode_token 다중 알고리즘 — RS 토큰 있는데 HS 토큰도 들어와도 OK ---
def test_decode_accepts_both_when_rs_available(monkeypatch):
    pytest.importorskip("Crypto")
    import subprocess as sp
    import tempfile

    workdir = tempfile.mkdtemp()
    repo = os.path.dirname(os.path.dirname(__file__))
    script = os.path.join(repo, "scripts", "security", "jwt_keygen.sh")
    sp.run(["bash", script], cwd=workdir, check=True, capture_output=True)

    with open(os.path.join(workdir, "jwt_private.pem")) as f:
        priv = f.read()
    with open(os.path.join(workdir, "jwt_public.pem")) as f:
        pub = f.read()

    monkeypatch.setenv("JWT_PRIVATE_KEY", priv)
    monkeypatch.setenv("JWT_PUBLIC_KEY", pub)

    from jose import jwt as jose_jwt

    from ada.core.config import settings
    from ada.security import jwt as jwt_mod

    monkeypatch.setattr(settings, "jwt_algo", "RS256")
    jwt_mod.reset_key_cache()

    # HS256 으로 발급된 토큰 (구 환경에서 발급)
    hs_tok = jose_jwt.encode({"sub": "old", "role": "analyst"}, settings.jwt_secret, algorithm="HS256")
    # 새 환경에서 decode 시도 → 통과해야 함 (호환)
    decoded = jwt_mod.decode_token(hs_tok)
    assert decoded["sub"] == "old"


# ----- 5) Vault 로드 우선순위 — Vault 가 있으면 환경변수보다 우선 ----------------
def test_vault_priority_over_env(monkeypatch):
    """Vault 가 키를 반환하면 환경변수는 무시."""
    from ada.security import jwt as jwt_mod, vault as vault_mod

    monkeypatch.setenv("JWT_PRIVATE_KEY", "env-priv")
    monkeypatch.setenv("JWT_PUBLIC_KEY", "env-pub")
    monkeypatch.setattr(
        vault_mod, "read_secret", lambda path, mount="secret": {"private_key": "vault-priv", "public_key": "vault-pub"}
    )
    jwt_mod.reset_key_cache()
    keys = jwt_mod._load_rs_keys()
    assert keys["private_key"] == "vault-priv"
    assert keys["public_key"] == "vault-pub"

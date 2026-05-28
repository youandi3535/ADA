"""ADR-009 hj-day5 자체 검증 스크립트.

RS256 JWT 전환 + Vault 키 로딩 변경의 정적 검증.
실행: PYTHONUTF8=1 python scripts/dev/verify_day5.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def wrapper(fn):
        try:
            fn()
            results.append((name, True, ""))
            print(f"  OK  {name}")
        except Exception as e:
            results.append((name, False, str(e)))
            print(f"  FAIL  {name}: {e}")
        return fn

    return wrapper


print("=" * 70)
print("ADR-009 hj-day5 검증 (RS256 JWT + Vault key loading)")
print("=" * 70)


# ===== L1 — 구현 파일 존재 + 핵심 API ============================================
print("\n[L1] 구현 파일 정적 검증")


@check("L1.1 — ada/security/jwt.py 존재 + 공개 API")
def _():
    src = (REPO_ROOT / "ada/security/jwt.py").read_text(encoding="utf-8")
    for sym in ("def create_access_token(", "def decode_token(", "def reset_key_cache("):
        assert sym in src, f"누락: {sym}"


@check("L1.2 — _load_rs_keys 가 Vault 먼저, env fallback")
def _():
    src = (REPO_ROOT / "ada/security/jwt.py").read_text(encoding="utf-8")
    assert "from ada.security.vault import read_secret" in src
    assert 'read_secret("jwt/rs256")' in src
    assert "JWT_PRIVATE_KEY" in src and "JWT_PUBLIC_KEY" in src


@check("L1.3 — _effective_algo 가 settings.jwt_algo + 키 존재로 분기")
def _():
    src = (REPO_ROOT / "ada/security/jwt.py").read_text(encoding="utf-8")
    assert "_effective_algo" in src
    assert "settings.jwt_algo" in src and '"RS256"' in src


@check("L1.4 — decode_token 가 RS256·HS256 둘 다 시도")
def _():
    src = (REPO_ROOT / "ada/security/jwt.py").read_text(encoding="utf-8")
    # pairs 리스트 패턴 — RS 키 있으면 RS256 먼저, HS256 폴백
    assert 'pairs.append((rs["public_key"], "RS256"))' in src
    assert 'pairs.append((settings.jwt_secret, "HS256"))' in src


@check("L1.5 — _verify_keys 데드코드 제거됨 (Day 5)")
def _():
    src = (REPO_ROOT / "ada/security/jwt.py").read_text(encoding="utf-8")
    assert "def _verify_keys(" not in src, "데드코드가 다시 추가됨"


# ===== L2 — 키 생성 스크립트 ====================================================
print("\n[L2] keygen 스크립트")


@check("L2.1 — scripts/security/jwt_keygen.sh 존재 + 실행 비트")
def _():
    p = REPO_ROOT / "scripts/security/jwt_keygen.sh"
    assert p.is_file()
    # Windows 에서는 X_OK 가 의미 없음 — 그래도 존재만 보장
    if os.name != "nt":
        assert os.access(p, os.X_OK), "실행 비트 없음 — chmod +x 필요"


@check("L2.2 — keygen 스크립트가 openssl + Vault 모드 모두 지원")
def _():
    src = (REPO_ROOT / "scripts/security/jwt_keygen.sh").read_text(encoding="utf-8")
    assert "openssl genrsa" in src
    assert "openssl rsa -in" in src and "-pubout" in src
    assert "--vault" in src
    assert "vault kv put secret/jwt/rs256" in src


# ===== L3 — Vault seed placeholder =============================================
print("\n[L3] Vault seed")


@check("L3.1 — vault_seed.sh 에 secret/jwt/rs256 placeholder")
def _():
    src = (REPO_ROOT / "scripts/vault_seed.sh").read_text(encoding="utf-8")
    assert "secret/jwt/rs256" in src, (
        "vault_seed.sh 에 secret/jwt/rs256 placeholder 가 없음 — "
        "운영 Raft 전환 시 jwt._load_rs_keys() 가 404 로 깨질 수 있음"
    )


# ===== L4 — 테스트 ==============================================================
print("\n[L4] 단위 테스트")


@check("L4.1 — tests/test_day5_rs256_jwt.py 가 5 케이스 정의")
def _():
    src = (REPO_ROOT / "tests/test_day5_rs256_jwt.py").read_text(encoding="utf-8")
    for t in (
        "test_keygen_script_exists",
        "test_hs256_roundtrip",
        "test_rs256_roundtrip_via_env",
        "test_decode_accepts_both_when_rs_available",
        "test_vault_priority_over_env",
    ):
        assert f"def {t}" in src, f"누락: {t}"


@check("L4.2 — DoD 핵심 — RS256 토큰 헤더 alg 검증 어서션 존재")
def _():
    src = (REPO_ROOT / "tests/test_day5_rs256_jwt.py").read_text(encoding="utf-8")
    assert 'header["alg"] == "RS256"' in src


# ===== L5 — 설정 ================================================================
print("\n[L5] 설정/계약")


@check("L5.1 — settings 에 jwt_algo, jwt_secret, vault_addr 존재")
def _():
    src = (REPO_ROOT / "ada/core/config.py").read_text(encoding="utf-8")
    for f in ("jwt_secret:", "jwt_algo:", "vault_addr:"):
        assert f in src, f"settings 누락: {f}"


@check("L5.2 — settings.jwt_algo 기본은 HS256 (운영 전환 시 .env 로 override)")
def _():
    from ada.core.config import settings  # lazy import — config 사이드이펙트 회피

    assert settings.jwt_algo.upper() in ("HS256", "RS256")


# ===== 요약 ====================================================================
print("\n" + "=" * 70)
ok = sum(1 for _, p, _ in results if p)
total = len(results)
print(f"결과: {ok}/{total} 통과")
if ok < total:
    print("\n실패한 체크:")
    for name, passed, err in results:
        if not passed:
            print(f"  - {name}: {err}")
    sys.exit(1)
print("✅ Day 5 정적 검증 모두 통과")

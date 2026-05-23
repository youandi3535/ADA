#!/usr/bin/env bash
# jwt_keygen.sh — Day 5 HJ
#
# RS256 키쌍 생성 + Vault KV v2 (secret/jwt/rs256) 에 저장.
# 출력: jwt_private.pem, jwt_public.pem (현재 디렉토리)
#
# 사용:
#   bash scripts/security/jwt_keygen.sh              # 키쌍 생성만
#   bash scripts/security/jwt_keygen.sh --vault      # 생성 + Vault 저장
#
# 이미 발급된 access token 은 신구 키 모두로 검증되도록
# ada/security/jwt.py 가 다중 알고리즘+다중 키 검증 지원.

set -euo pipefail

VAULT=false
[[ "${1:-}" == "--vault" ]] && VAULT=true

PRIV="${JWT_PRIVATE_KEY_PATH:-./jwt_private.pem}"
PUB="${JWT_PUBLIC_KEY_PATH:-./jwt_public.pem}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "RS256 키쌍 생성 — $PRIV / $PUB"
command -v openssl >/dev/null || { echo "openssl 미설치"; exit 1; }

# 2048 bit (운영은 4096 권장)
openssl genrsa -out "$PRIV" 2048 2>/dev/null
openssl rsa -in "$PRIV" -pubout -out "$PUB" 2>/dev/null
chmod 600 "$PRIV"
chmod 644 "$PUB"
log "OK — 키 생성 완료"

if $VAULT; then
  log "Vault 저장 (secret/jwt/rs256)"
  command -v vault >/dev/null || { echo "vault CLI 미설치"; exit 1; }

  vault kv put secret/jwt/rs256 \
    "private_key=@$PRIV" \
    "public_key=@$PUB"

  log "OK — Vault 저장 완료"
  log "검증: vault kv get secret/jwt/rs256"
else
  log "Vault 저장 생략 — 환경변수 export 예시:"
  echo "export JWT_ALGO=RS256"
  echo "export JWT_PRIVATE_KEY=\"\$(cat $PRIV)\""
  echo "export JWT_PUBLIC_KEY=\"\$(cat $PUB)\""
fi

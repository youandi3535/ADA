#!/usr/bin/env sh
# ============================================================
# scripts/vault_seed.sh  -  Vault KV v2 mount + 시크릿 시드
# 작업지시서 §7 (Day01 v2)
#
# 사용 (sec profile 기동 후):
#   docker compose --profile sec up -d vault
#   docker compose --profile sec exec vault sh /scripts/vault_seed.sh
#
# 전제: compose 의 vault 서비스가 ./scripts:/scripts:ro 로 마운트되어 있어야 함
# ============================================================
set -eu

: "${VAULT_ADDR:=http://127.0.0.1:8200}"
: "${VAULT_DEV_TOKEN:?VAULT_DEV_TOKEN 환경변수 필요}"

export VAULT_ADDR VAULT_TOKEN="${VAULT_DEV_TOKEN}"

echo "[vault_seed] VAULT_ADDR=${VAULT_ADDR}"

# 1) KV v2 secrets engine 마운트 (이미 있으면 무시)
vault secrets enable -path=ada -version=2 kv 2>/dev/null \
  || echo "[skip] kv v2 already mounted at ada/"

# 2) 핵심 시크릿 시드 (.env 의 값을 Vault 에도 동기화)
vault kv put ada/llm \
  anthropic_api_key="${ANTHROPIC_API_KEY:-}" \
  langsmith_api_key="${LANGSMITH_API_KEY:-}"

vault kv put ada/db \
  postgres_user="${POSTGRES_USER:-autoai}" \
  postgres_password="${POSTGRES_PASSWORD:-}"

vault kv put ada/s3 \
  minio_access_key="${MINIO_ACCESS_KEY:-minioadmin}" \
  minio_secret_key="${MINIO_SECRET_KEY:-}"

vault kv put ada/jwt \
  jwt_secret="${JWT_SECRET:-}" \
  secret_key="${SECRET_KEY:-}"

echo "[done] Vault seeded:"
vault kv list ada/

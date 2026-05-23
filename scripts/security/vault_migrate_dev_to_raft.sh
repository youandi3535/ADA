#!/usr/bin/env bash
# vault_migrate_dev_to_raft.sh — Day 2 HJ
#
# Dev 모드 (in-memory) Vault → Raft 스토리지 백엔드로 안전 마이그레이션 시나리오.
# 본 스크립트는 --apply 플래그가 없으면 **dry-run** 으로 동작 (시뮬레이션만).
#
# 사용법:
#   bash scripts/security/vault_migrate_dev_to_raft.sh            # dry-run (기본)
#   bash scripts/security/vault_migrate_dev_to_raft.sh --apply    # 실제 실행
#
# 흐름:
#   1) Dev Vault 에서 모든 KV v2 secret snapshot 추출 → vault-snapshot.json
#   2) Raft 모드 Vault 컨테이너 기동 (compose --profile raft up)
#   3) Raft Vault 에 unseal/init
#   4) snapshot 의 모든 secret 을 Raft 로 PUT
#   5) /sys/health 검증 후 dev 컨테이너 종료
#
# 의도: 운영 전환 리허설. 데이터 손실 위험 0 (dry-run 보호).

set -euo pipefail

DRY_RUN=true
[[ "${1:-}" == "--apply" ]] && DRY_RUN=false

# Vault 환경
VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_DEV_TOKEN="${VAULT_DEV_TOKEN:-root}"
RAFT_DATA_DIR="${VAULT_RAFT_DATA_DIR:-/vault/raft-data}"
SNAPSHOT_FILE="./vault-snapshot.json"
KV_MOUNT="${KV_MOUNT:-secret}"

log() { echo "[$(date +%H:%M:%S)] $*"; }
run() {
  if $DRY_RUN; then
    echo "  (dry-run) $*"
  else
    eval "$@"
  fi
}

log "vault_migrate_dev_to_raft — $($DRY_RUN && echo DRY-RUN || echo APPLY)"
log "VAULT_ADDR=$VAULT_ADDR  KV_MOUNT=$KV_MOUNT  RAFT_DATA_DIR=$RAFT_DATA_DIR"

# --- 사전 점검 ----------------------------------------------------------------
log "1/6  사전 점검 — vault CLI 와 jq 필요"
command -v vault >/dev/null || { echo "vault CLI 미설치"; exit 1; }
command -v jq    >/dev/null || { echo "jq 미설치"; exit 1; }

# --- Dev Vault 인증 -----------------------------------------------------------
log "2/6  Dev Vault 인증 (VAULT_TOKEN)"
export VAULT_TOKEN="$VAULT_DEV_TOKEN"
run vault status >/dev/null || true

# --- snapshot 추출 ------------------------------------------------------------
log "3/6  Dev KV v2 snapshot 추출 → $SNAPSHOT_FILE"
if $DRY_RUN; then
  echo "  (dry-run) 모든 secret 키 목록 + 값 JSON 저장 시뮬"
else
  vault kv list -format=json "$KV_MOUNT/" > /tmp/keys.json
  echo "{}" > "$SNAPSHOT_FILE"
  for key in $(jq -r '.[]' /tmp/keys.json); do
    val=$(vault kv get -format=json "$KV_MOUNT/$key" | jq '.data.data')
    jq --arg k "$key" --argjson v "$val" '. + {($k): $v}' "$SNAPSHOT_FILE" > "${SNAPSHOT_FILE}.tmp"
    mv "${SNAPSHOT_FILE}.tmp" "$SNAPSHOT_FILE"
  done
fi

# --- Raft Vault 기동 ----------------------------------------------------------
log "4/6  Raft Vault 컨테이너 기동 (docker compose --profile raft up -d)"
run "docker compose --profile raft up -d vault-raft"
run "sleep 5"

# --- Raft init + unseal -------------------------------------------------------
log "5/6  Raft init / unseal (자동화는 운영에서 KMS 권장)"
if $DRY_RUN; then
  echo "  (dry-run) vault operator init -key-shares=3 -key-threshold=2 → unseal keys 보관"
  echo "  (dry-run) 3 unseal key 중 2개로 vault operator unseal"
else
  vault operator init -key-shares=3 -key-threshold=2 -format=json > /tmp/init.json
  for i in 0 1; do
    KEY=$(jq -r ".unseal_keys_b64[$i]" /tmp/init.json)
    vault operator unseal "$KEY"
  done
  ROOT_TOKEN=$(jq -r '.root_token' /tmp/init.json)
  export VAULT_TOKEN="$ROOT_TOKEN"
fi

# --- secret 복원 --------------------------------------------------------------
log "6/6  snapshot → Raft 복원"
if $DRY_RUN; then
  echo "  (dry-run) jq -r 'keys[]' $SNAPSHOT_FILE | xargs -I{} vault kv put $KV_MOUNT/{}"
  echo "  (dry-run) /sys/health 검증 후 Dev 컨테이너 종료"
else
  vault secrets enable -path="$KV_MOUNT" kv-v2 || true
  for key in $(jq -r 'keys[]' "$SNAPSHOT_FILE"); do
    jq -r --arg k "$key" '.[$k] | to_entries[] | "\(.key)=\(.value)"' "$SNAPSHOT_FILE" \
      | xargs vault kv put "$KV_MOUNT/$key"
  done
  curl -sf "$VAULT_ADDR/v1/sys/health" >/dev/null
  docker compose stop vault
fi

log "OK — 마이그레이션 $($DRY_RUN && echo 'DRY-RUN' || echo '실제 실행') 완료"
$DRY_RUN && echo "운영 전환 시: bash $0 --apply"

#!/usr/bin/env bash
# =============================================================
# sync_datasets.sh
# -------------------------------------------------------------
# 로컬 리눅스 서버(저장소) ↔ VPS 간 대용량 데이터셋 동기화.
# 기본 방향: 로컬서버 → VPS (pull). 인자 'push' 시 반대.
#
# 사용:
#   ./scripts/sync_datasets.sh             # 로컬서버 → VPS (기본)
#   ./scripts/sync_datasets.sh push        # VPS → 로컬서버 (실수 방지용 명시 인자)
#   DRY_RUN=1 ./scripts/sync_datasets.sh   # 실제 전송 없이 미리보기
#
# 전제:
#   - .env 의 BACKUP_HOST/USER, BACKUP_DIR_DATA 가 설정돼 있음
#   - VPS 측 데이터셋 마운트 위치: /opt/ada/data  (compose volume 또는 bind)
#   - 원본 데이터셋은 로컬 리눅스 서버에 보존, VPS 는 사본/작업본
# =============================================================
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/ada/.env}"
[[ -f "$ENV_FILE" ]] || { echo "ENV file not found: $ENV_FILE"; exit 1; }
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

VPS_DATA_DIR="${VPS_DATA_DIR:-/opt/ada/data}"
DIRECTION="${1:-pull}"   # pull (default) | push

RSYNC_OPTS=(
  -avh                    # archive + verbose + human-readable
  --partial               # 끊긴 전송 이어받기
  --info=progress2        # 전체 진행률
  --exclude='.DS_Store'
  --exclude='*.tmp'
  --exclude='__pycache__'
)
[[ "${DRY_RUN:-0}" == "1" ]] && RSYNC_OPTS+=(--dry-run)

case "${DIRECTION}" in
  pull)
    echo "[$(date -Is)] PULL  ${BACKUP_HOST}:${BACKUP_DIR_DATA}/  ->  ${VPS_DATA_DIR}/"
    mkdir -p "${VPS_DATA_DIR}"
    rsync "${RSYNC_OPTS[@]}" \
      "${BACKUP_USER}@${BACKUP_HOST}:${BACKUP_DIR_DATA}/" \
      "${VPS_DATA_DIR}/"
    ;;
  push)
    echo "[$(date -Is)] PUSH  ${VPS_DATA_DIR}/  ->  ${BACKUP_HOST}:${BACKUP_DIR_DATA}/"
    # 원본 보호: 로컬서버에서 지워진 파일을 VPS 가 강제 삭제하지 않도록 --delete 미사용
    rsync "${RSYNC_OPTS[@]}" \
      "${VPS_DATA_DIR}/" \
      "${BACKUP_USER}@${BACKUP_HOST}:${BACKUP_DIR_DATA}/"
    ;;
  *)
    echo "Usage: $0 [pull|push]"
    exit 1
    ;;
esac

echo "[$(date -Is)] sync OK (${DIRECTION})"

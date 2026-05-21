#!/usr/bin/env bash
# =============================================================
# sync_datasets.sh  (Pull 방식 — 로컬 리눅스 서버에서 실행)
# -------------------------------------------------------------
# 로컬 리눅스(원본 보관) ↔ VPS(작업 사본) 간 데이터셋 동기화.
#
# 방향 정의:
#   push (기본) : 로컬 리눅스 → VPS   (학습 전 데이터셋 전송)
#   pull        : VPS → 로컬 리눅스   (VPS 작업 결과물 회수)
#
# 사용:
#   ./scripts/sync_datasets.sh             # 로컬 → VPS (기본)
#   ./scripts/sync_datasets.sh pull        # VPS → 로컬
#   DRY_RUN=1 ./scripts/sync_datasets.sh   # 실제 전송 없이 미리보기
#
# 전제:
#   - /etc/ada-backup.conf 에 설정값 입력 (backup.conf.example 참고)
# =============================================================
set -euo pipefail

CONF_FILE="${CONF_FILE:-/etc/ada-backup.conf}"
[[ -f "$CONF_FILE" ]] && { set -a; source "$CONF_FILE"; set +a; }

VPS_HOST="${VPS_HOST:-}"
VPS_USER="${VPS_USER:-ada}"
VPS_SSH_PORT="${VPS_SSH_PORT:-22}"
VPS_DATA_DIR="${VPS_DATA_DIR:-/opt/ada/data}"
LOCAL_DATA_DIR="${LOCAL_DATA_DIR:-/srv/backup/ada/datasets}"
DIRECTION="${1:-push}"

[[ -z "$VPS_HOST" ]] && { echo "[ERROR] VPS_HOST 가 설정되지 않았습니다. /etc/ada-backup.conf 확인"; exit 1; }

RSYNC_OPTS=(
  -avh
  --partial
  --info=progress2
  -e "ssh -p ${VPS_SSH_PORT} -o StrictHostKeyChecking=accept-new"
  --exclude='.DS_Store'
  --exclude='*.tmp'
  --exclude='__pycache__'
)
[[ "${DRY_RUN:-0}" == "1" ]] && RSYNC_OPTS+=(--dry-run)

case "${DIRECTION}" in
  push)
    echo "[$(date -Is)] PUSH  ${LOCAL_DATA_DIR}/  ->  ${VPS_USER}@${VPS_HOST}:${VPS_DATA_DIR}/"
    rsync "${RSYNC_OPTS[@]}" \
      "${LOCAL_DATA_DIR}/" \
      "${VPS_USER}@${VPS_HOST}:${VPS_DATA_DIR}/"
    ;;
  pull)
    echo "[$(date -Is)] PULL  ${VPS_USER}@${VPS_HOST}:${VPS_DATA_DIR}/  ->  ${LOCAL_DATA_DIR}/"
    mkdir -p "${LOCAL_DATA_DIR}"
    rsync "${RSYNC_OPTS[@]}" \
      "${VPS_USER}@${VPS_HOST}:${VPS_DATA_DIR}/" \
      "${LOCAL_DATA_DIR}/"
    ;;
  *)
    echo "Usage: $0 [push|pull]"
    exit 1
    ;;
esac

echo "[$(date -Is)] sync OK (${DIRECTION})"

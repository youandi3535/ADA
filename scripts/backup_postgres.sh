#!/usr/bin/env bash
# =============================================================
# backup_postgres.sh  (Pull 방식 — 로컬 리눅스 서버에서 실행)
# -------------------------------------------------------------
# 로컬 리눅스가 VPS에 SSH로 접속해서 pg_dump를 파이프로 받아
# 로컬에 직접 저장한다. VPS에 임시 파일 남지 않음.
#
# 설치 (로컬 리눅스 서버):
#   sudo cp scripts/backup_postgres.sh /usr/local/bin/
#   sudo chmod +x /usr/local/bin/backup_postgres.sh
#   # crontab -e
#   0 3,12,18 * * *  /usr/local/bin/backup_postgres.sh >> /var/log/ada-backup.log 2>&1
#
# 전제:
#   - 로컬 리눅스의 SSH 키가 VPS authorized_keys 에 등록돼 있어야 함
#     ([백업]학원리눅스서버컴 키 — 이미 등록 완료)
#   - /etc/ada-backup.conf 에 설정값 입력 (backup.conf.example 참고)
# =============================================================
set -euo pipefail

CONF_FILE="${CONF_FILE:-/etc/ada-backup.conf}"
[[ -f "$CONF_FILE" ]] && { set -a; source "$CONF_FILE"; set +a; }

VPS_HOST="${VPS_HOST:-}"
VPS_USER="${VPS_USER:-ada}"
VPS_SSH_PORT="${VPS_SSH_PORT:-22}"
POSTGRES_USER="${POSTGRES_USER:-autoai}"
POSTGRES_DB="${POSTGRES_DB:-autoai}"
CONTAINER="${CONTAINER:-ada-postgres}"
BACKUP_DIR_DB="${BACKUP_DIR_DB:-/srv/backup/ada/postgres}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"

[[ -z "$VPS_HOST" ]] && { echo "[ERROR] VPS_HOST 가 설정되지 않았습니다. /etc/ada-backup.conf 확인"; exit 1; }

TS="$(date +%Y%m%d_%H%M%S)"
DUMP_NAME="ada_${POSTGRES_DB}_${TS}.sql.gz"
LOCAL_PATH="${BACKUP_DIR_DB}/${DUMP_NAME}"

mkdir -p "${BACKUP_DIR_DB}"

echo "[$(date -Is)] BEGIN pull_backup -> ${DUMP_NAME}"

# 1) VPS에 SSH 접속 → docker exec으로 pg_dump → 파이프로 로컬에 직접 저장
ssh -p "${VPS_SSH_PORT}" \
    -o StrictHostKeyChecking=accept-new \
    -o ConnectTimeout=30 \
    "${VPS_USER}@${VPS_HOST}" \
    "docker exec -i ${CONTAINER} \
      pg_dump -U ${POSTGRES_USER} -d ${POSTGRES_DB} \
      --no-owner --clean --if-exists" \
    | gzip -9 > "${LOCAL_PATH}"

SIZE=$(du -h "${LOCAL_PATH}" | cut -f1)
echo "[$(date -Is)] saved: ${LOCAL_PATH} (${SIZE})"

# 2) 오래된 백업 로컬에서 직접 정리
find "${BACKUP_DIR_DB}" -type f -name "ada_*.sql.gz" \
     -mtime "+${BACKUP_RETENTION_DAYS}" -delete

echo "[$(date -Is)] cleanup done (retention: ${BACKUP_RETENTION_DAYS}days)"
echo "[$(date -Is)] END pull_backup OK"

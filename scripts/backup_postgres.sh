#!/usr/bin/env bash
# =============================================================
# backup_postgres.sh
# -------------------------------------------------------------
# VPS 에서 실행되어, PostgreSQL 컨테이너의 덤프를 떠서
# 로컬 리눅스 서버(BACKUP_HOST)의 BACKUP_DIR_DB 로 SCP push.
#
# 설치(VPS):
#   sudo cp scripts/backup_postgres.sh /usr/local/bin/
#   sudo chmod +x /usr/local/bin/backup_postgres.sh
#   # crontab -e
#   0 3 * * *  /usr/local/bin/backup_postgres.sh >> /var/log/ada-backup.log 2>&1
#
# 전제:
#   - .env 가 /opt/ada/.env 에 존재 (또는 ENV_FILE 환경변수로 지정)
#   - VPS 가 BACKUP_HOST 로 ssh 키 인증 가능 (~/.ssh/id_ed25519)
#   - 로컬 리눅스 서버는 Tailscale 또는 사무실 LAN 으로 접근 가능
# =============================================================
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/ada/.env}"
[[ -f "$ENV_FILE" ]] || { echo "ENV file not found: $ENV_FILE"; exit 1; }
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

TS="$(date +%Y%m%d_%H%M%S)"
DUMP_NAME="ada_${POSTGRES_DB}_${TS}.sql.gz"
TMP_PATH="/tmp/${DUMP_NAME}"

echo "[$(date -Is)] BEGIN backup_postgres -> ${DUMP_NAME}"

# 1) 컨테이너 내부에서 pg_dump (custom format + gzip)
docker exec -i ada-postgres \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --clean --if-exists \
  | gzip -9 > "${TMP_PATH}"

SIZE=$(du -h "${TMP_PATH}" | cut -f1)
echo "[$(date -Is)] dump ok: ${SIZE}"

# 2) 로컬 리눅스 서버로 SCP push
scp -q -o StrictHostKeyChecking=accept-new \
  "${TMP_PATH}" \
  "${BACKUP_USER}@${BACKUP_HOST}:${BACKUP_DIR_DB}/"

echo "[$(date -Is)] uploaded to ${BACKUP_HOST}:${BACKUP_DIR_DB}/"

# 3) 원격에서 오래된 백업 정리 (BACKUP_RETENTION_DAYS 이상)
ssh -o StrictHostKeyChecking=accept-new \
  "${BACKUP_USER}@${BACKUP_HOST}" \
  "find '${BACKUP_DIR_DB}' -type f -name 'ada_*.sql.gz' -mtime +${BACKUP_RETENTION_DAYS} -delete"

# 4) 로컬 임시 파일 제거
rm -f "${TMP_PATH}"

echo "[$(date -Is)] END backup_postgres OK"

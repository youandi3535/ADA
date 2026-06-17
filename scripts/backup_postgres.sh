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

# ── root(sudo) 실행 차단 ─────────────────────────────────────────────────────
# 이 스크립트는 SSH 키가 등록된 사용자(예: ada)로 실행해야 한다. sudo 로 돌리면 root 의
# /root/.ssh 에 키가 없어 'Permission denied (publickey)' 로 SSH 가 실패한다(설치만 sudo).
#   설치:  sudo cp ... /usr/local/bin/  &&  sudo chmod +x ...
#   실행:  /usr/local/bin/backup_postgres.sh        ← sudo 없이!
# root 가 SSH 키를 가졌다면 ALLOW_ROOT=1 로 우회할 수 있다.
if [[ "${EUID:-$(id -u)}" -eq 0 && -z "${ALLOW_ROOT:-}" ]]; then
    echo "[ERROR] root(sudo)로 실행하지 마세요 — SSH 키가 등록된 사용자(예: ada)로 실행하세요:"
    echo "          /usr/local/bin/backup_postgres.sh"
    echo "        (root 에 SSH 키를 등록했다면 ALLOW_ROOT=1 /usr/local/bin/backup_postgres.sh 로 우회)"
    exit 1
fi

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

# 1-b) backup_catalog 기록 — 운영 콘솔(관리자 대시보드)이 백업 신선도를 🟢 정상으로
#      표시할 수 있게 VPS DB(ada-postgres)에 한 행 INSERT 한다.
#      SQL 은 stdin 으로 흘려보내 SSH/docker/psql 따옴표 중첩을 피한다(pg_dump 파이프의 역방향).
#      DB 기록 실패해도 백업 파일 자체는 이미 정상 저장됐으므로, if 가드로 비치명 처리한다
#      (set -e 가 if 조건절에서는 종료를 유발하지 않음).
SIZE_BYTES=$(stat -c%s "${LOCAL_PATH}" 2>/dev/null || echo 0)
SHA=$(sha256sum "${LOCAL_PATH}" | cut -d' ' -f1)
NOTE="pull pg_dump.gz · 보존 ${BACKUP_RETENTION_DAYS}일"
# client_encoding 을 UTF8 로 고정 — VPS 로케일이 SQL_ASCII 여도 한글 note 가 깨지거나 INSERT 가
# 실패하지 않도록 방어한다(이 한 줄이 없으면 환경에 따라 INSERT 가 조용히 실패 → 카탈로그 0행).
CAT_SQL="SET client_encoding TO 'UTF8'; INSERT INTO backup_catalog (id, backup_type, minio_path, sha256, size_bytes, status, note, created_at) VALUES (gen_random_uuid(), 'db', '${LOCAL_PATH}', '${SHA}', ${SIZE_BYTES}, 'ok', '${NOTE}', now());"
if printf '%s' "${CAT_SQL}" | ssh -p "${VPS_SSH_PORT}" \
       -o StrictHostKeyChecking=accept-new \
       -o ConnectTimeout=30 \
       "${VPS_USER}@${VPS_HOST}" \
       "docker exec -i ${CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -v ON_ERROR_STOP=1 -q"; then
    # 기록 직후 누적 행수를 조회해 사용자가 즉시 성공을 확인할 수 있게 출력한다.
    CNT=$(ssh -p "${VPS_SSH_PORT}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=30 \
            "${VPS_USER}@${VPS_HOST}" \
            "docker exec -i ${CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -tAc 'SELECT count(*) FROM backup_catalog'" 2>/dev/null || echo '?')
    echo "[$(date -Is)] backup_catalog 기록 완료 (size=${SIZE_BYTES}B · 누적 ${CNT}행) — 대시보드 백업 카드 🟢 정상 전환"
else
    echo "[$(date -Is)] WARN: backup_catalog 기록 실패 — 백업 파일은 정상 저장됨 (위 psql 오류 메시지 확인)"
fi

# 2) 오래된 백업 로컬에서 직접 정리
find "${BACKUP_DIR_DB}" -type f -name "ada_*.sql.gz" \
     -mtime "+${BACKUP_RETENTION_DAYS}" -delete

echo "[$(date -Is)] cleanup done (retention: ${BACKUP_RETENTION_DAYS}days)"
echo "[$(date -Is)] END pull_backup OK"

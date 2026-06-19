#!/usr/bin/env bash
# =============================================================
# backup_postgres.sh  (Pull 방식 — 로컬 리눅스 서버에서 실행)
# -------------------------------------------------------------
# 로컬 리눅스가 VPS에 SSH로 접속해서 두 가지를 로컬에 직접 백업한다:
#   (1) PostgreSQL  : pg_dump 를 파이프로 받아 .sql.gz 로 저장(스냅샷, 영구 누적).
#   (2) MinIO 오브젝트: 업로드 데이터셋·산출물(PPT/PDF)·모델이 든 버킷을 mc mirror 로
#                       로컬에 '증분 미러'(append-only). 원본 삭제돼도 로컬은 보존(영구 저장).
# VPS 에 임시 파일을 남기지 않는다(pg_dump 는 파이프, MinIO 는 SSH 터널 경유 직접 미러).
#
# 설치 (로컬 리눅스 서버):
#   sudo cp scripts/backup_postgres.sh /usr/local/bin/
#   sudo chmod +x /usr/local/bin/backup_postgres.sh
#   # MinIO 미러용 mc(MinIO Client) 설치 — 1회:
#   curl -sSLo /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc && sudo chmod +x /usr/local/bin/mc
#   # crontab -e  (증분 미러라 3회/일도 가볍다 — 새 객체만 동기화)
#   0 3,12,18 * * *  /usr/local/bin/backup_postgres.sh >> /var/log/ada-backup.log 2>&1
#
# 전제:
#   - 로컬 리눅스의 SSH 키가 VPS authorized_keys 에 등록돼 있어야 함
#     ([백업]학원리눅스서버컴 키 — 이미 등록 완료)
#   - /etc/ada-backup.conf 에 설정값 입력 (backup.conf.example 참고)
#   - MinIO 미러를 쓰려면: 로컬에 mc 설치 + conf 에 MINIO_ACCESS_KEY/SECRET_KEY/BUCKET 입력
#     (VPS .env 의 값과 동일하게). VPS MinIO 는 127.0.0.1 바인딩이라 SSH 터널로 접근한다.
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
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-0}"   # 0 = 영구 보관(자동 삭제 안 함). N 일만 보존하려면 N 지정.

# ── MinIO(오브젝트 스토리지) 증분 미러 백업 설정 ─────────────────────────────
# DB(pg_dump)와 별개로, 업로드 데이터셋·산출물(PPT/PDF)·모델이 든 MinIO 버킷을 로컬에
# 증분 미러(append-only)한다. VPS MinIO 는 127.0.0.1:9100 바인딩(비공개)이라 SSH 터널로 접근.
MINIO_BACKUP_ENABLED="${MINIO_BACKUP_ENABLED:-1}"      # 0 = MinIO 미러 건너뜀(DB만 백업)
MINIO_API_PORT="${MINIO_API_PORT:-9100}"               # VPS 호스트의 S3 API 포트(compose: 127.0.0.1:9100:9000)
MINIO_TUNNEL_PORT="${MINIO_TUNNEL_PORT:-19100}"        # 로컬에서 열 SSH 터널 포트(로컬에서만 사용)
MINIO_BUCKET="${MINIO_BUCKET:-autoai-artifacts}"       # 미러할 버킷명(.env 의 MINIO_BUCKET 과 동일)
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-}"               # VPS .env 의 MINIO_ACCESS_KEY
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-}"               # VPS .env 의 MINIO_SECRET_KEY
BACKUP_DIR_MINIO="${BACKUP_DIR_MINIO:-/srv/backup/ada/minio}"
MC_BIN="${MC_BIN:-mc}"                                 # MinIO Client 경로(로컬 설치 필요)

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

# ── 카탈로그 기록 헬퍼 ───────────────────────────────────────────────────────
# backup_catalog 에 한 행 INSERT. client_encoding UTF8 고정(로케일 무관 한글 note 안전).
# 실패해도 비치명(백업 파일/미러는 이미 정상). 인자: type path sha size note
_catalog_insert() {
    local btype="$1" bpath="$2" bsha="$3" bsize="$4" bnote="$5"
    local SQL="SET client_encoding TO 'UTF8'; INSERT INTO backup_catalog (id, backup_type, minio_path, sha256, size_bytes, status, note, created_at) VALUES (gen_random_uuid(), '${btype}', '${bpath}', '${bsha}', ${bsize}, 'ok', '${bnote}', now());"
    if printf '%s' "${SQL}" | ssh -p "${VPS_SSH_PORT}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=30 \
           "${VPS_USER}@${VPS_HOST}" "docker exec -i ${CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -v ON_ERROR_STOP=1 -q"; then
        echo "[$(date -Is)] backup_catalog 기록 완료 (type=${btype} · size=${bsize}B)"
    else
        echo "[$(date -Is)] WARN: backup_catalog(${btype}) 기록 실패 — 백업 실물은 정상(위 psql 오류 확인)"
    fi
}

# ── MinIO 증분 미러 백업 ─────────────────────────────────────────────────────
# VPS MinIO(127.0.0.1:9100)로 SSH 터널을 열고, 로컬 mc 로 버킷을 증분 미러한다.
# set -e 와 무관하게 단계별 실패를 직접 처리한다(이 함수는 `|| ...` 로 호출되어 set -e 가 꺼짐).
# 어떤 실패도 DB 백업에는 영향 주지 않는다(이미 저장 완료 후 호출).
backup_minio() {
    command -v "${MC_BIN}" >/dev/null 2>&1 || {
        echo "[$(date -Is)] WARN: mc 미설치 — MinIO 미러 건너뜀. 설치: curl -sSLo /usr/local/bin/mc https://dl.min.io/client/mc/release/linux-amd64/mc && chmod +x /usr/local/bin/mc"
        return 0
    }
    if [[ -z "${MINIO_ACCESS_KEY}" || -z "${MINIO_SECRET_KEY}" ]]; then
        echo "[$(date -Is)] WARN: MINIO_ACCESS_KEY/SECRET_KEY 미설정 — MinIO 미러 건너뜀(/etc/ada-backup.conf 확인)"
        return 0
    fi

    local MIRROR_DIR="${BACKUP_DIR_MINIO}/${MINIO_BUCKET}"
    local ALIAS="adabkp_$$"
    local CTRL="/tmp/ada-minio-tunnel.$$"
    mkdir -p "${MIRROR_DIR}"

    # 종료 시(정상/오류 무관) 터널·alias 정리 — RETURN 트랩.
    trap 'ssh -O exit -o ControlPath="'"${CTRL}"'" "'"${VPS_USER}@${VPS_HOST}"'" 2>/dev/null || true; "'"${MC_BIN}"'" alias rm "'"${ALIAS}"'" >/dev/null 2>&1 || true' RETURN

    # 1) SSH 터널 — 로컬:MINIO_TUNNEL_PORT → VPS:127.0.0.1:MINIO_API_PORT (공개 노출 없이 접근).
    if ! ssh -p "${VPS_SSH_PORT}" \
            -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=30 \
            -o ControlMaster=yes -o ControlPath="${CTRL}" -fN \
            -L "127.0.0.1:${MINIO_TUNNEL_PORT}:127.0.0.1:${MINIO_API_PORT}" \
            "${VPS_USER}@${VPS_HOST}"; then
        echo "[$(date -Is)] WARN: SSH 터널 생성 실패(포트 ${MINIO_TUNNEL_PORT} 사용 중?) — MinIO 미러 건너뜀"
        return 0
    fi

    # 2) mc alias 등록 + 연결 준비 대기(최대 ~10초).
    "${MC_BIN}" alias set "${ALIAS}" "http://127.0.0.1:${MINIO_TUNNEL_PORT}" "${MINIO_ACCESS_KEY}" "${MINIO_SECRET_KEY}" >/dev/null 2>&1 || true
    local ok=0 i
    for i in $(seq 1 10); do
        if "${MC_BIN}" ls "${ALIAS}/${MINIO_BUCKET}" >/dev/null 2>&1; then ok=1; break; fi
        sleep 1
    done
    if [[ "${ok}" -ne 1 ]]; then
        echo "[$(date -Is)] WARN: MinIO 연결 실패(터널/자격증명/버킷명 확인) — 미러 건너뜀"
        return 0
    fi

    # 3) 증분 미러 — 새/변경 객체만 복사(--overwrite). --remove 없음 → 원본 삭제돼도 로컬 보존(영구).
    echo "[$(date -Is)] MinIO 증분 미러 시작 → ${MIRROR_DIR}"
    "${MC_BIN}" mirror --overwrite --quiet "${ALIAS}/${MINIO_BUCKET}" "${MIRROR_DIR}" \
        || echo "[$(date -Is)] WARN: 일부 객체 미러 실패(위 mc 메시지) — 나머지는 정상 복사됨"

    # 4) 카탈로그 기록(backup_type='minio') — 대시보드 백업 카드에 표시.
    local M_SIZE M_CNT M_SHA
    M_SIZE=$(du -sb "${MIRROR_DIR}" 2>/dev/null | cut -f1 || echo 0)
    M_CNT=$(find "${MIRROR_DIR}" -type f 2>/dev/null | wc -l | tr -d ' ')
    M_SHA=$(find "${MIRROR_DIR}" -type f -printf '%s %P\n' 2>/dev/null | sort | sha256sum | cut -d' ' -f1)
    echo "[$(date -Is)] MinIO 미러 완료 — 객체 ${M_CNT}개 · ${M_SIZE}B"
    _catalog_insert "minio" "${MIRROR_DIR}" "${M_SHA:-mirror}" "${M_SIZE:-0}" "mc mirror 증분 · 객체 ${M_CNT}개 · 영구 저장"
}

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
if [ "${BACKUP_RETENTION_DAYS}" -gt 0 ] 2>/dev/null; then NOTE="pull pg_dump.gz · 보존 ${BACKUP_RETENTION_DAYS}일"; else NOTE="pull pg_dump.gz · 영구 저장"; fi
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

# 2) 보존정책 — 기본(0)은 영구 보관(자동 삭제 안 함). BACKUP_RETENTION_DAYS>0 일 때만 N일 지난 백업 정리.
if [ "${BACKUP_RETENTION_DAYS}" -gt 0 ] 2>/dev/null; then
    find "${BACKUP_DIR_DB}" -type f -name "ada_*.sql.gz" -mtime "+${BACKUP_RETENTION_DAYS}" -delete
    echo "[$(date -Is)] cleanup done (retention: ${BACKUP_RETENTION_DAYS}days)"
else
    echo "[$(date -Is)] 영구 보관 — 자동 삭제 없음 (BACKUP_RETENTION_DAYS=0)"
fi

# 3) MinIO 증분 미러 — DB 와 독립 단계. `|| ...` 호출로 set -e 를 끄고 단계별 실패를 자체 처리.
#    이 단계가 실패해도 위 DB 백업/카탈로그는 이미 완료됐으므로 전체 백업은 성공으로 끝낸다.
if [ "${MINIO_BACKUP_ENABLED}" = "1" ]; then
    backup_minio || echo "[$(date -Is)] WARN: MinIO 미러 단계 비정상 종료(무시) — DB 백업은 정상"
else
    echo "[$(date -Is)] MinIO 미러 비활성 (MINIO_BACKUP_ENABLED=${MINIO_BACKUP_ENABLED})"
fi

echo "[$(date -Is)] END pull_backup OK (DB + MinIO)"

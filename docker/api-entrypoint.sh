#!/bin/sh
# docker/api-entrypoint.sh — api 컨테이너 부팅 시 스키마 동기화 후 서버 기동.
#
# 흐름:
#   1) Postgres advisory lock 획득 (한 번에 한 인스턴스만 alembic 실행)
#   2) alembic upgrade head — 미적용 마이그레이션 자동 적용
#   3) lock 해제
#   4) uvicorn 으로 FastAPI 기동
#
# 안전:
#   - set -e — alembic 실패 시 컨테이너가 죽고 docker restart 정책에 맡김
#   - pg_advisory_lock — 다중 api 인스턴스 동시 부팅 시 마이그레이션 충돌 차단
#     (다른 인스턴스는 lock 대기 → 마이그레이션 끝나면 즉시 통과)
#   - workers=1 고정 — Dockerfile.api 주석 참조 (SentenceTransformer 싱글턴 공유)
#
# 멀티 인스턴스 운영 시 권장:
#   별도 Job/initContainer 로 마이그레이션 분리 + ALEMBIC_SKIP_UPGRADE=1 로 api 측 skip.

set -e

LOCK_KEY="${ALEMBIC_LOCK_KEY:-727412354}"  # 임의의 bigint — 같은 키여야 동일 잠금

# DATABASE_URL 에서 host/port/db/user 추출 (psql 호출용)
if [ -z "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] WARNING: DATABASE_URL 미설정 — alembic 그대로 시도"
    DBURL_FOR_PSQL=""
else
    # postgresql+asyncpg:// → postgresql:// 정규화 (psql 은 driver suffix 비호환)
    DBURL_FOR_PSQL=$(printf '%s' "$DATABASE_URL" | sed 's|postgresql+asyncpg://|postgresql://|')
fi

if [ "${ALEMBIC_SKIP_UPGRADE:-0}" = "1" ]; then
    echo "[entrypoint] ALEMBIC_SKIP_UPGRADE=1 → alembic 우회"
elif [ -n "$DBURL_FOR_PSQL" ] && command -v psql >/dev/null 2>&1; then
    echo "[entrypoint] alembic upgrade head (advisory lock=${LOCK_KEY})"
    # pg_advisory_lock 은 트랜잭션 종료 시 자동 해제. alembic 자체가 트랜잭션 사용.
    # 별도 psql 에서 lock 잡으면 alembic 종료 후 해제되도록 BEGIN/COMMIT 묶음.
    psql "$DBURL_FOR_PSQL" -v ON_ERROR_STOP=1 -c "SELECT pg_advisory_lock(${LOCK_KEY});" \
        > /dev/null
    set +e
    alembic upgrade head
    AL_RC=$?
    set -e
    psql "$DBURL_FOR_PSQL" -v ON_ERROR_STOP=1 -c "SELECT pg_advisory_unlock(${LOCK_KEY});" \
        > /dev/null || true
    if [ "$AL_RC" != "0" ]; then
        echo "[entrypoint] alembic upgrade failed (rc=$AL_RC)"
        exit "$AL_RC"
    fi
else
    # psql 미설치 환경 — lock 없이 그대로 실행 (단일 인스턴스 가정)
    echo "[entrypoint] alembic upgrade head (no advisory lock — psql 미설치)"
    alembic upgrade head
fi

echo "[entrypoint] starting uvicorn"
exec uvicorn api.main:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1 --loop uvloop

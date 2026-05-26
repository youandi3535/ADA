#!/bin/sh
# docker/api-entrypoint.sh — api 컨테이너 부팅 시 스키마 동기화 후 서버 기동.
#
# 흐름:
#   1) alembic upgrade head — 미적용 마이그레이션 자동 적용
#      (docker-compose 의 depends_on: postgres service_healthy 가 이미 DB 가용성 보장)
#   2) uvicorn 으로 FastAPI 기동
#
# 안전:
#   - set -e — alembic 실패 시 컨테이너가 죽고 docker restart 정책에 맡김
#   - workers=1 고정 — Dockerfile.api 주석 참조 (SentenceTransformer 싱글턴 공유)
#
# 멀티 인스턴스 주의:
#   동시에 여러 api 컨테이너가 부팅되면 alembic 동시 실행 가능 → 락 충돌.
#   현재 docker-compose 는 단일 컨테이너이므로 안전. 운영에서 replica > 1 로 가면
#   별도 마이그레이션 잡(Job/initContainer)로 분리 권장.

set -e

echo "[entrypoint] alembic upgrade head"
alembic upgrade head

echo "[entrypoint] starting uvicorn"
exec uvicorn api.main:app \
    --host 0.0.0.0 --port 8000 \
    --workers 1 --loop uvloop

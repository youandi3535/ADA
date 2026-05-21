# ADR-003 Alembic 의무화 (v2.2)

## Status
Accepted (2026-05-19)

## Context
`migrations/*.sql` 직접 실행은 멱등성 보장이 어렵고, 다중 환경에서 적용 상태 추적 불가.

## Decision
- 모든 스키마 변경 = `alembic revision -m "..."` + `alembic upgrade head`
- `alembic_version` 테이블이 권위
- 베이스라인: `migrations/versions/001_initial_v2_schema.py`

## Consequences
- 신규 테이블/컬럼은 `--autogenerate` 후 PR
- 운영에서 `alembic downgrade` 금지

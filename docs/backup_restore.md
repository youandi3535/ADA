# 백업 / 복구 절차 (Day21)

## 1) 일일 백업
- `scripts/backup_postgres.sh` (cron `0 2 * * *`)
- pg_dump → `s3://autoai-artifacts/backups/postgres/{YYYY-MM-DD}.sql.gz`
- SHA256 → `backup_catalog` 등록 (R-901 R-902)

## 2) 복구
```bash
mc cp local/autoai-artifacts/backups/postgres/2026-05-20.sql.gz ./backup.sql.gz
gunzip backup.sql.gz
psql $DATABASE_URL -f backup.sql
alembic upgrade head
```

## 3) Vault 복구 (Raft 모드)
```bash
vault operator raft snapshot restore /var/snapshots/vault-2026-05-20.snap
vault status   # sealed=false 확인
```

## 4) MinIO 데이터
- `scripts/sync_datasets.sh` 가 매일 23시 백업 호스트로 rsync.

## 5) DR Game Day (KP13)
- 분기 1회, 4 시나리오(DB / MinIO / Vault / 전체) 게임데이.

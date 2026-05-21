# ADR-004 Vault Raft 모드 (R-903)

## Status
Accepted (2026-05-19)

## Context
Day01 Vault Dev 모드는 root token 노출 + 메모리 백엔드. 운영 부적합.

## Decision
- 운영 환경: Vault Raft 스토리지 백엔드 + snapshot
- KV v2 + AppRole 인증
- 마이그레이션: `scripts/security/vault_migrate_dev_to_raft.sh`

## Consequences
- VAULT_DEV_TOKEN 은 dev 전용
- `vault status` 가 Raft + sealed=false 통과 시에만 운영 인정

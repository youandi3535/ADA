# VPS 백업 설정 기록

## 백업 방식: Pull 백업 (로컬 서버 → VPS 주도)

ADA 프로젝트는 **로컬 백업 서버(학원 Linux 서버)가 VPS에서 데이터를 가져오는 Pull 방식**을 사용합니다.

```
[학원 Linux 서버] --SSH--> [VPS ada-prod] --pg_dump--> [로컬 백업 서버]
```

- VPS는 수동적 역할 (SSH 키 등록만 돼 있음)
- 백업 스케줄/제어권은 로컬 서버에 있음
- VPS에는 별도의 백업 cron이 **없어야 함**

---

## VPS 측 설정 (수동 불필요)

| 항목 | 내용 |
|---|---|
| SSH 인가 키 | `[백업]학원리눅스서버컴` 키 등록됨 |
| DB 접근 | PostgreSQL Docker 컨테이너 (`ada-postgres`) |
| 외부 노출 | DB 포트 5433은 `127.0.0.1`만 바인딩 → 백업 서버는 SSH 터널로 접근 |

---

## 정리 이력

### 2026-06-09 — VPS push 백업 스크립트 제거

VPS에 불필요한 push 백업이 존재했음 → 제거 완료.

**제거 항목:**
- root crontab: `0 12 * * *`, `0 18 * * *`, `0 3 * * *` — `/usr/local/bin/backup_postgres.sh` 3개 항목
- 스크립트: `/usr/local/bin/backup_postgres.sh`

**사유:** Pull 방식이 올바른 방식이므로 VPS의 push 스크립트는 불필요한 중복 실행이었음.

---

## 백업 복구 절차 (장애 시)

1. 로컬 백업 서버에서 최신 덤프 파일 확인
2. VPS `ada-postgres` 컨테이너에 복구:
   ```bash
   docker exec -i ada-postgres psql -U autoai autoai < backup_YYYYMMDD.sql
   ```
3. MLflow 아티팩트 (MinIO): 별도 MinIO 백업에서 복원

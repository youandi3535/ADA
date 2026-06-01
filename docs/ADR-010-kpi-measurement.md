# ADR-010 — KPI 자동 측정 + Streamlit 대시보드

- **Status**: Accepted
- **Date**: 2026-06-01
- **Author**: HJ
- **Day**: 10

## Context

ADA v2 운영 가시성을 위해 5종 핵심 KPI 를 자동 측정 + Streamlit 대시보드에 표시해야 한다.

- **KP1** — E2E 성공률 (terminal jobs 중 success 비율)
- **KP2** — 평균 종단 시간 (분)
- **KP5** — API p95 응답 시간 (ms)
- **KP9** — KB 적용률 (KB 인용 ≥1 인 job 비율)
- **n_jobs** — 측정 기간 내 job 수 (분모 신뢰도 근거)

기존 코드 (Day 9 시점):
- `scripts/kpi_measure.py` — 151 줄 CLI, DB + Prometheus 파서 골격만
- `frontend/app.py` Tab 5 — KPI 카드 5개 존재. `subprocess.run("python scripts/kpi_measure.py")` 호출 → Docker 안에서 동작 불가
- `ada/observability/metrics.py` — Prometheus histogram/counter 완비
- `Job` 모델에 `kb_citation_count`, `started_at`, `finished_at` 없음 → 마이그레이션 금지 룰로 우회 필요

## Decision

### 1. 단일 진실 원천 (`ada/observability/kpi.py` 신규)

KPI 계산 로직을 별도 모듈로 분리. CLI 와 API 모두 본 모듈 호출.

- `compute_kpis(db, *, since_hours, include_prometheus, prometheus_url) -> KPIResponse`
- `parse_window(value: int | str) -> int` — `24` / `"7d"` / `"2w"` 모두 정규화
- `KPIResponse` (Pydantic) — 각 KPI + `data_source` + `warnings`

### 2. KP9 데이터 소스 — `AgentRun.payload->>'kb_citations'`

마이그레이션 금지로 신규 컬럼 추가 불가. 기존 `AgentRun.payload` (JSONB) 의 키를 사용.

- 분자: `AgentRun.payload['kb_citations'] > 0` 인 DISTINCT job
- 분모: terminal jobs
- 폴백: payload 결측 시 None + `kp9_failed` warning

**제약**: supervisor 가 payload 에 키를 기록해야 동작. 미기록 시 KP9 항상 0 → Day 11 supervisor patch 필요 (백로그).

### 3. KP5 — in-process Prometheus 우선, 외부 옵션

- 기본: `render_metrics()` → histogram bucket 선형 보간
- 옵션: `KPI_PROMETHEUS_URL` 환경변수 설정 시 외부 Prometheus `/api/v1/query` 호출
- 실패 시 in-process 로 자동 폴백

**제약**: uvicorn `--workers > 1` 환경에선 in-process 가 워커별 분리 → 부분 통계. 운영은 외부 Prometheus 권장.

### 4. REST API — `/admin/observability/kpi`

- `api/routes/observability.py` 신규
- admin RBAC (`require_perm("admin.audit.read")`)
- Query: `since_hours` (1~720), `cache` (default | bypass)
- 응답 헤더: `X-KPI-Cache-Status`, `X-KPI-Cache-Age`

### 5. 캐싱 — in-memory TTL

- TTL: `KPI_CACHE_TTL_SECONDS` (기본 60)
- 키: `(since_hours,)` 튜플
- TTL=0 시 비활성
- bypass: `?cache=bypass`

**제약**: 멀티 워커에서 워커별 독립 캐시 → 약간의 부정확. TTL 짧아 허용.

### 6. Streamlit Tab 5 — subprocess 제거, API 호출

- 기존 `subprocess.run("python scripts/kpi_measure.py")` 제거 (Docker 동작 불가)
- `requests.get(f"{API_BASE}/admin/observability/kpi")` 단일 경로
- emoji 상태 (🟢🟡🔴) + 임계치
- session_state 트렌드 히스토리 (최근 20회)
- warnings 표시 + JSON 다운로드

### 7. 임계치 (가설값, v3 SLO 정의 후 조정)

| KPI | 🟢 초록 | 🟡 노랑 | 🔴 빨강 |
|---|---|---|---|
| KP1 (성공률) | ≥95% | 80~95% | <80% |
| KP2 (분) | ≤10 | 10~30 | >30 |
| KP5 (ms) | ≤500 | 500~2000 | >2000 |
| KP9 (KB 비율) | ≥30% | 10~30% | <10% |

## Consequences

### Positive

- CLI / API / Streamlit 모두 같은 코드 → 일관성 보장
- Docker / dev / VPS 어디서든 KPI 측정 가능
- 마이그레이션 0건 — 영역 제약 준수
- 캐시로 부하 보호
- 백워드 호환 (기존 `tests/test_day10_kpi.py` 그대로 통과)

### Negative

- KP9 정확도 제한 — supervisor patch 전엔 0% 가능
- 멀티 워커 Prometheus 부정확 (외부 서버 도입 전까지)
- 캐시 무효화 메커니즘 없음 (TTL 만)
- 트렌드 히스토리 영구 저장 안 됨 (session_state)

### Backlog (Day 11+)

| # | 항목 | 우선순위 |
|---|---|---|
| 1 | supervisor 가 `AgentRun.payload['kb_citations']` 기록 | High |
| 2 | KPI 시계열 영구 저장 (DB 또는 Redis) | High |
| 3 | 외부 Prometheus 서버 + Grafana 연동 | Medium |
| 4 | KPI 카테고리별 분해 (`breakdown_by`) | Medium |
| 5 | KPI 임계치 알림 (Slack webhook) | Medium |
| 6 | KPI 조회 audit log | Low |
| 7 | KP2 median / p95 (robust statistics) | Low |
| 8 | analyst role read-only KPI 허용 | Low |
| 9 | Streamlit 자동 갱신 (autorefresh) | Low |

## Alternatives Considered

1. **신규 컬럼 + 마이그레이션** — CLAUDE.md §2 마이그레이션 금지 룰 위반
2. **외부 Prometheus 서버 우선** — Day 10 스코프 (1일) 초과, 운영팀 합의 필요
3. **Redis 캐시** — 신규 의존성, 60초 TTL 에 과한 인프라
4. **Grafana 직접 연동** — Streamlit 통합 비용 + Tab 5 UX 일관성 깨짐

## References

- `TEAM_10DAY_SCHEDULE.md` — Day 10 HJ 행
- `docs/HJ_DAY10_DESIGN.md` — 225-step 디테일 설계도
- `CLAUDE.md` §1 (HJ 영역), §2 (마이그레이션 금지), §3 (R-201/R-501)
- `ada/observability/metrics.py` — Prometheus registry
- `api/routes/admin.py:_admin_only` — RBAC 패턴 참고

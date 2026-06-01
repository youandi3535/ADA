# ADA v2 — KPI 측정 운영 가이드 (Day 10)

본 문서는 ADA v2 의 5종 운영 KPI 자동 측정 시스템 사용법.

> 설계 상세: [ADR-010](ADR-010-kpi-measurement.md) · [HJ_DAY10_DESIGN](HJ_DAY10_DESIGN.md)

## 측정 대상 5종

| KPI | 정의 | 단위 | 좋은 값 |
|---|---|---|---|
| **KP1** | E2E 성공률 = 종료된 job 중 success 비율 | % | ≥95% |
| **KP2** | 평균 종단 시간 (AgentRun 합 우선) | 분 | ≤10 |
| **KP5** | API p95 응답 시간 (Prometheus 히스토그램 보간) | ms | ≤500 |
| **KP9** | KB 적용률 = `AgentRun.payload['kb_citations']>0` 인 job 비율 | % | ≥30% |
| **n_jobs** | 측정 기간 내 전체 job 수 (분모 신뢰도 근거) | int | — |

## 데이터 흐름

```
  agents/* ─ record_agent_run() ─→ ada.observability.metrics (Prometheus registry)
                                          │
                                          ↓
       ada.db.models.Job / AgentRun ──→ compute_kpis() ──→ KPIResponse
                                          │                     │
                            ┌─────────────┴─────────┐           │
                            ↓                       ↓           ↓
                  /admin/observability/kpi    scripts/kpi_measure.py
                            │                       │
                            ↓                       ↓
                    Streamlit Tab 5         CLI (--since 24 --json)
```

## 사용법

### 1. CLI

```bash
# 기본 (최근 24시간)
python scripts/kpi_measure.py

# 7일 윈도우 + compact JSON
python scripts/kpi_measure.py --since 7d --json

# Prometheus 미가용 환경
python scripts/kpi_measure.py --no-prometheus
```

응답 (백워드 호환 키):

```json
{
  "since_hours": 24,
  "measured_at": "2026-06-01T05:00:00+00:00",
  "KP1_e2e_success_rate": 0.92,
  "KP2_avg_duration_min": 12.34,
  "KP5_p95_api_ms": 850.5,
  "KP9_kb_citation_rate": 0.31,
  "KP_AGENT_AVG_DURATION_SEC": 1.234,
  "n_jobs": 50,
  "n_jobs_total": 50,
  "n_jobs_terminal": 48,
  "data_source": {...},
  "warnings": []
}
```

### 2. REST API (admin 전용)

```bash
# JWT 토큰 발급
JWT=$(python -c "from ada.security.jwt import encode_token; print(encode_token({'sub':'admin','role':'admin'}))")

# 호출
curl -s "http://localhost:8000/admin/observability/kpi?since_hours=24" \
  -H "Authorization: Bearer $JWT" | jq

# 캐시 무시
curl -s "http://localhost:8000/admin/observability/kpi?since_hours=24&cache=bypass" \
  -H "Authorization: Bearer $JWT" -i | grep X-KPI-Cache
```

응답 헤더:
- `X-KPI-Cache-Status: fresh | cached`
- `X-KPI-Cache-Age: 23.5` (캐시 age 초)

응답 본문 (snake_case):

```json
{
  "since_hours": 24,
  "measured_at": "2026-06-01T05:00:00+00:00",
  "kp1_e2e_success_rate": 0.92,
  "kp2_avg_duration_min": 12.34,
  "kp5_p95_api_ms": 850.5,
  "kp9_kb_citation_rate": 0.31,
  "n_jobs_total": 50,
  "n_jobs_terminal": 48,
  "agent_avg_duration_sec": 1.234,
  "data_source": {
    "kp1": "db.jobs (success=44/48)",
    "kp2": "db.agent_runs.duration_ms",
    "kp5": "prometheus.in_process_histogram",
    "kp9": "db.agent_runs.payload.kb_citations (15/48)"
  },
  "warnings": []
}
```

### 3. Streamlit Tab 5 "KPI 대시보드"

- 사이드바에 admin JWT 입력
- "최근 (시간)" 입력 후 "🔄 KPI 갱신"
- 카드 5종 + emoji 상태 (🟢🟡🔴⚪)
- "강제 갱신 (캐시 무시)" 체크박스 → bypass
- 트렌드 차트 (세션 한정, 최근 20회)
- raw JSON 다운로드

## 환경변수

| 변수 | 기본값 | 의미 |
|---|---|---|
| `KPI_CACHE_TTL_SECONDS` | 60 | API 응답 캐시 TTL. 0 시 비활성 |
| `KPI_DEFAULT_WINDOW_HOURS` | 24 | CLI / UI 기본 윈도우 |
| `KPI_PROMETHEUS_URL` | "" | 외부 Prometheus 서버 (옵션) |

## 임계치 (가설)

| KPI | 🟢 정상 | 🟡 주의 | 🔴 위험 |
|---|---|---|---|
| KP1 | ≥95% | 80~95% | <80% |
| KP2 | ≤10분 | 10~30분 | >30분 |
| KP5 | ≤500ms | 500~2000ms | >2000ms |
| KP9 | ≥30% | 10~30% | <10% |

운영 후 SLO 정의 시 ADR-010 업데이트.

## 트러블슈팅

### Q. API 가 401 / 403 반환

```
401 → JWT 토큰 누락. 사이드바 또는 Authorization 헤더 확인
403 → role != admin / service. RBAC 매트릭스 (ada/security/rbac.py) 참조
```

### Q. KP5 가 항상 None

```
- /metrics 엔드포인트 응답 확인 → ada_agent_duration_seconds 노출되는지
- Prometheus 미설치: pip list | grep prometheus_client
- in-process registry 비어있음: 에이전트가 record_agent_run() 호출했는지 grep
```

### Q. KP9 가 항상 0

```
- AgentRun.payload['kb_citations'] 키가 실제로 기록되는지:
    psql -c "SELECT payload->>'kb_citations' FROM agent_runs LIMIT 10"
- supervisor 가 RAG 호출 후 카운트 누적해야 함 (Day 11 백로그)
```

### Q. KP2 평균이 비정상적으로 큼

```
- AgentRun.duration_ms 가 비어있어 updated_at-created_at 폴백 사용 시:
  - warnings 에 "kp2_fallback_used" 메시지 확인
- outlier > 720h (30일) 자동 제외, warnings 에 "outlier_excluded" 표시
```

### Q. 멀티 워커 환경 (uvicorn --workers 4)

```
- in-process Prometheus 는 워커별 분리 → 부분 통계
- 운영: KPI_PROMETHEUS_URL 설정 + 외부 Prometheus 서버
- 또는 PROMETHEUS_MULTIPROC_DIR 설정 (Day 11+ 백로그)
```

## 테스트

```bash
# 단위 테스트 (mock DB)
pytest tests/test_kpi_compute.py -v

# 통합 테스트 (FastAPI TestClient)
pytest tests/integration/test_observability_kpi_api.py -v

# 기존 정적 테스트 (Day 10 호환)
pytest tests/test_day10_kpi.py -v
```

## 참고

- [ADR-010](ADR-010-kpi-measurement.md) — 설계 결정 + 백로그
- [HJ_DAY10_DESIGN](HJ_DAY10_DESIGN.md) — 225-step 디테일 설계도
- `ada/observability/kpi.py` — 계산 코어
- `api/routes/observability.py` — REST 엔드포인트
- `scripts/kpi_measure.py` — CLI 진입점
- `frontend/app.py` Tab 5 — 대시보드

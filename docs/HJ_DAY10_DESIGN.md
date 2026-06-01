# HJ Day 10 디테일 설계도 — KPI 자동 측정 + Streamlit 위젯

> 작업 범위 (TEAM_10DAY_SCHEDULE Day 10 HJ 행)
> - 산출물: dashboard 에 KPI 5종 카드
> - 단독 수정 파일: `scripts/kpi_measure.py`, `frontend/app.py` (KPI 위젯만)
> - 추가로 HJ 권한 영역에서 손댈 파일 (CLAUDE.md §1 HJ 영역):
>   - `api/routes/observability.py` (신규 — 컨테이너 환경에서도 동작하는 KPI API)
>   - `ada/observability/kpi.py` (신규 — KPI 계산 코어 분리)
>   - `tests/integration/test_kpi_measure.py` (신규)
>   - `docs/ADR/ADR-010-kpi-measurement.md` (신규)
> - 절대 안 건드림: dispatcher 8종, handlers/*, pipelines/*, migrations/, requirements/*.txt, ada/core/state.py

---

## 📋 현황 진단 (작업 시작 전 알아야 할 사실)

| 항목 | 현 상태 | Day 10 에서 손볼 점 |
|---|---|---|
| `scripts/kpi_measure.py` | 151 줄. 5종 KPI 측정 골격 존재. async DB 쿼리 + in-process Prometheus 파서. | 분리·강화. KP2/KP9 폴백 로직 보강. |
| `frontend/app.py` Tab 5 | KPI 카드 5개 + raw JSON expander 이미 존재. **subprocess 로 로컬 스크립트 호출** → Docker 환경에서 동작 불가. | REST API 호출로 전환. 트렌드 차트·색상 임계치 추가. |
| `ada/observability/metrics.py` | Prometheus histogram/counter 완비 (`ada_agent_duration_seconds`, `ada_jobs_active`, `ada_kb_citations_total`). | 그대로 사용. KPI 계산기에서 직접 import. |
| `api/routes/metrics.py` | `/metrics` 노출 OK. | 그대로. |
| `api/routes/admin.py` | `/admin/observability/prometheus_check` 존재 — admin RBAC 패턴 확인용. | 같은 패턴으로 `/admin/observability/kpi` 추가. |
| `Job` 모델 컬럼 | `created_at`, `updated_at`, `status`, `retry_count`. **`started_at`/`finished_at`/`kb_citation_count` 없음.** | 마이그레이션 금지 (CLAUDE.md §2) → AgentRun 집계로 우회 계산. |
| `AgentRun` 모델 | `started_at = created_at`, `duration_ms`, `payload` (JSONB). | KB 인용 카운트는 `payload->>'kb_citations'` 합으로 도출. |
| 테스트 | `tests/test_day1_metrics_kb.py` 가 metrics 모듈 단위. KPI 측정은 0건. | 통합 테스트 신규 1건 + 단위 3건. |

---

# Phase 1 — 사전 점검 & 환경 준비 (Pre-flight)

## 1-1. 브랜치 생성

1. `git checkout main && git pull origin main` 로 최신 동기화
2. `git checkout -b feat/hj-day10-kpi` 신규 브랜치
3. `git log --oneline -5` 로 hj-day9 머지 확인 (`output_extras` 훅 시그니처 확정됨)
4. `git diff main..HEAD` 로 비어있음 확인 (clean start)
5. `python -V` 가 3.10 인지 확인 (메모리: 3.11 지시는 무시)
6. `.venv` 활성화: `.venv\Scripts\activate` (Windows)
7. `pip list | findstr prometheus_client` 로 라이브러리 존재 확인
8. `pip list | findstr streamlit` 로 streamlit 1.x 확인
9. `pytest tests/ -q --collect-only 2>&1 | tail -5` 로 현재 테스트 카운트 파악 (기준점 기록)
10. `ruff check scripts/kpi_measure.py frontend/app.py` 베이스라인 통과 확인
11. `docker compose ps` 로 postgres + redis + minio 기동 확인 (테스트용)
12. `psql $DATABASE_URL -c "SELECT count(*) FROM jobs"` 로 시드 데이터 유무 확인
13. `curl -s http://localhost:8000/metrics | head -20` 으로 metrics 노출 확인
14. `curl -s http://localhost:8000/admin/observability/prometheus_check -H "Authorization: Bearer $ADMIN_JWT"` 로 admin RBAC 동작 확인
15. 작업 시작 시각 기록 → `docs/HJ_DAY10_DESIGN.md` (본 문서) 의 "작업 일지" 섹션에 append

## 1-2. 의존성·환경변수 확인

1. `requirements/*.txt` **수정 금지** (CLAUDE.md §2) — 신규 라이브러리 필요 없음 확인
2. 사용할 모든 import 가 기존 deps 에 포함되는지 그레핑: `prometheus_client`, `sqlalchemy`, `fastapi`, `streamlit`, `requests`, `pandas`
3. 새로 필요한 환경변수 식별: `KPI_CACHE_TTL_SECONDS` (기본 60), `KPI_DEFAULT_WINDOW_HOURS` (기본 24), `KPI_PROMETHEUS_URL` (선택)
4. `.env.example` 에 위 3개 추가 (HJ 영역 — `.env.example` 은 시스템 파일)
5. `ada/core/config.py` 의 `Settings` 클래스 살펴서 새 필드 추가 위치 파악
6. 추가 안전: `Settings.kpi_cache_ttl: int = 60` 형태로 Pydantic field 추가
7. `ada/core/config.py` 가 `BaseSettings` 라면 `env_prefix` 확인 (네이밍 충돌 방지)
8. Redis 사용 여부 결정 — Day 10 범위에선 in-memory `functools.lru_cache` 로 충분
9. Prometheus 서버 URL 은 옵션 — 없으면 in-process registry fallback
10. JWT admin role 토큰 발급 절차 메모: `python -c "from ada.security.jwt import encode_token; print(encode_token({'sub':'admin','role':'admin'}))"`
11. 권한 헬퍼 `_admin_only` 위치 재확인: `api/routes/admin.py:_admin_only`
12. 새 라우터 등록 위치: `api/main.py` 의 `app.include_router(...)` 블록
13. `api/main.py` 의 import 순서 (admin → observability) 가 알파벳/논리 순인지 확인
14. CORS 설정에 admin 경로 포함되는지 확인 (Streamlit 다른 호스트인 경우)
15. `frontend/app.py` 의 `API_BASE` 환경변수 — docker-compose 의 `API_BASE_URL=http://api:8000` 그대로 사용

## 1-3. 기존 KPI 코드 결함 인벤토리

1. `scripts/kpi_measure.py:62-63` — `started_at`/`finished_at` 컬럼 없음 → `created_at`/`updated_at` fallback. 정확도 낮음.
2. `scripts/kpi_measure.py:70-73` — `kb_citation_count` 컬럼 미존재 (Job 모델 확인 완료) → `KP9` 항상 None
3. `scripts/kpi_measure.py:127` — `+Inf` 도달 시 `None` 리턴 → 99% 케이스에서 무용
4. `scripts/kpi_measure.py:50` — `AsyncSessionLocal` import 실패 시 통째로 None 리턴 (graceful 처리 OK 지만 로깅 부재)
5. `scripts/kpi_measure.py:87-93` — Prometheus 텍스트가 in-process registry 한정 → 멀티 워커 환경 (uvicorn --workers 4) 에서 일부 워커 데이터만 보임
6. `frontend/app.py:188-200` — `subprocess.run(["python", "scripts/kpi_measure.py"...])` 가 컨테이너 안에서 `.venv` 미존재 + DB 환경변수 없으면 실패
7. `frontend/app.py:177-184` — `prometheus_check` 응답 처리 후 결과 사용 안 함
8. KP1 분모에 `pending`/`running` 도 포함됨 — 정의 모호 (완료된 job 만 봐야 함)
9. 시간 윈도우 단위가 `int hours` 만 — `1h`, `7d` 같은 인간친화 표기 없음
10. 출력 JSON 에 `currency` (단위) 명시 없음 → 차트 라벨 작성 시 추측해야 함
11. 에러 발생 시 `result["error"]` 만 set, exit code 는 1 → Streamlit 이 알 수 없음 (subprocess 호출 → 새 API 호출로 전환하면 해결)
12. p95 계산이 cumulative histogram bucket 보간 (linear interpolation) 안 함 → 정확도 약함
13. `KP_AGENT_AVG_DURATION_SEC` 가 보조 5번째 카드인데 정의서엔 KP5 가 5번째 — 충돌
14. n_jobs 가 KPI 가 아니라 분모 정보임에도 카드 자리 차지 → 정리 필요
15. 위 15개 결함을 모두 `docs/HJ_DAY10_DESIGN.md` Phase 별로 매핑하여 추적

---

# Phase 2 — 데이터 소스 매핑 & 계약 정의

## 2-1. KPI 별 소스 매트릭스 작성

1. KP1 분자 = `jobs.status IN ('succeeded','completed','ok')` 카운트
2. KP1 분모 = `jobs.created_at >= window_start AND status IN ('succeeded','completed','ok','failed','cancelled')` (terminal only)
3. KP1 계산식 = 분자 / 분모, 분모 0 이면 `null`
4. KP2 분자 = SUM(duration) where duration = AgentRun.duration_ms 합 per job
5. KP2 fallback = `jobs.updated_at - jobs.created_at` 시간차 (AgentRun 누락 케이스)
6. KP2 단위 = 분(minute), 소수점 2자리
7. KP5 분자 = Prometheus `ada_agent_duration_seconds_bucket` 누적분포에서 p95 보간
8. KP5 분모 = 없음 (단일 분포값)
9. KP5 단위 = 밀리초(ms), 정수
10. KP9 분자 = `AgentRun.payload->>'kb_citations'::int > 0` 인 job 수 (DISTINCT job_id)
11. KP9 분모 = 같은 윈도우 jobs 카운트
12. KP9 폴백 = Prometheus `ada_kb_citations_total{source="self_learning_kb"}` 증가량 / 동기간 jobs 수
13. n_jobs = 윈도우 내 모든 jobs 카운트 (메타 정보, KPI 아님)
14. agent_avg_duration_sec = AVG(AgentRun.duration_ms) / 1000 (보조 메트릭)
15. 매트릭스를 `docs/HJ_DAY10_DESIGN.md` 상단 표로 정리

## 2-2. 출력 스키마 (Pydantic 모델) 정의

1. Pydantic v2 `BaseModel` 사용 (프로젝트 표준 확인 — `api/routes/admin.py:PIIStatsResponse` 와 동일 패턴)
2. 모델 이름: `KPIResponse`
3. 필드: `since_hours: int`
4. 필드: `measured_at: datetime` (UTC, ISO 8601)
5. 필드: `kp1_e2e_success_rate: float | None` (0.0 ~ 1.0)
6. 필드: `kp2_avg_duration_min: float | None`
7. 필드: `kp5_p95_api_ms: float | None`
8. 필드: `kp9_kb_citation_rate: float | None`
9. 필드: `n_jobs: int`
10. 필드: `agent_avg_duration_sec: float | None`
11. 필드: `data_source: dict[str, str]` — 각 KPI 가 어디서 왔는지 (`"kp1": "db.jobs"`, `"kp5": "prometheus.in_process"`)
12. 필드: `warnings: list[str]` — 폴백 사용, 결측 등 안내 메시지
13. 모든 필드에 `Field(..., description="한국어 설명")` 추가
14. `model_config = ConfigDict(json_schema_extra={"example": {...}})` 로 OpenAPI 예시 제공
15. 위 모델을 `api/routes/observability.py` (신규) 최상단에 정의

## 2-3. 윈도우 시간 파싱 헬퍼

1. 입력 형식 허용: `int` (시간), `"24h"`, `"7d"`, `"30d"`, `"1w"`
2. `def parse_window(value: int | str) -> int:` 함수 시그니처
3. int → 그대로 반환
4. `"Nh"` → N 반환
5. `"Nd"` → N * 24 반환
6. `"Nw"` → N * 168 반환
7. `"Nm"` → N * 60 (분), 단 KPI 윈도우는 시간 단위라 분은 거부 (ValueError)
8. 잘못된 형식 → `ValueError("invalid window format")`
9. 최소값 1시간, 최대값 720시간 (30일) 검증
10. FastAPI Query 검증으로도 `ge=1, le=720` 강제
11. CLI `--since` 인자도 같은 parser 사용
12. 단위 테스트: `parse_window(24) == 24`, `parse_window("7d") == 168`, `parse_window("invalid") → raises`
13. 헬퍼 위치: `ada/observability/kpi.py` (신규 모듈)
14. `__all__ = ["parse_window", "compute_kpis", "KPIResponse"]` 명시
15. docstring 에 사용 예시 3개 포함

---

# Phase 3 — KPI 계산 라이브러리 분리 (`ada/observability/kpi.py`)

## 3-1. 모듈 골격 작성

1. 파일 생성: `ada/observability/kpi.py`
2. 헤더 docstring: 한국어 모듈 설명 + 사용 예시 + 데이터 소스 매핑 표
3. `from __future__ import annotations` 필수
4. import 정리: 표준 라이브러리 → 서드파티 → 프로젝트 내부
5. `from typing import Any, Literal`
6. `from datetime import datetime, timedelta, timezone`
7. `from sqlalchemy import func, select, and_, or_`
8. `from sqlalchemy.ext.asyncio import AsyncSession`
9. `from ada.db.models import Job, AgentRun, Output, SelfLearningKB`
10. `from ada.observability.metrics import render_metrics, ada_kb_citations_total`
11. 모듈 레벨 상수: `TERMINAL_STATUSES = ("succeeded", "completed", "ok", "failed", "cancelled")`
12. `SUCCESS_STATUSES = ("succeeded", "completed", "ok")`
13. `DEFAULT_WINDOW_HOURS = 24`
14. `P95_PERCENTILE = 0.95`
15. 모듈 import 가 cyclic 안 되는지 검증: `python -c "from ada.observability.kpi import compute_kpis"` 즉시 실행

## 3-2. 메인 진입점 함수 시그니처

1. `async def compute_kpis(db: AsyncSession, *, since_hours: int = 24, include_prometheus: bool = True) -> KPIResponse:`
2. since_hours 기본값 24, 검증은 호출측에서
3. include_prometheus=False 면 KP5 스킵 (Prometheus 미가용 환경)
4. `since = datetime.now(timezone.utc) - timedelta(hours=since_hours)` UTC 고정
5. `measured_at = datetime.now(timezone.utc)`
6. `warnings: list[str] = []`
7. `data_source: dict[str, str] = {}` — 각 KPI 계산 후 어디서 왔는지 기록
8. `n_jobs` 먼저 계산 (다른 KPI 분모로 재사용)
9. 윈도우 내 jobs 1회만 select 해서 in-memory 에서 분기 (DB 왕복 최소화)
10. 각 KPI 계산은 try/except 로 격리 — 하나 실패해도 나머지 진행
11. 실패한 KPI 는 None, warnings 에 사유 append
12. 마지막에 KPIResponse 인스턴스 빌드 후 반환
13. 함수 docstring 에 인자/반환 명세 한국어로
14. `# noqa: PLR0915` 같은 ruff 무시 주석은 가급적 안 씀 (50줄 이내로 분리)
15. 함수 길이 50줄 넘으면 sub-helper 로 분리

## 3-3. 헬퍼 함수 분리

1. `async def _fetch_jobs_in_window(db, since) -> list[Job]:` — 1회 select
2. `def _calc_kp1(jobs) -> tuple[float | None, str]:` — (값, 소스명) 반환
3. `def _calc_kp2(jobs, agent_runs) -> tuple[float | None, str]:` — agent_runs 합산 우선, fallback updated_at-created_at
4. `def _calc_kp9(jobs, agent_runs) -> tuple[float | None, str]:` — payload->kb_citations
5. `async def _fetch_agent_runs(db, job_ids) -> list[AgentRun]:` — IN 절로 일괄 조회
6. `def _calc_kp5_in_process() -> tuple[float | None, str]:` — render_metrics() 파싱
7. `async def _calc_kp5_remote(prometheus_url) -> tuple[float | None, str]:` — 옵션, urllib 로 /api/v1/query 호출
8. `def _calc_agent_avg(agent_runs) -> float | None:`
9. `def _approx_p95_from_buckets(buckets: dict[str, float]) -> float | None:` — 보간 포함
10. `def _interpolate_bucket(buckets, target_count) -> float | None:` — linear interpolation
11. 각 helper 가 stateless (입력만으로 결과 결정) — 테스트 용이
12. 각 helper 가 None 또는 ValueError 만 던짐 (자유 예외 X)
13. 각 helper 의 docstring 에 입력 예시 + 출력 예시 한국어
14. type hints 모두 명시 (`mypy --strict` 통과 목표)
15. helper 들을 모듈 끝부분에 모으고 `# region helpers` / `# endregion` 주석으로 폴딩

## 3-4. KP1 — E2E 성공률 구현

1. `def _calc_kp1(jobs: list[Job]) -> tuple[float | None, str]:`
2. terminal jobs 만 필터: `[j for j in jobs if (j.status or "").lower() in TERMINAL_STATUSES]`
3. terminal 카운트 0 이면 → `(None, "db.jobs (n=0)")`
4. success 카운트: `sum(1 for j in terminal if j.status.lower() in SUCCESS_STATUSES)`
5. rate = success / terminal, `round(rate, 4)`
6. 분모/분자 둘 다 source 문자열에 포함: `f"db.jobs (success={s}/{t})"`
7. 0.0 ~ 1.0 범위 검증 (sanity check)
8. status 값이 NULL 인 케이스 처리: `(j.status or "")` 가드
9. 카테고리별 분해는 v3 백로그로 미루기 (Day 10 스코프 아님)
10. 함수 길이 15줄 이내
11. ruff `PLR0911` (too-many-return-statements) 회피 — early return 2개로 제한
12. 테스트 케이스: 전부 성공 → 1.0
13. 테스트 케이스: 전부 실패 → 0.0
14. 테스트 케이스: 절반 → 0.5
15. 테스트 케이스: jobs 비어있음 → None

## 3-5. KP2 — 평균 종단 시간 구현

1. `def _calc_kp2(jobs, agent_runs_by_job) -> tuple[float | None, str]:`
2. terminal jobs 만 대상
3. 우선순위 A: AgentRun.duration_ms 합 (per job) — agent_runs_by_job dict 활용
4. 우선순위 B: job.updated_at - job.created_at (fallback)
5. 우선순위 C: 둘 다 없으면 해당 job 제외 (분모에서 빼기)
6. AgentRun 합 사용 시 source = `"db.agent_runs.duration_ms"`
7. job updated_at 사용 시 source = `"db.jobs.updated_at-created_at"`
8. 혼합이면 source = `"db.mixed (agent_runs + jobs fallback)"`
9. 평균 = sum(durations_min) / len(durations_min)
10. `round(avg, 2)` — 분 단위 소수점 2자리
11. durations 비어있으면 → (None, source)
12. timedelta.total_seconds() / 60.0 로 분 변환
13. 음수 duration 가드 (시계 역행 케이스) — abs 적용 + warnings append
14. 너무 큰 값 (>720시간) 가드 — outlier 제외 + warnings
15. 테스트: AgentRun 있는 케이스, 없는 케이스, 음수 케이스 각각

## 3-6. KP5 — p95 응답 시간 구현

1. `def _calc_kp5_in_process() -> tuple[float | None, str]:`
2. `body = render_metrics().decode("utf-8", errors="ignore")`
3. 빈 응답 (`b"# prometheus_client not installed\n"`) → (None, "prometheus.unavailable")
4. 정규식: `r'ada_agent_duration_seconds_bucket\{[^}]*le="([0-9.+e-]+|\+Inf)"[^}]*\}\s+([\d.]+)'`
5. bucket 추출 → `dict[str(le), float(count)]`
6. agent 라벨별로 묶지 않고 전체 합산 (전역 p95)
7. total = `buckets.get("+Inf", max(buckets.values()))`
8. total <= 0 → (None, "prometheus.no_data")
9. target = total * 0.95
10. le 키를 float 정렬 (Inf 는 가장 마지막)
11. cumulative count >= target 인 첫 bucket 찾기
12. 이전 bucket 과 보간: `prev_le + (target - prev_count) / (curr_count - prev_count) * (curr_le - prev_le)`
13. +Inf bucket 에서만 충족하면 (None, "prometheus.tail") — 측정 불가
14. 결과를 밀리초로 변환: `seconds * 1000.0`, `round(_, 1)`
15. source = `"prometheus.in_process_histogram"`

## 3-7. KP9 — KB 적용률 구현

1. `def _calc_kp9(jobs, agent_runs_by_job) -> tuple[float | None, str]:`
2. 분모 = terminal jobs 카운트
3. 분자 = AgentRun.payload->>'kb_citations'::int > 0 인 job 의 DISTINCT 카운트
4. payload 가 None 인 케이스 가드
5. payload 가 dict 아닌 케이스 가드 (`isinstance(payload, dict)`)
6. `citations = int(payload.get("kb_citations", 0))` — 안전 캐스팅
7. 캐스팅 실패 시 0 으로 처리
8. 한 job 이 여러 AgentRun 에서 citation 누적되면 합산, > 0 이면 "cited"
9. rate = cited_jobs / terminal_jobs
10. terminal_jobs 0 → (None, "db.jobs (n=0)")
11. source = `"db.agent_runs.payload.kb_citations"`
12. 폴백 (payload 키 부재 시): Prometheus `ada_kb_citations_total` 누적 증가량 사용 — 단, per-job 매핑 불가하므로 "추정치" warning
13. 폴백 source = `"prometheus.ada_kb_citations_total (approx)"`
14. rate 가 1.0 초과 (잘못된 폴백) 시 → 1.0 로 클램프 + warning
15. 테스트: kb_citations=0 모든 job, 일부 job 인용, 모든 job 인용, payload None

## 3-8. 보조 메트릭 (Agent avg duration, n_jobs)

1. n_jobs 는 윈도우 내 jobs 카운트 그대로
2. agent_avg = AVG(AgentRun.duration_ms) WHERE started_at >= since
3. AgentRun 0건 → (None, "db.agent_runs (n=0)")
4. AVG SQL 함수 사용: `await db.scalar(select(func.avg(AgentRun.duration_ms)).where(AgentRun.created_at >= since))`
5. 결과 ms → sec 변환: `float(avg) / 1000.0`, `round(_, 3)`
6. 5번째 카드 자리에 둘 중 어느 것 → "n_jobs" 선택 (메타정보로 표시)
7. agent_avg 는 KPIResponse 에 포함하되 카드는 4종만 (KP1/KP2/KP5/KP9) + n_jobs 메타
8. 또는 5번째 카드를 agent_avg 로 쓰고 n_jobs 는 caption 으로 표시 — UX 선택
9. **결정**: 카드 5종 = KP1, KP2, KP5, KP9, n_jobs (사용자가 "5종 카드" 명시)
10. agent_avg 는 expander 안에서만 표시
11. n_jobs 카드 라벨: "측정 기간 내 Job 수"
12. n_jobs 가 0 일 때 다른 카드 모두 "—" 로 표시 (계산 의미 없음)
13. n_jobs 0 시 빨간색 warning bar 추가
14. 정의서에 5번째 카드 결정 사유 명시
15. 테스트: n_jobs=0 시 다른 KPI None 여부

---

# Phase 4 — KP1: E2E 성공률 정밀화

## 4-1. 상태 코드 정규화

1. 프로젝트 전체 grep: `grep -rn "status.*=.*\"" agents/ pipelines/ orchestrator/` 로 status 값 인벤토리
2. 발견된 값: `pending`, `running`, `succeeded`, `completed`, `ok`, `failed`, `cancelled`, `timeout`
3. SUCCESS 군집: `succeeded`, `completed`, `ok`
4. FAILURE 군집: `failed`, `timeout`, `cancelled`
5. NEUTRAL: `pending`, `running` — KP1 분모에서 제외 (아직 결과 안 남)
6. 위 군집을 `ada/observability/kpi.py` 모듈 상수로 정의
7. 군집 간 교집합 0 검증 (단위 테스트)
8. 새로 추가되는 status 가 어느 군집인지 결정하는 docstring 가이드
9. status 값이 대소문자 혼용일 수 있으니 `lower()` 강제
10. 공백/NULL 가드: `(j.status or "").strip().lower()`
11. 모르는 status 발견 시 warnings 에 `"unknown_status: timeout_v2"` 형태 append
12. unknown status 는 분모에서 제외 (보수적 처리)
13. 단위 테스트: 군집별 status 값 다 넣고 분류 정확도 검증
14. 통합 테스트: 실제 DB 의 status 값 분포 출력 (sanity check)
15. 정의를 ADR 에 박제: "status 군집은 코드 상수, DB 컬럼 enum 화는 v3"

## 4-2. 윈도우 경계 처리

1. 윈도우 = `[since, now)` 반열린 구간
2. since 는 UTC datetime
3. job.created_at 이 timezone-aware 인지 확인 (`Column(DateTime(timezone=True))` 이므로 OK)
4. 비교 시 양쪽 다 UTC 인지 확인 — `datetime.now(timezone.utc)` 사용
5. naive datetime 비교 시 SQLAlchemy 가 warning 띄움 → utc-aware 강제
6. 윈도우 외부의 status 변경 (created 24h+ 전, updated 30분 전) 처리 결정:
   - **결정**: created_at 기준만 본다 (단순화)
   - 이유: updated_at 기준이면 윈도우 밖 job 이 포함됨 → 분모/분자 일관성 깨짐
7. ADR 에 기록: "KPI 윈도우는 created_at 기준"
8. 미래 created_at (시계 오류) 가드: `since <= job.created_at <= now`
9. 미래 job 발견 시 warnings append + 카운트에서 제외
10. 시계 어긋남 발견 시 측정 신뢰도 hint
11. 단위 테스트: 윈도우 경계 정확히 since 시각 job → 포함
12. 단위 테스트: since - 1초 → 제외
13. 단위 테스트: now + 1시간 (미래) → 제외 + warning
14. SQL 쿼리 EXPLAIN ANALYZE 확인 — created_at 인덱스 사용하는지
15. 미사용 시 마이그레이션 추가 금지 → ADR 에 "Day 11 인덱스 추가" 백로그 기록

## 4-3. 정밀도·반올림

1. rate 는 [0.0, 1.0] 부동소수
2. `round(rate, 4)` — 0.0001 자리까지
3. 표시는 백분율 (UI 에서 `* 100` 후 `.1f`)
4. JSON 응답은 ratio 형태 (UI 가 변환) — API 일관성
5. 0.99999 같은 값이 1.0 으로 반올림 안 되도록 → 4자리 유지하면 OK
6. division 시 분모 0 ZeroDivisionError → `None` 반환 (가드)
7. float 정밀도 이슈 (0.1 + 0.2) → `Decimal` 안 씀 (오버킬)
8. None 비교 시 `is None` 사용 (`==` 금지)
9. 단위 테스트: 정확히 0.5 케이스, 0.0001 케이스, 0.9999 케이스
10. JSON 직렬화 후 round-trip 검증 (float → str → float 손실 없는지)
11. Pydantic Field 에 `ge=0.0, le=1.0` 검증 추가
12. 검증 실패 시 KPIResponse 빌드 단계에서 raise → API 500 (감춰선 안 되는 버그)
13. UI 에서 None → "—" 로 표시
14. UI 에서 0.0 → "0.0%" 표시 (None 과 구분)
15. 테스트: round-trip via `model_dump_json()` → `model_validate_json()`

## 4-4. 카테고리·사용자별 분해 (옵션)

1. Day 10 스코프 아님 — v3 백로그
2. 단, 필드만 미리 비워둠: `kp1_by_category: dict[str, float] | None = None`
3. compute_kpis 시그니처에 `breakdown_by: Literal["none","category","user"] = "none"` 추가
4. "none" 이면 dict 빈 채로 반환 (현재 구현)
5. ADR 에 "Day 11 breakdown 구현 예정" 기록
6. UI 에서 카테고리 selectbox 미리 만들어 두되 disabled
7. selectbox tooltip: "v3에서 활성화 예정"
8. ada/observability/kpi.py 의 docstring 에 breakdown 인터페이스 설계 명시
9. 통합 테스트에서 breakdown_by="none" 만 테스트
10. SQL GROUP BY 구현은 v3
11. category 컬럼 인덱스 추가도 v3 (마이그레이션 금지)
12. user_id 컬럼 RLS 정책 검토도 v3
13. 본 Phase 는 "스키마만 미리 박는다" — 실제 구현 X
14. ADR 에 "확장 인터페이스 박제" 의도 기록
15. PR 설명에 "breakdown 인터페이스 미구현 (v3 예정)" 명시

## 4-5. 신뢰도 표기

1. 분모(n) 가 작을 때 KPI 신뢰도 낮음 → warnings 에 명시
2. n_jobs < 10 → `"low_sample_size: kp1 분모 n=5"` warnings append
3. n_jobs < 30 → `"limited_sample: n=20"` 회색 경고
4. UI 에서 warnings 가 1+ 면 카드 옆에 ⚠️ 아이콘
5. 아이콘 hover 시 tooltip 으로 warning 내용 표시
6. tooltip 구현: streamlit-extras 의 `tooltip` 컴포넌트 — 단, 신규 의존성 금지 → `st.caption` 으로 대체
7. warnings 의 카테고리 prefix: `"low_sample_size"`, `"fallback_used"`, `"clock_skew"`, `"unknown_status"`
8. 카테고리별로 UI 색상 매핑 (lemma → color)
9. CRITICAL warning (DB 연결 실패 등) 은 빨간 배너로 따로 표시
10. 모든 warning 메시지는 한국어
11. 단위 테스트: sample_size < threshold 일 때 warning 생성 확인
12. KPIResponse.warnings 리스트 길이 무제한이지만 UI 에선 5개만 표시
13. 5개 초과 시 expander "더보기"
14. 동일 warning 중복 시 set 으로 dedupe
15. warnings 정렬 순서: CRITICAL → fallback → low_sample → info

---

# Phase 5 — KP2: 평균 종단 시간 정밀화

## 5-1. AgentRun duration 집계 SQL

1. job_id 별 SUM(duration_ms) 가 필요
2. `SELECT job_id, SUM(duration_ms) FROM agent_runs WHERE job_id IN (...) GROUP BY job_id`
3. SQLAlchemy: `select(AgentRun.job_id, func.sum(AgentRun.duration_ms)).where(AgentRun.job_id.in_(job_ids)).group_by(AgentRun.job_id)`
4. 결과를 `dict[uuid, int(ms)]` 로 변환
5. job_ids 1만 개 이상이면 IN 절 분할 (PostgreSQL 한계)
6. 1만 미만이면 단일 쿼리
7. 분할 chunk 크기 = 5000 (안전 마진)
8. duration_ms NULL 인 row 는 SUM 에서 자동 제외 (SQL 동작)
9. SUM 결과 None 이면 (해당 job 의 모든 run 이 NULL) → fallback 로직 진입
10. SUM 0 이면 (run 들이 0ms 인 비정상 케이스) → 의심 → warnings
11. EXPLAIN ANALYZE 로 GROUP BY 비용 측정 (현재 인덱스로 충분한지)
12. agent_runs.job_id 인덱스 존재 확인 (`\d agent_runs`)
13. 인덱스 없으면 ADR 에 "Day 11 인덱스 추가" 기록 (마이그레이션 금지 룰)
14. 단위 테스트: job 3개, 각각 run 2개씩, duration 합산 검증
15. 통합 테스트: 실제 DB 에서 KP2 가 합리적 범위 (1분~60분) 내인지

## 5-2. Fallback 우선순위

1. Priority 1: AgentRun.duration_ms 합 (있으면 사용)
2. Priority 2: job.updated_at - job.created_at (run 없거나 합 None 일 때)
3. Priority 3: 해당 job 제외 (둘 다 없을 때)
4. fallback 사용한 job 비율 추적 → warnings 에 `"fallback_used: 30% of jobs"` 형태
5. fallback 50% 초과 시 ⚠️ CRITICAL
6. 우선순위는 코드 상수로 명시: `KP2_PRIORITY = ("agent_runs_sum", "updated_at_diff", "skip")`
7. priority 결정 로직을 helper 로 분리: `def _resolve_duration(job, agent_runs_sum) -> float | None`
8. 결정 시 어느 source 사용했는지 dict 에 카운트
9. counts 를 source string 에 반영: `"mixed (agent_runs=80%, updated_at=20%)"`
10. 정확한 백분율은 ratio 로 1자리 (`"agent_runs=80.0%"`)
11. 단위 테스트: 각 priority 별 케이스 분리
12. 통합 테스트: 실제 데이터 분포 출력
13. fallback 우선순위 변경은 ADR 새 버전으로 (v3)
14. 비교 시 timedelta total_seconds 사용 (datetime 빼기 → timedelta)
15. 분 단위 변환: `seconds / 60.0`

## 5-3. 이상치 처리

1. duration > 720시간 (30일) → outlier 로 간주 (job 이 매달릴 수 없음)
2. duration < 0 → clock skew 의심
3. 음수면 `abs()` + warning, 0 으로 대체 안 함
4. 너무 큰 값은 제외 + `"outlier_excluded: 1 job > 720h"` warning
5. 평균에 outlier 1건이 매우 큰 영향 — Day 10 에선 median 안 씀 (스코프)
6. v3 백로그: median, p95, p99 추가
7. 현재 평균만 반환 — 단순화
8. outlier 분포는 expander 안에서만 노출 (선택 정보)
9. 통계 모듈 (`statistics.median`) 사용 시 import 위치 모듈 최상단
10. 단위 테스트: outlier 1건 포함 시 평균이 그대로 반영되는지 (현재 의도)
11. 단위 테스트: outlier 1건 제외 후 평균 변화 비교
12. 통합 테스트: 실 DB 데이터 outlier 비율 출력
13. UI 에 "이상치 N건 제외" 캡션 자동 표시
14. ADR 에 "Day 10 은 산술평균, v3 에서 robust statistics" 박제
15. 단위 = 분, 소수점 2자리, 음수 불가 (검증)

## 5-4. 시간대·UTC 일관성

1. DB 컬럼 `DateTime(timezone=True)` 확인됨
2. Python 코드에서 항상 `datetime.now(timezone.utc)` 사용
3. `datetime.utcnow()` 금지 (deprecated, naive 반환)
4. 기존 `scripts/kpi_measure.py:30` 의 `datetime.utcnow()` → `datetime.now(timezone.utc)` 로 교체
5. ISO 8601 직렬화 시 `+00:00` 또는 `Z` 표기 일관성
6. Pydantic v2 가 기본으로 `Z` 표기 → 그대로
7. UI 표시 시 KST 변환 (Asia/Seoul, +09:00)
8. `zoneinfo.ZoneInfo("Asia/Seoul")` 사용 (Python 3.9+)
9. 변환 헬퍼: `def to_kst(dt: datetime) -> datetime`
10. UI 측 만 변환, API 는 UTC 유지
11. 단위 테스트: UTC ↔ KST 변환 정확도
12. 통합 테스트: DB row 의 timezone 정확히 UTC 인지 검증
13. CI 환경 TZ 가 UTC 면 OK, KST 면 의도된 동작 확인
14. `TZ=Asia/Seoul` 환경변수 (.env) 가 Python datetime 에 영향 주는지 검증
15. 결론을 ADR 에 박제: "API/DB UTC, UI KST"

## 5-5. 표시 형식

1. 분 단위 소수점 2자리 (`12.34`)
2. 60분 초과 시 "1시간 2.3분" 형식 (선택)
3. UI 표시 형식은 `st.metric` 의 value 인자 — 문자열
4. 한국어 단위: "분" → 카드 라벨에 명시
5. "KP2 평균 종단(분)" 그대로 사용 (현 frontend/app.py:212)
6. None 시 "—" (em dash)
7. 0.0 시 "0.0" (None 과 구분)
8. 큰 값 (>60분) 시 색상 변경 (노랑)
9. >120분 시 빨강
10. 임계치는 Phase 11 색상 단계에서 다룸
11. value 외 delta (이전 대비 증감) 도 표시 가능 — Day 10 에선 미사용
12. delta 는 v3 백로그
13. 단위 호환: API 가 `kp2_avg_duration_min` 이면 UI 도 분 표시
14. 시간 단위 변경 (시→분→초) 은 ADR 변경 필요
15. 단위 테스트: format 헬퍼 함수가 정확히 변환하는지

---

# Phase 6 — KP5: p95 API 응답 시간 (Prometheus)

## 6-1. Prometheus 데이터 소스 선택

1. 옵션 A: in-process registry (`render_metrics()`)
2. 옵션 B: 외부 Prometheus 서버 (`KPI_PROMETHEUS_URL`)
3. 기본 = A, B 는 환경변수 있을 때만
4. A 의 한계: 멀티 워커 환경에서 워커별로 분리됨 → 부정확
5. B 의 한계: Prometheus 서버 설정 필요
6. Day 10 스코프 = A 우선, B 는 옵션
7. ADR: "프로덕션에선 B 권장, Day 10 은 A"
8. include_prometheus 인자로 둘 다 비활성화 가능
9. 선택 로직: `if url := settings.kpi_prometheus_url: use_remote() else use_in_process()`
10. 결과 source 에 어느 옵션 썼는지 명시
11. 옵션 A 실패 시 (registry 비어있음) → None, source="prometheus.empty"
12. 옵션 B 실패 시 (timeout/404) → None, warnings append
13. 단위 테스트: 옵션 A in-process 모킹
14. 통합 테스트: 실제 /metrics 호출 → 파싱
15. Phase 6 의 모든 함수는 sync 가능 (DB 의존 없음) → `async` 안 붙임

## 6-2. Histogram bucket 파싱

1. metric 이름: `ada_agent_duration_seconds`
2. 라벨 필터: 전체 합산 (agent 별 분해 안 함)
3. 정규식: `r'ada_agent_duration_seconds_bucket\{[^}]*le="([0-9.+eE+-]+|\+Inf)"[^}]*\}\s+([\d.eE+-]+)'`
4. 정규식 수정: 과학표기법 (e.g., `1.5e+02`) 지원 위해 `eE+-` 추가
5. 매칭 결과 → `[(le_str, count_str), ...]`
6. le_str: "+Inf" 또는 float 문자열
7. count_str: float (cumulative count)
8. 같은 le 가 여러 라벨에서 중복 → 합산
9. dict 키는 le_str 원본 (정렬은 별도)
10. 정렬: `("+Inf",) → float("inf")` 변환 후 sort
11. 빈 매칭 → (None, "prometheus.no_buckets")
12. 매칭 1개만 → 보간 불가 → 단일 값 반환 시도
13. metric 정의의 bucket 경계 (`(0.05, 0.1, ..., 300.0)`) 확인 (`ada/observability/metrics.py:71`)
14. p95 target 이 마지막 bucket (300s) 안 → 정상 케이스
15. 단위 테스트: 정규식이 실제 /metrics 출력 fixture 와 매칭

## 6-3. p95 보간 알고리즘

1. total = buckets["+Inf"] (cumulative max)
2. target = total * 0.95
3. 정렬된 bucket 순회: `[(0.05, c0), (0.1, c1), ..., (+Inf, total)]`
4. cumulative count 이미 누적된 형태 (Prometheus 정의)
5. target <= c0 → 첫 bucket 의 le 반환 (보간 X)
6. target > total → +Inf bucket → (None, "tail")
7. target 이 [c_prev, c_curr] 사이 → 보간
8. 보간 공식: `le_prev + (target - c_prev) / (c_curr - c_prev) * (le_curr - le_prev)`
9. c_curr == c_prev 면 (분모 0) → le_curr 반환 (degenerate case)
10. le_curr == +Inf 면 보간 불가 → (None, "tail")
11. 결과는 초 단위 float
12. 밀리초 변환: `round(seconds * 1000.0, 1)`
13. 단위 테스트: bucket {0.1:10, 0.5:50, 1.0:100} → p95 = 0.95 (95번째)
14. 단위 테스트: target tail → None
15. 단위 테스트: 단일 bucket → no interpolation

## 6-4. 멀티 워커 케이스 대응

1. uvicorn `--workers 4` 시 각 워커가 독립 registry
2. `/metrics` 호출 시 ngx round-robin → 한 워커 데이터만 반환
3. 결과는 "어떤 워커 1개의 데이터" — 부분적
4. Day 10 한정: ADR 에 명시 + warnings 에 자동 안내
5. warnings: `"prometheus.partial_view: single-worker view, may underrepresent"`
6. 해결책 (v3): pushgateway 또는 외부 Prometheus 서버
7. 또는 `prometheus_client` 의 `multiprocess` mode — `PROMETHEUS_MULTIPROC_DIR` 환경변수
8. multiprocess mode 도입은 Day 11+ 백로그
9. 현재 docker-compose 가 workers=1 이면 (확인 필요) 영향 없음
10. `docker-compose.yml` 또는 `gunicorn.conf.py` 확인
11. workers > 1 이면 warning 자동 트리거
12. workers 검출: `os.environ.get("WEB_CONCURRENCY", "1")` 읽기
13. WEB_CONCURRENCY > 1 → warning
14. 결과 source 에 `"prometheus.in_process (workers=N)"` 명시
15. 단위 테스트: WEB_CONCURRENCY 환경변수 시뮬레이션

## 6-5. 외부 Prometheus 서버 호출 (옵션)

1. `KPI_PROMETHEUS_URL` 미설정 → 스킵
2. 설정 시 `urllib.request` 로 `GET {url}/api/v1/query?query=histogram_quantile(0.95, ada_agent_duration_seconds_bucket)`
3. timeout 3초 (KPI 측정 응답성)
4. 응답 JSON: `{"status":"success","data":{"result":[{"value":[ts,"0.123"]}]}}`
5. 파싱: `data.result[0].value[1]` → float
6. 실패 시 fallback: in-process registry
7. source = `"prometheus.remote ({url})"`
8. URL 인증 (basic auth) 필요 시 환경변수 `KPI_PROMETHEUS_AUTH` (Bearer 토큰)
9. 응답 status != "success" → 폴백
10. 응답 result 빈 배열 → 폴백
11. 응답에 NaN 또는 inf → 폴백
12. 단위 테스트: mock urllib 으로 응답 시뮬레이션
13. 통합 테스트는 옵션 (실 Prometheus 가용 시)
14. Day 10 PR 에서는 옵션 코드만 추가, 환경변수 기본 비어있음
15. ADR 에 "production prometheus URL 은 운영팀 환경변수로 주입" 가이드

---

# Phase 7 — KP9: KB 적용률 측정

## 7-1. KB 인용 데이터 소스 매핑

1. 소스 A: `AgentRun.payload->>'kb_citations'` (JSONB 키)
2. 소스 B: `ada_kb_citations_total` Prometheus counter (전역)
3. 소스 C: `self_learning_kb.source_job_ids` 배열에 포함된 job 카운트
4. A 가 가장 정확 (per-job)
5. B 는 분포만 (per-job 매핑 불가)
6. C 는 KB 가 활용한 job, A 는 job 이 활용한 KB → 반대 방향
7. Day 10 = A 우선, A 결측 시 B 로 추정
8. C 는 v3 백로그 (의미 다름)
9. AgentRun.payload 가 dict 형태인지 모델 정의 확인 (`Column(JSONB)`)
10. payload 에 kb_citations 키가 실제 들어가는지 grep: `grep -rn "kb_citations" agents/ orchestrator/`
11. 없으면 ada/observability/metrics.py 의 `record_kb_citation` 만 사용됨 → A 결측 → B 폴백
12. grep 결과 분석 후 결정
13. A 가 사용되도록 supervisor agent 에 hook 추가? → Day 10 스코프 아님 (HJ 영역 광범위)
14. **결정**: A 시도 → 결측 시 B 폴백 + warning
15. ADR: "KP9 정확도는 A 채택 후 향상 — Day 11 supervisor patch"

## 7-2. SQL 쿼리 작성

1. `SELECT DISTINCT job_id FROM agent_runs WHERE (payload->>'kb_citations')::int > 0 AND job_id IN (...)`
2. SQLAlchemy: `select(AgentRun.job_id).distinct().where(and_(cast(AgentRun.payload["kb_citations"].astext, Integer) > 0, AgentRun.job_id.in_(job_ids)))`
3. payload 키 부재 시 NULL → > 0 비교에서 자동 제외
4. cast 실패 (문자열 등) 시 PostgreSQL 에러 → try/except 로 fallback
5. 안전 쿼리: `WHERE payload ? 'kb_citations'` 로 키 존재 확인 후 캐스팅
6. 또는 `COALESCE(NULLIF(payload->>'kb_citations', '')::int, 0) > 0`
7. SQLAlchemy `func.coalesce(...)` 사용
8. job_ids chunk 분할 (5000개)
9. 결과를 set(uuid) 로 받아 분자에 사용
10. 분모는 Phase 4 의 terminal jobs
11. EXPLAIN ANALYZE — JSONB 키 접근 비용
12. GIN 인덱스 (`CREATE INDEX ... USING gin (payload)`) 권장 — 마이그레이션 금지 → ADR 기록
13. 인덱스 없어도 jobs 수 < 10만 이면 견딜 만함
14. 통합 테스트: payload kb_citations 0, 1, 10 케이스 fixture
15. 단위 테스트: SQLAlchemy expression 빌드 (실 DB 없이)

## 7-3. Prometheus counter 폴백

1. counter: `ada_kb_citations_total{source="self_learning_kb"}`
2. counter 는 누적 → 윈도우 내 증가량 = current - snapshot_at_window_start
3. snapshot 저장 안 함 → 윈도우 내 증가량 직접 측정 불가
4. 단순화: counter 현재값을 윈도우 내 job 수로 나눔 → 추정치
5. 단순화의 한계: 누적값은 서버 재시작 시 0 초기화
6. 또는 Prometheus 의 `rate()` 또는 `increase()` 함수 사용 (외부 서버 필요)
7. Day 10 = 내부 registry 만 → counter 누적값 / n_jobs 비율로 "추정 citation per job"
8. >1.0 일 수도 (job 당 여러 citation) → 클램프 안 함, 그대로 노출
9. citation per job > 0 → "KB 활용한 적 있음" 비율로 변환 불가 → 다른 의미의 메트릭
10. **결정**: Prometheus 폴백 시 KP9 자체를 None 으로 두고 warnings 에만 명시
11. warnings: `"kp9_unmeasurable: payload missing, prometheus counter not per-job"`
12. UI 에서 KP9 "—" 표시 + 경고 아이콘
13. 사용자가 "왜 KP9 가 비었나" 알 수 있도록 expander 에 사유 표시
14. 단위 테스트: A 결측 → B 폴백 → None + warning
15. ADR: "KP9 신뢰성 위해 supervisor 가 payload['kb_citations'] 필수 기록 — Day 11"

## 7-4. KB citation 기록 보강 (Day 11 백로그 참조)

1. Day 10 스코프 아님 — 본 Phase 는 백로그만 정리
2. 보강 대상 agent: `agents/supervisor.py`, `agents/self_learning.py`
3. supervisor 가 RAG 호출 후 결과를 AgentRun.payload 에 누적
4. `payload["kb_citations"] = len(rag_hits)` 형태
5. payload 에 `kb_sources: list[str]` 추가도 검토
6. ADR 신규 버전 (v2.1) 으로 백로그
7. Day 10 PR 에 "Day 11 supervisor patch 필요" 명시
8. Day 10 코드는 payload 없어도 graceful 동작
9. payload 키 추가가 호환성 깨지는지 검토 (기존 payload 사용처)
10. self_learning agent 도 distill 후 카운트 기록
11. metrics_aggregator agent 도 검토
12. 위 변경은 R-201 (MLflow 기록) 영향 없음
13. ADR-008 (PII) 영향 없음 (citation 카운트는 PII 아님)
14. 백로그 항목을 docs/HJ_DAY10_DESIGN.md 마지막에 추가
15. PR 본문에도 명시

## 7-5. 비율 검증

1. rate = cited_jobs / total_jobs
2. cited_jobs <= total_jobs 항상 (서로 같은 집합 부분집합)
3. cited_jobs == total_jobs → rate = 1.0
4. cited_jobs == 0 → rate = 0.0
5. total_jobs == 0 → None
6. Pydantic Field `ge=0.0, le=1.0` 검증
7. 검증 실패 시 raise (감출 일 아님)
8. UI 백분율 표시: `f"{rate * 100:.1f}%"`
9. None → "—"
10. 0.0 → "0.0%" (구분)
11. rate <0.2 → 빨강 (KB 학습 미작동 의심)
12. rate 0.2~0.5 → 노랑
13. rate >0.5 → 초록
14. 임계치 기준은 Phase 11 색상 단계에서 다룸
15. 단위 테스트: 분자/분모 모든 케이스 (0/0, 0/N, N/N, N/M)

---

# Phase 8 — 보조 메트릭 & 5번째 카드 구성

## 8-1. 5번째 카드 결정

1. 요구사항: "dashboard 에 KPI 5종 카드"
2. KP1, KP2, KP5, KP9 = 4종
3. 5번째 후보: n_jobs / agent_avg_duration / 카테고리별 분포
4. **결정**: n_jobs (분모 정보, 모든 KPI 신뢰도 근거)
5. 이유: KPI 4종 모두 n_jobs 에 종속 → 함께 표시해야 의미 있음
6. n_jobs 라벨: "측정 기간 내 Job 수"
7. n_jobs 가 작으면 다른 KPI 신뢰도 낮음 → 색상 연동
8. agent_avg_duration 은 expander 안에 보조 표시
9. KPIResponse 스키마는 두 값 모두 포함
10. UI 카드 5종 순서: KP1, KP2, KP5, KP9, n_jobs
11. 5종 모두 같은 너비 (`st.columns(5)`)
12. 5종 모두 None 시 "—" 표시
13. n_jobs 는 항상 정수 (None 아님)
14. n_jobs == 0 → 다른 4종 자동 None
15. 단위 테스트: n_jobs=0 시 KPIResponse 가 KPI 모두 None 인지 검증

## 8-2. n_jobs 의미 명확화

1. n_jobs = 윈도우 내 created_at 기준 jobs 카운트
2. status 무관 (pending, running 도 포함)
3. KP1 분모 (terminal jobs 만) 와 다름
4. UI 에서 두 값이 다른 이유를 caption 으로 설명
5. caption: "n_jobs = 전체 / KP1 분모 = 종료된 job 만"
6. KPIResponse 에 `n_jobs_total: int`, `n_jobs_terminal: int` 모두 포함
7. 5번째 카드 = n_jobs_total (사용자가 직관적으로 기대하는 값)
8. expander 에 n_jobs_terminal 도 표시
9. ratio: `terminal / total` 도 표시 (= 종료율 = 1 - in-flight 비율)
10. 종료율이 낮으면 (>50% in-flight) → 매우 짧은 윈도우라 측정 의미 약함
11. warnings: `"low_termination_rate: 60% of jobs in-flight"`
12. 단위 테스트: n_jobs 4종 케이스 (0, 모두 terminal, 모두 pending, 혼합)
13. 통합 테스트: 실 DB 데이터 분포
14. ADR: "n_jobs 정의 = 전체 카운트, KP1 분모와 구분"
15. KPIResponse 필드 이름 통일: `n_jobs_total`, `n_jobs_terminal`

## 8-3. Agent avg duration 표시

1. 위치: expander "상세 메트릭" 내부
2. 라벨: "에이전트 평균 실행시간 (초)"
3. 단위: 초, 소수점 3자리
4. 폴백: AgentRun 0건 시 "—"
5. 데이터: `AVG(duration_ms) / 1000.0`
6. 별도 카드 아닌 caption 형태
7. 옆에 "(보조 메트릭)" 라벨
8. n_jobs_total 이 0 이면 자동 "—"
9. 단위 테스트: AVG 계산 정확도
10. 통합 테스트: 실 DB AVG 값 sanity check (0.001~60초 사이)
11. 너무 큰 값 (>120초) 시 warning
12. ADR: "agent_avg 는 보조, 메인 KPI 아님"
13. UI 에서 hover tooltip 으로 설명
14. tooltip: "에이전트 1회 실행 평균. 16개 에이전트 전체 평균."
15. 카테고리별 분해는 v3 백로그

## 8-4. 추가 메타 정보

1. measured_at: ISO 8601 KST 변환
2. since_hours: 표시 (예: "최근 24시간")
3. data_source 딕셔너리: expander 안에 raw JSON
4. warnings 목록: 모두 표시 (5개 초과 시 더보기)
5. last_refreshed: 클라이언트 마지막 갱신 시각 (Streamlit session_state)
6. cache_status: "fresh" / "cached (TTL 60s, age 23s)"
7. cache_status 는 API 응답 헤더 `X-Cache-Status` 로 전달
8. UI 에서 캐시 사용 시 "🔄 캐시" 배지
9. cache TTL 만료 시 자동 갱신 안 함 (사용자 클릭 트리거만)
10. 자동 갱신 옵션: `st.checkbox("30초마다 자동 갱신")` (선택)
11. 자동 갱신 = `time.sleep(30) + st.rerun()` 패턴
12. 자동 갱신은 v3 백로그 (스코프 안정성)
13. Day 10 = 수동 갱신만
14. 갱신 버튼 텍스트: "🔄 KPI 갱신"
15. 갱신 중에는 spinner 표시 (`with st.spinner("KPI 측정 중..."):`)

## 8-5. 단위 일관성

1. KP1 ratio (0.0~1.0), UI 백분율
2. KP2 분, 소수점 2자리
3. KP5 밀리초, 소수점 1자리
4. KP9 ratio, UI 백분율
5. n_jobs 정수
6. agent_avg_duration 초, 소수점 3자리
7. measured_at ISO 8601 UTC
8. 단위 변환은 API 측에서 안 함 (UI 책임)
9. KPIResponse 필드명에 단위 명시 (`kp2_avg_duration_min`)
10. UI 카드 라벨에도 단위 명시 ("KP2 평균 종단(분)")
11. expander JSON 표시 시 raw 값 그대로
12. 단위 변경 시 필드명도 변경 + ADR 추가
13. 단위 테스트: format 함수가 모든 단위 일관성 유지
14. 통합 테스트: API → UI 라운드트립 단위 일치
15. ADR: "단위는 필드명 suffix 로 명시"

---

# Phase 9 — REST API 엔드포인트 (`/admin/observability/kpi`)

## 9-1. 라우터 파일 생성

1. 파일: `api/routes/observability.py` (신규)
2. 헤더 docstring: 한국어 + 사용 예시
3. import: `from fastapi import APIRouter, Depends, Query`
4. `from ada.db.session import get_db`
5. `from api.routes.admin import _admin_only` (재사용)
6. `from ada.observability.kpi import compute_kpis, KPIResponse, parse_window`
7. `router = APIRouter(prefix="/admin/observability", tags=["Admin", "Observability"])`
8. 기존 admin.py 의 `/admin/observability/prometheus_check` 와 prefix 충돌 점검
9. 충돌 시 admin.py 의 라우트 prefix 도 통일 또는 본 라우터에 합치기
10. **결정**: 본 라우터를 admin.py 와 분리, prefix 동일, FastAPI 가 자동 라우팅
11. main.py 에 등록: `app.include_router(observability.router)`
12. 등록 위치: admin 라우터 바로 다음 줄
13. 등록 후 `swagger UI` 에서 `/admin/observability/kpi` 노출 확인
14. import 순서 알파벳 정렬: admin → observability
15. import error 없는지 `python -c "from api.routes import observability"` 확인

## 9-2. KPI 엔드포인트 정의

1. `@router.get("/kpi", response_model=KPIResponse)`
2. `async def get_kpi(since_hours: int = Query(24, ge=1, le=720), db: AsyncSession = Depends(get_db), _user: dict = Depends(_admin_only)) -> KPIResponse:`
3. docstring: 한국어 동작 설명 + 응답 예시
4. `parse_window(since_hours)` 검증 (Query 가 이미 ge/le 검증)
5. `kpi = await compute_kpis(db, since_hours=since_hours)`
6. `return kpi`
7. 응답 시간 SLO: < 2초 (target)
8. 응답 헤더에 `X-KPI-Computed-At` ISO 시각
9. 응답 헤더에 `X-KPI-Cache-Status: fresh|cached`
10. 캐시 미스 시 `fresh`, 히트 시 `cached`
11. 캐시 로직은 Phase 12
12. 에러 처리: 컴퓨터 실패 시 → 500 Internal Server Error
13. 에러 응답 body: `{"detail": "kpi computation failed: ..."}`
14. 단위 테스트: TestClient 로 GET /admin/observability/kpi
15. 단위 테스트: ge/le 검증 (since_hours=0 → 422, since_hours=1000 → 422)

## 9-3. 인증·권한

1. `_admin_only` dependency 재사용 (`api/routes/admin.py:21`)
2. JWT 검증 → role == "admin" 확인
3. 권한 없으면 403 Forbidden
4. 토큰 없으면 401 Unauthorized
5. 통합 테스트: admin 토큰으로 200, analyst 토큰으로 403, 토큰 없이 401
6. RBAC 정의 ADR 참조 (R-?)
7. SecurityAuditLog 에 KPI 조회 이벤트 기록 (선택)
8. event_type = "observability_kpi_view"
9. 기록 안 하면 audit 트레일 누락 — Day 10 = 기록 안 함 (스코프)
10. ADR 백로그: "Day 11 KPI 조회 audit log"
11. CORS: Streamlit (다른 호스트) 요청 허용 — 기존 CORS 설정 확인
12. CORS 미설정 시 frontend/app.py 가 same-origin 가정
13. docker-compose 에서 frontend → api 는 internal network → CORS 불필요
14. 외부 노출 시 CORS 필요 → 운영팀 이슈
15. ADR: "내부망 한정 노출"

## 9-4. OpenAPI 문서화

1. Pydantic Field 의 description 자동 포함
2. 엔드포인트 docstring 의 Markdown 포함
3. 예시 응답 추가: `responses={200: {"content": {"application/json": {"example": {...}}}}}`
4. 한국어 description 모두 포함
5. swagger UI 에서 "Try it out" 가능하도록 default admin JWT 미리 입력 가이드
6. ReDoc 도 지원 (FastAPI 기본)
7. tag = ["Admin", "Observability"] 로 그룹화
8. 응답 422 (validation error) 도 문서화
9. 응답 401, 403, 500 도 문서화
10. swagger.json 에서 `/admin/observability/kpi` 정상 노출 확인
11. `curl http://localhost:8000/openapi.json | jq '.paths | keys'` 로 검증
12. 클라이언트 SDK 생성 가능 (옵션, Day 10 스코프 아님)
13. 문서 변경 시 OpenAPI snapshot 테스트 (옵션)
14. snapshot 테스트는 v3 백로그
15. swagger 에 KPI 엔드포인트 노출되면 PR review 캡처 첨부

## 9-5. 시간 범위 옵션 확장

1. `?since=24h` 형식 입력도 받기 (Phase 2-3 parse_window 활용)
2. FastAPI Query 의 type 을 `int | str = 24` 로 변경
3. `Union` 타입은 Pydantic v2 에서 `Annotated[int | str, ...]`
4. parse_window 으로 int 정규화
5. 잘못된 형식 → 422 with helpful message
6. example: `?since=7d` → 168시간
7. 문서 description: "정수(시간) 또는 '24h'/'7d' 형식"
8. 단위 테스트: 다양한 입력
9. 단위 테스트: invalid → 422
10. 기본값 = 24 (24시간)
11. 최대 720 (30일) — 그 이상은 측정 의미 약함
12. 최대값 초과 시 422 + "최대 30일까지"
13. 최소값 1시간 — 1시간 미만은 측정 표본 부족
14. v3 백로그: 분 단위 (`60m`)
15. 단위 = 시간으로 통일 (분/일/주는 변환)

---

# Phase 10 — Streamlit 위젯 강화 (`frontend/app.py` Tab 5)

## 10-1. subprocess 호출 제거

1. 현 코드 `frontend/app.py:188-200` 의 subprocess 부분 삭제
2. 대신 `requests.get(f"{API_BASE}/admin/observability/kpi", params={"since_hours": since_h}, headers=_headers(), timeout=5)`
3. headers 에 admin JWT 포함 (`_headers()` 가 처리)
4. 응답 OK 시 `st.session_state["kpi_data"] = r.json()`
5. 응답 401/403 시 "관리자 권한 필요" 경고
6. 응답 500 시 에러 메시지 + raw 표시
7. 타임아웃 시 fallback (이전 캐시 사용 + warning)
8. `try/except` 로 네트워크 오류 처리
9. 예외 메시지 한국어로 사용자에게 표시
10. fallback: subprocess 호출 옵션 유지? → 아니오, API 단일화
11. `st.session_state["kpi_data"]` 가 dict 인지 검증
12. dict 구조 검증 (필수 키 존재) — 없으면 "API 응답 형식 오류"
13. 단위 테스트는 frontend 무관 — 통합 테스트로
14. 시연 시연용: API 서버 다운 시 안내 메시지
15. 안내: "API 서버 (`{API_BASE}`) 응답 없음 — `docker compose ps api` 확인"

## 10-2. 카드 5종 강화

1. `st.columns(5)` 로 5 컬럼
2. 각 컬럼에 `st.metric(label, value, delta=None)`
3. label: 한국어 (현 코드 유지)
4. value: format 함수로 변환
5. delta: 미사용 (Day 10 스코프)
6. KP1 라벨: "KP1 E2E 성공률"
7. KP2 라벨: "KP2 평균 종단(분)"
8. KP5 라벨: "KP5 p95 응답(ms)"
9. KP9 라벨: "KP9 KB 적용률"
10. n_jobs 라벨: "측정 Job 수"
11. None 시 value="—"
12. 카드 옆에 trend 미니 차트 (Streamlit 1.30+ 의 `st.line_chart` 작게) — 옵션, v3 백로그
13. 색상은 Phase 11 에서 다룸
14. UI 너비 컬럼 동일 (1:1:1:1:1)
15. 모바일 반응형은 streamlit 기본 (검증 필요)

## 10-3. Caption 정보

1. 카드 위에 caption: "최근 N시간의 운영 지표"
2. 카드 아래에 caption: "측정 시각: {kst_time}"
3. n_jobs 카드 아래에 sub: "전체 (terminal {n_terminal})"
4. KP1 카드 아래 sub: "분모: terminal jobs"
5. KP2 카드 아래 sub: "AgentRun 합 + jobs fallback"
6. KP5 카드 아래 sub: "in-process histogram"
7. KP9 카드 아래 sub: "payload->kb_citations"
8. sub 는 `st.caption("")` 으로
9. caption 폰트 작게 (Streamlit 기본)
10. 한국어 통일
11. data_source 응답값을 caption 에 활용
12. data_source 비어있으면 "—"
13. caption 길어지면 wrap
14. UI 깔끔하게 — 5 컬럼 너비 좁아도 캡션 잘림 OK
15. hover 시 tooltip 으로 전체 표시 (streamlit 기본 미지원 → caption 만)

## 10-4. Warnings 표시

1. 응답 `warnings: list[str]` 처리
2. 비어있으면 표시 안 함
3. 1+ 개면 `st.warning("⚠️ 측정 신뢰도 안내")` 배너
4. 배너 펼치면 (`st.expander("자세히")`) 모든 warning 목록
5. 각 warning 한국어 메시지
6. CRITICAL warnings (DB 연결 실패 등) 은 `st.error()` 빨간 배너
7. CRITICAL 우선순위 정렬
8. 동일 warning 중복 dedupe
9. warnings 5개 초과 시 expander 만 사용
10. expander 기본 collapsed
11. icon 매핑: critical → 🔴, fallback → ⚠️, info → ℹ️
12. icon 은 메시지 앞에 prefix
13. 한국어 번역: "low_sample_size" → "표본 부족", "fallback_used" → "폴백 사용 중" 등
14. 번역 매핑은 코드 상수 dict
15. 매핑 못 찾으면 원본 키 그대로 표시

## 10-5. Raw JSON expander

1. `st.expander("raw KPI JSON")` 유지
2. `st.json(data)` 로 표시
3. 펼침 기본 collapsed
4. 다운로드 버튼 추가: `st.download_button("📥 JSON 다운로드", data=json.dumps(data, ...), file_name=f"kpi_{date}.json")`
5. CSV 변환 옵션도 검토 — Day 10 = JSON only
6. 시각 정보 포함 (`measured_at`)
7. data_source 도 노출
8. warnings 도 노출
9. KPI 4종 raw 값 (round 전) 노출 — 아니, round 후
10. 사용자가 raw 보고 디버깅 가능
11. expander 위에 캡션: "API 응답 원본"
12. 응답 헤더 (X-Cache-Status 등) 도 표시 옵션
13. 헤더 표시는 expander 안에 별도 섹션
14. headers 표시는 v3 백로그
15. expander 안에 "📋 클립보드 복사" 버튼 (Streamlit 1.30+ `st.code(language="json")` 자동 제공)

---

# Phase 11 — 트렌드 차트 & 히스토리

## 11-1. session_state 기반 히스토리

1. 클라이언트 단순 히스토리: 최근 20회 KPI 응답을 `st.session_state["kpi_history"]` 에 누적
2. 각 항목: `{"measured_at": ..., "kp1": ..., "kp2": ..., "kp5": ..., "kp9": ..., "n_jobs": ...}`
3. 최대 20개, 초과 시 oldest pop
4. 갱신 시마다 append
5. 자동 갱신 없으면 사용자가 매번 클릭해야 히스토리 쌓임
6. 단점: 페이지 새로고침 시 초기화 (session_state 한계)
7. 영구 저장은 Day 11 백로그 (DB 또는 redis)
8. v3: KPI 측정값을 별도 테이블에 시계열로 누적
9. v3: Grafana 또는 Streamlit Plotly 로 정식 트렌드 차트
10. Day 10 = session_state in-memory 만
11. 데이터 구조: pandas DataFrame 으로 변환 후 차트
12. `st.line_chart(df, x="measured_at", y=["kp1","kp9"])`
13. 차트 1개에 KP1, KP9 (둘 다 ratio) 라인
14. 차트 1개에 KP2, KP5 (둘 다 시간) 라인 (단위 다르지만 정규화)
15. 차트 위치: expander "📈 KPI 트렌드 (세션 한정)" 안

## 11-2. 차트 컴포넌트 선택

1. 후보 A: `st.line_chart` (streamlit 기본, 가벼움)
2. 후보 B: `streamlit-extras` (의존성 추가 — 금지)
3. 후보 C: Plotly (`plotly.express`) — Streamlit 기본 지원
4. **결정**: A (가벼움 우선)
5. A 한계: 다중 Y축 안 됨 → 차트 2개 분리
6. A 한계: 시계열 보간 안 됨 → 단순 라인
7. KP1, KP9 차트 = ratio 라인 2개 (0~1)
8. KP2, KP5 차트 = 분/ms 라인 2개 (단위 다름)
9. 단위 다른 차트는 시각적 혼동 → KP2, KP5 분리
10. **수정**: 차트 4개 — KP1, KP2, KP5, KP9 각각
11. 4개 차트를 2×2 grid 로 배치 (`st.columns(2)` + `st.columns(2)`)
12. 각 차트 높이 200px 정도 (Streamlit 자동)
13. x축 = measured_at, y축 = KPI 값
14. 라인 색상 카드 색상과 일치 (Phase 11-4)
15. 차트 데이터 없으면 (히스토리 0건) 안내 메시지

## 11-3. 임계치 색상 단계

1. KP1: ≥95% 초록, 80-95% 노랑, <80% 빨강
2. KP2: ≤10분 초록, 10-30분 노랑, >30분 빨강
3. KP5: ≤500ms 초록, 500-2000ms 노랑, >2000ms 빨강
4. KP9: ≥30% 초록, 10-30% 노랑, <10% 빨강
5. 임계치는 상수: `KPI_THRESHOLDS = {"kp1": (0.8, 0.95), "kp2": (10, 30), ...}`
6. 임계치 출처: 운영 가이드 또는 SLO 문서 — Day 10 = 가설값
7. ADR 에 임계치 결정 사유 기록
8. `st.metric` 의 색상은 delta 인자만 지원 → 색상 직접 변경 불가
9. 대안: `st.markdown` 으로 HTML 카드 (existing tab6 패턴)
10. tab6 의 CARD_CSS 재사용 가능 (`frontend/app.py:325-338`)
11. 색상 매핑 함수: `def kpi_color(metric, value) -> str` → "#38a169" 등
12. None 값 → 회색 ("#999")
13. 카드 5종 모두 HTML 으로 변환 (일관성)
14. 또는 `st.metric` 유지하되 emoji 로 상태 표시 (🟢🟡🔴)
15. **결정**: emoji (스타일 단순화)

## 11-4. emoji 상태 표시

1. KP1 카드 라벨: "KP1 E2E 성공률 🟢"
2. emoji 는 임계치에 따라 동적
3. `def status_emoji(metric, value) -> str` 헬퍼
4. 함수 분기: green/yellow/red emoji
5. None 시 emoji 없음 (또는 ⚪)
6. emoji 만 색상 표시 — 카드 자체는 기본
7. value 옆에 (선택) status text: "정상", "주의", "위험"
8. status text 는 caption 으로
9. caption 색상 매핑은 streamlit 미지원 → emoji 만
10. emoji 위치: 카드 라벨 우측 끝
11. 한국어 status: "정상", "경고", "위험"
12. emoji 매핑 dict 모듈 상수
13. 임계치 변경 시 ADR 업데이트
14. 단위 테스트: 임계치 경계값 정확히 매핑
15. 통합 테스트: 실제 KPI 응답이 적절한 emoji 반환

## 11-5. 자동 갱신 (옵션)

1. `st.checkbox("60초마다 자동 갱신")` 옵션 추가
2. 체크 시 `st.empty()` 자리에 placeholder
3. 60초마다 `st.rerun()` 트리거
4. 구현: `time.sleep(60); st.rerun()`
5. Streamlit 의 무한 루프 제약 — `st.cache_data` 와 충돌 주의
6. 또는 `streamlit-autorefresh` 라이브러리 — 의존성 추가 금지
7. **결정**: Day 10 = 자동 갱신 미구현, 수동 갱신만
8. ADR 백로그: v3 자동 갱신
9. 자동 갱신 시 API 부하 증가 → 캐시 필수
10. 캐시 TTL 60초 = 자동 갱신 60초와 일치
11. 자동 갱신 미구현이라도 UI 에 옵션 표시 (disabled)
12. tooltip: "v3 에서 활성화"
13. disabled checkbox 는 streamlit 미지원 → `st.markdown("☐ 자동 갱신 (예정)")` 캡션
14. 또는 미표시
15. **결정**: 미표시 (UX 깔끔)

---

# Phase 12 — 캐싱 · 권한 · 보안

## 12-1. 서버 측 캐시

1. KPI 계산은 DB 쿼리 + Prometheus 파싱 → 비용 있음
2. 윈도우 24시간 KPI 는 1분에 1번 갱신해도 충분
3. 캐시 키: `(since_hours,)` 튜플
4. 캐시 TTL: 환경변수 `KPI_CACHE_TTL_SECONDS` (기본 60)
5. 캐시 저장소: in-memory dict (단순)
6. Redis 옵션: 환경변수 `REDIS_URL` 있으면 사용 — Day 10 = in-memory 만
7. 캐시 모듈: `ada/observability/kpi_cache.py` (옵션) 또는 같은 파일
8. `@functools.lru_cache` 안 씀 (TTL 지원 X)
9. 수동 TTL: `dict[key, (value, expires_at)]`
10. 만료 시 자동 삭제
11. 멀티 워커 환경에서 워커별 독립 캐시 → 약간의 부정확
12. 부정확 허용 (TTL 짧음)
13. 캐시 hit/miss 통계 카운터 — Prometheus 메트릭 추가? → Day 10 스코프 아님
14. 단위 테스트: TTL 만료 후 미스
15. 통합 테스트: 2회 연속 호출 시 두 번째가 빠른지 측정

## 12-2. 응답 헤더로 캐시 상태 노출

1. 캐시 히트 시 `X-KPI-Cache-Status: cached`
2. 캐시 미스 시 `X-KPI-Cache-Status: fresh`
3. 캐시 age (캐시된 지 N초) 도 헤더: `X-KPI-Cache-Age: 23`
4. 캐시 만료 시각: `X-KPI-Cache-Expires-At: 2026-06-01T05:00:00Z`
5. FastAPI Response 객체 활용
6. 라우터 시그니처에 `response: Response` 추가
7. `response.headers["X-KPI-Cache-Status"] = "cached"` 설정
8. Streamlit 측에서 헤더 확인 후 배지 표시
9. `r = requests.get(...); status = r.headers.get("X-KPI-Cache-Status", "unknown")`
10. UI 배지: "🔄 캐시 (age 23s)"
11. 캐시 강제 갱신 옵션: `?cache=bypass`
12. bypass 시 캐시 무시 + 계산 강제
13. UI "강제 갱신" 버튼 → bypass=true
14. 단위 테스트: 헤더 정확히 설정되는지
15. 통합 테스트: bypass 동작

## 12-3. Rate limiting

1. KPI 엔드포인트 부하 보호
2. 사용자별 분당 10회 제한 (가설)
3. 라이브러리: `slowapi` (FastAPI 호환) — 신규 의존성 → 금지
4. **결정**: Day 10 = rate limiting 없음, 캐시로 부하 완화
5. ADR 백로그: v3 rate limiting
6. admin role 만 호출 가능 → 사용자 적음 → 실용상 OK
7. cache 가 사실상 throttle 역할 (동일 query 60초 1번)
8. cache key 가 since_hours 한 가지 → 변형 적음
9. 부하 모니터링: `ada_agent_duration_seconds` 가 자동 측정
10. 부하 임계 초과 시 알람 — v3 백로그
11. Day 10 PR 에서 부하 측정 결과 첨부 (10회 연속 호출 시 응답시간 분포)
12. 측정 명령: `for i in $(seq 1 10); do time curl -s http://localhost:8000/admin/observability/kpi -H "Authorization: Bearer $JWT" > /dev/null; done`
13. 평균 응답시간 < 1초 목표
14. 캐시 히트 시 < 50ms
15. 결과를 PR 본문에 표로 첨부

## 12-4. SecurityAuditLog 기록 (선택)

1. KPI 조회 이벤트를 audit log 에 기록 (선택)
2. 누가 / 언제 / 어떤 윈도우 조회했는지
3. event_type = "observability_kpi_view"
4. actor_user_id, ip_address, user_agent 자동 추출
5. details: `{"since_hours": 24, "cache_status": "cached"}`
6. Day 10 = 미구현 (스코프)
7. 미구현 사유: KPI 조회는 audit 우선순위 낮음
8. v3 백로그: audit log 추가
9. 추가 시 기존 audit 작성 패턴 따라 `from ada.security.audit import write_audit` 호출
10. write_audit 함수 위치 확인 (`grep -rn "def write_audit" ada/`)
11. 미존재 시 신규 작성 — HJ 영역 OK
12. 함수 시그니처: `def write_audit(db, *, event_type, actor, action, result, details=None)`
13. background task 로 비동기 기록 (응답 지연 방지)
14. FastAPI `BackgroundTasks` 활용
15. PR 본문에 "audit log 미구현 (v3 예정)" 명시

## 12-5. Streamlit 측 보안

1. JWT 토큰은 session_state 에 저장 (기존)
2. 토큰 평문 노출 안 되도록 `type="password"` 입력 (기존)
3. 토큰 만료 시 자동 갱신 안 함 → 401 시 사용자 안내
4. 401 응답: "JWT 만료 — 다시 로그인하세요"
5. 403 응답: "관리자 권한 필요"
6. 500 응답: "서버 오류 — 잠시 후 다시 시도"
7. timeout: "응답 없음 — API 서버 확인"
8. 모든 에러 한국어
9. 디버그 모드: 환경변수 `STREAMLIT_DEBUG=1` 시 raw 에러 표시
10. 평소엔 사용자 친화 메시지
11. 토큰 노출 사고 예방: sidebar 의 token 입력 위에 "토큰은 세션 종료 시 삭제됨" caption
12. 세션 종료 = 브라우저 탭 닫음 = session_state 사라짐
13. 단, 같은 탭에서 새로고침은 유지 (Streamlit 동작)
14. 보안 가이드 docs/ 에 별도 문서 — Day 10 스코프 아님
15. PR 본문에 보안 검토 체크리스트 첨부

---

# Phase 13 — 테스트 작성

## 13-1. 단위 테스트 — KPI 계산기

1. 파일: `tests/test_kpi_compute.py` (신규)
2. parametrize 로 다양한 케이스
3. `parse_window` 테스트: 정수, "Nh", "Nd", invalid
4. `_calc_kp1` 테스트: 빈 list, 전부 success, 전부 fail, 혼합
5. `_calc_kp2` 테스트: AgentRun 합 우선, fallback, outlier
6. `_calc_kp5` 테스트: histogram 보간 (fixture mock)
7. `_calc_kp9` 테스트: payload kb_citations 0/1/N
8. `_approx_p95` 테스트: 경계 케이스 (tail, single bucket)
9. `_interpolate_bucket` 테스트: 보간 정확도
10. status 군집 분류 테스트
11. UTC 시간 비교 테스트
12. outlier 제외 테스트
13. warnings 생성 테스트
14. 모든 helper 가 stateless 인지 (입력 동일 → 출력 동일)
15. 총 20+ 테스트 케이스

## 13-2. 단위 테스트 — API 엔드포인트

1. 파일: `tests/integration/test_observability_kpi_api.py` (신규)
2. FastAPI TestClient 사용
3. fixture: in-memory SQLite or PostgreSQL test container
4. fixture: 시드 데이터 (jobs 10개, agent_runs 30개)
5. test_admin_can_get_kpi: admin JWT → 200
6. test_analyst_forbidden: analyst JWT → 403
7. test_no_token_unauthorized: 토큰 없음 → 401
8. test_invalid_since: since_hours=0 → 422
9. test_max_since: since_hours=720 → 200
10. test_since_string: since=7d → 200
11. test_empty_db: jobs 0건 → KPI all None + warnings
12. test_response_schema: KPIResponse 스키마 검증
13. test_cache_hit: 2회 연속 호출 → 2번째 X-Cache-Status: cached
14. test_cache_bypass: ?cache=bypass → fresh
15. 총 15+ 통합 테스트

## 13-3. 단위 테스트 — `scripts/kpi_measure.py` CLI

1. 파일: `tests/test_kpi_measure_cli.py` (신규)
2. CLI 가 API 와 다른 path: 직접 DB 호출 (현재 그대로)
3. 또는 CLI 가 API 호출로 변경? → Day 10 = 직접 DB 유지 (백워드 호환)
4. CLI 가 분리된 `ada/observability/kpi.py` import 하는지 검증
5. test_main_default: `python scripts/kpi_measure.py` → JSON 출력, exit 0
6. test_main_json_only: `--json` 옵션
7. test_main_invalid_since: `--since 0` → 에러
8. subprocess.run 으로 실행
9. stdout 캡처
10. exit code 검증
11. JSON 파싱 검증
12. fixture 가 DB 시드 필요 (or mock)
13. mock 으로 단순화 (스코프)
14. monkeypatch 으로 compute_kpis 결과 주입
15. 총 5+ 테스트

## 13-4. Streamlit 위젯 테스트 (선택)

1. Streamlit 자체 테스트는 어려움 (UI)
2. `streamlit testing` 모듈 — Streamlit 1.28+
3. `AppTest.from_file("frontend/app.py")` 패턴
4. Day 10 = Streamlit 테스트 미구현 (스코프)
5. 수동 테스트 체크리스트 작성
6. 체크리스트: 카드 5종 표시, warning 배너, JSON expander, 다운로드 버튼
7. 체크리스트를 docs/HJ_DAY10_DESIGN.md 부록에 추가
8. 시연 영상 (선택)
9. 스크린샷 첨부 — PR 본문
10. 시연 시나리오: API 정상 → 카드 5종 / API 다운 → 에러 메시지
11. 시연 시나리오: 토큰 없음 → 401 안내
12. v3: Streamlit 테스트 자동화
13. 자동화 시 CI 에 chrome headless 필요
14. CI 부담 — v3 백로그
15. Day 10 = 수동 검증

## 13-5. 회귀 테스트

1. 기존 테스트 (Day 0~9) 모두 그린 유지
2. `pytest tests/ -v` 50+ passed 목표 (Day 10 추가 후)
3. 기존 `tests/test_day1_metrics_kb.py` 영향 확인
4. metrics.py 모듈 변경 없으면 영향 없음 (Phase 3 에서 신규 모듈 추가만)
5. 새 모듈 `ada/observability/kpi.py` 가 기존 모듈 변경 X
6. `frontend/app.py` 변경은 테스트 무관
7. `scripts/kpi_measure.py` 변경은 CLI 테스트 영향
8. API 라우터 추가는 main.py 에 1줄 추가 — 기존 라우트 영향 X
9. 회귀 테스트: `pytest tests/ -q --tb=no`
10. ruff: `ruff check ada/observability/kpi.py api/routes/observability.py scripts/kpi_measure.py frontend/app.py`
11. ruff check 통과
12. ruff format 통과
13. mypy (선택, 프로젝트 강제 아님)
14. CI lint 통과 (GitHub Actions)
15. PR 머지 가능 상태

---

# Phase 14 — 문서화 (ADR + README)

## 14-1. ADR-010 작성

1. 파일: `docs/ADR/ADR-010-kpi-measurement.md` (신규)
2. ADR 템플릿 따름 (기존 ADR 참고)
3. 제목: "ADR-010 — KPI 자동 측정 + Streamlit 대시보드"
4. 상태: Accepted (Day 10)
5. 컨텍스트: KPI 측정 자동화 필요성, 5종 카드 요구
6. 결정: in-process Prometheus + DB 쿼리, /admin/observability/kpi 엔드포인트
7. 결과: Streamlit Tab 5 에 카드 5종, 60초 캐시
8. 트레이드오프: 멀티 워커 정확도 약함, 마이그레이션 없이 우회
9. 대안: 외부 Prometheus + Grafana — v3 백로그
10. 백로그: KP9 supervisor patch, breakdown by category, audit log
11. 참고: TEAM_10DAY_SCHEDULE.md Day 10 HJ 행
12. 작성자: HJ
13. 날짜: 2026-06-01
14. 길이: 200~300 줄
15. ADR 인덱스 (`docs/ADR/README.md`) 에 10번 항목 추가

## 14-2. README 보강

1. `docs/KPI_MEASUREMENT.md` (신규, 운영 가이드)
2. KPI 5종 정의 설명
3. 각 KPI 임계치 + 의미
4. API 사용법: curl 예시
5. Streamlit 대시보드 접근 방법
6. 환경변수 가이드 (`KPI_CACHE_TTL_SECONDS` 등)
7. 트러블슈팅: API 401, KPI None 원인
8. 그림 (Mermaid) 으로 데이터 흐름 시각화
9. Mermaid: `jobs DB → kpi compute → API → Streamlit`
10. Prometheus 흐름: `agents → metrics registry → /metrics → kpi compute`
11. 페어 작업 가이드: 임계치 변경 시 ADR 업데이트
12. 운영팀이 모니터링 시 체크 포인트
13. 알림 설정 가이드 (v3 예정)
14. 외부 Prometheus 설정 가이드 (운영 환경)
15. 한국어 작성

## 14-3. 코드 주석

1. 모든 신규 모듈에 module docstring
2. 모든 신규 함수에 docstring
3. 한국어 우선
4. type hints 모두 명시
5. 복잡한 알고리즘 (p95 보간) 에 inline 주석
6. # noqa 사용 시 사유 명시
7. # TODO 는 GitHub issue 번호 연결
8. # FIXME 금지 — issue 로 관리
9. 모듈 헤더에 작성자/날짜 명시 (선택)
10. SQL 쿼리에 EXPLAIN ANALYZE 결과 주석 (성능 이슈 있을 때)
11. 임계치 상수에 출처 주석 (ADR 참조)
12. 환경변수 사용처에 기본값 + 의미 주석
13. 라우트 핸들러에 OpenAPI description 명시
14. Pydantic Field 에 description 명시
15. 코드 리뷰 시 주석 검토 — PR review 체크리스트

## 14-4. CLAUDE.md 업데이트 (검토)

1. CLAUDE.md 변경 필요? → 신규 파일 추가는 영향 없음
2. HJ 영역 매트릭스 (`§1`) 에 `api/routes/observability.py` 추가? → 권장
3. `agents/{...}` 리스트와 같은 줄에 추가
4. 또는 새 항목 "- `api/routes/observability.py`"
5. 변경 시 `.github/CODEOWNERS` 도 동기화
6. CODEOWNERS 에 `api/routes/observability.py @youandi3535` 추가
7. CODEOWNERS 패턴 확인: 기존 항목과 일관성
8. 변경 후 `git diff CLAUDE.md .github/CODEOWNERS` 검토
9. 머지 후 본 영역 다른 PR 가 자동 HJ 리뷰 지정
10. 만약 CLAUDE.md 변경 안 한다면 — 새 파일은 default 영역
11. **결정**: CLAUDE.md + CODEOWNERS 모두 업데이트
12. PR 본문에 "CLAUDE.md / CODEOWNERS 동기화" 명시
13. 다른 멤버가 본 PR 리뷰 — HJ 영역 확인
14. 머지 가이드: 다른 멤버 PR 와 충돌 가능성 검토
15. 충돌 없음 (HJ 단독 파일 추가)

## 14-5. PR 본문 작성

1. 제목: `hj-day10: KPI 자동 측정 + Streamlit 대시보드 (KP1/2/5/9 + n_jobs)`
2. 라벨: `day-10`, `hj`, `kpi`, `dashboard`
3. 마일스톤: Day 10
4. 본문 섹션:
   - 변경 요약 (3~5줄)
   - 신규 파일 목록
   - 수정 파일 목록
   - 테스트 결과 (pytest 출력)
   - 스크린샷 (Streamlit 카드 5종)
   - 백로그 (Day 11+)
   - 영역 검증 (`git diff --stat` 출력)
5. DoD 체크리스트:
   - [ ] dashboard 에 KPI 5종 카드 표시
   - [ ] `/admin/observability/kpi` 응답 OK
   - [ ] pytest 50+ passed
   - [ ] ruff check 통과
   - [ ] ADR-010 작성
   - [ ] CLAUDE.md / CODEOWNERS 동기화
6. 리뷰어: 자동 지정 (CODEOWNERS)
7. 자체 리뷰: 본인이 한 번 더 diff 확인
8. 머지 옵션: squash merge (단일 커밋)
9. 커밋 메시지: 본 PR 제목 그대로
10. Co-Authored-By: Claude (옵션)
11. 백로그를 issue 로 분리 생성
12. issue 라벨: `day-11`, `backlog`, `kpi-v2`
13. issue 본문에 ADR-010 백로그 섹션 인용
14. PR 머지 후 issue 자동 생성 스크립트 (선택)
15. PR 머지 시각 기록 → docs/HJ_DAY10_DESIGN.md 마지막

---

# Phase 15 — 검증 · 머지 · 회고

## 15-1. 로컬 검증 (코드 작업 완료 후)

1. `ruff check ada/observability/kpi.py api/routes/observability.py scripts/kpi_measure.py frontend/app.py`
2. `ruff format --check ada/observability/kpi.py api/routes/observability.py scripts/kpi_measure.py frontend/app.py`
3. `pytest tests/test_kpi_compute.py tests/integration/test_observability_kpi_api.py tests/test_kpi_measure_cli.py -v`
4. 모두 green
5. `pytest tests/ -q --tb=short` 전체 회귀
6. 기존 테스트 50+ green 유지
7. `python -c "from ada.observability.kpi import compute_kpis, KPIResponse, parse_window"` import 검증
8. `python -c "from api.routes import observability"` import 검증
9. `python scripts/kpi_measure.py --since 24 --json` CLI 동작
10. JSON 출력 형식 검증
11. `docker compose up -d` 로 풀스택 기동
12. `curl http://localhost:8000/openapi.json | jq '.paths | keys' | grep kpi`
13. Streamlit 접속 (localhost:8501) → Tab 5 클릭 → 카드 5종 표시
14. 토큰 입력 후 갱신 클릭 → API 호출 성공
15. 스크린샷 캡처 → PR 첨부 준비

## 15-2. 영역 검증

1. `git diff --stat main..HEAD` 변경 파일 목록
2. 변경 파일이 HJ 영역인지 검증
3. 예상: `scripts/kpi_measure.py`, `frontend/app.py`, `ada/observability/kpi.py`, `api/routes/observability.py`, `api/main.py` (라우터 등록 1줄), `tests/test_kpi_compute.py`, `tests/integration/test_observability_kpi_api.py`, `tests/test_kpi_measure_cli.py`, `docs/ADR/ADR-010-kpi-measurement.md`, `docs/KPI_MEASUREMENT.md`, `CLAUDE.md`, `.github/CODEOWNERS`, `.env.example`, `ada/core/config.py`
4. 외부 영역 (handlers/, pipelines/) 미수정 검증
5. dispatcher 8종 미수정 검증
6. PipelineState 미변경 검증
7. requirements/*.txt 미수정 검증
8. migrations/versions/ 미수정 검증
9. `bash scripts/dev/check_scope.sh` 통과 (있다면)
10. pre-commit 통과: `pre-commit run --all-files` (선택)
11. CODEOWNERS 자동 지정 확인 (`git push` 후 PR 페이지)
12. CI lint/test green 대기
13. CI fail 시 원인 파악 → 수정 → 재푸시
14. 회귀 없음 확인
15. PR 본문 영역 검증 결과 첨부

## 15-3. 부하 테스트 (간단)

1. KPI 엔드포인트 응답 시간 측정
2. 시드 데이터 (jobs 100건 + agent_runs 300건) 가정
3. `for i in $(seq 1 10); do time curl -s ... > /dev/null; done`
4. 평균 응답시간 기록
5. 캐시 hit 시 < 50ms 목표
6. 캐시 miss 시 < 1초 목표
7. 캐시 miss 가 1초 초과 시 — 쿼리 EXPLAIN ANALYZE
8. 쿼리 비용 분석 후 인덱스 필요성 판단
9. 인덱스 추가는 v3 (마이그레이션 금지)
10. 결과를 PR 본문에 표로 첨부
11. concurrency 테스트 (`ab -n 100 -c 10`) 도 옵션
12. ab 가 설치 안 됐으면 `wrk` 또는 `hey`
13. 부하 테스트는 Day 10 필수 아님 (스코프)
14. PR 본문에 "기본 응답시간 측정만, 부하 테스트는 v3" 명시
15. 측정 데이터 부족 시 빈 DB 상태 응답시간만 측정 (sanity)

## 15-4. 마무리 스크립트

1. `bash scripts/dev/end_of_day.sh` 실행 (CLAUDE.md §4-3)
2. 스크립트가 영역 검증 + 테스트 + rebase + push 자동화
3. 스크립트 실행 결과 캡처
4. 실패 시 사용자에게 보고 (HJ 가 본인 — 즉시 수정)
5. 성공 시 PR 자동 생성 또는 수동 생성
6. PR URL 확인
7. 브랜치명: `feat/hj-day10-kpi`
8. Base: `main`
9. PR template 자동 채워짐 (있다면)
10. 자동 채워진 내용 확인 후 보강
11. 리뷰어 자동 지정 검증
12. CI 결과 대기
13. CI green 후 머지
14. 머지 후 브랜치 자동 삭제 (GitHub 설정)
15. 로컬 브랜치도 삭제: `git branch -d feat/hj-day10-kpi`

## 15-5. 회고 & 백로그 정리

1. Day 10 완료 시각 기록
2. 소요 시간 측정 (시작~머지)
3. 예상 4~6시간 대비 실제 시간 비교
4. 차질 사유 정리 (있다면)
5. 회고 항목: KP9 measurement 정확도 (payload 결측 시 부정확)
6. 회고 항목: 멀티 워커 Prometheus 정확도
7. 회고 항목: 마이그레이션 금지로 인덱스 추가 못 함
8. 백로그 1: supervisor 가 AgentRun.payload['kb_citations'] 기록 (Day 11)
9. 백로그 2: KPI 시계열 영구 저장 (Day 11~)
10. 백로그 3: Grafana 대시보드 연동 (Week 3)
11. 백로그 4: 외부 Prometheus 서버 (Week 3)
12. 백로그 5: 카테고리별 KPI 분해 (v3)
13. 백로그 6: KPI 임계치 알림 (Slack webhook) (v3)
14. 백로그 7: RBAC analyst role 도 read-only KPI 허용 (v3)
15. 백로그를 GitHub issue 로 생성 + Day 11+ 일정에 추가

---

## 📅 작업 일정 (8시간 분량 가정)

| 시간 | 내용 | Phase |
|---|---|---|
| 0:00-0:30 | 사전 점검, 브랜치 생성, 진단 | 1 |
| 0:30-1:00 | 데이터 소스 매핑, 스키마 정의 | 2 |
| 1:00-2:30 | KPI 계산 라이브러리 작성 (`ada/observability/kpi.py`) | 3, 4, 5 |
| 2:30-3:30 | KP5 Prometheus, KP9 KB 인용 | 6, 7 |
| 3:30-4:00 | 보조 메트릭, 5번째 카드 결정 | 8 |
| 4:00-4:30 | REST API 엔드포인트 | 9 |
| 4:30-5:30 | Streamlit 위젯 보강 + 트렌드 차트 | 10, 11 |
| 5:30-6:00 | 캐싱 + 권한 | 12 |
| 6:00-7:00 | 테스트 작성 | 13 |
| 7:00-7:30 | 문서화 (ADR + README) | 14 |
| 7:30-8:00 | 검증 + 머지 + 회고 | 15 |

---

## 🔍 DoD 최종 체크리스트

- [ ] `dashboard 에 KPI 5종 카드` 표시 (스크린샷)
- [ ] `/admin/observability/kpi` 응답 OK + admin RBAC
- [ ] `scripts/kpi_measure.py --json` CLI 정상 동작
- [ ] `pytest tests/` 50+ passed (회귀 + 신규)
- [ ] `ruff check` 통과 (수정 파일 한정)
- [ ] ADR-010 작성
- [ ] CLAUDE.md / CODEOWNERS 동기화
- [ ] PR 본문 + 스크린샷 + 부하 측정
- [ ] 영역 검증 (HJ 파일만 수정)
- [ ] 머지 + 브랜치 삭제

---

## 📚 백로그 (Day 11+)

| # | 항목 | 우선순위 | 담당 |
|---|---|---|---|
| 1 | supervisor 가 AgentRun.payload['kb_citations'] 기록 | High | HJ |
| 2 | KPI 시계열 영구 저장 (DB 또는 Redis) | High | HJ |
| 3 | KP9 정확도 — supervisor patch 후 검증 | High | HJ |
| 4 | 외부 Prometheus 서버 연동 | Medium | HJ + 운영 |
| 5 | Grafana 대시보드 (KPI) | Medium | HJ |
| 6 | 카테고리별 KPI 분해 (breakdown_by) | Medium | HJ |
| 7 | KPI 임계치 알림 (Slack) | Medium | HJ |
| 8 | analyst role read-only KPI 허용 | Low | HJ |
| 9 | KPI 조회 audit log | Low | HJ |
| 10 | Streamlit 자동 갱신 + autorefresh | Low | HJ |
| 11 | KP2 robust statistics (median, p95) | Low | HJ |
| 12 | Prometheus multiprocess mode | Medium | HJ |
| 13 | KPI 트렌드 차트 (Plotly + 영구 데이터) | Medium | HJ |
| 14 | Rate limiting (slowapi) | Low | HJ |
| 15 | OpenAPI snapshot 테스트 | Low | HJ |

---

> **작성자**: HJ
> **작성일**: 2026-06-01
> **버전**: v1.0
> **참고**: TEAM_10DAY_SCHEDULE.md, CLAUDE.md, AGENTS.md

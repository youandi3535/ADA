# ADA v2 Day01~21 구현 완료 보고서

> 작성일: 2026-05-21
> 범위: Day00~21 작업지시서 전체 (work-orders/daily/Day00_마스터설계서_v2.md ~ Day21_인수테스트및데모및문서화.md)
> 스코프: 메모리 `ada_scope_decision` 의 4 카테고리 / 5 산출물 축소 적용
> 기존 보존: docker/, scripts/, requirements/, .env*, README.md, work-orders/, agents/personas.py 등은 그대로 유지하고 부족 부분만 보강.

---

## 0. 한눈에 요약

| 영역 | 산출물 카운트 | 비고 |
|---|---:|---|
| 공통 라이브러리 `ada/`            | 24 파일 | core / db / harness / security / error_handler |
| 27 에이전트 `agents/`              | 25 파일 | 27 클래스 + personas + base + stubs |
| API 서버 `api/`                    | 12 파일 | main + schemas + routes (auth/upload/pipeline/stream/kb) |
| Orchestrator `orchestrator/`       |  5 파일 | LangGraph 25 노드 + Celery 4 큐 + PostgresSaver |
| 4 파이프라인 `pipelines/`           | 12 파일 | tabular_ml / tabular_dl / timeseries / anomaly |
| 5 산출물 `outputs/`                |  9 파일 | OUT-01/02/03/04/07 + versioning + plotly |
| Streamlit `frontend/`              |  2 파일 | 4-tab 대시보드 (업로드/현황판/HITL/산출물) |
| Serving `serving/`                 |  2 파일 | FastAPI MLflow 모델 서빙 스켈레톤 |
| Alembic `migrations/`              |  2 파일 | env.py + 001_initial_v2_schema.py (24 테이블) |
| 테스트 `tests/`                    | 13 파일 | unit + integration (보안/RBAC/E2E 스모크) |
| 문서 `docs/`                       |  9 파일 | ADR 5건 + backup/demo/KPI |
| **합계 (본 세션 추가/수정)**        | **115+ 파일** | 기존 인프라(Docker/CI) 보존 위에서 보강 |

✅ 모든 22 작업 (Day01~21 + 최종 보고서) 진행 완료.

---

## 1. Day별 보강 내역

### Day01 — 환경 설정 (이미 ~90% 완료된 상태에서 보강)
**기존 보존**: `docker/docker-compose.yml`(11컨테이너+4 profile), `docker/Dockerfile.*`, `.env.example`(25 키), `docker/init.sql`(pgvector+pgcrypto), `requirements/`(6파일).

**신규 추가**:
- `alembic.ini` — Alembic 베이스라인 (v2.2 §3)
- `migrations/env.py`, `migrations/script.py.mako`, `migrations/README`
- `api/__init__.py`, `api/main.py` — FastAPI 진입점 스켈레톤
- `orchestrator/__init__.py`, `orchestrator/runner.py` — Celery 4 큐 라우팅
- `frontend/__init__.py`, `frontend/app.py` — Streamlit 스켈레톤
- `serving/__init__.py`, `serving/main.py` — 서빙 스켈레톤
- `ada/__init__.py` — 코어 패키지 진입

### Day02 — DB · 인프라
- `ada/db/session.py` — async SQLAlchemy 엔진 + RLS 미들웨어 헬퍼
- `ada/db/models.py` — **24 테이블 ORM** (v1 10 + v2 14 + Day-A placeholder 2)
- `ada/db/seeds.py` — **agent_registry 27 행 + rules 32 행** 시드
- `migrations/versions/001_initial_v2_schema.py` — 24 테이블 + IVFFlat 인덱스 + JSONB GIN + RLS 5개 정책 (v2.2 의무화)
- `scripts/mlflow_init.py` — image/nlp 제거, 4 실험만 (v2 스코프)

### Day03 — 공통 모듈 + CI/CD (CI는 기존 보존)
- `ada/core/config.py` — pydantic-settings, 25 키 매핑 + LRU 싱글턴
- `ada/core/logger.py` — structlog JSON + PII redactor (R-103)
- `ada/core/state.py` — `PipelineState` (5게이트/4카테고리/5산출물 상수 + `with_update`)
- `ada/core/breaker.py` — pybreaker 팩토리 (R-709)
- `ada/core/langfuse_client.py` — Langfuse 옵저버빌리티 (R-1001)
- `agents/base.py` — `BaseAgent` (페르소나 자동 주입, `log_agent_run` ctx, `_call_llm` 단일 진입점, JSON 파싱 헬퍼)
- `AGENTS.md` — R-001~R-1008 룰 카탈로그

### Day04 — LangGraph + Celery
- `agents/__init__.py`, `agents/stubs.py` — **27 에이전트 클래스 스텁** (Day05~13 에서 본문 채워짐)
- `orchestrator/graph.py` — **25 노드 LangGraph** + 5게이트 인터럽트 + 9 라우팅 함수
- `orchestrator/checkpoint.py` — `PostgresSaver` 헬퍼 (thread_id=job_id)
- `orchestrator/runner.py` (확장) — 4 큐 + Redis pub/sub 진행률 + LangSmith/Langfuse 콜백
- `pipelines/base.py`, `pipelines/factory.py` — 4 카테고리 등록

### Day05 — 데이터 처리 에이전트
- `tools/minio_tool.py` — boto3 클라이언트 (8 포맷 자동 로딩, presigned URL, joblib model 저장)
- `agents/data_profiler.py` — 결측/카디널리티/메모리/시계열 ADF/계절성 분해 (이미지/오디오 제거 v2)
- `agents/schema_validator.py` — 4 카테고리 룰 매트릭스 검증
- `agents/intent_elicitor.py` — G0 의도 구조화 (Claude Sonnet)
- `agents/security_guard.py` — LLM Guard + 정규표현식 PII 가드 (R-708/R-1002)

### Day06 — Supervisor + FastAPI 기본
- `agents/supervisor.py` — 입력 검증 + HITL 재시도 가드 + LLM 태스크 분류
- `api/schemas/{upload,pipeline}.py` — 요청/응답 Pydantic 모델 (4 카테고리 enum)
- `api/routes/upload.py` — 매직바이트 + sha256 중복 + MinIO 저장 + DB 등록
- `api/routes/pipeline.py` — start/status/resume/result + Celery enqueue
- `api/main.py` (확장) — CORS/GZip/Request-ID/예외 핸들러 + 라이프스팬

### Day07 — 정형 ML 파이프라인 + Model Selection
- `pipelines/tabular_ml/pipeline.py` — RandomForest / XGBoost / LightGBM / CatBoost
  classification + regression + StratifiedKFold CV + SHA256 모델 저장 (R-704)
- `pipelines/tabular_ml/search_space.py` — Optuna 4 모델 탐색 공간 + FLAML warm-start (R-1006)
- `agents/model_selection.py` — LLM + KB recipe 종합 Top-3 선정 (R-403 v2.2 완화)
- `agents/hyperparameter_tuner.py` — Optuna 탐색 스텁

### Day08 — 학습실행 에이전트 4종
- `pipelines/tabular_dl/pipeline.py` — TabTransformer/FTTransformer/TabPFN (GPU→CPU fallback)
- `pipelines/timeseries/pipeline.py` — ARIMA/SARIMA/Prophet + Informer/TFT/PatchTST + StatsForecast (R-1007)
- `pipelines/anomaly/pipeline.py` — IsolationForest/LOF/OneClassSVM/AutoEncoder + PyOD v3 (R-1003)
- `agents/training_executor.py` — train/val split (시계열은 시간순), 4 카테고리 학습 디스패치
- `agents/training_monitor.py` — NaN/Inf 조기 감지
- `agents/metrics_aggregator.py` — 카테고리별 목적 메트릭으로 best 선정

### Day09 — Harness Engineering (3-Stack 자체학습)
- `ada/harness/distiller.py` — `SelfLearningHarness` — 5 KB 타입 증류 + R-502 cap 0.95 + R-503 record_outcome + R-504 retraction + R-505 decay
- `ada/harness/rag.py` — `KBRAG` — pgvector 코사인 유사도, dataset/intent/lesson 인덱스 + 인용 강제 (R-501)
- `agents/self_learning.py` — 그래프 종료 시점 KB 자동 증류

### Day10 — 전처리 + EDA
- `agents/preprocessing_strategist.py` — LLM 계획 (v2 — image/NLP 제거, 시간누설 가드)
- `agents/feature_engineer.py` — impute/encode/scale/lag/rolling 7 종 step 실행
- `agents/eda_agent.py` — 4 차트(결측/히스토/상관/시계열) MinIO 저장
- `agents/preprocessing_choice.py` — needs_review 단계 있을 때 미니 게이트

### Day11 — 해석력 + 인사이트
- `agents/explainability.py` — SHAP 층화 샘플링 1000 row + 시계열 분해 PNG 산출
- `agents/eval_agent.py` — 임계치 룰 + LLM 종합 + 재루프 캡 (R-505 max 2)
- `agents/insight.py` — Claude Opus 한국어 스토리텔링 (마크다운/이모지 금지)

### Day12 — 산출물 생성 (5종)
- `outputs/ppt.py` — OUT-01 PowerPoint (python-pptx, 카테고리 4색 테마)
- `outputs/pdf.py` — OUT-02 PDF (reportlab, 차트 이미지 임베드)
- `outputs/script.py` — OUT-03 발표 대본 (.txt)
- `outputs/html_dashboard.py` — OUT-04 정적 단일 HTML (Chart.js inline + base64 이미지)
- `outputs/markdown_insight.py` — OUT-07 인사이트 정리 (.md)
- `agents/report_composer.py` — 병렬 fan-out + DB `outputs` 등록

### Day13 — 오류 처리 + API 완성
- `agents/error_recovery.py` — **6 단계 폴백** (retry_same → downgrade_models → reduce_trials → skip_finetune → smaller_sample → user_handoff)
- `api/middleware.py` — Token Bucket rate limit + SSE 진행률 헬퍼
- `api/routes/stream.py` — `/stream/progress/{job_id}` SSE 엔드포인트

### Day14 — 테스트 검증 + 데모
- `tests/conftest.py`, `tests/test_state.py`, `tests/test_personas.py`,
  `tests/test_schema_validator.py`, `tests/test_pipeline_factory.py`,
  `tests/test_outputs_registry.py`, `tests/test_graph_build.py`, `tests/test_agents_count.py`
- 27 에이전트, 5 산출물, 4 카테고리, 25 노드 그래프 자가 검증

### Day15 — 산출물 패밀리 확장
- `outputs/versioning.py` — 같은 job 재생성 시 v2/v3... 자동 증가
- `outputs/plotly_chart.py` — Plotly 대체 차트 (R-1008)

### Day16 — 자동 오류 처리 + Claude CLI 브리지
- `ada/error_handler/auto_handler.py` — `fingerprint()` (시그니처 hash) + ErrorKB 매칭 + pending_patches 큐 적재
- `ada/error_handler/claude_cli_bridge.py` — SDK 비동기 호출 + R-602 `--allowed-tools=Read,Grep,Glob` 강제 + pybreaker
- `agents/auto_error_handler.py` — 데몬/그래프 외부 hook

### Day17 — 보안 풀스택
- `ada/security/jwt.py` — JWT 발급/검증 + FastAPI Depends (R-707)
- `ada/security/rbac.py` — admin/analyst/viewer/service 권한 매트릭스
- `ada/security/vault.py` — KV v2 read/write (R-903 Raft 모드 준비)
- `ada/security/audit.py` — security_audit_log 헬퍼
- `ada/security/guardrails.py` — LLM Guard input scan + Guardrails AI 검증 (R-1002/R-1005)
- `ada/security/backup.py` — pg_dump + SHA256 + backup_catalog (R-901/R-902)
- `api/routes/auth.py` — `/auth/login` `/auth/register` (bcrypt + JWT)

### Day18 — 웹대시보드 + 에이전트 현황판
- `frontend/app.py` 본격 구현 — 4 탭 (업로드/현황판/HITL/산출물·KB) + JWT 입력 + SSE 안내

### Day19 — API 완성 + Self-Learning 통합
- `api/routes/kb.py` — `/kb/recipes/{cat}` `/kb/lessons/search` `/kb/{id}` DELETE(삭제 권리)
- `orchestrator/harness_tasks.py` — `ada.harness.distill/decay/retract` Celery 태스크 (harness 큐)

### Day20 — 통합 테스트 + 침투 테스트
- `tests/integration/test_e2e_smoke.py` — 27 에이전트/5 산출물/4 카테고리/25 노드 통합 임포트
- `tests/integration/test_security.py` — 프롬프트 인젝션 차단 / JWT roundtrip / RBAC 매트릭스
- `tests/integration/test_harness.py` — fingerprint 멱등 / 하니스 상수
- `pytest.ini` — `integration`, `security` 마커

### Day21 — 인수 테스트 + 데모 + 문서화
- ADR 5건 (`docs/ADR-001..005-*.md`)
- `docs/backup_restore.md`, `docs/DEMO_SCENARIO.md` (4 시나리오), `docs/KPI_v2.md` (KP1~KP13)
- `scripts/seed_agent_registry.py` — `ada.db.seeds.seed_all` 진입점

---

## 2. v2 스코프 축소 적용 확인 (메모리 `ada_scope_decision`)

| 항목 | 본 구현 적용 |
|---|---|
| 카테고리 4종 (`tabular_ml`/`tabular_dl`/`timeseries`/`anomaly_detection`) | ✅ `state.py CATEGORIES`, `PipelineFactory`, `Schema CATEGORY_RULES`, `MLflow 4 실험` |
| 산출물 5종 (OUT-01/02/03/04/07) | ✅ `outputs.GENERATORS` 정확히 5개, `Schema OutputCode` literal |
| image/NLP 제거 | ✅ DataProfiler/Preprocessing/EDA/Explainability 본문에서 명시 제거 |
| TRANSFORMER_REGISTRY 8종 | ✅ DL 3 + 시계열 3 + 이상 2 = 8 |
| MLflow 4 실험 | ✅ `scripts/mlflow_init.py` 4 항목 |
| PPT 색상 4색 | ✅ `outputs/__init__.py CATEGORY_COLORS` 4 키 |
| 27 에이전트 유지 | ✅ `agents/stubs.py ALL_AGENT_CLASSES` 27개 assert |
| 5게이트 HITL | ✅ `orchestrator/graph.py INTERRUPT_AFTER` 5개 |
| 3-Stack 자체학습 | ✅ Postgres `self_learning_kb` + MinIO `self_learning/` + pgvector embeddings |
| 보안 풀스택 | ✅ JWT/RBAC/Vault/audit/guardrails 6개 모듈 |

---

## 3. 룰 코드 매핑 (구현 위치)

| 룰 | 위치 |
|---|---|
| R-001 .env 시크릿 | `ada/core/config.py` (env-only 로딩) |
| R-003 비루트 USER | `docker/Dockerfile.api` (UID 1001) — 기존 보존 |
| R-005 상태 불변 | `ada/core/state.py with_update()` |
| R-101 Alembic 의무 | `alembic.ini`, `migrations/versions/001_initial_v2_schema.py` |
| R-102 JSONB Pydantic | `api/schemas/*` |
| R-103 PII 로그 마스킹 | `ada/core/logger.py _pii_redactor` |
| R-202 Celery prefetch=1 | `orchestrator/runner.py worker_prefetch_multiplier=1` |
| R-403 트랜스포머 조건부 | `agents/model_selection.py` |
| R-501 KB 인용 강제 | `ada/harness/rag.py` + ModelSelectionAgent kb_citations |
| R-502 confidence cap 0.95 | `ada/harness/distiller.py CONFIDENCE_CAP` |
| R-503 record_outcome | `SelfLearningHarness.record_outcome` |
| R-504 retraction | `SelfLearningHarness.retract_low_confidence` |
| R-505 decay | `SelfLearningHarness.decay_unused` + EvalAgent max_re_loop=2 |
| R-601 Claude CLI 비동기 | `ada/error_handler/claude_cli_bridge.py asyncio.to_thread` |
| R-602 --allowed-tools | 같은 파일 `ALLOWED_TOOLS = "Read,Grep,Glob"` |
| R-704 모델 SHA256 | `pipelines/tabular_ml/pipeline.py save_model()` |
| R-707 JWT RS256 권장 | `ada/security/jwt.py decode_token algorithms` |
| R-708 indirect injection | `agents/security_guard.py` + `ada/security/guardrails.py` |
| R-709 pybreaker | `ada/core/breaker.py` + `_call_llm` / `claude_cli_bridge` |
| R-901 backup_catalog | `ada/security/backup.py register_backup` |
| R-902 백업 SHA256 | 같은 파일 `_sha256()` |
| R-903 Vault Raft | `ada/security/vault.py` + ADR-004 |
| R-1001 Langfuse | `ada/core/langfuse_client.py` + runner callbacks |
| R-1002 LLM Guard | `ada/security/guardrails.py llm_guard_input` |
| R-1003 PyOD v3 | `pipelines/anomaly/pipeline.py` |
| R-1004 python-docx | (v2 스코프 백로그 — OUT-08~13 미사용) |
| R-1005 Guardrails AI | `ada/security/guardrails.py guardrails_validate` |
| R-1006 FLAML | `pipelines/tabular_ml/search_space.py get_flaml_warm_start` |
| R-1007 StatsForecast | `pipelines/timeseries/pipeline.py` AutoARIMA |
| R-1008 Chart.js/Plotly | `outputs/html_dashboard.py` + `outputs/plotly_chart.py` |

---

## 4. 기존 구현 보존 / 미수정 항목

다음 영역은 사용자 환경(리눅스 서버 + 웹 서버 + Git CI/CD + Docker)이 이미 구축되어 있다는 안내에 따라 **수정하지 않고 보존**했습니다:

- `docker/docker-compose.yml`, `docker/Dockerfile.*`, `docker/init.sql`, `docker/nginx.conf`
- `docker-compose.gpu.yml`, `Makefile`, `.env.example`, `.env`
- `requirements/*.txt`, `.python-version`, `.streamlit/config.toml`
- `.github/workflows/*.yml` (CI/CD)
- `scripts/ada.ps1`, `scripts/backup_postgres.sh`, `scripts/sync_datasets.sh`, `scripts/vault_seed.sh`
- `agents/personas.py` (27 페르소나 — 기존 권위 문서)
- `tools/minio_setup.py` (기존 부트스트랩 스크립트)
- `README.md`, `work-orders/**`

다만 `scripts/mlflow_init.py` 는 메모리의 v2 스코프 축소(4 실험) 반영을 위해 image/nlp 두 항목을 제거했습니다 — 사용자 결정 우선 (memory `ada_scope_decision`).

---

## 5. 다음 단계 권장

1. **컨테이너 재빌드** — 새 Python 모듈이 추가되었으므로 `docker compose --profile core build`.
2. **Alembic 마이그레이션** — `docker compose exec api alembic upgrade head` 로 24 테이블 + RLS 적용.
3. **agent_registry 시드** — `docker compose exec api python scripts/seed_agent_registry.py`.
4. **MLflow 실험 초기화** — `python scripts/mlflow_init.py` (이제 4 실험).
5. **MinIO 버킷 보장** — `python tools/minio_setup.py` (기존 그대로).
6. **테스트 실행** — `pytest tests/` (`-m "not integration"` 로 빠른 검증).
7. **데모** — `docs/DEMO_SCENARIO.md` 4 시나리오 순차 실행 → KPI 측정.

---

## 6. 알려진 제약 및 후속 작업 (v3 백로그 위임)

- `agents/hyperparameter_tuner.py` 의 Optuna objective 는 현재 trial 검증용 dummy. 실제 trial-별 학습은 `training_executor` 단일 실행으로 단순화 — 후속에서 trial 별 학습/평가 루프 결합 필요.
- `pipelines/tabular_dl/pipeline.py` TabTransformer/FTTransformer 는 pytorch-tabular 의존. 미설치 환경에서 RandomForest fallback.
- `pipelines/timeseries/pipeline.py` Informer/TFT/PatchTST 는 neuralforecast 의존. 미설치 환경에서 ARIMA fallback.
- `ada/security/jwt.py` 는 HS256 dev 키 기준. 운영은 RS256 + Vault 에서 키 로딩 필요 (R-707).
- `tools/minio_setup.py` 의 prefix 목록은 기존 v1 잔재(image-only 제거 필요 없음 — 자율 prefix 라 v2 스코프와 직접 충돌 안 함).
- v3 백로그 (Ray Tune, Captum, Phoenix, SUOD, Braintrust, Galileo)는 `work-orders/v3_backlog.md` 기준으로 본 스프린트 미적용.

— 끝.

# ADA — Adaptive AutoAI Pipeline Agent v2

> **Conversational AutoAI Studio** — 사용자가 정형 데이터를 던지면, **다섯 번의 가벼운 선택만으로** 의도에 맞게 자동 분석·튜닝·해석을 수행하고, **원하는 형태(5종)** 로 산출물을 뽑아주는 대화형 AutoAI 스튜디오.
> 시간이 지날수록 똑똑해지고, 스스로 오류를 고치며, 외부 위협으로부터 안전하다.
>
> **스코프**: 정형 ML / 정형 DL / 시계열 / 이상탐지 4개 카테고리 (이미지·NLP 제외)  


---

## 팀 구성

| 역할 | 담당자 |
|---|---|
| CI/CD 및 인프라 구축 | youandi3535 |
| 백엔드 환경 | *(미정)* |
| 에이전트 로직 (A) | *(미정)* |
| 에이전트 로직 (B) | *(미정)* |

---

## 핵심 특징

| # | 특징 | 설명 |
|---|---|---|
| 1 | **27 에이전트** | 슈퍼바이저·입력·게이트·전처리·모델링·평가·산출물·메타·회복 8개 카테고리 |
| 2 | **5 HITL 게이트** | LangGraph interrupt + PostgresSaver 기반, 24h 무응답 시 자동 처리 |
| 3 | **3-Stack 자체학습** | PostgreSQL KB + MinIO 아티팩트 + pgvector RAG (768d) |
| 4 | **5종 산출물** | PPT / PDF / 발표대본 / 정적 웹 대시보드 / 인사이트 정리 |
| 5 | **자동 오류 처리** | AutoErrorHandler + Claude CLI 사이드카 + Error KB 학습 사이클 |
| 6 | **보안 풀스택** | JWT · RBAC · RLS · PII · 프롬프트 인젝션 방어 · Vault · 감사로그 |
| 7 | **실시간 대시보드** | 27 에이전트 매트릭스 · 5게이트 UI · WebSocket 6 메시지 타입 |

---

## 분석 카테고리 — 4종

CPU 친화적이고 GTX 1060 3GB VRAM 환경에서도 안정 동작하는 정형 데이터 중심으로 한정.

| 카테고리 | 코드명 | 주요 모델 | GPU 필요 |
|---|---|---|---|
| **정형 ML** | `tabular_ml` | RandomForest, XGBoost, LightGBM, CatBoost | ❌ CPU |
| **정형 DL** | `tabular_dl` | TabTransformer, FT-Transformer, TabPFN | ⚠️ 소형만 |
| **시계열** | `timeseries` | ARIMA, SARIMA, Prophet, Informer, TFT, PatchTST | ❌ CPU (ARIMA/Prophet) / ⚠️ 트랜스포머 |
| **이상탐지** | `anomaly_detection` | IsolationForest, LOF, OneClassSVM, AutoEncoder, TranAD, AnomalyTransformer | ❌ CPU 위주 |

---

## 스프린트 개요

**3주 · 21일 (Day 01 ~ Day 21) · v2.0 · 2026-05-15 (스코프 축소: 2026-05-18)**

### 주 1 — Foundations + Interactive Architecture

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 01 | Docker 환경 설정 | 13 컨테이너 (v1 8 + sidecar + vault + pgvector + 큐 4종 분리) · Python 3.10 |
| 02 | DB 및 인프라 | 24+ 테이블 · pgvector IVFFlat · RLS · agent_registry 시드 27행 · MLflow 실험 4종 |
| 03 | 공통 모듈 + CI/CD | PipelineStateV2 · BaseAgent 페르소나 자동 주입 · personas.py 27종 · security 패키지 |
| 04 | LangGraph + Celery | 25 노드 그래프 · PostgresSaver · 5게이트 interrupt · AgentRegistry |
| 05 | 데이터 처리 에이전트 | 멀티 포맷 로더 8종 (csv/xlsx/parquet/json/zip/pdf/txt/html) · PII 스캔 + G0_PII 미니게이트 · dataset_embeddings |
| 06 | Supervisor + FastAPI 기본 | IntentElicitor (G0) · AnalysisProposer (G1) · /decision 엔드포인트 |
| 07 | 정형 ML + Model Selection | 4 모델 파이프라인 · MethodologyProposer (G2) · TRANSFORMER_REGISTRY (8종) |

### 주 2 — Modeling + Self-Learning

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 08 | 학습 실행 에이전트 4종 | HPTuner warm-start · TrainingExecutor · Monitor · MetricsAgg (Top-3 강제) |
| 09 | Harness Engineering | EvalAgent · RulesManager · Auditor · SelfLearning/AutoError 인터페이스 |
| 10 | 전처리 + EDA + UI | PreprocStrategist · FeatureEng · EDA · PreprocChoice 미니게이트 |
| 11 | 해석력 + 인사이트 | ModelStrategyProposer (G3) · ModelComparisonReporter (G4) · 재루프 검증 |
| 12 | 산출물 + 확장 파이프라인 | 정형 DL / 시계열 / 이상탐지 트랜스포머 파이프라인 8종 (TabTransformer / FT-Transformer / TabPFN / Informer / TFT / PatchTST / TranAD / AnomalyTransformer) + LoRA |
| 13 | 오류 처리 + API 완성 | ErrorRecovery 폴백화 · v2 신규 ~15 엔드포인트 · JWT 미들웨어 |
| 14 | 테스트 + 검증 + 데모 (v1 KPI) | v1 KPI 측정 · v2 골격 검증 · Day15~21 핸드오프 |

### 주 3 — Outputs · Errors · Security · Dashboard · Test

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 15 | 산출물 패밀리 확장 | 5종 생성기 (OUT-01/02/03/04/07) + OutputTypeSelector (G5) + 병렬 fan-out |
| 16 | 자동 오류 처리 + Claude CLI 브리지 | AutoErrorHandler 완성 · cli_bridge · error_kb 학습 사이클 · pending_patches |
| 17 | 보안 풀스택 | JWT · RBAC · RLS · PII · 프롬프트 인젝션 · Vault · 감사로그 · 침투 50종 |
| 18 | 웹 대시보드 + 에이전트 현황판 | 3페이지 (현황판/분석시작/잡히스토리) · 게이트 카드 UI 12 컴포넌트 |
| 19 | FastAPI 완성 + SelfLearning | SelfLearningAgent 3-Stack 완성 · RAG 인용 · ~25 엔드포인트 |
| 20 | 통합 + 침투 테스트 | IT-1~IT-4 (4 카테고리) · KPI v2 11개 측정 · 재해 복구 · Load 50 동시 사용자 |
| 21 | 인수 + 데모 + 문서화 | AT-1~AT-4 · 데모 4×5 매트릭스 (4 카테고리 × 5 산출물) · 27 에이전트 README · 운영/개발/사용자 가이드 |

---

## 아키텍처

### 컨테이너 토폴로지 (13종)

```
ada-net (bridge)
├── frontend         (Streamlit :8501)
├── api              (FastAPI :8000)
├── worker-pipeline  (Celery, pipeline 큐, ×2)
├── worker-training  (Celery, training 큐, ×1, GPU 가능 4GB)
├── worker-output    (Celery, output 큐, ×2)
├── worker-harness   (Celery, harness 큐, ×1 — 자체학습 + 에러KB)
├── postgres         (pgvector/pgvector:pg16 :5432)
├── redis            (:6379 — broker + cache + pubsub + rate limit)
├── minio            (:9000/:9001)
├── mlflow           (:5000)
├── claude-cli-sidecar (read-only 마운트, --cap-drop ALL)
├── vault            (HashiCorp Vault dev :8200)
└── nginx            (TLS 종료, Day17~)
```

### 5 HITL 게이트 + G0_PII 미니게이트

| 게이트 | 시점 | 사용자 입력 | 자동 처리 정책 |
|---|---|---|---|
| **G0** | 데이터 업로드 직후 | 자유 텍스트 (의도) | 즉시 |
| **G0_PII** | PII 감지 시 (조건부) | 컬럼별 마스킹/제외/유지 | 24h → 기본=마스킹 |
| **G1** | 데이터 프로파일링 후 | 3안 중 1안 선택 | 24h → 1순위 자동 채택 |
| **G2** | EDA 후 | 방법론 1개 선택 (정형 ML / 정형 DL / 시계열 / 이상탐지) | 24h → 자동 |
| **G3** | 전처리 + FE 후 | 모델 전략 1개 선택 | 24h → 자동 |
| **G4** | Top-3 학습 후 | 비교표에서 최적 모델 선택 | 24h → 자동 |
| **G5** | 평가 완료 후 | 산출물 5종 중 다중 선택 (체크박스) | 24h → 기본 [OUT-01, OUT-02] |

### 27 에이전트 카탈로그

| # | 카테고리 | 에이전트 | LLM | 역할 |
|---|---|---|---|---|
| 01 | 슈퍼바이저 | SupervisorAgent | Sonnet | 입출항 관제사 |
| 02 | 입력·검증 | IntentElicitorAgent | Sonnet | 비즈니스 분석 인터뷰어 |
| 03 | | DataProfilerAgent | none | 데이터 검수관 |
| 04 | | SchemaValidatorAgent | none | 데이터 품질 감사관 |
| 05 | 의사결정 게이트 | AnalysisProposerAgent | Opus | 데이터 전략 컨설턴트 (G1) |
| 06 | | MethodologyProposerAgent | Sonnet | AutoML 자문가 (G2) |
| 07 | | ModelStrategyProposerAgent | Opus | 모델링 아키텍트 (G3) |
| 08 | | ModelComparisonReporterAgent | none | 모델 평가 리포터 (G4) |
| 09 | | OutputTypeSelectorAgent | Sonnet | 리서치 디자인 큐레이터 (G5) |
| 10 | 전처리·EDA | PreprocessingStrategistAgent | Sonnet | 시니어 데이터 엔지니어 |
| 11 | | FeatureEngineerAgent | none | 피처 빌더 |
| 12 | | EDAAgent | none | EDA 분석가 |
| 13 | | PreprocessingChoiceAgent | Sonnet | 전처리 큐레이터 (미니 게이트) |
| 14 | 모델링·튜닝 | ModelSelectionAgent | Sonnet | AutoML 큐레이터 |
| 15 | | HyperparameterTunerAgent | none | 하이퍼파라미터 튜너 |
| 16 | | TrainingExecutorAgent | none | ML 트레이닝 엔지니어 |
| 17 | | TrainingMonitorAgent | none | 학습 안전 감독관 |
| 18 | | MetricsAggregatorAgent | none | 메트릭 심판관 |
| 19 | | FineTuneExecutorAgent | none | 미세조정 전문가 (정형 트랜스포머) |
| 20 | 평가·해석 | EvalAgent | Opus | 모델 QA 평가관 |
| 21 | | ExplainabilityAgent | none | 해석성 분석가 (SHAP 전용) |
| 22 | | InsightAgent | Opus | 분석 스토리텔러 |
| 23 | 산출물 | ReportComposerAgent | none | 산출물 PM (병렬 fan-out, 5종) |
| 24 | 메타 | SelfLearningAgent | none | 지식 큐레이터 (3-Stack KB) |
| 25 | | AutoErrorHandlerAgent | CLI | 자동 오류 정비공 |
| 26 | | SecurityGuardAgent | none | 보안 가드 (PII + 프롬프트 인젝션) |
| 27 | 회복 | ErrorRecoveryAgent | Opus | 회복 코디네이터 (최후 폴백) |

### 5종 산출물 패밀리

| 코드 | 산출물 | 형식 | 생성 시간 | 비고 |
|---|---|---|---|---|
| **OUT-01** | PPT 발표자료 (기본) | .pptx | ~30s | python-pptx, 7~10 슬라이드 |
| **OUT-02** | PDF 리포트 (기본) | .pdf | ~20s | WeasyPrint + Jinja2 |
| **OUT-03** | 발표 대본 | .txt | ~15s | Claude Sonnet, 슬라이드별 30~60초 |
| **OUT-04** | 정적 웹 대시보드 (단일 HTML) | .html | ~10s | Chart.js + 인라인 base64, ≤5MB |
| **OUT-07** | 인사이트 정리 (Markdown) | .md | ~15s | SHAP top10 · 차트 임베드 · 한계점 |

> `ReportComposerAgent`가 `ThreadPoolExecutor(max_workers=4)`로 병렬 fan-out 생성

---

## 모델 카탈로그

### 정형 ML — 4종 (CPU)
- RandomForest (scikit-learn)
- XGBoost
- LightGBM
- CatBoost

### 정형 DL — 3종 (트랜스포머)
- TabTransformer
- FT-Transformer
- TabPFN

### 시계열 — 6종
- ARIMA / SARIMA (statsmodels)
- Prophet
- Informer (트랜스포머)
- TFT — Temporal Fusion Transformer
- PatchTST

### 이상탐지 — 6종
- IsolationForest
- LOF (LocalOutlierFactor)
- OneClassSVM
- AutoEncoder (PyTorch MLP)
- TranAD (트랜스포머)
- AnomalyTransformer

**합계: 19종 모델 / TRANSFORMER_REGISTRY 8종**

---

## 기술 스택

| 레이어 | 기술 |
|---|---|
| 언어 | **Python 3.10** |
| 컨테이너 | Docker / Docker Compose |
| 오케스트레이션 | LangGraph (25 노드, interrupt 기반) + Celery (큐 4종) |
| API | FastAPI (~25 엔드포인트) |
| 프론트엔드 | Streamlit |
| DB | PostgreSQL 16 + pgvector (IVFFlat, 768d) |
| 캐시/브로커 | Redis 7 |
| 아티팩트 스토어 | MinIO |
| 실험 추적 | MLflow (4 실험: tabular-ml / tabular-dl / timeseries / anomaly) |
| 시크릿 관리 | HashiCorp Vault (KV v2) |
| 리버스 프록시 | nginx (TLS 종료) |
| LLM | Claude Sonnet / Opus / CLI 사이드카 |
| 임베딩 | sentence-transformers/all-mpnet-base-v2 |
| OS (개발) | WSL 2 (Ubuntu) / Windows 11 또는 Ubuntu 22.04 LTS Server |

---

## 지원 데이터 형식 — 8종

| 형식 | 확장자 | 카테고리 활용 |
|---|---|---|
| CSV | .csv | 전체 카테고리 |
| Excel | .xlsx, .xls | 전체 카테고리 |
| Parquet | .parquet | 전체 카테고리 |
| JSON | .json | 전체 카테고리 |
| ZIP | .zip | 다중 파일 묶음 |
| PDF | .pdf | 표 추출 (정형) |
| Text | .txt | 시계열 로그 |
| HTML | .html | 표 추출 |

> ❌ 이미지(jpg/png) · 오디오(wav) 는 본 스코프에서 제외

---

## 프로젝트 구조

```
ADA/
├── agents/                  # 27 에이전트 모듈
│   ├── personas.py          # 27 에이전트 페르소나 단일 권위 모듈
│   ├── base.py              # BaseAgent (페르소나 자동 주입)
│   ├── supervisor/
│   ├── proposers/           # G1~G5 게이트 에이전트
│   ├── preprocessing/
│   ├── modeling/
│   ├── evaluation/
│   ├── output/
│   └── meta/                # SelfLearning · AutoError · Security
├── api/                     # FastAPI 앱 (~25 엔드포인트)
│   └── services/
├── pipelines/               # 4 카테고리 파이프라인 + factory
│   ├── tabular_ml/
│   ├── tabular_dl/
│   ├── timeseries/
│   └── anomaly/
├── reports/                 # 5종 산출물 생성기
│   ├── ppt_generator.py        # OUT-01
│   ├── pdf_generator.py        # OUT-02
│   ├── script_generator.py     # OUT-03
│   ├── dashboard_artifact.py   # OUT-04
│   └── insight_md.py           # OUT-07
├── orchestrator/            # LangGraph 그래프 (25 노드) + Celery 러너
├── docker/                  # Dockerfile 5종 + init.sql
├── scripts/                 # lint_personas.py 등 유틸
├── tests/                   # 통합·침투·인수 테스트
├── work-orders/             # 에이전트 구축 작업 지시서
│   └── daily/               # Day00(마스터) ~ Day21 작업지시서 22개
├── .github/                 # CI/CD 워크플로우
├── docker-compose.yml
└── .env.example
```

---

## KPI v2 — 11개 지표

| KPI | 기준 | 측정 시점 |
|---|---|---|
| KP1 | E2E 성공률 ≥ 85% | Day20 |
| KP2 | 응답 속도 ≤ 120s (게이트 시간 제외) | Day20 |
| KP3 | 자동 재루프 성공률 ≥ 75% | Day20 |
| KP4 | 분석 카테고리 커버 **4/4** | Day20 |
| KP5 | API p95 < 400ms | Day20 |
| KP6 | AGENTS.md 자동 룰 ≥ 15 | Day20 |
| KP7 | 자체학습 효과: 2회차 메트릭 +5%p, Optuna trial -30% | Day20 |
| KP8 | 자체 오류 해결률 ≥ 60% | Day20 |
| KP9 | 트랜스포머 채택률 ≥ 25% (G4 기준, 정형 DL/시계열/이상탐지) | Day20 |
| KP10 | 보안 침투 0건 통과 (50종 페이로드) | Day20 |
| KP11 | 사용자 1순위 채택률 ≥ 60% (G1 기준) | Day20 |

---

## 개발 환경 설정

```bash
# 1. 저장소 클론
git clone <repo-url>
cd ADA

# 2. 환경 변수 설정
cp .env.example .env
# .env 파일을 열어 필요한 값 입력

# 3. 컨테이너 전체 기동 (Compose profile 활용)
docker compose --profile core up -d           # 평소 작업
docker compose --profile core --profile ml up -d   # 학습 단계

# 4. 상태 확인 (코어 8개 + ml 3개 = 11개)
docker compose ps
```

> 하드웨어 권장: 16GB RAM 이상, GTX 1060 3GB 이상 (또는 CPU-only), 100GB+ SSD. 자세한 환경 가이드는 `LINUX_DOCKER_SETUP_GUIDE.md` 참조.

---

## 브랜치 전략

| 브랜치 | 용도 |
|---|---|
| `main` | 안정 버전 (직접 push 금지) |
| `feat/기능명` | 새 기능 개발 |
| `fix/버그명` | 버그 수정 |
| `ci/항목명` | CI/CD 관련 |

## 작업 흐름

1. `main`에서 최신 코드 받기: `git pull origin main`
2. 새 브랜치 생성: `git checkout -b feat/내기능`
3. 작업 후 커밋: `git commit -m "feat: 기능 설명"`
4. push 후 PR 생성: `git push -u origin feat/내기능`
5. CI 통과 + 리뷰 승인 → 머지

---

## 관련 문서

| 문서 | 위치 |
|---|---|
| 마스터 설계서 (v2 권위 문서) | [work-orders/daily/Day00_마스터설계서_v2.md](work-orders/daily/Day00_마스터설계서_v2.md) |
| Notion 요약 인덱스 | [work-orders/NOTION_요약_v2.md](work-orders/NOTION_요약_v2.md) |
| 일별 작업지시서 (Day01~21) | [work-orders/daily/](work-orders/daily/) |
| Docker 환경 인벤토리 | [DOCKER_ENV_INVENTORY.md](DOCKER_ENV_INVENTORY.md) |
| Linux + Docker 셋업 가이드 | [LINUX_DOCKER_SETUP_GUIDE.md](LINUX_DOCKER_SETUP_GUIDE.md) |
| 개발 환경 셋업 (Windows/WSL) | [DEV_SETUP_GUIDE.md](DEV_SETUP_GUIDE.md) |

> 설계 스냅샷: v2.0 · 2026-05-15 · **스코프 축소: 2026-05-18** (카테고리 6→4, 산출물 13→5, Python 3.10 확정)
> 변경 이력: v1.0 (14일) → v2.0 (21일, 5게이트, 3-Stack SL, AutoError, 보안 풀스택, 27 에이전트 페르소나) → v2.1 (정형 데이터 중심 스코프 축소)

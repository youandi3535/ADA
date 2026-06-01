# ADA — Adaptive AutoAI Pipeline Agent v2

> **Conversational AutoAI Studio** — 사용자가 정형 데이터를 던지면, **다섯 번의 가벼운 선택만으로** 의도에 맞게 자동 분석·튜닝·해석을 수행하고, **원하는 형태(5종)** 로 산출물을 뽑아주는 대화형 AutoAI 스튜디오.
> 시간이 지날수록 똑똑해지고, 스스로 오류를 고치며, 외부 위협으로부터 안전하다.
>
> **스코프**: 정형 ML / 정형 DL / 시계열 / 이상탐지 4개 카테고리 (이미지·NLP 제외)

---

## 팀 구성

| 역할 | 담당자 |
|---|---|
| 시스템·메타·인프라 (HJ) | youandi3535 |
| 에이전트 로직 — timeseries (CS) | chang-seon |
| 에이전트 로직 — anomaly (NY) | NY |
| 에이전트 로직 — tabular (jh) | jh |

---

## 핵심 특징

| # | 특징 | 설명 |
|---|---|---|
| 1 | **27 에이전트** | 슈퍼바이저·입력·게이트·전처리·모델링·평가·산출물·메타·회복 8개 카테고리 |
| 2 | **5 HITL 게이트** | LangGraph interrupt + PostgresSaver 기반, 24h 무응답 시 자동 처리 |
| 3 | **3-Stack 자체학습** | PostgreSQL KB + MinIO 아티팩트 + pgvector RAG (768d) |
| 4 | **5종 산출물** | PPT / PDF / 발표대본 / 정적 웹 대시보드 / 인사이트 정리 |
| 5 | **Guardian v2 자동 오류 처리** | 5-Tier 체계 (Static → ErrorKB → 검증 패치 재사용 → Ollama → Claude CLI) |
| 6 | **팀 집단지성 KB** | 모든 VS Code·Cowork Q&A 자동 수집 → 벡터 KB → UserPromptSubmit 훅으로 Claude API 비용 0 |
| 7 | **보안 풀스택** | JWT · RBAC · RLS · PII · 프롬프트 인젝션 방어 · Vault · 감사로그 |
| 8 | **실시간 대시보드** | 27 에이전트 매트릭스 · 5게이트 UI · WebSocket 6 메시지 타입 |

---

## Guardian v2 — 팀 집단지성 자가학습 시스템

팀원들이 Claude Code / Cowork에서 나누는 모든 Q&A를 자동으로 수집·임베딩하여,
다음 질문부터는 Claude API 호출 없이 팀 KB에서 즉시 답변합니다.

### 전체 흐름

```
┌─────────────────────────────────────────────────────────┐
│  개발자 PC                                              │
│                                                         │
│  VS Code Claude Code                                    │
│   ├─ UserPromptSubmit 훅 → KB 히트 시 exit 2           │
│   │   (Claude API 비용 0, 응답 즉시 반환)               │
│   └─ Stop 훅 → collect_qa.py → Q&A 실시간 전송         │
│                                                         │
│  Cowork (Claude Desktop App)                            │
│   └─ 훅 없음 → ingest_history.py 5분 폴링              │
│      %APPDATA%\Claude\local-agent-mode-sessions\        │
└──────────────────┬──────────────────────────────────────┘
                   │ HTTPS
                   ▼
┌─────────────────────────────────────────────────────────┐
│  VPS (웹 서버, Docker)                                  │
│                                                         │
│  FastAPI  --workers 1  (임베딩 일관성 보장)             │
│   /kb/search      → 3-gate KB 검색                     │
│   /kb/conversation → Q&A 수신 + 품질 게이트 저장        │
│                                                         │
│  PostgreSQL + pgvector                                  │
│   self_learning_kb  (벡터 + success_count)              │
│   conversation_logs (source: claude_code_history/cowork)│
│   pending_patches   (자동 수정 패치 큐)                 │
└──────────────────┬──────────────────────────────────────┘
                   │ SSH (하루 3회)
                   ▼
┌─────────────────────────────────────────────────────────┐
│  Linux 데스크탑 서버                                    │
│  backup_postgres.sh · linux_kb_sync.py                  │
│  Ollama  qwen2.5:7b · qwen2.5-coder:7b                  │
└─────────────────────────────────────────────────────────┘
```

### 3-Tier Q&A 응답 체계

| Tier | 조건 | 응답 시간 | API 비용 |
|---|---|---|---|
| **1 — 팀 KB** | 코사인 유사도 ≥ 0.85 + hit_count ≥ 3 + 단어 겹침 ≥ 50% | < 100ms | **0원** |
| **2 — Ollama** | KB 미스 (qwen2.5:7b 로컬) | 2~5s | 0원 |
| **3 — Claude** | Ollama 실패 시 폴백 | 3~10s | 과금 |

> 유사도 ≥ 0.98 (사실상 동일 문장)이면 hit_count / 단어 겹침 게이트 면제

### Guardian v2 5-Tier 자동 오류 수정

| Tier | 방식 | LLM | 속도 |
|---|---|---|---|
| **0 — Static fixers** | 6종 결정론적 패턴 (relative import / NoneType slicing / NameError typo 등) | ❌ | < 100ms |
| **1 — Error KB** | 과거 검증 패치 벡터 검색 (confidence ≥ 0.7) | ❌ | < 200ms |
| **1.5 — 검증 패치 재사용** | `pending_patches` 중 `review_status='approved'` 재활용 | ❌ | < 50ms |
| **2 — Ollama** | qwen2.5-coder:7b 로컬 LLM | ✅ Local | 5~15s |
| **3 — Claude CLI** | 최후 폴백 | ✅ Cloud | 10~30s |

### KB 품질 게이트

KB 저장 전 자동 품질 평가 (0.0~1.0). 점수 < 0.45는 저장 거부.

- ❌ 거부 패턴: "죄송합니다 / 모르겠습니다 / 할 수 없습니다" 류 거절 답변
- ❌ 거부 패턴: 너무 짧은 답변 (50자 미만)
- ❌ 거부 패턴: Python 에러 traceback 그대로
- ✅ 통과: 구체적 설명 + 코드 포함 + 충분한 길이

### 관련 스크립트

| 파일 | 역할 |
|---|---|
| `scripts/query_kb_hook.py` | UserPromptSubmit 훅 — KB 히트 시 Claude 차단, exit 2 |
| `scripts/collect_qa.py` | Stop 훅 — 매 응답 후 Q&A 실시간 전송 |
| `scripts/ingest_history.py` | VS Code + Cowork 과거 이력 일괄 수집 (5분 cron) |
| `scripts/kb_mcp_server.py` | MCP 서버 — Claude 내에서 직접 KB 조회 |
| `scripts/linux_kb_sync.py` | 리눅스 서버 KB 동기화 |

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
| 02 | DB + 인프라 + 자동 오류 처리 기반 | 24+ 테이블 · pgvector IVFFlat · RLS · agent_registry 시드 27행 · MLflow 실험 4종 · 자동 오류 감지·해결 파이프라인 Phase 1~2 |
| 03 | 공통 모듈 + Langfuse + audit 라우트 | PipelineStateV2 · BaseAgent 페르소나 자동 주입 · Langfuse 깊이 통합 (track_llm) · audit 라우트 4종 (failure_logs/patch/circuit/budget) · ADR-007 |
| 04 | LangGraph + PII + LLM Guard | 25 노드 그래프 · PostgresSaver · 5게이트 interrupt · PII anonymize·re-attach · LLM Guard 풀 통합 · 캐리어 5종 output_extras 훅 |
| 05 | 보안 + 파이프라인 학습 검증 | JWT RS256 전환 · HashiCorp Vault 시드 · 파이프라인 E2E 학습 테스트 4종 (tabular-ml/dl/timeseries/anomaly) · Windows 훅 터미널 창 숨김 |
| 06 | Cowork 통합 + KB 파서 | Cowork JSONL 파서 안정화 · Windows Store 앱 경로 자동 감지 · ADR-010 구현 가이드 |
| 07 | 환경 표준화 + 테스트 보정 | venv→.venv 전환 · 훅·스크립트 Windows 환경 보정 · 테스트 3건 수정 |

### 주 2 — Modeling + Self-Learning

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 08 | InsightAgent Guardrails | InsightAgent 메트릭 수치 인용 강제 Guardrails 본구현 · 테스트 15건 GREEN |
| 09 | OUT carrier 훅 완성 | OUT-01~07 carrier output_extras 훅 본구현 · 테스트 11건 GREEN |
| 10 ✅ | E2E 검증 + KPI + 카테고리별 데모 | **HJ**: KPI 자동 측정 (ada/observability/kpi.py) · Streamlit Tab5 대시보드 · hook 3-tier 배지 시스템 완성 · harness distiller/rag 확장 · anomaly_demo.py<br>**CS**: timeseries E2E 5시나리오 (ScenarioResult·롤백 R1/R2/R3·OUT-04) · test_e2e<br>**jh**: tabular E2E 3시나리오 (Titanic·Iris·Adult) + 데모<br>**NY**: anomaly 전체 핸들러 완성 · EDA 시간축 차트 · profiler 이음새 수정 |
| 11 🔄 | hook 버그 수정 (진행 중) | hook 배지 누락 버그 수정 (suppressOriginalPrompt 제거 · Ollama timeout 단축) |
| 12 | 산출물 + 확장 파이프라인 | 정형 DL / 시계열 / 이상탐지 트랜스포머 파이프라인 8종 + LoRA |
| 13 | 오류 처리 + API 완성 | ErrorRecovery 폴백화 · v2 신규 ~15 엔드포인트 · JWT 미들웨어 |
| 14 | 테스트 + 검증 + 데모 (v1 KPI) | v1 KPI 측정 · v2 골격 검증 · Day15~21 핸드오프 |

### 주 3 — Outputs · Errors · Security · Dashboard · Test

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 15 | 산출물 패밀리 확장 | 5종 생성기 (OUT-01/02/03/04/07) + OutputTypeSelector (G5) + 병렬 fan-out |
| 16 | Guardian v2 자동 오류 처리 | 5-Tier AutoErrorHandler · Static Fixers 6종 · Error KB · Ollama coder · Claude CLI |
| 17 | 보안 풀스택 | JWT · RBAC · RLS · PII · 프롬프트 인젝션 · Vault · 감사로그 · 침투 50종 |
| 18 | 웹 대시보드 + 에이전트 현황판 | 3페이지 (현황판/분석시작/잡히스토리) · 게이트 카드 UI 12 컴포넌트 |
| 19 | 팀 KB + 집단지성 자가학습 | Q&A 수집 파이프라인 · 3-Tier 응답 · KB 훅 · Cowork 지원 · MCP 서버 |
| 20 | 통합 + 침투 테스트 | IT-1~IT-4 (4 카테고리) · KPI v2 11개 측정 · 재해 복구 · Load 50 동시 사용자 |
| 21 | 인수 + 데모 + 문서화 | AT-1~AT-4 · 데모 4×5 매트릭스 (4 카테고리 × 5 산출물) · 27 에이전트 README · 운영/개발/사용자 가이드 |

---

## 아키텍처

### 컨테이너 토폴로지 (core 프로파일 기준 9종)

```
ada-net (bridge)
├── api              (FastAPI :8000, --workers 1)
├── frontend         (Streamlit :8501)
├── worker-pipeline  (Celery, pipeline 큐, ×2)
├── worker-harness   (Celery, harness 큐, ×1 — 자체학습 + 에러KB)
├── nginx            (리버스 프록시 :80)
├── postgres         (pgvector/pgvector:pg16 :5432)
├── redis            (:6379 — broker + cache + pubsub + rate limit)
├── minio            (:9000/:9001)
└── mlflow           (:5000)

ml 프로파일 추가:
├── worker-training  (Celery, training 큐, ×1, GPU 가능 4GB)
├── worker-output    (Celery, output 큐, ×2)
└── serving          (:8080)

sec 프로파일 추가:
├── vault            (HashiCorp Vault dev :8200)
└── claude-cli-sidecar (read-only 마운트, --cap-drop ALL)
```

> `api` 컨테이너는 **반드시 `--workers 1`** — sentence-transformers 싱글톤이 단일 프로세스에서만 일관된 임베딩을 생성함.

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
| 25 | | AutoErrorHandlerAgent | CLI | 자동 오류 정비공 (5-Tier) |
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
| 컨테이너 | Docker / Docker Compose (profile: core / ml / sec) |
| 오케스트레이션 | LangGraph (25 노드, interrupt 기반) + Celery (큐 4종) |
| API | FastAPI (~25 엔드포인트), uvicorn **--workers 1** |
| 프론트엔드 | Streamlit |
| DB | PostgreSQL 16 + pgvector (IVFFlat, 768d) |
| 캐시/브로커 | Redis 7 |
| 아티팩트 스토어 | MinIO |
| 실험 추적 | MLflow (4 실험: tabular-ml / tabular-dl / timeseries / anomaly) |
| 시크릿 관리 | HashiCorp Vault (KV v2) |
| 리버스 프록시 | nginx |
| LLM (Cloud) | Claude Sonnet / Opus / CLI 사이드카 |
| LLM (Local) | Ollama — qwen2.5:7b (Q&A 폴백) · qwen2.5-coder:7b (에러 수정) |
| 임베딩 | sentence-transformers/all-mpnet-base-v2 |
| 팀 KB | pgvector + UserPromptSubmit 훅 + Stop 훅 + Cowork 폴링 |
| IDE 훅 | Claude Code hooks (UserPromptSubmit, Stop) + MCP 서버 |
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
│   ├── handlers/
│   │   ├── timeseries/      # CS 담당
│   │   ├── anomaly/         # NY 담당
│   │   └── tabular/         # jh 담당
│   └── meta/                # SelfLearning · AutoError · Security
├── ada/
│   ├── core/                # config · state · utils
│   ├── db/                  # models · session
│   ├── error_handler/       # auto_handler · static_fixers (6종) · daemon
│   ├── security/            # jwt · pii · prompt injection
│   └── observability/       # metrics · langfuse
├── api/                     # FastAPI 앱 (~25 엔드포인트)
│   └── routes/
│       ├── kb_search.py     # 3-gate KB 검색 + success_count 자동 증가
│       └── conversation_kb.py # Q&A 수신 + 품질 게이트 + 임베딩
├── pipelines/               # 4 카테고리 파이프라인 + factory
│   ├── tabular_ml/
│   ├── tabular_dl/
│   ├── timeseries/
│   └── anomaly/
├── outputs/                 # 5종 산출물 생성기
├── orchestrator/            # LangGraph 그래프 (25 노드) + Celery 러너
├── scripts/
│   ├── query_kb_hook.py     # UserPromptSubmit 훅 (KB 히트 → exit 2)
│   ├── collect_qa.py        # Stop 훅 (Q&A 실시간 수집)
│   ├── ingest_history.py    # VS Code + Cowork 과거 이력 일괄 수집
│   ├── kb_mcp_server.py     # MCP 서버 (Claude 내 KB 직접 조회)
│   ├── linux_kb_sync.py     # 리눅스 서버 KB 동기화
│   ├── kpi_measure.py       # KPI 11개 자동 측정 (ada/observability/kpi.py 위임)
│   ├── run_hook.py          # hook 수동 실행 유틸
│   ├── demo/
│   │   ├── timeseries_demo.py  # AirPassengers E2E 데모 (5시나리오·ScenarioResult·OUT-04)
│   │   ├── anomaly_demo.py     # anomaly E2E 데모
│   │   └── tabular_demo.py     # tabular E2E 데모 (Titanic·Iris·Adult)
│   ├── security/            # 보안 검증 스크립트
│   └── dev/
│       ├── end_of_day.sh    # 하루 마무리 (영역검증→테스트→rebase→push)
│       └── check_scope.sh   # 영역 외 수정 차단
├── migrations/              # Alembic 마이그레이션
├── docker/                  # Dockerfile 5종 + docker-compose.yml
├── tests/                   # 통합·침투·인수 테스트
├── .claude/
│   └── settings.json        # UserPromptSubmit + Stop 훅 + MCP 서버 등록
├── .github/                 # CI/CD 워크플로우
└── .env.example
```

---

## 개발 환경 설정

### 초기 설정 (최초 1회)

```bash
# 1. 저장소 클론
git clone <repo-url>
cd ADA

# 2. 환경 변수 설정 (.env 는 gitignore — HJ에게 값 공유 요청)
cp .env.example .env
# KB_SERVER_URL, KB_COLLECT_SECRET 등 입력

# 3. 컨테이너 기동
cd docker
docker compose --profile core up -d           # 평소 작업
docker compose --profile core --profile ml up -d   # 학습 단계

# 4. DB 마이그레이션
docker compose exec api alembic upgrade head

# 5. Cowork 5분 폴링 등록 (Windows, 1회)
$action = New-ScheduledTaskAction -Execute "python" `
    -Argument "scripts/ingest_history.py" `
    -WorkingDirectory "C:\path\to\ADA"
$trigger = New-ScheduledTaskTrigger `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)
Register-ScheduledTask -TaskName "ADA-IngestHistory" -Action $action -Trigger $trigger -Force
```

### 일일 작업 마무리

```bash
bash scripts/dev/end_of_day.sh
# 영역 검증 → pytest → rebase → push 자동화
```

> 하드웨어 권장: 16GB RAM 이상, GTX 1060 3GB 이상 (또는 CPU-only), 100GB+ SSD.

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
| KP8 | 자동 오류 해결률 ≥ 60% (Guardian v2 5-Tier 기준) | Day20 |
| KP9 | 트랜스포머 채택률 ≥ 25% (G4 기준) | Day20 |
| KP10 | 보안 침투 0건 통과 (50종 페이로드) | Day20 |
| KP11 | 사용자 1순위 채택률 ≥ 60% (G1 기준) | Day20 |

---

## 브랜치 전략

| 브랜치 | 용도 |
|---|---|
| `main` | 안정 버전 (직접 push 금지) |
| `feat/HJ` | HJ 기능 개발 |
| `feat/CS` | CS(timeseries) 기능 개발 |
| `feat/NY` | NY(anomaly) 기능 개발 |
| `feat/jh` | jh(tabular) 기능 개발 |

### 작업 흐름

```bash
# 매일 아침
git checkout main && git pull origin main
git checkout -b feat/{본인이니셜}-day{N}

# 매일 저녁
bash scripts/dev/end_of_day.sh   # 자동 (영역검증 → 테스트 → rebase → push)
```

---

## 관련 문서

| 문서 | 위치 |
|---|---|
| 마스터 설계서 (v2 권위 문서) | [work-orders/daily/Day00_마스터설계서_v2.md](work-orders/daily/Day00_마스터설계서_v2.md) |
| 에이전트 룰 카탈로그 | [AGENTS.md](AGENTS.md) |
| 역할 & 작업 규칙 | [CLAUDE.md](CLAUDE.md) |
| 병렬 작업 가드 | [docs/PARALLEL_WORK_GUARDS.md](docs/PARALLEL_WORK_GUARDS.md) |
| 10일 병렬 일정 | [TEAM_10DAY_SCHEDULE.md](TEAM_10DAY_SCHEDULE.md) |
| KPI 측정 가이드 | [docs/KPI_MEASUREMENT.md](docs/KPI_MEASUREMENT.md) |
| KPI ADR-010 | [docs/ADR-010-kpi-measurement.md](docs/ADR-010-kpi-measurement.md) |
| HJ Day10 설계서 | [docs/HJ_DAY10_DESIGN.md](docs/HJ_DAY10_DESIGN.md) |
| Notion 요약 인덱스 | [work-orders/NOTION_요약_v2.md](work-orders/NOTION_요약_v2.md) |
| Linux + Docker 셋업 가이드 | [LINUX_DOCKER_SETUP_GUIDE.md](LINUX_DOCKER_SETUP_GUIDE.md) |
| 개발 환경 셋업 (Windows/WSL) | [DEV_SETUP_GUIDE.md](DEV_SETUP_GUIDE.md) |

---

> 설계 스냅샷: v2.3 · 2026-06-01  |  현재 진행: **Day 11** (HJ 진행 중 🔄)
> 변경 이력:
> - v1.0 (14일) — 기초 파이프라인
> - v2.0 (21일) — 5게이트 · 3-Stack SL · AutoError · 보안 풀스택 · 27 에이전트
> - v2.1 (2026-05-18) — 정형 데이터 중심 스코프 축소 (카테고리 6→4, 산출물 13→5)
> - v2.2 (2026-05-25) — Guardian v2 · 팀 집단지성 KB · 3-Tier Q&A · Cowork 지원 · 5-Tier 자동 오류 수정
> - v2.3 (2026-06-01) — Day 10 완료: KPI 자동 측정 · Streamlit Tab5 · hook 3-tier 배지 시스템 · E2E 데모 3종 (timeseries/tabular/anomaly) · anomaly 핸들러 전체 완성 · scripts/demo/ 추가

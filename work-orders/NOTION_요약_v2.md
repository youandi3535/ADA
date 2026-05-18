# 📘 ADA v2 — 작업지시서 설계 요약 (Notion용)

> **프로젝트** : Adaptive AutoAI Pipeline Agent v2 — Conversational AutoAI Studio
> **스프린트** : 3주 · 21일 (Day 1 ~ Day 21)
> **문서 버전** : v2.0 · 2026-05-15 · 한국어
> **이 페이지의 역할** : 22개 일별 작업지시서를 노션 한 페이지로 압축한 인덱스 + 핵심 설계 결정 요약

---

## 📍 한 줄 정의

> 사용자가 어떤 데이터든 던지면, **다섯 번의 가벼운 선택만으로** 의도에 맞게 자동 분석·튜닝·해석을 수행하고, **원하는 형태(PPT/대시보드/영상 프롬프트/논문/기획안/보고서/요약/대본 등 13종)** 로 산출물을 뽑아주는 대화형 AutoAI 스튜디오. 시간이 지날수록 똑똑해지고, 스스로 오류를 고치며, 외부 위협으로부터 안전하다.

---

## 🎯 4가지 핵심 설계 결정

| # | 결정 | 채택안 | 위치 |
|---|---|---|---|
| 1 | HITL(사용자 게이트) 구현 방식 | **LangGraph interrupt + PostgresSaver 체크포인터** | Day 4 |
| 2 | 자체학습 깊이 | **3-Stack 풀스택** (Postgres KB + MinIO 아티팩트 + pgvector RAG) | Day 14 · Day 19 |
| 3 | Claude CLI 자동 오류 처리 | **subprocess + 격리 셸** (read-only 마운트, --cap-drop ALL) | Day 16 |
| 4 | 스프린트 길이 | **21일 (3주)** | 전체 일정 |

---

## 🚀 v1 vs v2 한눈 비교

| 항목 | v1 (14일) | v2 (21일) |
|---|---|---|
| 사용자 개입 | error_recovery 시 HITL 1회 | **5단계 HITL 게이트** (interrupt 기반) |
| 입력 데이터 | csv/parquet/zip 중심 | **csv/xlsx/parquet/json/zip/pdf/txt/html/이미지/음성** 전부 |
| 산출물 종류 | 3종 (PPT/PDF/대본) | **13종** (+대시보드/영상프롬프트/논문/기획안/요약/리포트/팟캐스트/인포그래픽) |
| 학습 효과 | success_patterns 누적 | **3-Stack Self-Learning** (RAG 인용) |
| 오류 처리 | ErrorRecovery in-flow | **AutoErrorHandler 데몬** + Claude CLI 사이드카 + Error KB |
| 모델 정책 | 4 트리 + DL 1종 | **트랜스포머 우선** (G4 후보 1개 이상 강제) |
| 보안 | .env + SHA256 | **풀스택** (JWT/RBAC/RLS/PII/암호화/Vault/감사로그) |
| 대시보드 | 진행률 바 | **에이전트 현황판** (27 에이전트 실시간 매트릭스) |
| 에이전트 페르소나 | 없음 | **27 에이전트 전원** 1줄 페르소나 + 자동 주입 |

---

## 🗺️ 21일 스프린트 로드맵

### 📅 주1 — Foundations + Interactive Architecture

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 01 | Docker 환경 설정 | 8 v1 서비스 + claude-cli-sidecar + vault + pgvector + 큐 4종 분리 |
| 02 | DB 인프라 | 24+ 테이블 (v1 10 + v2 15) · pgvector IVFFlat · RLS · agent_registry 시드 27행 |
| 03 | 공통 모듈 + CI/CD | PipelineStateV2 · BaseAgent persona 자동 주입 · personas.py 27 · security 패키지 |
| 04 | LangGraph + Celery | 25 노드 그래프 · PostgresSaver · 5게이트 interrupt · AgentRegistry |
| 05 | 데이터 처리 에이전트 | 멀티 포맷 로더 8종 · PII 스캔 + G0_PII 미니게이트 · dataset_embeddings |
| 06 | Supervisor + FastAPI 기본 | IntentElicitor (G0) · AnalysisProposer (G1) · /decision 엔드포인트 |
| 07 | 정형 ML + Model Selection | 4 모델 파이프라인 · MethodologyProposer (G2) · TRANSFORMER_REGISTRY |

### 📅 주2 — Modeling + Self-Learning

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 08 | 학습 실행 에이전트 4종 | HPTuner warm-start · TrainingExecutor · Monitor · MetricsAgg (Top-3 강제) |
| 09 | Harness Engineering | EvalAgent · RulesManager · Auditor · SelfLearning/AutoError 인터페이스 |
| 10 | 전처리 + EDA + UI | PreprocStrategist · FeatureEng · EDA · PreprocChoice 미니게이트 (Day10 owner) |
| 11 | 해석력 + 인사이트 | ModelStrategyProposer (G3) · ModelComparisonReporter (G4) · 재루프 검증 |
| 12 | 산출물 + 확장 파이프라인 | **트랜스포머 파이프라인 9종** (TabTransformer/Informer/TFT/ViT/BERT/TranAD …) + LoRA |
| 13 | 오류 처리 + API 완성 | ErrorRecovery 폴백화 · v2 신규 ~15 엔드포인트 · JWT 미들웨어 |
| 14 | 테스트 + 검증 + 데모 (v1 KPI) | v1 KPI 측정 · v2 골격 검증 · Day15~21 핸드오프 |

### 📅 주3 — Outputs · Errors · Security · Dashboard · Test

| Day | 제목 | 핵심 산출물 |
|---|---|---|
| 15 | 산출물 패밀리 확장 | **13종 생성기** + OutputTypeSelector (G5) + 병렬 fan-out |
| 16 | 자동 오류 처리 + Claude CLI 브리지 | AutoErrorHandler 완성 · cli_bridge · error_kb 학습 사이클 · pending_patches |
| 17 | 보안 풀스택 | JWT · RBAC · RLS · PII · 프롬프트 인젝션 · Vault · 감사로그 · **침투 50종** |
| 18 | 웹 대시보드 + 에이전트 현황판 | 3페이지 (현황판/분석시작/잡히스토리) · 게이트 카드 UI 12 컴포넌트 |
| 19 | FastAPI 완성 + SelfLearning | SelfLearningAgent 3-Stack 완성 · RAG 인용 · ~30 엔드포인트 |
| 20 | 통합 + 침투 테스트 | IT-1~IT-5 · KPI v2 11개 측정 · 재해 복구 · Load 50 동시 사용자 |
| 21 | 인수 + 데모 + 문서화 | AT-1~AT-5 · 데모 5×5 매트릭스 · 27 에이전트 README · 운영/개발/사용자 가이드 |

---

## 🤖 27 에이전트 카탈로그

> 카테고리별 그룹핑. 모든 에이전트는 가벼운 1줄 페르소나를 가지며 `agents/personas.py`에서 BaseAgent가 자동 주입합니다.

### I 슈퍼바이저 (1)
| # | Agent | LLM | 페르소나 한 줄 |
|---|---|---|---|
| 01 | SupervisorAgent | Sonnet | 입출항 관제사 — 입력 유효성 + 다음 단계 적합성 판정 |

### A 입력·검증 (3)
| # | Agent | LLM | 페르소나 |
|---|---|---|---|
| 02 | IntentElicitorAgent | Sonnet | 비즈니스 분석 인터뷰어 |
| 03 | DataProfilerAgent | none | 데이터 검수관 |
| 04 | SchemaValidatorAgent | none | 데이터 품질 감사관 |

### B 의사결정 제안 게이트 (5)
| # | Agent | LLM | 페르소나 | 게이트 |
|---|---|---|---|---|
| 05 | AnalysisProposerAgent | Opus | 데이터 전략 컨설턴트 | **G1** — 3안 |
| 06 | MethodologyProposerAgent | Sonnet | AutoML 자문가 | **G2** — 방법론 |
| 07 | ModelStrategyProposerAgent | Opus | 모델링 아키텍트 | **G3** — 전략 |
| 08 | ModelComparisonReporterAgent | none | 모델 평가 리포터 | **G4** — 최적 모델 |
| 09 | OutputTypeSelectorAgent | Sonnet | 리서치 디자인 큐레이터 | **G5** — 산출물 |

### C 전처리 · EDA + 미니게이트 (4)
| # | Agent | LLM | 페르소나 |
|---|---|---|---|
| 10 | PreprocessingStrategistAgent | Sonnet | 시니어 데이터 엔지니어 |
| 11 | FeatureEngineerAgent | none | 피처 빌더 |
| 12 | EDAAgent | none | EDA 분석가 |
| 13 | PreprocessingChoiceAgent | Sonnet | 전처리 큐레이터 (미니 게이트) |

### D 모델링 + 트랜스포머 튜닝 (6)
| # | Agent | LLM | 페르소나 |
|---|---|---|---|
| 14 | ModelSelectionAgent | Sonnet | AutoML 큐레이터 |
| 15 | HyperparameterTunerAgent | none | 하이퍼파라미터 튜너 |
| 16 | TrainingExecutorAgent | none | ML 트레이닝 엔지니어 |
| 17 | TrainingMonitorAgent | none | 학습 안전 감독관 |
| 18 | MetricsAggregatorAgent | none | 메트릭 심판관 |
| 19 | FineTuneExecutorAgent | none | 미세조정 전문가 |

### E 평가 · 해석 (3)
| # | Agent | LLM | 페르소나 |
|---|---|---|---|
| 20 | EvalAgent | Opus | 모델 QA 평가관 |
| 21 | ExplainabilityAgent | none | 해석성 분석가 |
| 22 | InsightAgent | Opus | 분석 스토리텔러 |

### F 산출물 오케스트레이터 (1)
| # | Agent | LLM | 페르소나 |
|---|---|---|---|
| 23 | ReportComposerAgent | none | 산출물 PM (병렬 fan-out) |

### G 메타 (3)
| # | Agent | LLM | 페르소나 |
|---|---|---|---|
| 24 | SelfLearningAgent | none | 지식 큐레이터 (3-Stack KB) |
| 25 | AutoErrorHandlerAgent | CLI | 자동 오류 정비공 |
| 26 | SecurityGuardAgent | none | 보안 가드 (PII + 프롬프트 인젝션) |

### H 회복 (1)
| # | Agent | LLM | 페르소나 |
|---|---|---|---|
| 27 | ErrorRecoveryAgent | Opus | 회복 코디네이터 (최후 폴백) |

---

## 🚪 5 HITL 게이트 + G0_PII 미니게이트

| 게이트 | 시점 | 사용자 입력 | 응답 시간 정책 |
|---|---|---|---|
| **G0** | 데이터 업로드 직후 | 자유 텍스트 (의도) | 즉시 |
| **G0_PII** | PII 감지 시에만 (조건부) | 컬럼별 마스킹/제외/유지 | 24h → 기본=마스킹 |
| **G1** | 데이터 프로파일링 후 | 3안 중 1안 선택 | 24h → 1순위 자동 채택 |
| **G2** | EDA 후 | 방법론 1개 선택 | 24h → 자동 |
| **G3** | 전처리 + FE 후 | 모델 전략 1개 선택 | 24h → 자동 |
| **G4** | Top-3 학습 후 | 비교표에서 최적 모델 선택 | 24h → 자동 |
| **G5** | 평가 완료 후 | 산출물 다중 선택 (체크박스) | 24h → 기본 [OUT-01, OUT-02] |

자동 처리 결정은 `interactive_sessions.auto_resolved=true` 로 마킹되어 학습 KB로 들어갑니다.

---

## 🧠 자체학습 3-Stack

```
Layer 1  — PostgreSQL  self_learning_kb (kb_type 5종 partition)
              ├─ success_pattern    : 성공한 파이프라인 config 스냅샷
              ├─ recipe             : 카테고리×메트릭별 best practice
              ├─ eda_template       : 도메인별 EDA 차트 셋
              ├─ hpo_warm_start     : Optuna 시드 best_params
              └─ failure_lesson     : 실패 교훈

Layer 2  — MinIO  self_learning/...
              ├─ data_profiles/{job_id}.json
              ├─ shap_values/{job_id}.npy
              ├─ learning_curves/{job_id}.csv
              └─ prompts/{job_id}/{agent}.json  (LLM 미세조정용)

Layer 3  — pgvector (768d, all-mpnet-base-v2)
              ├─ dataset_embeddings  : 데이터 프로파일 임베딩
              ├─ intent_embeddings   : 사용자 의도 임베딩
              └─ lesson_embeddings   : 실패 교훈 임베딩
```

**사이클** : 잡 종료 → `SelfLearningAgent.distill(job_id)` 가 Celery `harness` 큐에서 비동기 실행 → 3계층 동시 누적 → 다음 잡의 G1/G2/G3 제안 단계에서 RAG로 인용

---

## 🛠️ 자동 오류 처리 흐름

```
BaseAgent.__call__ try/except 훅
    ↓ 예외
AutoErrorHandlerAgent.handle(state, exc, agent_name)
    ↓
[1] error_hash = sha256(agent + exc_type + normalized_stack)
[2] error_kb LOOKUP
    │
    ├── hit & confidence ≥ 0.8  →  자동 패치 (param_adjust/retry/fallback)
    │                              성공 시 confidence += 0.05
    ├── hit & confidence 0.5~0.8 →  retry + 모니터
    │
    └── miss                     →  claude-cli-sidecar 호출
                                    ↓
                                    격리 컨테이너에서 진단 (Read/Grep/Glob만 허용)
                                    ↓
                                    응답 검증 후 error_kb INSERT
                                    code_patch 인 경우 → pending_patches 큐 (인간 검토)
                                    param/retry/fallback 인 경우 → 자동 적용

(모두 실패)  →  ErrorRecoveryAgent (최후 폴백)
```

**핵심 안전장치**
- 사이드카: `--cap-drop ALL`, read-only 마운트, 비루트, 30일 평균 비용 < $5/일
- `code_patch` 자동 적용 절대 금지 (`pending_patches` 인간 승인 필수)
- 동일 오류 5회 시뮬레이션 후 자동 해결률 ≥ 80% 목표 (KP8 ≥ 60%)

---

## 🔐 보안 풀스택

| 위협 | 대응 |
|---|---|
| API 무단 접근 | JWT (HS256, access 24h + refresh 30d) + RBAC 4역할 |
| 시크릿 노출 | HashiCorp Vault (KV v2) |
| PII 유출 | `SecurityGuardAgent` + 정규식 + NER + 결정론적 가명화 + G0_PII 미니게이트 |
| 프롬프트 인젝션 | 정규식 50종 + `wrap_in_user_block` + 시스템 프롬프트 격리 |
| SQL 인젝션 | SQLAlchemy ORM 강제 + RLS 정책 |
| 권한 우회 | 자원 소유권 검증 (analyst는 본인 잡만) |
| 컨테이너 탈출 | seccomp + cap_drop + 비루트 + read-only |
| 비용 폭주 | Redis 토큰 버킷 rate limit + 일일 한도 |
| 감사 추적 | `security_audit_log` 전체 보안 이벤트 INSERT |

**4역할 RBAC** : `admin` / `analyst` / `viewer` / `service`
**침투 테스트** : 50종 페이로드 (SQL 20 + 프롬프트 15 + 권한 5 + JWT 5 + Path traversal 3 + Zip bomb 2) — Day20에서 0건 통과 검증

---

## 📦 13 산출물 패밀리

| 코드 | 산출물 | 추천 청중 | 생성 시간 |
|---|---|---|---|
| OUT-01 | PPT 발표자료 | 모두 (기본) | ~30s |
| OUT-02 | PDF 리포트 | 모두 (기본) | ~20s |
| OUT-03 | 발표 대본 | OUT-01 동반 | ~15s |
| OUT-04 | 정적 웹 대시보드 (단일 HTML) | 시각화 중심 | ~10s |
| OUT-05 | 영상 제작 프롬프트 (Sora/Veo/Kling/Runway/Pika 5종) | 마케팅 | ~20s |
| OUT-06 | 외부 PPT 생성기 프롬프트 (Gamma/Beautiful.ai) | 디자인 도구 사용자 | ~10s |
| OUT-07 | 인사이트 정리 (Markdown) | 기획/전략 | ~15s |
| OUT-08 | 학술 논문 초안 (IEEE/ACM LaTeX → PDF) | 학계/R&D | ~60s |
| OUT-09 | 기획안 (Word/Markdown) | 사업 기획 | ~30s |
| OUT-10 | 1페이지 Executive Summary | 임원 | ~10s |
| OUT-11 | 상세 비즈니스 리포트 (20~30 페이지) | 의사결정용 | ~45s |
| OUT-12 | 인포그래픽 디자인 프롬프트 | 마케팅/홍보 | ~15s |
| OUT-13 | 팟캐스트 대본 + SSML | 콘텐츠 제작 | ~20s |

**병렬 생성** : `ReportComposerAgent` 가 `ThreadPoolExecutor(max_workers=4)` 로 fan-out

---

## 🖥️ 웹 대시보드 — 3페이지

### P1 시스템 현황판
- 헬스 게이지 (postgres/redis/minio/llm 4종)
- **27 에이전트 매트릭스** (5초 폴링, 색상 상태)
- 실행 중인 잡 테이블
- 자체학습 누적 효과 (success_patterns / recipes / Claude CLI 호출 추이)
- 보안 알람 패널 (24h)

### P2 분석 시작 (인터랙티브 워크플로우)
- 파일 업로드 + 의도 입력 (G0)
- **G1~G5 게이트 카드 UI** (실시간 인터럽트 수신)
- WebSocket 메시지 6종 (progress · interrupt · completed · agent_status · warning · error)
- 산출물 다운로드 카드

### P3 잡 히스토리
- 내 분석 이력 (필터: 카테고리/상태/기간)
- 산출물 다시 받기, 재실행

---

## 📊 KPI v2 — 11개 지표

| KPI | 기준 | 측정 |
|---|---|---|
| KP1 | E2E 성공률 ≥ 85% | jobs 테이블 |
| KP2 | 응답 속도 ≤ 120s (게이트 시간 제외) | 타이머 |
| KP3 | 자동 재루프 성공률 ≥ 75% | retry_count > 0 AND status='completed' |
| KP4 | 카테고리 커버 6/6 | 라벨링 |
| KP5 | API p95 < 400ms | locust |
| KP6 | AGENTS.md 자동 룰 ≥ 15 | grep `^### R-A` |
| **KP7** | **자체학습 효과** : 2회차 메트릭 +5%p, Optuna trial -30% | 비교 측정 |
| **KP8** | **자체 오류 해결률 ≥ 60%** | error_kb hit_then_success / total |
| **KP9** | **트랜스포머 채택률 ≥ 33%** (G4 기준) | decisions 테이블 |
| **KP10** | **보안 침투 0건 통과** | 50종 페이로드 |
| **KP11** | **사용자 1순위 채택률 ≥ 60%** (G1 기준) | decisions.adopted_rank |

신규 v2 KPI = KP7~KP11 (모두 Day20에서 측정)

---

## 📋 룰 코드 체계

| 범위 | 카테고리 |
|---|---|
| R-001 ~ R-099 | 핵심 아키텍처 |
| R-101 ~ R-199 | 데이터 |
| R-201 ~ R-299 | 모델 |
| R-301 ~ R-399 | 학습 |
| **R-401 ~ R-499** | **인터랙티브 게이트** (v2) |
| **R-501 ~ R-599** | **자체학습 / KB** (v2) |
| **R-601 ~ R-699** | **오류 처리 / Claude CLI** (v2) |
| **R-701 ~ R-799** | **보안** (v2) |
| R-801 ~ R-899 | 산출물 (v2 확장) |
| R-901 ~ R-999 | Harness / 테스트 |
| R-A001 ~ | **자동 누적 룰** (HarnessAuditor + Claude CLI) |

**v2 신설 핵심 룰**
- R-005 보강 / R-006 / R-007 — 페르소나 정책
- R-401 / R-402 / R-403 — 사용자 입력 sanitize · 24h 자동 처리 · 트랜스포머 강제
- R-501 / R-502 — distill 자동 발행 · PII 마스킹 후만 임베딩
- R-601 / R-602 — confidence ≥ 0.9 자동 적용 · 사이드카 read-only
- R-701 ~ R-714 — 14개 보안 룰
- R-801 — G5 선택만 생성

---

## 🗂️ 작업지시서 파일 목록 (22개)

> 파일 경로 : `C:\IT\workspace_python\ADA\work-orders\daily\`

| 파일 | 종류 | 분량 |
|---|---|---|
| **Day00_마스터설계서_v2.md** | 마스터 (신규) | ~1100 줄 · v2 아키텍처 권위 문서 |
| Day01_환경설정.md | v1 + v2 확장 | Docker · sidecar · vault · pgvector |
| Day02_DB및인프라.md | v1 + v2 확장 | 24+ 테이블 · pgvector · RLS · agent_registry 시드 |
| Day03_공통모듈및CICD.md | v1 + v2 확장 | PipelineStateV2 · BaseAgent persona · personas.py |
| Day04_LangGraph및Celery.md | v1 + v2 확장 | 25 노드 · interrupt 5게이트 · PostgresSaver |
| Day05_데이터처리에이전트.md | v1 + v2 확장 | 멀티 포맷 로더 8종 · PII 스캔 |
| Day06_Supervisor및FastAPI기본.md | v1 + v2 확장 | IntentElicitor (G0) · AnalysisProposer (G1) |
| Day07_정형ML파이프라인및ModelSelection.md | v1 + v2 확장 | MethodologyProposer (G2) · TRANSFORMER_REGISTRY |
| Day08_학습실행에이전트4종.md | v1 + v2 확장 | HPTuner warm-start · Top-3 강제 |
| Day09_HarnessEngineering.md | v1 + v2 확장 | Auditor + SelfLearning/AutoError 인터페이스 |
| Day10_전처리및EDA에이전트.md | v1 + v2 확장 | PreprocChoice 미니게이트 (Day10 단독 소유) |
| Day11_해석력및인사이트에이전트.md | v1 + v2 확장 | ModelStrategyProposer (G3) · ModelComparisonReporter (G4) |
| Day12_산출물생성및확장파이프라인.md | v1 + v2 확장 | 트랜스포머 9 파이프라인 · LoRA |
| Day13_오류처리및API완성.md | v1 + v2 확장 | ErrorRecovery 폴백화 · v2 신규 엔드포인트 |
| Day14_테스트검증및데모.md | v1 + v2 변경 | v1 KPI 확정 · v2 핸드오프 |
| **Day15_산출물패밀리확장.md** | v2 신규 | 13종 생성기 · G5 게이트 · 병렬 fan-out |
| **Day16_자동오류처리및ClaudeCLI브리지.md** | v2 신규 | AutoErrorHandler · cli_bridge · error_kb 사이클 |
| **Day17_보안풀스택.md** | v2 신규 | JWT · RBAC · PII · Vault · 침투 50종 |
| **Day18_웹대시보드및에이전트현황판.md** | v2 신규 | 3페이지 · 27 매트릭스 · 게이트 UI 12 컴포넌트 |
| **Day19_API완성및SelfLearning통합.md** | v2 신규 | SelfLearningAgent 3-Stack · RAG 인용 |
| **Day20_통합테스트및침투테스트.md** | v2 신규 | IT-1~IT-5 · KPI v2 측정 · 침투 50종 |
| **Day21_인수테스트및데모및문서화.md** | v2 신규 | AT-1~AT-5 · 데모 5×5 매트릭스 · 70+ 문서 |

---

## ✅ 정합성 감사 결과 + 수정 사항

> 22개 문서 작성 후 독립 감사 (general-purpose agent) 를 통해 **11개의 실제 정합성 문제** 를 발견하고 모두 수정했습니다.

| # | 분류 | 문제 | 수정 |
|---|---|---|---|
| 1 | CRITICAL | Self-Learning KB 5개 분리 테이블 vs 단일 통합 테이블 불일치 | 마스터를 단일 `self_learning_kb` + `kb_type` partition으로 통일 |
| 2 | CRITICAL | "31 에이전트" 주장 vs 실제 합계 26 | 정식 합계표 신설 → **27 에이전트** (preprocessing_choice + fine_tune 포함) |
| 3 | MODERATE | G0_PII 미니게이트가 §3.1 표에 없음 | 마스터 §3.1에 G0_PII 행 추가 |
| 4 | MODERATE | DashboardOrchestratorAgent 카탈로그만 있고 미구현 | 서비스 레이어 `api/services/dashboard.py` 로 재정의, 합계 제외 |
| 5 | MODERATE | Day04 "29 노드" vs 실제 25 | 25 노드로 정정 (번호 매김 가능한 리스트) |
| 6 | MODERATE | preprocessing_choice Day08/Day10 소유권 분쟁 | Day10 단독 소유로 일원화 |
| 7 | MODERATE | `pending_patches` 마스터 §11.1 누락 | 마스터 §11.1에 추가 + 다른 누락 4개도 보충 |
| 8 | MODERATE | OUT-07 클래스명 `InsightAgent` vs `InsightMDGenerator` | `InsightMDGenerator` 로 통일 |
| 9 | MODERATE | /admin/rules vs /admin/patches 혼동 | Day13에서 2개 엔드포인트로 분리 + reject 추가 |
| 10 | MODERATE | `ws://api/dashboard/stream` 미구현 | 폴링 기본 + push 백로그로 명확화 |
| 11 | MODERATE | `recommend_outputs.py` 위치가 보안 폴더 | `agents/proposers/` 로 이동 |

**감사 OK 판정 (정합성 유지)**
- 26 에이전트 클래스명 모든 파일 동일 철자 ✓
- 16 테이블명 일관 ✓
- G0~G5 게이트 명명 일관 ✓
- R-001 ~ R-A001 룰 범위 충돌 없음 ✓
- KP1~KP11 일관 ✓
- 임베딩 모델 `sentence-transformers/all-mpnet-base-v2` 일관 ✓
- TRANSFORMER_REGISTRY 카테고리별 동일 ✓
- WebSocket 6 메시지 타입 일관 ✓
- ErrorRecovery 폴백 위치 일관 ✓
- Day1→Day2→Day3 의존성 체인 일관 ✓

---

## 🎭 페르소나 정책 (R-005/006/007)

- **모든 27 에이전트**가 가벼운 1줄 페르소나 보유 (마스터 §4.3 권위 표)
- `agents/personas.py` 가 단일 권위 모듈 (검증된 27개 dict + 자가 검증 코드)
- `BaseAgent._call_llm()` 이 system 프롬프트 맨 앞에 자동 prepend
- 시스템 프롬프트 내부에 페르소나 중복 작성 시 `scripts/lint_personas.py` 가 CI에서 잡음
- 페르소나 변경은 PR 리뷰 2인 + `persona_version` bump 필수
- **Day20에 KP12 (페르소나 효과 A/B) 추가 권장** : 27 ON vs 6 ON vs 0 OFF 비교 측정

---

## 📐 시스템 토폴로지 (컨테이너 13종)

```
ada-net (bridge)
├── frontend (Streamlit :8501)
├── api (FastAPI :8000)
├── worker-pipeline   (Celery, pipeline 큐, ×4)
├── worker-training   (Celery, training 큐, ×2, GPU 가능, 8GB)
├── worker-output     (Celery, output 큐, ×2)
├── worker-harness    (Celery, harness 큐, ×1, 자체학습 + 에러KB)
├── postgres (pgvector/pgvector:pg16 :5432)
├── redis :6379 (broker + cache + pubsub + rate limit)
├── minio :9000/:9001
├── mlflow :5000
├── claude-cli-sidecar (read-only 마운트, --cap-drop ALL)
├── vault (HashiCorp Vault dev :8200)
└── nginx (TLS 종료, Day17)
```

---

## 🔗 다음 단계 / 권장 백로그

1. **Day20에 KP12 추가** — 페르소나 A/B 측정 (27 ON / 6 ON / 0 OFF) 결과로 다음 스프린트 페르소나 정책 확정
2. **OUT-04 push 기반 대시보드** — 현재 폴링 5초, push로 전환 시 ws topic `dashboard:agents` 활성화
3. **Vault 프로덕션 전환** — dev 모드 → AppRole 인증 + HA 클러스터
4. **TabPFN 대형 데이터 확장** — 현재 10K행 한계, 청크 추론 패턴 연구
5. **멀티모달 카테고리 정식 추가** — CLIP/BLIP-2 기반 (마스터 §7.2 옵션)
6. **이벤트 소싱 도입 검토** — 현재 LangGraph checkpointer로 충분하나 감사 추적 수요 늘면 별도 이벤트 스토어 고려
7. **다국어 산출물** — 현재 한국어 우선, 영어 OUT-08 LaTeX는 옵션. v3에서 다국어 매트릭스 확장

---

## 📎 부록 — 노션 임포트 팁

1. **단일 페이지 임포트**: 이 파일을 노션 임포트 메뉴 → Markdown & CSV → 이 파일 선택
2. **22개 일별 파일 함께 임포트**: `daily/` 폴더 전체를 ZIP으로 묶어 임포트하면 22개 sub-page 자동 생성
3. **테이블 보기 추천**:
   - "27 에이전트 카탈로그" → 노션 데이터베이스 변환 → LLM 컬럼 필터 추천
   - "21일 스프린트 로드맵" → 캘린더 뷰 변환 → 담당자 컬럼 추가
   - "13 산출물 패밀리" → 갤러리 뷰 (코드별 카드)
4. **토글 활용**: 각 H3 섹션이 노션에서 자동 접힘 가능 → 긴 페이지를 스캔 친화적으로
5. **백링크**: 작업지시서 22 파일 + 이 요약 페이지를 노션의 백링크로 양방향 연결

---

> 본 요약은 **2026-05-15 시점 v2 설계 스냅샷** 입니다. Day20~21에서 KPI 측정 후 v2.1 회고 페이지에서 갱신 예정.
> 변경 이력 : v1.0 (14일 스프린트) → v2.0 (21일, 5게이트, 3-Stack SL, AutoError, 보안 풀스택, 27 페르소나, 정합성 감사 완료)

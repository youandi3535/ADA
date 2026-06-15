# ADA v2 코드베이스 전수조사 보고서

> 작성일: 2026-06-15 · 대상: `C:\IT\workspace_python\ADA` 전체
> 방식: 영역별 7개 조사 + 루트 문서/설정 직접 확인 + 핵심 수치 교차검증
> 브랜치: `feat/NY` · 최근 커밋: 2026-06-14 20:16 (NY 산출물 PDF v4.5)

---

## 0. 한눈에 보기

ADA v2 = **대화형 AutoAI 스튜디오**. 사용자가 정형 데이터를 올리면 **5번의 가벼운 선택(HITL 게이트)** 만으로 자동 분석·튜닝·해석을 수행하고 **5종 산출물**(PPT/PDF/대본/HTML/MD)을 생성. 시간이 지날수록 스스로 학습(팀 KB)하고 오류를 자가수정(5-Tier)하며 보안 풀스택을 갖춤.

- **스코프**: 4개 카테고리 — `tabular_ml`, `tabular_dl`, `timeseries`, `anomaly_detection` (이미지·NLP 제외)
- **팀**: HJ(시스템·인프라, youandi3535) / CS(timeseries) / NY(anomaly) / jh(tabular)
- **규모**: 소스 파일 약 2,382개 중 **Python 423개 · 약 119,000 LOC** + 문서 125개(md) + SVG 1,552개(주로 ny_docs/assets)

### 규모 분포 (Python LOC 기준, 큰 순서)

| 영역 | LOC | 비중 | 핵심 |
|---|---|---|---|
| `outputs/` | 31,271 | 26% | 5종 산출물 생성 엔진 (최대 규모) |
| `agents/` | 25,798 | 22% | 28개 에이전트 + handlers |
| `tests/` | 23,850 | 20% | 103개 테스트 파일 |
| `ada/` | 7,928 | 7% | 인프라 코어 |
| `scripts/` | 7,219 | 6% | 운영·KB·검증 스크립트 |
| `api/` | 3,673 | 3% | FastAPI 백엔드 |
| `pipelines/` | 3,211 | 3% | 4종 학습 파이프라인 |
| `frontend/` | 2,964 | 2% | Streamlit 단일파일 |
| `orchestrator/` | 2,159 | 2% | LangGraph + Celery |
| `migrations/` | 947 | 1% | Alembic 6버전 |
| `tools/` | 834 | 1% | MinIO·비주얼 도구 |
| `serving/` | 433 | <1% | 모델 서빙 |

---

## 1. 전체 디렉토리 지도

```
ADA/
├── ada/                  # 인프라 코어 (config·state·db·error_handler·security·harness·observability)
├── agents/               # 28 에이전트 + gates(5) + handlers(4 카테고리)
├── pipelines/            # 4종 학습 파이프라인 + factory
├── orchestrator/         # LangGraph 그래프(27노드) + Celery 러너 + 체크포인트
├── outputs/              # 5종 산출물 엔진 (context→architect→carrier→visuals)
├── api/                  # FastAPI (12 라우터, ~30 엔드포인트)
├── frontend/             # Streamlit app.py (단일 2,963줄)
├── serving/              # 모델 추론 서빙 (FastAPI)
├── tools/                # MinIO + 비주얼(stock_image/svg/illustration/font)
├── tests/                # 103 파일 (handlers/integration/autofix/day별)
├── scripts/              # KB 수집·동기화·검증·데모 + dev/*.sh
├── migrations/           # Alembic (001~005)
├── docs/                 # 13 설계/운영 문서 (ADR 포함)
├── 작업설계/             # jh tabular E2E 설계서 3종
├── ny_docs/              # NY 개인 작업노트·서버 인프라 가이드 (272+ 파일, 리포 외부 성격)
├── docker/               # Dockerfile 5종 + compose(core/ml/sec 프로파일)
├── mlruns/               # MLflow 로컬 실험 기록 (런타임 생성)
├── .github/              # CI(ci.yml·deploy.yml·auto-pr.yml) + CODEOWNERS
├── .claude/              # settings.json(28KB, 훅+MCP) + settings.local.json
└── 루트 문서             # README·AGENTS·CLAUDE·각종 *_REPORT·TEAM_10DAY_SCHEDULE
```

---

## 2. ada/ — 인프라 코어 (7,928 LOC)

자동 오류복구(ADR-006)를 중심으로 한 엔터프라이즈급 ML 백본.

- **core/**: `state.py`(PipelineState, R-005 `with_update()` 불변패턴, 13 stage report_context), `config.py`(pydantic Settings 중앙화), `logger.py`(structlog + R-103 PII 자동마스킹), `langfuse_client.py`, `breaker.py`, `lang_guard.py`(한국어 강제)
- **db/**: `models.py`(552줄, **24개 테이블** = v1 10 + v2 14), `session.py`(AsyncSession + RLS 훅), `seeds.py`
- **error_handler/**: 5-Tier 자동수정 엔진
  - `auto_handler.py`(843줄) — Tier 0~3 폴백 오케스트레이션
  - `classifier.py` — 5종 분류(TRANSIENT/CODE_BUG/CONFIG/DATA/USER_INPUT) → LLM 비용 절감
  - `static_fixers.py`(546줄) — 6종 결정론적 패치 (LLM 0원)
  - `sandbox.py`(496줄) — git worktree 격리 + ruff + pytest 검증
  - `circuit_breaker.py` — Redis 공유 회로차단(Ollama/Claude)
  - `claude_cli_bridge.py` — 제한모드/전체모드 2종
  - `fixer_promoter.py` — 반복패턴(success≥3) → Tier 0 자동 승격
  - `budget.py` — LLM 비용추적 + 일일한도, `patcher.py` — git apply+hot-reload, `redactor.py` — 단방향 PII
- **security/**: `jwt.py`(RS256/HS256), `rbac.py`, `vault.py`, `guardrails.py`(LLM Guard + 양방향 PIIAnonymizer), `code_redactor.py`(AWS/GCP/SSH키/DSN 마스킹), `raw_error_crypto.py`(AES-GCM)
- **harness/**: `rag.py`(pgvector 3컬렉션, 768d), `distiller.py`(완료 job → 5종 KB 증류 + 감쇠/재교정)
- **observability/**: `kpi.py`(505줄, KP1/KP2/KP5/KP9 자동측정), `metrics.py`(Prometheus + per-agent 인용 ContextVar)

**핵심 루프**: 첫 오류 → Claude 고가 수정 → KB 적재 → 다음 동일오류는 Tier 0에서 무료 해결 (자가강화 사이클).

---

## 3. agents/ — 에이전트 계층 (25,798 LOC)

### 3-1. 기반
- `base.py`(977줄) — **BaseAgent**. R-004 단일 LLM 진입점 `_call_llm()`(Ollama/Anthropic/Claude CLI 라우팅 + 페르소나 자동주입 + 한국어 가드 + 토큰추적 + 진행률 보간), `log_agent_run()`(AgentRun 기록 + KB 인용카운터), `contribute_to_context()`(13 stage 적립)
- `personas.py`(28개 페르소나 단일권위), `stubs.py`(28 클래스 재노출)

### 3-2. 28개 에이전트 (README는 27로 표기 — 실제 28)
supervisor(1) · 입력검증(3: intent_elicitor/data_profiler/schema_validator) · 게이트(5) · 전처리EDA(4) · 모델링(6) · 평가해석(3) · 산출물(2: report_architect/report_composer) · 메타(3) · 회복(1)

**Dispatcher 8종** — `data_profiler`(1279줄)·`preprocessing_strategist`·`feature_engineer`·`eda_agent`·`model_selection`·`eval_agent`·`insight`·`report_composer`. 각자 `get_handler(category, capability)`로 4개 카테고리 핸들러에 분기.

### 3-3. gates/ — 5개 의사결정 게이트
`_base_gate.py`(interrupt/auto-bypass 공통) + G2 analysis_proposer(645줄) · G3 methodology_proposer(567줄) · G4 model_strategy_proposer · G5 model_comparison_reporter · G6 output_type_selector. 리루프 중에는 G6 제외 자동통과.

### 3-4. handlers/ — 카테고리 구현체 (38개 파일)
레지스트리 패턴. capability: profile/plan/apply/apply_split/charts/score/evaluate/generate/assets/build/g1/g2

| capability | tabular(jh) | timeseries(CS) | anomaly(NY) |
|---|---|---|---|
| profile | 불균형·VIF·상관·카디널리티 | 7-Phase(정상성 ADF/KPSS·ACF/PACF·STL·계절·추세 Mann-Kendall·이상치) | 12섹션 47키(IQR·Z·Mahalanobis·PCA·IF·LOF·contamination) |
| preprocess | 15종 변환 카탈로그(2522줄) | 8-Phase(shift(1) 누수차단) | 3단계(RobustScale→Winsorize→PCA95%) |
| 특화 | SMOTE·class_weight·SHAP·확률보정·임계치최적화 | walk-forward CV·MASE/sMAPE·계절성 | PyOD 앙상블 7+종·Otsu 임계·precision@k |

**최대 파일**: tabular/preprocessor.py(2522), timeseries/profiler.py(1569), tabular/output_extras.py(1221), timeseries/preprocessor.py(1042), anomaly/profiler.py(914)

---

## 4. orchestrator/ — 오케스트레이션 (2,159 LOC)

- `graph.py`(445줄) — LangGraph **27 add_node** + 5 게이트 `interrupt_after`. safe_node/safe_gate_node 이중 래퍼(에러→route_after_* 분기). gate_outputs는 상위에러 무시하고 산출물 선택 보장.
- `runner.py`(1236줄) — Celery 4큐(pipeline/training/output/harness) + beat(30초 에러스캔, KB 감쇠/retract). phase기반 진행률 발행(AGENT_PHASE_MAP). ETA: DB실측 우선→파일크기 baseline. resume 시 **fresh invocation**(경로의존 제거) + Redis 분산락. g2/g3 prefetch로 게이트 대기중 다음단계 선계산(120~165초 단축).
- `training_tasks.py` — HEAVY_MODELS(DL/트랜스포머) GPU 워커 위임
- `harness_tasks.py` — distill/decay/retract Celery 태스크
- `checkpoint.py` — CompatMemorySaver + Redis pickle 직렬화(HITL 브리지)

**노드 흐름**: supervisor→intent→profiler→schema →**[G1 direction]**→ eda →**[G2 methodology]**→ preprocess→feature→[preprocessing_choice] →**[G3 model_strategy]**→ model_selection→tuner→training→monitor→metrics →**[G4 best_model]**→ [finetune]→eval→explainability→insight→report_architect →**[G5 outputs]**→ report_composer→self_learning→END

**리루프**: metrics_aggregator가 baseline 못이기면 preprocessing부터 재시작(최대 3회).

---

## 5. pipelines/ — 학습 (3,211 LOC)

`factory.py`(레이지 로딩) → 4종 `BasePipeline`:
- **tabular_ml**(461줄): 베이스라인 3(Dummy/LogReg/Ridge) + 강모델 4(RF/XGB/LGBM/CatBoost), Optuna HPO, joblib 병렬학습, Isotonic 보정
- **tabular_dl**(113줄): TabTransformer/FTTransformer/TabPFN (pytorch_tabular, 미설치시 RF 폴백)
- **timeseries**(674줄): 통계9(ARIMA/SARIMA/SARIMAX/Prophet/ETS + STL/VAR/VARMA/GARCH/AutoARIMA/AutoETS) + NeuralProphet + ML6 + DL7. 과적합방어(행수 적응 order 상한). models_dl_transformer는 **비활성**(활성화 절차 주석 기재)
- **anomaly**(619줄): PyOD 7종 + 상위3 가중앙상블 + Otsu 임계

라이브러리: sklearn·statsmodels·statsforecast·darts·pyod·xgboost/lightgbm/catboost·pytorch

---

## 6. outputs/ — 산출물 엔진 (31,271 LOC, 최대 영역)

**흐름**: `context`(빌드) → `architect`(skeleton 선정) → `content`(본문 채움) → `visuals`(차트) → `carriers`(렌더)

- **context/**: `schema.py`(13묶음 ReportContext dataclass) · `builder.py`(state→정규화, 비파괴) · `citation_manager.py`(498줄, **R-501 출처강제** "수치 0건 무출처") · `code_extractor.py`(재현 코드, redact 통과본) · `completeness.py`(완전성 게이트)
- **architect/**: skeleton 4종 — `report_skeleton.py`(2939) · `ml_pitch.py`(1772) · `anomaly_pitch.py`(1408) · `dl_pitch.py`(1322) · `timeseries_pitch.py`(1102). + `substitution_manifest.py`(카테고리 치환을 config로) · `skeleton_helpers.py`. Action Title·MECE·Pyramid 검증.
- **carriers/**: `pptx_infographics.py`(**4032줄**, 20+ 인포그래픽 함수) · `pptx_designer.py`(1857, 슬라이드별 디자인) · `templates_init.py`(1475, 레지스트리) · `pdf_carrier.py`(1151, reportlab + 한글폰트 7단 폴백) · `llm_copywriter.py`/`llm_designer.py`(LLM 카피/디자인) · html/md/script carrier
- **visuals/**: `render.py`(820, matplotlib + Pretendard 폴백) · `charts.py`(8종 주석패턴)
- **style/**: `visual_kit.py` · `text_budget.py`(글자예산, 중간잘림 금지) · palette(카테고리별 테마색)
- **content/**: `slide_writer.py` · `body_enricher.py` (so_what_scorer·tone_calibrator·speaker_notes·qa_anticipator)
- **layouts/**: 18종 레이아웃 토큰 (grid 12×8)
- **개발용**: `dev_preview3.py`(ReportContext만으로 PDF 프리뷰) · `dev_golden.py`(구조 골든테스트)

산출물: OUT-01 pptx / OUT-02 pdf / OUT-03 txt대본 / OUT-04 html / OUT-07 md. LLM 없으면 템플릿 폴백(graceful degradation).

---

## 7. 웹 계층 — api/ + frontend/ + serving/ + tools/

### api/ (3,673 LOC, FastAPI 12 라우터)
`pipeline.py`(816, start/status/resume/result/gate/download + G2 prefetch) · `conversation_kb.py`(655, Q&A 자동수집+품질게이트) · `kb_search.py`(513, 3-Tier 폴백) · `admin.py`(364, 감사·autofix 대시보드) · `upload.py`(308, magic byte·CP949·prefetch) · `error_dashboard.py`(260) · `auth.py`(120, JWT+Google OAuth) · `observability.py`(KPI 캐싱) · kb/stream/metrics · `middleware.py`(rate limit + SSE)

### frontend/app.py (2,963줄, Streamlit 단일파일)
iframe srcdoc로 임베드된 대형 JS 대시보드. 7단계 스텝퍼, 게이트별 모달(타자기 애니로 분석시간 흡수), G2 주제팝업, F5 복원(URL해시+localStorage), SSE+폴링 진행률.

### serving/main.py (432줄)
MLflow pyfunc 우선 → MinIO joblib 폴백, **R-704 SHA256 무결성검증**, thread-safe 캐시, /predict(분류/회귀/이상).

### tools/ (834 LOC)
`minio_tool.py`(S3호환, CSV 한글 강건처리, DataFrame 캐시) + visual(stock_image API 3종·svg(Lucide)·illustration(unDraw)·font(Pretendard))

---

## 8. 지원 계층 — tests/ scripts/ migrations/ docs/

### tests/ (103 파일, 23,850 LOC)
handlers/{tabular,timeseries,anomaly} 카테고리별 + integration(test_gate_flow 763줄 G1~G7 회귀방어) + pipelines + autofix_phase{1,2}(분류/redactor/sandbox/budget/circuit) + day별(test_day1~24) + 구조검증(graph_build/agents_count/personas)

### scripts/ (48 파일)
- KB: collect_qa(Stop훅) · collect_error_fix(Day24) · ingest_history(Cowork 5분폴링) · query_kb_hook(UserPromptSubmit) · linux_kb_sync(하루3회) · kb_mcp_server
- 검증: dev/verify_autofix_phase2(1205) · verify_day{3,4,5} · verify_oauth_db
- 데모: demo/{tabular,timeseries,anomaly}_demo
- dev/*.sh: **end_of_day.sh**(영역검증→테스트→rebase→push) · **check_scope.sh**(CODEOWNERS 영역강제) · verify_frontend.sh

### migrations/ (Alembic 001~005)
001 초기 24테이블 + pgvector IVFFlat + RLS / 002 conversation_logs / 003 lesson unique / 004 autofix(raw_error 암호화·patch_applications·circuit_breaker_events) / 005 OAuth

### docs/ (13개)
ADR-010(KPI) · KPI_MEASUREMENT · HJ_DAY10_DESIGN · **PARALLEL_WORK_GUARDS**(4인 영역분리 3중방어) · category_extras_schema · carrier_inventory · cs handoff · server/(보안·백업·관리)

### 작업설계/ (3) — jh tabular E2E 설계서 + SVG
### ny_docs/ (272+) — NY 개인 작업노트 + VPS/보안/배포 인프라 가이드 (리포 외부 성격, SVG 다수)

---

## 9. 인프라·배포

- **docker/**: Dockerfile 5종(api/frontend/worker/serving/mlflow) + claude-cli-sidecar + compose(프로파일 core 9종 / ml +3 / sec +2). frontend는 라이브 마운트(F5 반영).
- **컨테이너**: postgres(pgvector pg16)·redis·minio·mlflow·api(**--workers 1** 임베딩 일관성)·frontend·worker-pipeline/harness/training/output·beat·nginx·serving·vault
- **requirements/**: 영역별 분리(base/api/worker/frontend/serving + handlers-{tabular,timeseries,anomaly} + torch-{cpu,cu121} + constraints)
- **.env**: 33개 키(ANTHROPIC·DB·Redis·MinIO·MLflow·Vault·JWT·KB_SERVER·MAX_DAILY_LLM_USD·KPI)
- **pyproject.toml**: v2.4.0, ruff(line 120, 영역별 per-file-ignores), HJ 단독수정
- **.github/**: ci.yml(ruff+pytest+docker) · deploy.yml · auto-pr.yml · CODEOWNERS(서버측 영역강제)
- **LLM**: Cloud(Claude Sonnet/Opus/CLI) + Local(Ollama qwen2.5:7b Q&A · qwen2.5-coder:7b 에러수정, GTX 1060 3GB 대응 CPU강제)

---

## 10. ⚠️ 문서-코드 불일치 (중요)

README는 **v2.3 · 2026-06-01 · Day 11** 상태로 멈춰 있으나, 코드는 **Day 24~25 + 2026-06-14**까지 진행됨. 주요 차이:

| 항목 | README(문서) | 실제 코드 |
|---|---|---|
| 에이전트 수 | 27 | **28** (personas/stubs 모두 28) |
| 그래프 노드 | 25 노드 | **27** add_node |
| 체크포인터 | PostgresSaver | CompatMemorySaver + Redis |
| OUT-02 PDF | WeasyPrint + Jinja2 | **reportlab + matplotlib** |
| 임베딩 모델 | all-mpnet-base-v2 | **paraphrase-multilingual-mpnet-base-v2**(다국어 768d) |
| 시계열 모델 | 6종 | 통계만 11종+ (STL/VAR/GARCH/Auto* 추가) |
| 버전 | v2.3 | pyproject **2.4.0** |
| 진행상황 | "Day 11 진행중" | Day 24 KB·errorkb 브리지까지 |

→ **README/AGENTS 갱신 필요**. 특히 산출물 라이브러리·에이전트 수·노드 수.

---

## 11. 강점·위험·TODO

### 강점
- 5-Tier 자동수정 + 자가강화 KB(고가→저가→무료 학습 사이클)
- 누수차단 3중방어(apply_split·shift(1)·leakage_safe 메타)
- 출처강제(R-501) + 완전성 게이트로 산출물 신뢰성
- LLM 전 구간 폴백(없어도 템플릿 동작)
- 4인 병렬 3중방어(pre-commit·CODEOWNERS·CI) + category_extras 격리

### 위험
- Redis 다운 시 회로차단/예산 동기화 손실(in-memory 폴백은 워커별 독립)
- SHA256 검증이 선택적(expected 없으면 스킵)
- pptx_infographics.py 4032줄 단일파일(분할 권장)
- Celery soft_time_limit 예외처리 부재(GPU 타임아웃)
- rate limit in-memory(다중워커 비공유 → Redis 이전 필요)
- Ollama CPU강제 저사양 타임아웃, Claude CLI 미설치시 Tier 3 스킵

### TODO (소스 전체에 단 6건 — 매우 잘 관리됨)
주로 models_dl_transformer 활성화 대기, timeseries CCF profiler 연동 대기, RLS 미들웨어 활성화 등.

---

## 12. 검증된 핵심 수치 (bash 실측)

- Python 파일 **423개** / 약 **119,167 LOC**
- 에이전트 **28** (personas.py 28 = stubs.py 28)
- 그래프 노드 **27** (add_node 27회) / 게이트 interrupt **5**
- DB 테이블 **24** (migrations 001) / handlers 파일 **38**
- 소스 TODO/FIXME **6건**
- git: feat/NY, 최근 2026-06-14 20:16, owner youandi3535(=HJ)
```

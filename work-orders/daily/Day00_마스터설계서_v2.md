# Day 0 — 마스터 설계서 v2 (Adaptive AutoAI Pipeline Agent / ADA)
> 프로젝트 코드네임: **ADA v2 — Conversational AutoAI Studio**
> 스프린트: 3주 / 21일 (Day1 ~ Day21)
> 문서 버전: v2.1 (2026-05-18 스코프 축소 리뉴얼 — image/NLP 카테고리 및 8종 산출물 제거, Python 3.10 고정)

---

## 0. 이 문서를 읽는 법

본 문서는 v1(14일 스프린트)에서 정의된 단방향 파이프라인을 **대화형 인터랙티브 멀티 에이전트 분석 스튜디오**로 확장하는 v2 마스터 설계서다. Day1~Day14의 기존 작업지시서는 **유지**되며, 본 문서의 §3~§11에서 정의한 신규 컴포넌트가 각 Day 파일의 "🆕 v2 확장 작업" 섹션을 통해 주입된다. Day15~Day21은 v2 신규 작업으로 단독 작성된다.

읽는 순서:

1. §1 — 프로덕트 비전: 우리가 만들려는 시스템의 한 줄 정의와 사용자 여정
2. §2 — 시스템 토폴로지: 컨테이너/서비스/네트워크 구성도
3. §3 — 인터랙티브 5게이트 플로우: HITL(Human-in-the-Loop) 5단계 의사결정 지점
4. §4 — 에이전트 카탈로그 v2: 27 에이전트 + 5 산출물 생성기 유틸리티
5. §5 — 자체학습 에이전트 (3-Stack Self-Learning) 설계
6. §6 — 자동 오류 처리 에이전트 + Claude CLI 사이드카 브리지
7. §7 — Transformer 우선 정책과 모델 레지스트리 (8종)
8. §8 — 산출물 패밀리 (PPT/PDF/대본/대시보드/인사이트 5종)
9. §9 — 웹 대시보드 — 에이전트 현황판 설계
10. §10 — 보안 아키텍처 (인증·인가·감사·프롬프트 인젝션·기밀)
11. §11 — DB 스키마 v2 마이그레이션 명세
12. §12 — 21일 스프린트 일정과 의존성 다이어그램
13. §13 — KPI v2와 인수 기준
14. §14 — 룰 코드 체계 v2 (R-001 ~ R-9xx)

---

## 1. 프로덕트 비전 (한 줄과 사용자 여정)

> **한 줄 정의** — "사용자가 정형/시계열 데이터를 던지면, 다섯 번의 가벼운 선택만으로 의도에 맞게 자동 분석·튜닝·해석을 수행하고, 원하는 형태(PPT/PDF/대본/웹 대시보드/인사이트 5종)로 산출물을 뽑아주는 대화형 AutoAI 스튜디오. 시간이 지날수록 더 똑똑해지고, 자체적으로 오류를 고치며, 외부 위협으로부터 안전하다."

### 1.1 사용자 여정 (Customer Journey)

```
①  웹 대시보드 진입
        ↓
②  시스템 현황판 확인 (어떤 에이전트가 어떤 역할로 돌아가고 있는가)
        ↓
③  데이터 업로드 (csv/xlsx/parquet/json/zip/pdf/txt/html — 정형/시계열 8종)
        ↓
④  "시작" 클릭 → 의도 입력창 (자유서술 1~3문장)
        ↓
⑤  [HITL-1] 에이전트가 "분석 방향 3안" 제시 → 사용자 1안 선택
        ↓
⑥  자동 EDA 수행
        ↓
⑦  [HITL-2] 에이전트가 "방법론(정형 ML / 정형 DL / 시계열 / 이상탐지)" 제안 + 이유 → 사용자 선택
        ↓
⑧  자동 전처리 + 피처 엔지니어링 수행
        ↓
⑨  [HITL-3] 에이전트가 "최종 모델 전략" 제안 + 이유(예: '왜 딥러닝인가') → 사용자 선택
        ↓
⑩  Top-3 후보 모델 학습 + 비교 (트랜스포머 사용 가능하면 무조건 포함)
        ↓
⑪  [HITL-4] 에이전트가 비교표 제시 → 사용자 최종 모델 선택
        ↓
⑫  최종 모델 튜닝 (Optuna + 트랜스포머 강화)
        ↓
⑬  평가 → 해석 → 인사이트 생성
        ↓
⑭  [HITL-5] "어떤 산출물이 필요한가" 메뉴 제시 → 사용자 선택 (다중 선택 가능)
        ↓
⑮  산출물 배포 + 다운로드 + 대시보드 영구 저장
```

언제든 ⑥~⑫는 에이전트 스스로의 판단으로 **반복(re-loop)**될 수 있다. 사용자에게는 진행 중인 재반복도 현황판에 투명하게 표시된다.

### 1.2 v1 대비 핵심 변화

| 항목 | v1 (Day1~14) | v2 (Day1~21) |
|---|---|---|
| 사용자 개입 지점 | error_recovery 시 HITL 1회 | **5단계 HITL 게이트** (LangGraph interrupt 기반) |
| 입력 데이터 | csv/parquet/zip 중심 | **csv/xlsx/parquet/json/zip/pdf/txt/html** 8종 (정형/시계열) |
| 산출물 | PPT/PDF/대본 3종 | **5종** (OUT-01 PPT / OUT-02 PDF / OUT-03 발표 대본 / OUT-04 정적 웹 대시보드 / OUT-07 인사이트 정리) |
| 학습 효과 | 단순 success_patterns 누적 | **3-Stack Self-Learning** (Postgres KB + MinIO artifacts + pgvector RAG) |
| 오류 처리 | ErrorRecoveryAgent in-flow | **AutoErrorHandlerAgent 데몬** + Claude CLI 사이드카 + Error KB |
| 모델 정책 | 4종 트리 + DL 1종 | **트랜스포머 우선 정책** (가능하면 무조건 트랜스포머 조합) |
| 보안 | 시크릿 .env + SHA256 | **풀스택 보안 모델** (인증·RBAC·PII 레닥션·프롬프트 인젝션 방어·전송/저장 암호화·감사 로그) |
| 대시보드 | 진행률 바 | **에이전트 현황판** (실시간 역할/상태/부하/누적 효과 시각화) |

---

## 2. 시스템 토폴로지

### 2.1 컨테이너 구성 (Docker Compose v2)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          ada-net (bridge)                                │
│                                                                          │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  ┌─────────┐ │
│  │ frontend │──▶│   api    │──▶│  worker  │──▶│  mlflow  │  │ minio   │ │
│  │ Streamlit│   │ FastAPI  │   │ Celery×N │   │ tracking │  │ S3-호환 │ │
│  │  :8501   │   │  :8000   │   │  ×4 큐   │   │  :5000   │  │  :9000  │ │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘  └─────────┘ │
│       │              │               │               │            │     │
│       └──────────────┼───────────────┼───────────────┼────────────┘     │
│                      ▼               ▼               ▼                   │
│              ┌──────────────────────────────────────────┐                │
│              │  postgres :5432  (autoai + mlflow +      │                │
│              │  langgraph_checkpoints + pgvector)       │                │
│              └──────────────────────────────────────────┘                │
│                      │                                                   │
│              ┌──────────────────────────────────────────┐                │
│              │  redis :6379  (broker + cache + pubsub + │                │
│              │  rate limit token bucket)                │                │
│              └──────────────────────────────────────────┘                │
│                                                                          │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────┐   │
│  │ claude-cli-     │  │ qdrant :6333     │  │ vault :8200            │   │
│  │ sidecar         │  │ (옵션, pgvector  │  │ HashiCorp Vault Dev    │   │
│  │ (subprocess     │  │  로 대체 가능)   │  │ (시크릿 매니저)        │   │
│  │  격리, Day16)   │  │                  │  │                        │   │
│  └─────────────────┘  └──────────────────┘  └────────────────────────┘   │
│                                                                          │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────────┐   │
│  │ otel-collector  │  │ prometheus :9090 │  │ grafana :3000          │   │
│  │ :4317           │  │                  │  │ (에이전트 현황판 백엔드│   │
│  │ (옵션)          │  │                  │  │  보조 시각화)          │   │
│  └─────────────────┘  └──────────────────┘  └────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

v1 대비 신규 컨테이너: **claude-cli-sidecar**, **vault (시크릿 매니저)**, 선택적으로 **qdrant**, **otel-collector/prometheus/grafana**. pgvector는 PostgreSQL 익스텐션으로 동거하므로 별도 컨테이너 불필요.

### 2.2 큐 토폴로지 (Celery v2)

| 큐 이름 | 워커 수 | 용도 |
|---|---|---|
| `pipeline` | 4 | 메인 파이프라인 (LangGraph 그래프 실행) |
| `training` | 2 (GPU 가능) | 모델 학습/튜닝 — 무거운 잡 격리 |
| `output` | 2 | 산출물 생성 (PPT/PDF/대본/대시보드/인사이트) |
| `harness` | 1 | 자체학습 데몬 + 에러KB 정리 작업 |

큐 분리 이유: 학습 잡이 메인 파이프라인 큐를 막지 않도록, 그리고 자체학습 작업이 백그라운드에서 조용히 돌도록.

### 2.3 LangGraph + Checkpointer

- `langgraph.checkpoint.postgres.PostgresSaver` 로 **모든 상태가 PostgreSQL 에 영속화**
- 각 HITL 인터럽트 지점에서 그래프가 멈추고 thread_id 별로 재개 가능
- `thread_id == job_id` 매핑 (1 job = 1 thread)

---

## 3. 인터랙티브 5게이트 플로우

### 3.1 게이트 정의

| 게이트 | 시점 | 사용자 입력 | 에이전트 책임 |
|---|---|---|---|
| **G0 (Intent)** | 데이터 업로드 직후 | 자유 텍스트 1~3문장 | IntentElicitorAgent — 의도 파악 후 구조화 |
| **G0_PII (PII Mini)** | 데이터 프로파일링 중 PII 감지 시에만 | 컬럼별 마스킹/제외/유지 선택 | DataProfiler + SecurityGuardAgent 협업 — PII 컬럼 발견 시 발동 |
| **G1 (Direction)** | 데이터 프로파일링 후 | 3안 중 1안 선택 | AnalysisProposerAgent — 데이터+의도로 3개 방향 제시 |
| **G2 (Methodology)** | EDA 후 | 정형 ML / 정형 DL / 시계열 / 이상탐지 중 선택 | MethodologyProposerAgent — 이유와 함께 제시 |
| **G3 (Model Strategy)** | 전처리+FE 후 | 최종 모델 전략 선택 (예: TabTransformer / XGBoost+SHAP / TFT) | ModelStrategyProposerAgent — 후보별 장단점 매트릭스 제시 |
| **G4 (Best Model)** | Top-3 학습 후 | 비교표에서 1개 모델 선택 | ModelComparisonReporterAgent — 비교 시각화 + 추천 |
| **G5 (Outputs)** | 평가/해석 완료 후 | 산출물 다중 선택 (체크박스) | OutputTypeSelectorAgent — 의도와 메트릭으로 추천 산출물 강조 |

> G0_PII 는 일반 흐름에서는 발동하지 않는 **조건부 미니 게이트**다. DataProfiler 가 PII 후보 컬럼을 검출했을 때에만 그래프가 일시정지되며 R-701 룰에 의해 강제된다. G0~G5 의 5개 정규 게이트는 모든 잡에서 항상 발동한다.

### 3.2 LangGraph interrupt 구현 패턴

```python
# orchestrator/graph_v2.py 발췌
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver
from typing import Annotated

def gate_direction(state: PipelineStateV2) -> PipelineStateV2:
    """G1 게이트 노드 — 3안 제시 후 interrupt."""
    proposals = AnalysisProposerAgent()(state).proposals  # [{title, why, plan_outline}*3]
    # state에 후보 저장, 사용자 선택 대기
    return state.model_copy(update={
        "proposals_g1": proposals,
        "awaiting_decision": "G1",
    })

def route_after_gate_direction(state: PipelineStateV2):
    """사용자 선택이 들어왔는지 확인 후 분기."""
    if state.user_choice_g1 is None:
        # interrupt — 그래프 일시정지
        from langgraph.errors import GraphInterrupt
        raise GraphInterrupt({"gate": "G1", "proposals": state.proposals_g1})
    return "eda_agent"

# 그래프 빌드
graph = StateGraph(PipelineStateV2)
graph.add_node("intent_elicitor", IntentElicitorAgent())
graph.add_node("data_profiler", DataProfilerAgent())
graph.add_node("schema_validator", SchemaValidatorAgent())
graph.add_node("gate_direction", gate_direction)
# ... v1 16개 핵심 노드 + 5개 게이트 노드 + 9개 신규 에이전트(intent_elicitor 4 proposers selflearn autoerror sec dash fine_tune)
# + self_learning_dispatch + error_recovery + END
# = 약 25 노드 (Day04 v2 정식 카운트 참조)
graph.add_conditional_edges("gate_direction", route_after_gate_direction, {...})

checkpointer = PostgresSaver.from_conn_string(settings.database_url)
compiled = graph.compile(checkpointer=checkpointer, interrupt_after=["gate_direction", "gate_methodology", ...])
```

API에서의 재개:

```python
# api/routes/decision.py
@router.post("/decision/{job_id}", response_model=DecisionAck)
async def submit_decision(job_id: str, req: DecisionRequest, db = Depends(get_db)):
    """G1~G5 사용자 선택을 받아 그래프를 resume."""
    # 1. 사용자 입력 검증 + 보안 (XSS/프롬프트 인젝션 필터, §10)
    sanitized = sanitize_user_input(req.choice)
    # 2. checkpointer에서 state 로드
    config = {"configurable": {"thread_id": job_id}}
    snap = compiled.get_state(config)
    # 3. state 업데이트 (user_choice_gX 필드에 주입)
    new_state = {**snap.values, f"user_choice_{req.gate.lower()}": sanitized}
    compiled.update_state(config, new_state)
    # 4. 재개를 Celery에 위임
    celery_app.send_task("resume_pipeline", args=[job_id], queue="pipeline")
    return DecisionAck(job_id=job_id, gate=req.gate, accepted=True)
```

### 3.3 게이트별 UI 컴포넌트 사양

- **G0**: `<textarea>` 1개 + "예시 의도 보기" 토글
- **G1**: 3장의 카드 (제목·이유·예상 결과·예상 소요시간), 라디오 선택
- **G2**: 표 형식 (방법론, 적합도 점수, 이유, 트랜스포머 가능 여부, 예상 메트릭), 라디오 선택
- **G3**: 매트릭스 (모델 후보 × 평가축), 라디오 선택 + "이유 자세히 보기" 펼침
- **G4**: 메트릭 비교 막대차트 + 학습곡선 + 해석 미리보기, 라디오 선택
- **G5**: 체크박스 그리드 (5종 산출물 OUT-01/02/03/04/07), 추천 산출물에 ⭐ 배지

### 3.4 타임아웃 정책

각 게이트의 사용자 응답 대기는 기본 **24시간**. 미응답 시 에이전트가 **자동 최적안**으로 선택을 대신하고 사용자에게 알림(이메일/대시보드 알림). 자동 선택 이력은 `interactive_sessions.auto_resolved=true` 로 마킹되어 자체학습 KB에 들어간다.

---

## 4. 에이전트 카탈로그 v2 (전체 30+ 종)

### 4.1 카테고리 별 분류

**A. 입력·검증 (3종)** — 기존 유지
- `IntentElicitorAgent` 🆕 — 자유 의도 텍스트를 구조화
- `DataProfilerAgent` (확장: xlsx/json/pdf/txt/html 핸들러 추가 — 정형/시계열 8종)
- `SchemaValidatorAgent`

**B. 의사결정 제안 (5종, 신규)** 🆕
- `AnalysisProposerAgent` — G1, 3안 제시
- `MethodologyProposerAgent` — G2
- `ModelStrategyProposerAgent` — G3
- `ModelComparisonReporterAgent` — G4
- `OutputTypeSelectorAgent` — G5

**C. 전처리·EDA (3종)** — 기존 유지 + 사용자 선택 반영
- `PreprocessingStrategistAgent`
- `FeatureEngineerAgent`
- `EDAAgent`

**D. 모델링 (5종)** — 기존 + 트랜스포머 우선
- `ModelSelectionAgent` (확장: TabTransformer/FTTransformer/Informer/TFT/PatchTST/TranAD 우선)
- `HyperparameterTunerAgent`
- `TrainingExecutorAgent`
- `TrainingMonitorAgent`
- `MetricsAggregatorAgent`

**E. 평가·해석 (3종)** — 기존 유지
- `EvalAgent`
- `ExplainabilityAgent`
- `InsightAgent`

**F. 산출물 오케스트레이터 (에이전트 1종)** 🆕
- `ReportComposerAgent` — 오케스트레이터. 사용자가 G5 에서 고른 산출물 코드에 따라 아래 5개 **생성기 유틸리티 클래스** 를 병렬로 호출한다.
  - 생성기 유틸리티 (`reports/` 패키지, 에이전트 아님, 5종): `PresentationGenerator` (OUT-01) / `PDFGenerator` (OUT-02) / `ScriptGenerator` (OUT-03) / `DashboardArtifactGenerator` (OUT-04, 정적 HTML 단일 파일) / `InsightMDGenerator` (OUT-07)
  - 이들 생성기는 `agent_registry` 에 등록되지 **않으며** heartbeat 도 보내지 않는다. 단순 도구.

**G. 메타 (3종, 신규)** 🆕
- `SelfLearningAgent` — §5
- `AutoErrorHandlerAgent` — §6
- `SecurityGuardAgent` — §10 (프롬프트 인젝션·PII 검사)
- *(주: 마스터 §9 의 "DashboardOrchestratorAgent" 는 별도 백엔드 에이전트가 아니라 `DashboardOrchestratorService` 라는 FastAPI 서비스 레이어로 구현됨. `api/services/dashboard.py` 가 `agent_registry`, `self_learning_kb`, `jobs` 를 집계해 `/dashboard/*` 엔드포인트에 노출. 에이전트 카운트에 포함 안 됨.)*

**H. 회복 (1종)** — 기존
- `ErrorRecoveryAgent` (in-flow, AutoErrorHandler가 못 풀면 호출)

**I. 슈퍼바이저 (1종)** — 기존
- `SupervisorAgent` (확장: G0 IntentElicitor 호출 책임)

**합계 — 에이전트 27종 + 산출물 생성기 유틸 5종**:

| 카테고리 | 에이전트 수 | 비고 |
|---|---|---|
| I 슈퍼바이저 | 1 | SupervisorAgent |
| A 입력·검증 | 3 | IntentElicitor, DataProfiler, SchemaValidator |
| B 의사결정 제안 (게이트) | 5 | 5 Proposer |
| C 전처리·EDA + 미니게이트 | 4 | PreprocessingStrategist, FeatureEngineer, EDA, PreprocessingChoiceAgent |
| D 모델링 + 트랜스포머 튜닝 | 6 | 5종 + FineTuneExecutorAgent |
| E 평가·해석 | 3 | Eval, Explainability, Insight |
| F 산출물 오케스트레이터 | 1 | ReportComposer만. 5 생성기는 유틸리티(`reports/*.py`) |
| G 메타 | 3 | SelfLearning, AutoErrorHandler, SecurityGuard. (대시보드는 서비스 레이어) |
| H 회복 | 1 | ErrorRecoveryAgent |
| **agent_registry 시드 합계** | **27** | |

agent_registry seed migration(Day02 §5)은 정확히 **27 행**을 INSERT 한다. Day14 v2 / Day18 시스템 현황판 / Day21 README 모두 "27 에이전트" 기준으로 통일.

### 4.3 페르소나 권위 표 (27 에이전트)

> **정책**: 모든 에이전트는 **가벼운 1줄 페르소나 + 두꺼운 기능 지시** 패턴을 따른다. 페르소나는 LLM 호출이 있는 에이전트에 한해 `_call_llm()` 진입 직전 자동 주입되며, LLM 미사용 에이전트는 페르소나가 `agent_registry.persona` 컬럼에만 보존되어 대시보드/문서에서 사용된다. 페르소나 길이는 최대 80자(한글 기준)로 제한한다.

| # | Agent | LLM | Persona (1줄) |
|---|---|---|---|
| 01 | SupervisorAgent | Sonnet | 당신은 데이터 분석 파이프라인의 입출항 관제사로, 입력의 유효성과 다음 단계 적합성을 빠르게 판정합니다. |
| 02 | IntentElicitorAgent | Sonnet | 당신은 사용자의 한 줄 의도를 구조화된 분석 명세로 옮기는 비즈니스 분석 인터뷰어입니다. |
| 03 | DataProfilerAgent | none | 당신은 들어온 데이터의 형태와 결을 한눈에 파악하는 데이터 검수관입니다. |
| 04 | SchemaValidatorAgent | none | 당신은 분석 카테고리별 필수 요건을 엄격히 점검하는 데이터 품질 감사관입니다. |
| 05 | AnalysisProposerAgent (G1) | Opus | 당신은 분석 의도와 데이터를 보고 서로 다른 세 갈래의 길을 제시하는 데이터 전략 컨설턴트입니다. |
| 06 | MethodologyProposerAgent (G2) | Sonnet | 당신은 정형 ML / 정형 DL / 시계열 / 이상탐지 4종 방법론을 데이터 특성에 맞게 비교 권장하는 AutoML 자문가입니다. |
| 07 | ModelStrategyProposerAgent (G3) | Opus | 당신은 모델 아키텍처 후보를 장단점 매트릭스로 정리해 의사결정을 돕는 모델링 아키텍트입니다. |
| 08 | ModelComparisonReporterAgent (G4) | none | 당신은 학습 결과를 공정한 비교표와 그래프로 가시화하는 모델 평가 리포터입니다. |
| 09 | OutputTypeSelectorAgent (G5) | Sonnet | 당신은 의도·청중·메트릭을 보고 최적 산출물 조합을 권장하는 리서치 디자인 큐레이터입니다. |
| 10 | PreprocessingStrategistAgent | Sonnet | 당신은 데이터의 결을 살리는 전처리 단계를 설계하는 시니어 데이터 엔지니어입니다. |
| 11 | FeatureEngineerAgent | none | 당신은 결정된 전처리 계획을 정확하고 재현 가능하게 실행하는 피처 빌더입니다. |
| 12 | EDAAgent | none | 당신은 분포·관계·이상 신호를 빠르게 그림으로 옮기는 EDA 분석가입니다. |
| 13 | PreprocessingChoiceAgent | Sonnet | 당신은 자동 결정 신뢰도가 애매할 때 사용자와 최소 대화로 합의를 만드는 전처리 큐레이터입니다. |
| 14 | ModelSelectionAgent | Sonnet | 당신은 데이터 특성과 과거 성공 레시피를 종합해 최적 모델 후보 3종을 선정하는 AutoML 큐레이터입니다. |
| 15 | HyperparameterTunerAgent | none | 당신은 warm-start와 Optuna로 탐색 공간을 효율적으로 좁히는 하이퍼파라미터 튜너입니다. |
| 16 | TrainingExecutorAgent | none | 당신은 모델 학습 잡을 안정적이고 재현 가능하게 실행하는 ML 트레이닝 엔지니어입니다. |
| 17 | TrainingMonitorAgent | none | 당신은 발산·과적합·NaN 같은 학습 이상 신호를 조기에 포착하는 학습 안전 감독관입니다. |
| 18 | MetricsAggregatorAgent | none | 당신은 후보 모델의 메트릭을 정규화·비교해 최적 모델을 객관적으로 골라내는 메트릭 심판관입니다. |
| 19 | FineTuneExecutorAgent | none | 당신은 트랜스포머 모델의 마지막 1%를 끌어올리는 미세조정 전문가입니다. |
| 20 | EvalAgent | Opus | 당신은 임계치 룰과 도메인 감각을 결합해 모델 출시 가능성을 판정하는 모델 QA 평가관입니다. |
| 21 | ExplainabilityAgent | none | 당신은 모델 판단 근거를 SHAP과 시계열 분해로 시각화하는 해석성 분석가입니다. |
| 22 | InsightAgent | Opus | 당신은 분석 메트릭을 비즈니스 의사결정자가 이해할 수 있는 한국어 인사이트로 옮기는 분석 스토리텔러입니다. |
| 23 | ReportComposerAgent | none | 당신은 사용자가 선택한 산출물 조합을 병렬로 조율해 데드라인 안에 묶어 내는 산출물 PM입니다. |
| 24 | SelfLearningAgent | none | 당신은 매 분석에서 얻은 지식을 3-Stack KB에 깔끔히 정리해 다음 분석을 더 똑똑하게 만드는 지식 큐레이터입니다. |
| 25 | AutoErrorHandlerAgent | CLI | 당신은 처음 보는 오류는 빠르게 진단하고, 본 적 있는 오류는 KB로 즉시 해결하는 자동 오류 정비공입니다. |
| 26 | SecurityGuardAgent | none | 당신은 PII와 프롬프트 인젝션 시도를 끊임없이 감시하는 보안 가드입니다. |
| 27 | ErrorRecoveryAgent | Opus | 당신은 자동 처리가 끝까지 실패했을 때 사용자에게 친절히 상황을 설명하고 다음 행동을 안내하는 회복 코디네이터입니다. |

### 4.4 페르소나 활용 규칙

- **R-005 보강**: BaseAgent 서브클래스는 클래스 속성 `persona: str` 을 반드시 선언. 빈 문자열 금지.
- **R-006 (신규)**: `_call_llm()` 은 system 프롬프트 맨 앞에 `f"{self.persona}\n\n"` 를 자동 prepend. 서브클래스가 시스템 프롬프트에 페르소나를 중복 작성하면 린트 경고.
- **R-007 (신규)**: 페르소나 변경은 PR 리뷰 2인 + 변경 사유 기록 필수 (페르소나가 KB 인용/사용자 톤에 영향).
- **출력 일관성**: 페르소나는 톤·시점·우선순위 강제용이며, 사실 정확도에 의존하는 출력에는 페르소나가 아닌 **출력 스키마와 예시**로 보장한다.
- **A/B 측정**: Day20 통합 테스트에 페르소나 ON/OFF 비교 항목 추가 (KP12 — 페르소나 효과). 결과에 따라 다음 스프린트에서 페르소나 축소·강화 결정.

### 4.2 에이전트 레지스트리

모든 에이전트는 시작 시 `agent_registry` 테이블에 자기 자신을 등록한다.

```sql
CREATE TABLE agent_registry (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_name   VARCHAR(128) UNIQUE NOT NULL,
    role         VARCHAR(64) NOT NULL,           -- 'gate' | 'data' | 'modeling' | 'output' | 'meta'
    description  TEXT,
    llm_model    VARCHAR(64),                    -- 'none' | 'claude-sonnet-4-6' | 'claude-opus-4-7'
    inputs       JSONB,                          -- 입력 state 필드 목록
    outputs      JSONB,                          -- 출력 state 필드 목록
    capabilities JSONB,                          -- ['shap', 'tuning', 'tsdecompose', ...]
    version      VARCHAR(16) DEFAULT '2.0.0',
    is_active    BOOLEAN DEFAULT TRUE,
    last_heartbeat TIMESTAMPTZ,
    avg_duration_ms INTEGER,
    success_rate FLOAT,                          -- 최근 100회 기준
    registered_at TIMESTAMPTZ DEFAULT NOW()
);
```

대시보드 현황판은 이 테이블을 5초마다 폴링하여 시각화한다.

---

## 5. 자체학습 에이전트 (3-Stack Self-Learning)

### 5.1 설계 원칙

> **"매 분석이 끝나면 한 줌의 지식을 챙겨두고, 다음 분석에서 그 지식을 가장 먼저 끄집어낸다."**

- 학습은 **분석 종료 직후** Celery `harness` 큐에서 비동기 진행 (사용자 응답 차단 X)
- 학습 데이터는 **3개 층**에 동시 저장 (검색·재현·요약 각각 최적)
- 새 분석 시작 시 **G1/G2/G3 제안 단계에서 자체학습 KB를 RAG로 인용**

### 5.2 3-Stack 구조

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 1 — 구조화 KB (PostgreSQL)                            │
│  단일 테이블 `self_learning_kb` 의 `kb_type` 컬럼으로 분류:  │
│  - kb_type='success_pattern' (성공 파이프라인 config 스냅샷) │
│  - kb_type='recipe' (카테고리×메트릭별 best practice 레시피)│
│  - kb_type='eda_template' (도메인별 EDA 차트 셋)             │
│  - kb_type='hpo_warm_start' (Optuna warm start best params)│
│  - kb_type='failure_lesson' (실패 교훈)                      │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  Layer 2 — 원시 아티팩트 (MinIO)                             │
│  - data_profiles/{job_id}.json (전체 프로파일)                │
│  - shap_values/{job_id}.npy (해석 결과)                       │
│  - learning_curves/{job_id}.csv (학습 곡선)                   │
│  - best_model/{job_id}/* (모델 가중치 + 토크나이저 등)        │
│  - prompts/{job_id}/* (LLM 프롬프트/응답 페어 — 미세조정용)   │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  Layer 3 — 의미 검색 (pgvector / Qdrant)                     │
│  - dataset_embeddings (데이터 프로파일 → 768d 벡터)           │
│  - intent_embeddings (사용자 의도 → 768d 벡터)                │
│  - lesson_embeddings (failure_lessons 텍스트 → 768d 벡터)     │
│  임베딩 모델: `sentence-transformers/all-mpnet-base-v2`       │
│  거리: cosine, 검색: top-5 with score≥0.75                   │
└──────────────────────────────────────────────────────────────┘
```

### 5.3 학습 파이프라인 (KnowledgeDistillationPipeline)

```
job 완료 → Celery harness 큐에 distill_job(job_id) 발행
       ↓
SelfLearningAgent.distill(job_id) 실행:
   1. job의 모든 state, agent_runs, metrics, eval_result 수집
   2. Layer1 INSERT/UPSERT
       - success_patterns: 성공 시
       - failure_lessons: 실패 시 (Auditor가 만든 룰과 별개로)
       - model_recipes: best_model 메트릭이 threshold 상회 시
       - hpo_warm_starts: Optuna best_params
       - eda_templates: 사용된 차트 셋
   3. Layer2 아티팩트 영구화
       - data_profile, shap_values, learning_curves, prompts 페어 저장
   4. Layer3 임베딩 생성·저장
       - dataset 임베딩 = profile.summary 텍스트화 후 임베딩
       - intent 임베딩 = user_question 임베딩
       - lesson 임베딩 = failure_lesson 임베딩
   5. job_distillation_log 에 결과 기록
```

### 5.4 RAG 인용 패턴

새 분석에서 **G1 AnalysisProposerAgent** 가 호출될 때:

```python
def propose_3_directions(state):
    # 1. 사용자 의도 + 데이터 프로파일을 임베딩
    intent_emb = embed(state.user_intent)
    profile_emb = embed(state.data_profile.summary)
    # 2. Layer3에서 유사 과거 사례 검색
    similar_cases = vector_search(intent_emb + profile_emb, top_k=5, score≥0.75)
    # 3. Layer1에서 해당 사례들의 success_patterns / model_recipes 조회
    recipes = load_recipes(similar_cases.job_ids)
    # 4. Claude Opus에 "과거에 이런 케이스에서 통했던 레시피들"을 system context로 주입
    proposals = llm.call(prompt + recipes_context)
    # 5. proposals에는 항상 "참고한 과거 케이스 N건" 메타데이터 첨부
    return proposals
```

### 5.5 학습 누적 측정 (KPI v2-KP7)

- **재현 정확도**: 동일 데이터셋 2번째 분석 시 1번째 대비 메트릭 변화 ≥ +5%
- **수렴 속도**: Optuna trial 수가 동일 메트릭 도달까지 ≥ 30% 감소
- **G1 제안 품질**: 사용자가 "추천 1순위" 안을 선택하는 비율 ≥ 60%

### 5.6 안전장치

- 개인정보/PII 가 포함된 프롬프트·응답은 **저장 전 마스킹** (Day17 SecurityGuard)
- Layer2 prompts/* 는 90일 후 자동 익명화 (`anonymize_pipeline.sh` cron)
- Layer1 success_patterns 동일 해시 충돌 시 success_count 증가만 (덮어쓰기 X)

---

## 6. 자동 오류 처리 에이전트 (Auto-Error-Handler)

### 6.1 설계 원칙

> **"처음 보는 오류는 Claude CLI 에게 격리된 셸로 묻고, 본 적 있는 오류는 KB로 먼저 풀어본다."**

### 6.2 구조

```
                   ┌──────────────────────┐
                   │  모든 에이전트 호출  │
                   │  BaseAgent.__call__  │
                   │   try/except 래퍼   │
                   └──────────┬───────────┘
                              │ 예외 발생
                              ▼
              ┌─────────────────────────────────┐
              │  AutoErrorHandlerAgent           │
              │                                  │
              │  1. error_hash = sha256(         │
              │       agent + exc_type +         │
              │       normalize(stack_trace))    │
              │                                  │
              │  2. error_kb LOOKUP by hash      │
              │     - hit & confidence ≥ 0.8 →   │
              │         자동 패치 (3a)           │
              │     - hit & confidence < 0.8 →   │
              │         재시도 + 모니터 (3b)     │
              │     - miss →                     │
              │         Claude CLI 호출 (3c)     │
              │                                  │
              │  3a. 자동 패치 적용 후 재시도    │
              │      성공 시 confidence += 0.05  │
              │      실패 시 confidence -= 0.10  │
              │                                  │
              │  3b. 재시도 + 결과 기록          │
              │                                  │
              │  3c. claude-cli sidecar 호출:    │
              │      - 컨텍스트: 스택+코드+state │
              │      - 응답: 패치 제안 JSON      │
              │      - 신뢰도 평가 후 KB INSERT  │
              │      - 적용·재시도               │
              │                                  │
              │  4. 모든 결과 audit_log에 기록  │
              └──────────────┬──────────────────┘
                             │
                             ▼ (3회 실패 시)
                   ┌──────────────────────┐
                   │ ErrorRecoveryAgent   │
                   │ (인플로우 마지막 보루)│
                   └──────────────────────┘
```

### 6.3 Claude CLI 사이드카

전용 Docker 컨테이너 `claude-cli-sidecar`:

```dockerfile
# docker/claude-cli-sidecar.Dockerfile
FROM node:20-slim
RUN npm install -g @anthropic-ai/claude-code
# 격리: 다른 서비스 코드 마운트는 read-only
USER 1001
WORKDIR /workspace
ENTRYPOINT ["claude"]
```

`docker-compose.yml`:

```yaml
claude-cli-sidecar:
  build: ./docker/claude-cli-sidecar
  image: ada/claude-cli-sidecar:latest
  volumes:
    - .:/workspace:ro        # 소스코드 read-only 마운트
    - ./error_handler:/error_handler:rw   # 패치 출력만 쓰기 가능
  environment:
    - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
  networks:
    - ada-net
  # FastAPI worker가 subprocess로 docker exec 호출
```

호출 패턴 (Python):

```python
# error_handler/cli_bridge.py
import subprocess, json, tempfile

def ask_claude_cli(error_context: dict, max_turns: int = 3) -> dict:
    """error_context: {agent, exc_type, stack, code_snippet, state_summary}"""
    prompt = build_repair_prompt(error_context)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(json.dumps(error_context, ensure_ascii=False))
        ctx_path = f.name

    cmd = [
        "docker", "exec", "claude-cli-sidecar",
        "claude", "-p", prompt,
        "--max-turns", str(max_turns),
        "--output-format", "json",
        "--allowed-tools", "Read,Grep,Glob",   # 셸/쓰기 금지
        "--context-file", ctx_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"claude-cli failed: {res.stderr}")
    parsed = json.loads(res.stdout)
    return parsed   # {'root_cause', 'patch_diff', 'confidence', 'test_plan'}
```

보안 가드:
- Sidecar는 **read-only 코드 마운트** (어떤 파일도 직접 수정 못 함)
- 패치 적용은 메인 워커가 `error_handler/patches/` 에 수신 후 **샌드박스 적용** 후 단위 테스트 통과 시에만 메인 코드에 머지
- 신뢰도 ≥ 0.9 + 단위 테스트 통과 → 자동 적용
- 그 외 → `pending_patches` 큐로 인간 검토

### 6.4 Error KB 스키마

```sql
CREATE TABLE error_kb (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    error_hash        CHAR(64) UNIQUE NOT NULL,
    agent_name        VARCHAR(128),
    exc_type          VARCHAR(128),
    error_signature   TEXT,                     -- 정규화된 stack 핵심
    root_cause        TEXT,
    patch_strategy    JSONB,                    -- {type:'param_adjust'|'retry'|'fallback'|'code_patch', detail:{}}
    confidence        FLOAT DEFAULT 0.5,
    seen_count        INTEGER DEFAULT 1,
    success_count     INTEGER DEFAULT 0,
    fail_count        INTEGER DEFAULT 0,
    last_seen_at      TIMESTAMPTZ DEFAULT NOW(),
    source            VARCHAR(32) DEFAULT 'claude_cli',  -- 'claude_cli'|'human'|'heuristic'
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_error_kb_hash ON error_kb(error_hash);
CREATE INDEX idx_error_kb_agent ON error_kb(agent_name);
```

### 6.5 측정 지표 (KPI v2-KP8)

- **자체 해결률**: error_kb hit 후 자동 패치 성공 비율 ≥ 60% (스프린트 종료 시점)
- **반복 오류 감소**: 동일 error_hash 재발생률 시간에 따라 감소
- **Claude CLI 호출 감소**: 30일 평균 호출 수가 시간이 갈수록 줄어듦

---

## 7. Transformer 우선 정책

### 7.1 정책 선언

> **"분석할 모델이 트랜스포머로 구성 가능한 경우, 후보 3개 중 최소 1개는 트랜스포머 기반이어야 한다."**

### 7.2 카테고리별 트랜스포머 매핑

| 카테고리 | 트랜스포머 모델 | 라이브러리 |
|---|---|---|
| `tabular_ml` (분류/회귀) | **TabTransformer**, **FT-Transformer**, **TabPFN** | `pytorch-tabnet`, `tab-transformer-pytorch`, `tabpfn` |
| `tabular_dl` | **FT-Transformer**, **TabPFN** | 동상 |
| `timeseries` | **Informer**, **Temporal Fusion Transformer (TFT)**, **PatchTST** | `pytorch-forecasting`, `neuralforecast` |
| `anomaly_detection` | **TranAD**, **Anomaly Transformer** | `tranad` (자체 포팅), `anomaly-transformer-pytorch` |

> v2.1 스코프 축소: `image` / `nlp` / `multimodal` 카테고리는 본 프로젝트에서 제거되었다. TRANSFORMER_REGISTRY 총 **8종** (위 4 카테고리 × 평균 2~3종).

### 7.3 모델 레지스트리 (`pipelines/registry.py`)

```python
# TRANSFORMER_REGISTRY — v2.1 스코프 축소 후 4 카테고리 × 8종
TRANSFORMER_REGISTRY = {
    "tabular_ml":        ["TabTransformer", "FTTransformer", "TabPFN"],
    "tabular_dl":        ["FTTransformer", "TabPFN"],
    "timeseries":        ["Informer", "TFT", "PatchTST"],
    "anomaly_detection": ["TranAD", "AnomalyTransformer"],
}

def select_top3_with_transformer(state) -> list[str]:
    """ModelSelectionAgent 내부에서 호출.
    트랜스포머 후보 1개 + 트리계열 1개 + 도메인 특화 1개 = 3개."""
    transformer_cands = TRANSFORMER_REGISTRY.get(state.category, [])
    tree_cands = TREE_REGISTRY.get(state.category, [])
    specialty_cands = SPECIALTY_REGISTRY.get(state.category, [])
    return [
        pick_best(transformer_cands, state),
        pick_best(tree_cands, state),
        pick_best(specialty_cands, state),
    ][:3]
```

### 7.4 사전 학습 가중치 캐시

`./models_cache/` 볼륨 마운트로 한 번만 다운로드. Hugging Face Hub 토큰은 secrets/vault 관리.

### 7.5 Fine-tuning 정책

- 데이터 < 1,000: 백본 동결, 어댑터 학습 (LoRA — `peft` 라이브러리)
- 데이터 1,000 ~ 10,000: 마지막 N 레이어만 미세조정
- 데이터 > 10,000: 전체 미세조정 (lr=2e-5 ~ 5e-5)

---

## 8. 산출물 패밀리 (5종)

### 8.1 산출물 메뉴 (G5에서 사용자가 다중 선택)

| 코드 | 산출물 | 생성기 | 추천 시점 |
|---|---|---|---|
| `OUT-01` | PPT 발표자료 (.pptx) | `PresentationGenerator` | 모든 분석 (기본) |
| `OUT-02` | 상세 PDF 리포트 (.pdf) | `PDFGenerator` | 모든 분석 (기본) |
| `OUT-03` | 발표 대본 (.txt) | `ScriptGenerator` | OUT-01 함께 추천 |
| `OUT-04` | 정적 웹 대시보드 (.html 단일 파일) | `DashboardArtifactGenerator` | 시각화 중심 분석 |
| `OUT-07` | 인사이트 정리 (.md) | `InsightMDGenerator` (Day15 — InsightAgent 결과를 마크다운으로 패키징) | 기획/전략 의도 |

> v2.1 스코프 축소: 영상·외부PPT·논문·기획안·요약·비즈니스 리포트·인포그래픽·팟캐스트 8종(OUT-05/06/08~13)은 제거되었다. G5는 위 5종만 노출한다.

### 8.2 추천 로직

`OutputTypeSelectorAgent` 가 사용자 의도(`state.user_intent`)와 메트릭(`state.eval_result`)을 기반으로:

```python
# 청중별
RECOMMEND_BY_AUDIENCE = {
    "임원":      ["OUT-01", "OUT-03"],
    "분석가":    ["OUT-02", "OUT-07", "OUT-04"],
    "일반대중":  ["OUT-04"],
    "운영":      ["OUT-04", "OUT-02"],
}

# 목표별
RECOMMEND_BY_GOAL = {
    "예측":          ["OUT-01", "OUT-02"],
    "분류":          ["OUT-01", "OUT-02"],
    "군집화":        ["OUT-04", "OUT-07"],
    "이상탐지":      ["OUT-04", "OUT-07"],
    "예측+해석":     ["OUT-02", "OUT-07"],
    "의사결정지원":  ["OUT-01"],
}
```

추천된 산출물은 G5 UI에서 ⭐ 배지로 강조하되, 사용자는 자유롭게 추가/해제할 수 있다. 청중 카테고리 "학술"·"마케팅"은 사용하지 않거나 위 5종으로 매핑한다.

### 8.3 산출물 생성 병렬화

`ReportComposerAgent` 가 사용자가 선택한 N 개의 산출물(최대 5)을 `ThreadPoolExecutor(max_workers=4)` 로 병렬 생성. 각 생성기는 독립적인 MinIO 경로에 저장.

### 8.4 산출물 별 디테일 사양

자세한 명세는 **Day15_산출물패밀리확장.md** 참조. 여기서는 핵심 사양만 요약.

**OUT-01 PresentationGenerator**
- `python-pptx` 기반 10~18 슬라이드 (표지·요약·EDA·모델·평가·해석·결론·부록)
- 카테고리별 색상 테마: tabular_ml 파랑 / tabular_dl 청록 / timeseries 초록 / anomaly_detection 빨강

**OUT-02 PDFGenerator**
- `reportlab` 또는 Markdown→PDF (wkhtmltopdf) 기반 상세 보고서
- 메트릭 표·SHAP 차트·학습 곡선·인사이트 텍스트 포함

**OUT-03 ScriptGenerator**
- OUT-01 슬라이드별 1~2문단 한국어 발표 대본 (.txt)
- 분량: 슬라이드당 90~150자, 전체 5~8분 분량

**OUT-04 DashboardArtifactGenerator**
- 단일 HTML 파일에 Chart.js + 인라인 데이터 + EDA 차트 base64 인라인 + 모델 비교 인터랙티브 위젯
- 오프라인 동작 (CDN은 가능, 인터넷 없어도 핵심 동작)
- 약 500KB ~ 2MB

**OUT-07 InsightMDGenerator**
- InsightAgent 결과를 한국어 마크다운으로 패키징
- 섹션: 핵심 발견 / 데이터 한계 / 비즈니스 시사점 / 권장 후속 액션

---

## 8.5 모델 명명 규칙 표준 (트랜스포머 레지스트리)

§7.2 본문의 표시명과 §7.3 코드의 레지스트리 키 명명이 달라 혼동될 수 있어 다음을 **단일 권위** 로 선언한다.

| 카테고리 | 권위 키 (코드) | 라이브러리 로딩 시 표시명 (사람용) |
|---|---|---|
| tabular_ml / tabular_dl | `TabTransformer` | TabTransformer |
| tabular_ml / tabular_dl | `FTTransformer` | FT-Transformer |
| tabular_ml / tabular_dl | `TabPFN` | TabPFN |
| timeseries | `Informer` | Informer |
| timeseries | `TFT` | Temporal Fusion Transformer |
| timeseries | `PatchTST` | PatchTST |
| anomaly_detection | `TranAD` | TranAD |
| anomaly_detection | `AnomalyTransformer` | Anomaly Transformer |

코드(레지스트리 키, 함수 인자, MLflow 태그)는 **반드시 권위 키** 를 쓴다. 사용자 노출 텍스트(G3/G4 UI, 산출물)에서는 사람용 표시명을 쓴다. 총 **8종** (v2.1 스코프 축소 후 image/NLP 6종 제거).

---

## 9. 웹 대시보드 — 에이전트 현황판

### 9.1 핵심 요구

> **"한 페이지에서 우리 시스템의 모든 에이전트가 지금 무엇을 하고 있는지 보여야 한다."**

### 9.2 페이지 구성 (Streamlit `frontend/pages/01_시스템현황판.py`)

```
┌─────────────────────────────────────────────────────────────────┐
│  ADA v2 — System Status Board                    [🔄 새로고침]  │
├─────────────────────────────────────────────────────────────────┤
│  📊 헬스 게이지 ── 4개 인프라(Postgres/Redis/MinIO/LLM) 게이지  │
├─────────────────────────────────────────────────────────────────┤
│  🤖 에이전트 매트릭스 (27개 에이전트, 4 카테고리)                │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐       │
│  │  입력    │  의사결정│  전처리  │  모델링  │  메타    │       │
│  │  3개     │  5개     │  3개     │  5개     │  4개     │       │
│  │  ●●●     │  ●●○●●   │  ●●○     │  ●●●●○   │  ●●○○    │       │
│  └──────────┴──────────┴──────────┴──────────┴──────────┘       │
│                                                                  │
│  각 ●는 클릭하면 — 에이전트 상세 패널 (역할/현재 잡/성공률/    │
│  최근 24h 호출 수/평균 지속시간/사용 LLM 모델/캐퍼빌리티)     │
├─────────────────────────────────────────────────────────────────┤
│  🏃 실행 중인 작업                                              │
│  Job-7a1b... │ tabular_ml │ G3 대기중      │ 사용자: 김** │ 진행률 60% │
│  Job-9d2c... │ timeseries │ training_exec  │ 사용자: 박** │ 진행률 45% │
│  ...                                                            │
├─────────────────────────────────────────────────────────────────┤
│  📈 자체학습 누적 효과                                          │
│  - success_patterns: 137건 (지난 7일 +24)                       │
│  - model_recipes: 42건 (지난 7일 +8)                            │
│  - error_kb 자체해결률: 64% (지난 30일 평균)                    │
│  - Claude CLI 호출 추이 그래프                                  │
├─────────────────────────────────────────────────────────────────┤
│  🚨 최근 24h 알람                                                │
│  - 2건: PII 노출 시도 차단                                      │
│  - 1건: Rate limit 백오프 발동                                  │
│  - 0건: 보안 침해 감지                                          │
└─────────────────────────────────────────────────────────────────┘
```

### 9.3 데이터 소스

- **에이전트 매트릭스**: `agent_registry` 테이블 + 최근 `agent_runs` (5초 폴링)
- **실행 중인 작업**: `jobs` 테이블 WHERE status='running' 또는 'awaiting_decision' + LangGraph checkpoint snapshot
- **자체학습 누적**: Layer1 KB 카운트 + `job_distillation_log`
- **알람**: `security_audit_log`

### 9.4 실시간 갱신

- **기본 방식**: 폴링 5초마다 (`st.fragment(run_every=5)`) — 항상 동작. Day18 의 구현 기준.
- **(옵션)** WebSocket push: Day19 §5 에서 `pipeline:{job_id}:*` Redis pub/sub 토픽이 이미 있으므로, 추후 `dashboard:agents` 토픽을 확장하면 push 가능. v2 스프린트에는 폴링으로 충분하므로 push 구현은 정식 백로그.

### 9.5 분석 진행 페이지 (별도)

`frontend/pages/02_분석시작.py` — 사용자 여정 ②~⑮ 단일 페이지. 각 게이트마다 카드/표/체크박스 UI가 동적으로 펼쳐진다.

---

## 10. 보안 아키텍처

### 10.1 위협 모델

| 위협 | 대응 |
|---|---|
| API 무단 접근 | JWT + RBAC + IP allowlist (Day17) |
| 시크릿 노출 | HashiCorp Vault (Dev 모드), .env는 dev only |
| PII 유출 | `SecurityGuardAgent` 가 모든 LLM 입출력 사전 마스킹 |
| 프롬프트 인젝션 | 사용자 입력 sanitize + `meta_prompt_defense.py` 가드 + system 프롬프트 격리 |
| 모델 가중치 유출 | MinIO 버킷 정책 (서버사이드 암호화, 프리사인드 URL 단기 만료) |
| 컨테이너 탈출 | sidecar read-only, 비루트 사용자, seccomp 프로필 |
| SQL 인젝션 | SQLAlchemy ORM 사용 + 파라미터 바인딩 강제 |
| XSS (Streamlit) | `st.markdown(unsafe_allow_html=False)` 기본, 사용자 텍스트 HTML escape |
| DoS / 비용 폭주 | Redis 토큰 버킷 rate limit + Anthropic API 일일 한도 + 학습 잡 메모리/시간 상한 |
| 감사 추적 부재 | `security_audit_log` 전체 보안 이벤트 기록 |

### 10.2 인증·인가 (Day17 상세)

- **인증**: 이메일/패스워드 + JWT (HS256, 24h 만료, refresh 30d)
- **인가**: RBAC 4역할 — `admin`, `analyst`, `viewer`, `service`
  - `admin` 만 `agent_registry` 수정, 룰 관리, 사용자 관리
  - `analyst` 분석 실행·산출물 생성
  - `viewer` 결과 조회만
  - `service` 내부 워커 통신 (API key 별도)
- **권한 매트릭스**:

| 엔드포인트 | admin | analyst | viewer | service |
|---|---|---|---|---|
| POST /upload | ✓ | ✓ | ✗ | ✗ |
| POST /pipeline/start | ✓ | ✓ | ✗ | ✗ |
| POST /decision/{job_id} | ✓ | ✓ (본인 잡만) | ✗ | ✗ |
| GET /results/{job_id} | ✓ | ✓ (본인 잡만) | ✓ (공유된 잡) | ✗ |
| GET /dashboard/agents | ✓ | ✓ | ✓ | ✓ |
| POST /admin/rules | ✓ | ✗ | ✗ | ✗ |
| WS /pipeline/ws/{job_id} | ✓ | ✓ (본인 잡만) | ✗ | ✗ |

### 10.3 PII 레닥션 파이프라인

```
사용자 업로드 → DataProfiler 진입 전 → SecurityGuard.scan(df)
                                         ↓
                                  PII 패턴 (이메일, 전화, 주민번호,
                                          신용카드, 주소) 정규식 + NER
                                         ↓
                              매칭 컬럼 → 사용자에게 "이 컬럼은 PII로 보입니다.
                                          마스킹할까요? 제외할까요? 그대로 두시겠습니까?"
                                          (G0과 함께 추가 미니 게이트)
                                         ↓
                                  사용자 선택 적용 후 파이프라인 진입
```

마스킹은 `Faker` 기반 결정론적 가명화 (동일 원본 → 동일 가명, salt 고정).

### 10.4 프롬프트 인젝션 방어

```python
# security/prompt_defense.py
INJECTION_PATTERNS = [
    r"ignore\s+(previous|above)\s+instruction",
    r"system\s*[:>]",
    r"<\|system\|>",
    r"\\n\\nHuman:",
    r"jailbreak",
    r"이전\s*명령\s*무시",
]

def sanitize_user_input(text: str, max_len: int = 2000) -> str:
    if len(text) > max_len:
        text = text[:max_len]
    for pat in INJECTION_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            log_audit("prompt_injection_attempt", text[:200])
            text = re.sub(pat, "[BLOCKED]", text, flags=re.IGNORECASE)
    # 추가: HTML 태그 escape, 제어문자 제거
    text = html.escape(text)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    return text

def wrap_in_user_block(user_input: str) -> str:
    """사용자 입력을 명확한 구분자로 감싸 LLM이 시스템 지시로 오인하지 않도록."""
    return f"<<<USER_INPUT_BEGIN>>>\n{user_input}\n<<<USER_INPUT_END>>>"
```

### 10.5 데이터 암호화

- **전송 중**: Docker 내부 ada-net은 신뢰 영역 / 외부 노출 endpoint(api, frontend)는 nginx 리버스 프록시 + TLS (Day17)
- **저장 시**:
  - PostgreSQL: `pg_crypto` 로 PII 컬럼 (`users.email`, `audit_log.subject_email`) 컬럼 암호화
  - MinIO: SSE-S3 서버사이드 암호화 (`X-Amz-Server-Side-Encryption: AES256`)
  - `.env`: dev only, prod는 Vault KV v2

### 10.6 감사 로그 (`security_audit_log`)

```sql
CREATE TABLE security_audit_log (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(64) NOT NULL,   -- 'login', 'job_start', 'pii_redact', 'prompt_injection_attempt', 'rule_change', ...
    actor_user_id   UUID,
    actor_role      VARCHAR(32),
    resource_type   VARCHAR(64),
    resource_id     VARCHAR(128),
    ip_address      INET,
    user_agent      TEXT,
    severity        VARCHAR(16) DEFAULT 'info',   -- info | warn | error | critical
    details         JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_audit_event ON security_audit_log(event_type, created_at DESC);
CREATE INDEX idx_audit_actor ON security_audit_log(actor_user_id, created_at DESC);
```

대시보드 §9.2의 알람 패널은 `severity in ('warn','error','critical')` 최근 24h 를 집계.

### 10.7 비밀 키 관리 (Vault)

- 개발: HashiCorp Vault `-dev` 모드, root token 로컬 only
- 프로덕션: AWS Secrets Manager 또는 Vault HA
- 시크릿 회전: `ANTHROPIC_API_KEY` 30일, `POSTGRES_PASSWORD` 90일 자동 회전 (Day17 cron)

### 10.8 보안 단위 테스트 (Day20)

- 프롬프트 인젝션 페이로드 50종으로 sanitize 함수 호출 → 모두 [BLOCKED] 처리되는지 확인
- 권한 없는 사용자가 보호 엔드포인트 호출 → 401/403 반환 확인
- PII 패턴 포함 데이터 업로드 → 미니 게이트 발동 확인
- 컨테이너에서 root 권한 명령 실행 시도 → 거부 확인

---

## 11. DB 스키마 v2 마이그레이션

### 11.1 신규/변경 테이블 목록

| 테이블 | v1 | v2 변화 |
|---|---|---|
| users | 존재 | ✓ 컬럼 추가: `role`, `password_hash`, `last_login_at`, `is_active`, `mfa_secret` (nullable) |
| uploads | 존재 | ✓ 컬럼 추가: `original_mime`, `pii_scan_status`, `pii_columns` (JSONB) |
| jobs | 존재 | ✓ 컬럼 추가: `status` enum 확장 (`awaiting_decision_g1`..`g5`), `current_gate`, `auto_resolved` |
| agent_runs | 존재 | ✓ 컬럼 추가: `gate` (null이면 일반 에이전트), `was_re_loop` (bool) |
| 🆕 `agent_registry` | — | 신규 (§4.2) |
| 🆕 `interactive_sessions` | — | 신규 — HITL 게이트 응답 이력 |
| 🆕 `decisions` | — | 신규 — 각 게이트별 사용자 선택 + 시스템 추천 + 채택 안 |
| 🆕 `self_learning_kb` | — | **통합 KB 단일 테이블**. `kb_type ∈ {'success_pattern','recipe','eda_template','hpo_warm_start','failure_lesson'}` 컬럼으로 5개 유형을 한 테이블에 보관. `embedding VECTOR(768)` 포함. v1 의 `success_patterns` 는 이 테이블의 `kb_type='success_pattern'` 행으로 마이그레이션 |
| 🆕 `dataset_embeddings` | — | 신규 — pgvector |
| 🆕 `intent_embeddings` | — | 신규 — pgvector |
| 🆕 `lesson_embeddings` | — | 신규 — pgvector |
| 🆕 `error_kb` | — | 신규 (§6.4) |
| 🆕 `pending_patches` | — | 신규 — AutoErrorHandler가 생성한 미적용 코드 패치 인간 검토 큐 |
| 🆕 `security_audit_log` | — | 신규 (§10.6) |
| 🆕 `outputs` | — | 신규 — 생성된 산출물 인벤토리 |
| 🆕 `job_distillation_log` | — | 신규 — SelfLearningAgent.distill 실행 이력 |
| 🆕 `output_recipes` | — | 신규 — 사용자 의도 ↔ 추천 산출물 매핑 누적 학습 |
| 🆕 `gate_decision_metrics` | — | 신규 (VIEW) — KP11 측정 집계 |
| 🆕 `langgraph_checkpoints` | — | LangGraph PostgresSaver가 자동 생성 |
| rules | 존재 | ✓ 컬럼 추가: `pgvector_embedding`, `version`, `superseded_by` |
| failure_logs | 존재 | ✓ 컬럼 추가: `auto_handled_by_kb` (bool), `error_kb_id` (FK) |
| success_patterns | 존재 | v2에서 `self_learning_kb` (kb_type='success_pattern') 로 **데이터 이관** 후 v1 테이블은 read-only 호환을 위해 90일간 유지하다 폐기. 마이그레이션 스크립트 `migrations/008_migrate_success_patterns.sql` |

### 11.2 마이그레이션 파일

- `migrations/002_v2_schema.sql` — 모든 신규 테이블 + ALTER 문
- `migrations/003_pgvector_setup.sql` — `CREATE EXTENSION vector` + 임베딩 컬럼 + IVFFlat 인덱스
- `migrations/004_security_baseline.sql` — RLS(Row Level Security) 정책 + 컬럼 암호화 (pg_crypto)
- `migrations/005_seed_agent_registry.sql` — 27개 에이전트 메타데이터 시드 (§4.1 합계표 기준)

### 11.3 pgvector 인덱스 예시

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE dataset_embeddings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id      UUID REFERENCES jobs(id) ON DELETE CASCADE,
    category    VARCHAR(64),
    embedding   VECTOR(768) NOT NULL,
    summary     TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_dataset_emb_ivfflat
    ON dataset_embeddings
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
```

---

## 12. 21일 스프린트 일정 + 의존성

### 12.1 한 페이지 일정 다이어그램

```
주1 Foundations + Interactive Architecture
─────────────────────────────────────────────────────────────
Day01  Docker v2 (+ claude-cli-sidecar, vault) + Security baseline
Day02  DB v2 마이그레이션 (pgvector, interactive_sessions, error_kb, audit_log)
Day03  공통 모듈 v2 (SecurityGuard, BaseGateAgent, SelfLearningClient, ErrorHandler base)
Day04  LangGraph v2 (PostgresSaver, interrupt 기반 5 HITL 게이트) + AgentRegistry
Day05  데이터 처리 에이전트 v2 (xlsx/json/pdf/txt/html 핸들러 추가 — 정형/시계열 8종)
Day06  IntentElicitor + AnalysisProposer + Supervisor v2 + G0/G1 게이트
Day07  EDA + MethodologyProposer + G2 게이트

주2 Modeling + Self-Learning
─────────────────────────────────────────────────────────────
Day08  Tabular ML + ModelSelection v2 (트랜스포머 우선 레지스트리)
Day09  Tuner + TrainingExecutor + TrainingMonitor + Metrics (Top-3 강제)
Day10  PreprocessingStrategist + FeatureEngineer + G3 (PreprocessingChoice 미니 게이트)
Day11  ModelStrategyProposer + ModelComparisonReporter + G4 게이트
Day12  Transformer-first 파이프라인 (TabTransformer/FTTransformer/Informer/TFT/PatchTST/TranAD/AnomalyTransformer) + LoRA
Day13  Eval + Explainability + Insight + 재루프 검증
Day14  SelfLearningAgent (3-Stack) + KnowledgeDistillationPipeline + RAG 인용

주3 Outputs, Errors, Security, Dashboard, Test
─────────────────────────────────────────────────────────────
Day15  OutputTypeSelector + 5종 산출물 패밀리 (병렬 생성) + G5 게이트
Day16  AutoErrorHandlerAgent + Claude CLI 사이드카 브리지 + Error KB 학습 사이클
Day17  Security 풀스택 (JWT/RBAC/PII/프롬프트 인젝션/암호화/Vault/감사로그)
Day18  웹 대시보드 — 에이전트 현황판 + HITL 게이트 UI + 산출물 다운로드 페이지
Day19  FastAPI 완성 (12+5+@ 엔드포인트) + Streamlit UX 마무리 + WebSocket
Day20  통합 테스트 (5게이트 E2E + 자체학습 효과 + 자동오류해결 + 보안 침투)
Day21  인수 테스트 + KPI 측정 + 데모 매트릭스 4×5 (4 카테고리 × 5 산출물) + 풀 문서화
```

### 12.2 의존성 핵심 경로

```
Day01 ─┬─→ Day02 ─┬─→ Day03 ─→ Day04 ─→ Day05 ─→ Day06 ─→ Day07
       │          │                                          │
       └─→ Day17(보안 기초는 Day01 의존)                     │
                                                              │
Day08 ←──────────────────────────────────────────────────────┘
   ↓
Day09 ─→ Day10 ─→ Day11 ─→ Day12 ─→ Day13 ─→ Day14
                                                ↓
                                         Day15 ─→ Day16
                                                   ↓
                                         Day18 ←─ Day17 (보안 풀스택)
                                            ↓
                                         Day19 ─→ Day20 ─→ Day21
```

### 12.3 일별 산출물 게이트(완료 기준의 단일 척도)

각 Day 파일의 "완료 기준 (Done Criteria)"를 그대로 사용. 단, v2 게이트가 추가된 날은 추가 항목으로 명시.

---

## 13. KPI v2 + 인수 기준

| KPI | v1 기준 | v2 기준 | 측정 방법 |
|---|---|---|---|
| KP1 E2E 성공률 | ≥ 80% | ≥ 85% | `SELECT count(*) FILTER (status='completed')` |
| KP2 응답 속도 | Titanic E2E ≤ 90s | ≥ 게이트 응답 시간 제외 ≤ 120s | 타이머 |
| KP3 자동 재루프 성공률 | ≥ 70% | ≥ 75% | retry>0 AND status='completed' |
| KP4 카테고리 커버 | 6/6 | **4/4** (tabular_ml, tabular_dl, timeseries, anomaly_detection) | 라벨링 |
| KP5 API p95 | < 500ms | < 400ms (대시보드 폴링 제외) | locust |
| KP6 AGENTS.md 자동 룰 | ≥ 10 | ≥ 15 | grep |
| 🆕 KP7 자체학습 누적 효과 | — | 2회차 메트릭 +5%↑, Optuna trial -30% | 비교 측정 |
| 🆕 KP8 자체 오류 해결률 | — | ≥ 60% (스프린트 종료 시점) | error_kb hit_then_success / total |
| 🆕 KP9 트랜스포머 채택률 | — | G4 선택지 중 트랜스포머 비율 **≥ 25%** | decisions 테이블 |
| 🆕 KP10 보안 침해 0건 | — | 침투 테스트 50종 0건 통과 | 침투 시나리오 |
| 🆕 KP11 게이트 응답 만족도 | — | 사용자 1순위 안 채택률 ≥ 60% (G1 기준) | decisions.adopted_proposal_rank |

---

## 14. 룰 코드 체계 v2

| 범위 | 카테고리 |
|---|---|
| R-001 ~ R-099 | 핵심 아키텍처 (BaseAgent, state immutability, 등) |
| R-101 ~ R-199 | 데이터 |
| R-201 ~ R-299 | 모델 |
| R-301 ~ R-399 | 학습 |
| R-401 ~ R-499 | 인터랙티브 게이트 (🆕 v2) |
| R-501 ~ R-599 | 자체학습 / KB (🆕 v2) |
| R-601 ~ R-699 | 오류 처리 / Claude CLI (🆕 v2) |
| R-701 ~ R-799 | 보안 (🆕 v2) |
| R-801 ~ R-899 | 산출물 (🆕 v2 확장) |
| R-901 ~ R-999 | Harness / 테스트 |
| R-A001 ~      | 자동 누적 룰 (HarnessAuditor + Claude CLI) |

### 14.1 v2 신설 핵심 룰 (요약)

- **R-401**: 모든 사용자 입력은 `sanitize_user_input()` 통과 후에만 LLM 프롬프트에 삽입
- **R-402**: 게이트 응답 24h 미수신 시 자동 최적안 선택 + interactive_sessions에 `auto_resolved=true` 기록
- **R-403**: G4에서 트랜스포머 후보가 최소 1개 포함되지 않으면 ModelSelection은 재시도 (TRANSFORMER_REGISTRY 비어있는 경우 제외)
- **R-501**: 모든 잡 종료(success/failure) 직후 `SelfLearningAgent.distill(job_id)` 가 자동 호출
- **R-502**: PII가 마스킹되지 않은 데이터는 임베딩에 포함 금지
- **R-601**: AutoErrorHandler가 적용한 패치는 단위 테스트 통과 + confidence ≥ 0.9 일 때만 자동 머지
- **R-602**: claude-cli-sidecar 는 read-only 마운트 + `--allowed-tools` 제한 필수
- **R-701**: PII 컬럼 식별 시 G0 미니 게이트 우선 발동
- **R-702**: 모든 보안 이벤트는 `security_audit_log` INSERT
- **R-801**: G5에서 사용자가 선택한 산출물만 생성 (자동 전부 생성 금지)

---

## 15. 본 문서와 Day01~Day21 파일의 관계

- **Day01~Day14**: v1 파일 유지 + 각 파일 끝에 "## 🆕 v2 확장 작업" 섹션 추가
- **Day15~Day21**: v2 신규 전용 파일
- 모든 신규 명세의 권위 있는 출처는 본 마스터 문서 §3~§11

---

## 부록 A. 데이터 흐름 mermaid

```mermaid
flowchart TB
    user[👤 사용자] -->|업로드+의도| api[FastAPI]
    api --> minio[(MinIO)]
    api --> pg[(Postgres)]
    api --> celery[Celery worker]
    celery --> graph[LangGraph v2]
    graph -->|G1 interrupt| api
    api -.->|결정 수집| user
    user -.->|선택| api
    api -->|resume| graph
    graph --> mlflow[MLflow]
    graph --> minio
    graph -->|완료| api
    api --> user
    
    graph -.->|에러| autoerr[AutoErrorHandler]
    autoerr --> cli[claude-cli-sidecar]
    autoerr --> errkb[(error_kb)]
    
    graph -.->|종료 후| selflearn[SelfLearningAgent]
    selflearn --> kb1[(Postgres KB)]
    selflearn --> kb2[(MinIO artifacts)]
    selflearn --> kb3[(pgvector)]
    
    dashboard[🖥️ 현황판] -.->|폴링| pg
    dashboard -.->|폴링| registry[(agent_registry)]
```

## 부록 B. 변경 이력

| 버전 | 날짜 | 변경 | 작성자 |
|---|---|---|---|
| v1.0 | 2026-05-05 | 14일 스프린트 초안 | 팀 |
| v2.0 | 2026-05-15 | 5 HITL 게이트, 3-stack 자체학습, 자동 오류 처리, 보안 풀스택, 산출물 13종, 21일 확장 | 팀 |
| v2.1 | 2026-05-18 | 스코프 축소 — 분석 카테고리 6→4 (image/NLP 제거), 산출물 13→5 (OUT-05/06/08~13 제거), TRANSFORMER_REGISTRY 14→8종, MLflow 실험 6→4, KP4 4/4 · KP9 ≥25% 조정, Python 3.10 고정 | 팀 |
| v2.2 | 2026-05-19 | **감사 보고서 반영** — Day-A(백업/DR)·Day-B(자가학습 폐쇄)·Day-C(보안 보강) 신설, 트랜스포머 강제 정책 완화, KP2 트랙 분리, KP12·KP13 신설, Vault Dev 모드 폐지 일정, Alembic·pybreaker·mTLS·SBOM·indirect injection 가드 명문화 | 검토팀 |
| v2.3 | 2026-05-19 | **도구 카탈로그 통합** — Notion 18종 도구 도입. Day-D(즉시 4종)·Day-E(단기 4종) 신설, 중기 5종·장기 5종은 v3_backlog.md. R-1001~1008 신규 룰, R-1101~1105 백로그 룰. | 검토팀 |
| v2.4 | 2026-05-19 | **신설 Day 흡수** — Day-A/B/C/D/E 5개 신설 작업지시서를 기존 Day 안으로 통합·삭제. Day-A→Day17, Day-B→Day19, Day-C→Day17, Day-D/E는 도구별 4분산. 권위 위치 갱신, 스프린트 21일 유지. | 검토팀 |

---

## 부록 C. v2.2 감사 보고서 반영 요약 (2026-05-19)

> 출처: `ADA_v2_감사보고서.docx` — Day00~Day21 + 보조 문서 4종에 대한 프로덕션급 풀 감사.
> 본 부록은 감사에서 발견된 결함을 v2.1 본문에 ‘덮어쓰기’ 하지 않고 **차분(diff)** 으로 명시한다.
> Day별 구체 패치는 각 Day 파일의 “🆕 v2.2 보강” 섹션을 참조.

### C.1 신설 Day 3종 → 통합 완료 (v2.4)

신설 Day-A/B/C 파일은 v2.4 부터 본 마스터에서 명시한 기존 Day 안으로 흡수되었다.

| 원래 Day | 제목 | **통합 위치 (v2.4)** | 통합 섹션 헤더 |
|---|---|---|---|
| Day-A | 백업·DR·복구 인프라 | **Day17 보안풀스택** | 📦 통합본 (v2.4) — 원래 Day-A |
| Day-B | 자가학습 사이클 폐쇄 + Stage 1 | **Day19 API + SelfLearning** | 📦 통합본 (v2.4) — 원래 Day-B |
| Day-C | 보안 보강 | **Day17 보안풀스택** | 📦 통합본 (v2.4) — 원래 Day-C |

통합 후 스프린트는 21일 유지. 분량 증가는 Day17(보안+백업+DR 묶음)·Day19(자가학습 폐쇄)에 흡수.

### C.2 정책 변경

- **R-403 완화** — “트랜스포머 1개 강제 포함”은 *데이터 ≥ N 행 + GPU 가용* 시에만 적용. 그 외에는 “후보 노출 권장”. 무한 재시도 가드 (`max_retries=3`).
- **R-501 보강** — 모든 게이트 제안 단계는 `SelfLearningClient.fetch_recipes()` 호출이 단위 테스트로 강제됨.
- **R-503 신설** — 잡 종료 시 `record_outcome(kb_ids, success, metric_delta)` 호출 의무.
- **R-504 신설** — KB fail_rate ≥ 0.7 + used_count ≥ 5 → 자동 retraction.
- **R-505 신설** — KB confidence 시간 경과 decay (30일 미사용 시 ×0.95, 0.3 미만 비활성화).
- **R-601 보강** — Claude CLI subprocess → Anthropic SDK 비동기 호출. `pybreaker(5 fail / 30min OPEN)` + Redis 토큰 버킷 의무.
- **R-602 보강** — sidecar 폐지 또는 read-only 컨테이너에서 SDK Direct mode 만 허용.
- **R-703~709 신설** — mTLS, MLflow 인증, MFA 의무화, cosign 서명, JWT RS256, indirect injection 차단, pybreaker 의무 (Day-C 참조).
- **R-901~903 신설** — backup_catalog 등록, 모델 가중치 SHA256 검증, Vault Dev 모드 폐지 (Day-A 참조).

### C.3 KPI 재조정

| KPI | v2.1 | v2.2 |
|---|---|---|
| KP2 응답속도 | ≤ 120s (단일) | ≤ 90s (트리만) / ≤ 180s (트랜스포머 포함) **트랙 분리** |
| KP7 자체학습 효과 | +5%·-30% (동일 데이터) | 유사 데이터셋 군집 30일 회귀 기울기 (`kpi_kp7_trend` view) |
| KP8 자체 오류해결 | ≥ 60% | ≥ 40% + 회로차단기 의무 |
| KP11 1순위 채택률 | ≥ 60% | `gate_recommendation_shadow.matched` 비율로 자동 측정 |
| **KP12** (신설) | — | 백업 RPO 준수율 ≥ 99% (월간) |
| **KP13** (신설) | — | 분기 Game Day 통과율 (4/4) |

### C.4 아키텍처 변경 요약

- **에이전트 플랫폼 4계층 분리** — L1(Runtime)/L2(인터페이스 계약)/L3(구현)/L4(오케스트레이션). 한 방향 의존 강제(import-linter).
- **이벤트 버스 도입** — Redis Streams 1차. JobCreated·GateCompleted·ModelTrained·JobCompleted·JobFailed 도메인 이벤트. SelfLearning·Audit·Drift·BackupCheck 모두 구독자로 분리.
- **백업 사이드카** — postgres-backup-sidecar, minio-mirror-agent, vault-snapshot-cron 3종 추가.
- **DR 사이트(가상 단독 서버)** — Postgres hot standby + MinIO mc mirror --watch + Vault snapshot 외부 보관.
- **데이터 sanitize 위치 확장** — 사용자 입력만이 아니라 사용자 업로드 데이터 추출 텍스트도 sanitize (indirect injection 차단).
- **Alembic 의무화** — Day02 부터 모든 스키마 변경은 Alembic revision.
- **이미지 서명·SBOM·트리비** — Day03 CI 에 syft·trivy·cosign 통합.

### C.5 미해결 항목 (v3.0 백로그)

- Contextual Bandit (LinUCB/Thompson Sampling) — 자가학습 Stage 2
- Offline RL (CQL/BCQ) — 자가학습 Stage 3
- Patroni HA Postgres
- BentoML / KServe 모델 서빙
- Reflex/NiceGUI 비동기 대시보드
- Kafka 또는 NATS JetStream 영속 메시지 버스
- Feast 피처 스토어

### C.6 본문과 본 부록의 충돌 해결

본 부록과 §1~§14 본문 사이에 충돌이 있을 경우, **본 부록(v2.2)이 우선**한다.
단, 신설 Day-A/B/C 의 명세는 각 신설 Day 파일이 ‘단일 권위’ 다.

---

## 부록 D. v2.3 도구 카탈로그 통합 (2026-05-19)

> 출처: `TOOL_CATALOG_2026.md` (Notion 페이지 기반 18종 도구).
> 본 부록은 18개 외부 도구의 ADA 통합 단계·룰·코드 위치를 단일 권위로 정의한다.

### D.1 신설 작업지시서 2종 → 도구별 분산 통합 (v2.4)

신설 Day-D/E 파일은 v2.4 부터 도구 단위로 적절한 기존 Day 안으로 분산 흡수되었다.

| 원래 § | 도구 | **통합 위치 (v2.4)** | 우선순위 |
|---|---|---|---|
| Day-D §1 | Langfuse | **Day03 공통 모듈** | 🔴 |
| Day-D §2 | LLM Guard | **Day17 보안풀스택** | 🔴 |
| Day-D §3 | PyOD v3 | **Day12 산출물·AnomalyPipeline** | 🔴 |
| Day-D §4 | python-docx | **Day15 산출물 패밀리** | 🔴 |
| Day-E §1 | Guardrails AI | **Day17 보안풀스택** | 🟡 |
| Day-E §2 | FLAML | **Day07 ModelSelection** | 🟡 |
| Day-E §3 | StatsForecast | **Day08 학습 실행** | 🟡 |
| Day-E §4 | Chart.js / Plotly | **Day15 산출물 패밀리** | 🟡 |

Day-D / Day-E 종합 테스트·완료 기준·주의사항은 Day15 끝에 통합 보존.

### D.2 v3 백로그 문서 신설

`v3_backlog.md` — 중기 5종(Ray Tune · NeuralForecast · Captum · Arize Phoenix · SUOD) + 장기 5종(Qdrant · ClearML · SWE-agent · Braintrust · Galileo) = 10개 도구 도입 명세 + 의존성 다이어그램 + ADR 권고 + 비용·라이선스 분석.

### D.3 신규 룰 (R-1001~1008, v2.3)

| 룰 | 정책 | 도구 | 권위 위치 |
|---|---|---|---|
| R-1001 | 모든 LLM 호출에 Langfuse trace 자동 부착 | Langfuse | Day-D §1.3 |
| R-1002 | 사용자 입력 sanitize = LLM Guard 우선 → ADA 정규식 폴백 | LLM Guard | Day-D §2.4 |
| R-1003 | AnomalyPipeline 알고리즘 선택은 PyOD v3 레지스트리에서 | PyOD v3 | Day-D §3.5 |
| R-1004 | OUT-02 PDF 옵션 시 Word 초안 .docx 보존 | python-docx | Day-D §4.4 |
| R-1005 | 모든 게이트 LLM 응답은 Guardrails schema 검증 통과 후 state 반영 | Guardrails AI | Day-E §1.4 |
| R-1006 | HPO warm-start KB 없을 시 FLAML cost-aware 폴백 (budget = min(120s, total*0.2)) | FLAML | Day-E §2.4 |
| R-1007 | TimeseriesPipeline Top-3 에 StatsForecast 베이스라인 1개 + 딥러닝 1개 의무 | StatsForecast | Day-E §3.4 |
| R-1008 | OUT-04 단일 HTML 은 Chart.js 우선, 인터랙티브 시 Plotly 폴백 | Chart.js / Plotly | Day-E §4.4 |

### D.4 v3 백로그 룰 (R-1101~1105, 향후)

| 룰 | 정책 | 도구 |
|---|---|---|
| R-1101 | 학습 시간 ≥ 10분 예상 시 Ray Tune 분산 모드 권고 | Ray Tune |
| R-1102 | TimeseriesPipeline 의 딥러닝 후보는 NeuralForecast 우선 단일 진입점 | NeuralForecast |
| R-1103 | PyTorch 트랜스포머 모델 해석은 Captum 우선 | Captum |
| R-1104 | pgvector 임베딩 분포 변화 > 임계 시 Phoenix 알람 + audit_log | Arize Phoenix |
| R-1105 | 데이터 ≥ 100k 행 + anomaly_detection 시 SUOD 자동 활성화 | SUOD |

### D.5 카테고리별 보강 매핑

| ADA 카테고리 | v2.3 즉시·단기 도구 | v3 백로그 도구 |
|---|---|---|
| 옵저버빌리티 | Langfuse 🔴 | Arize Phoenix 🟢 |
| 벡터 DB / RAG | — | Qdrant ⚪ |
| ML / HPO / AutoML | FLAML 🟡 | Ray Tune 🟢 · ClearML ⚪ |
| 시계열 예측 | StatsForecast 🟡 | NeuralForecast 🟢 |
| 이상탐지 | PyOD v3 🔴 | SUOD 🟢 |
| 보안 / 가드레일 | LLM Guard 🔴 · Guardrails AI 🟡 | — |
| 산출물 생성 | python-docx 🔴 · Chart.js/Plotly 🟡 | — |
| 모델 해석성 | — | Captum 🟢 |
| 자가치유·평가 | — | SWE-agent ⚪ · Braintrust ⚪ · Galileo ⚪ |

### D.6 권위 우선순위 (v2.3 갱신)

`TOOL_CATALOG_2026.md` (도구 도입 단계) > `RENEWAL_SPEC.md v2.3` (스코프) > `Day00 부록 D` (본 부록, 도구 매핑) > `Day-D` / `Day-E` / `v3_backlog.md` (도구별 명세) > 기존 Day v2.3 도구 보강 섹션 (적용 위치).

### D.7 본 부록과 본문의 충돌 해결

본 부록과 §1~§14 본문 사이에 충돌이 있을 경우, **v2.3 부록(본 부록)이 우선**한다. v2.2 부록 C(감사 보강)와 동등 수준 권위.

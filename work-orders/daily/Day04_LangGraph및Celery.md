# Day 4 — LangGraph 오케스트레이터 + Celery 연동
> 프로젝트: Adaptive AutoAI Pipeline Agent | 2주 스프린트 Day 4/14

---

## 📋 오늘의 목표

LangGraph `StateGraph`를 사용하여 17개 에이전트 노드를 등록하고 조건부 라우팅 엣지를 완성한다. Celery를 통해 파이프라인 실행 태스크를 비동기 큐에 올리고, LangSmith 트레이싱과 Redis pub/sub 진행 상황 publish를 연동한다. `graph.get_graph().nodes` 에서 17개 노드가 전부 확인되어야 하며, Celery worker가 정상 기동되어야 한다.

---

## 👤 담당자

- **A** 주도 (전체 작업)
- 코드 리뷰: B (Celery 설정), C (DB 연동 부분)

---

## ✅ 작업 목록

### 1. orchestrator/graph.py 작성 — LangGraph StateGraph

- [ ] `StateGraph(PipelineState)` 인스턴스 생성
- [ ] **17개 노드** 등록:
  1. `supervisor` — SupervisorAgent 인스턴스
  2. `data_profiler` — DataProfilerAgent 인스턴스
  3. `schema_validator` — SchemaValidatorAgent 인스턴스
  4. `preprocessing_strategist` — PreprocessingStrategistAgent 인스턴스
  5. `feature_engineer` — FeatureEngineerAgent 인스턴스
  6. `eda_agent` — EDAAgent 인스턴스
  7. `model_selection` — ModelSelectionAgent 인스턴스
  8. `hyperparameter_tuner` — HyperparameterTunerAgent 인스턴스
  9. `training_executor` — TrainingExecutorAgent 인스턴스
  10. `training_monitor` — TrainingMonitorAgent 인스턴스
  11. `metrics_aggregator` — MetricsAggregatorAgent 인스턴스
  12. `explainability` — ExplainabilityAgent 인스턴스
  13. `eval_agent` — EvalAgent 인스턴스
  14. `insight` — InsightAgent 인스턴스
  15. `report_composer` — ReportComposerAgent 인스턴스
  16. `error_recovery` — ErrorRecoveryAgent 인스턴스
  17. `END` — LangGraph 종료 노드

- [ ] `route_after_validation(state)` 조건부 라우팅 함수:
  ```python
  def route_after_validation(state: PipelineState) -> str:
      if state.validation and state.validation.get("is_valid"):
          return "preprocessing_strategist"
      return "error_recovery"
  ```

- [ ] `route_after_eval(state)` 조건부 라우팅 함수:
  ```python
  def route_after_eval(state: PipelineState) -> str:
      if state.eval_result and state.eval_result.get("passed"):
          return "insight"
      if state.retry_count < state.max_retries:
          return "training_executor"
      return "error_recovery"
  ```

- [ ] `route_after_supervisor(state)` 조건부 라우팅 함수:
  ```python
  def route_after_supervisor(state: PipelineState) -> str:
      if state.error:
          return "error_recovery"
      return state.next_agent or "data_profiler"
  ```

- [ ] `route_after_error_recovery(state)` 조건부 라우팅 함수:
  ```python
  def route_after_error_recovery(state: PipelineState) -> str:
      if state.retry_count >= state.max_retries:
          return "END"
      return state.next_agent or "supervisor"
  ```

- [ ] **엣지 연결** 전체:
  ```
  START → supervisor
  supervisor → [route_after_supervisor] → data_profiler | error_recovery
  data_profiler → schema_validator
  schema_validator → [route_after_validation] → preprocessing_strategist | error_recovery
  preprocessing_strategist → feature_engineer
  feature_engineer → eda_agent
  eda_agent → model_selection
  model_selection → hyperparameter_tuner
  hyperparameter_tuner → training_executor
  training_executor → training_monitor
  training_monitor → metrics_aggregator
  metrics_aggregator → eval_agent
  eval_agent → [route_after_eval] → insight | training_executor | error_recovery
  insight → explainability
  explainability → report_composer
  report_composer → END
  error_recovery → [route_after_error_recovery] → supervisor | END
  ```

- [ ] `graph.set_entry_point("supervisor")`
- [ ] `compiled_graph = graph.compile()` 반환
- [ ] `get_pipeline_graph()` 팩토리 함수 작성 (싱글턴 패턴)

### 2. orchestrator/runner.py 작성 — Celery 태스크

- [ ] **Celery 앱 설정**:
  ```python
  celery_app = Celery(
      "ada_pipeline",
      broker=settings.redis_url,
      backend=settings.redis_url,
  )
  celery_app.conf.update(
      task_serializer="json",
      result_serializer="json",
      accept_content=["json"],
      task_acks_late=True,
      task_reject_on_worker_lost=True,
      worker_prefetch_multiplier=1,
      task_time_limit=settings.pipeline_timeout_min * 60,
      task_soft_time_limit=settings.pipeline_timeout_min * 60 - 60,
  )
  ```

- [ ] `@celery_app.task(bind=True, name="run_pipeline", max_retries=3)` 데코레이터
- [ ] `run_pipeline_task(self, job_id: str, initial_state: dict)` 구현:
  1. `initial_state` dict → `PipelineState` 변환
  2. DB `jobs.status` = `running` 업데이트
  3. LangSmith tracer 콜백 설정 (환경변수 `LANGSMITH_API_KEY` 있을 때만)
  4. `compiled_graph.invoke(state, config={"callbacks": [tracer]})` 실행
  5. 완료 시 DB `jobs.status` = `completed` 업데이트
  6. 실패 시 DB `jobs.status` = `failed`, `error_message` 기록
  7. Redis pub/sub으로 진행 상황 publish (`ada:pipeline:{job_id}` 채널)

- [ ] `publish_progress(job_id, current_agent, progress_pct)` 헬퍼 함수:
  ```python
  def publish_progress(job_id: str, current_agent: str, progress_pct: int):
      redis_client.publish(
          f"ada:pipeline:{job_id}",
          json.dumps({"agent": current_agent, "progress": progress_pct, "ts": time.time()})
      )
  ```

- [ ] `AGENT_PROGRESS_MAP: dict[str, int]` — 에이전트별 진행률 매핑:
  ```python
  AGENT_PROGRESS_MAP = {
      "supervisor": 5,
      "data_profiler": 10,
      "schema_validator": 15,
      "preprocessing_strategist": 20,
      "feature_engineer": 30,
      "eda_agent": 35,
      "model_selection": 40,
      "hyperparameter_tuner": 50,
      "training_executor": 65,
      "training_monitor": 70,
      "metrics_aggregator": 75,
      "eval_agent": 80,
      "insight": 85,
      "explainability": 88,
      "report_composer": 95,
      "error_recovery": 50,
      "END": 100,
  }
  ```

### 3. pipelines/base.py — BasePipeline 추상 클래스

- [ ] `class BasePipeline(ABC)` 정의
- [ ] `@abstractmethod train(self, X_train, y_train, model_name: str, params: dict) -> Any` 선언
- [ ] `@abstractmethod predict(self, model: Any, X: Any) -> np.ndarray` 선언
- [ ] `@abstractmethod evaluate(self, model: Any, X_val: Any, y_val: Any, task: str) -> dict` 선언
- [ ] `mlflow_run_id: Optional[str] = None` 인스턴스 속성
- [ ] `_start_mlflow_run(self, experiment_name: str, tags: dict) -> mlflow.ActiveRun` 헬퍼:
  - `mlflow.set_tracking_uri(settings.mlflow_tracking_uri)` 설정
  - `mlflow.set_experiment(experiment_name)` 설정
  - `mlflow.start_run(tags=tags)` 반환

### 4. pipelines/factory.py — PipelineFactory

- [ ] `PIPELINE_REGISTRY: dict[str, type[BasePipeline]]` 매핑:
  ```python
  PIPELINE_REGISTRY = {
      "tabular_ml": TabularMLPipeline,
      "tabular_dl": TabularDLPipeline,
      "timeseries": TimeSeriesPipeline,
      "anomaly_detection": AnomalyPipeline,
  }
  ```
- [ ] `PipelineFactory.create(category: str) -> BasePipeline` 정적 메서드:
  - 미등록 카테고리 시 `ValueError` 발생
  - 파이프라인 클래스 인스턴스 반환

---

## 🏗️ 구현 명세

### orchestrator/graph.py 전체 구조

```python
# orchestrator/graph.py
from langgraph.graph import StateGraph, END
from shared.state import PipelineState
from agents.supervisor import SupervisorAgent
from agents.data_profiler import DataProfilerAgent
from agents.schema_validator import SchemaValidatorAgent
# ... (나머지 에이전트 임포트)

_compiled_graph = None  # 싱글턴

def route_after_validation(state: PipelineState) -> str:
    if state.validation and state.validation.get("is_valid"):
        return "preprocessing_strategist"
    return "error_recovery"


def route_after_eval(state: PipelineState) -> str:
    if state.eval_result and state.eval_result.get("passed"):
        return "insight"
    if state.retry_count < state.max_retries:
        return "training_executor"
    return "error_recovery"


def build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)

    # 노드 등록
    graph.add_node("supervisor", SupervisorAgent())
    graph.add_node("data_profiler", DataProfilerAgent())
    graph.add_node("schema_validator", SchemaValidatorAgent())
    graph.add_node("preprocessing_strategist", PreprocessingStrategistAgent())
    graph.add_node("feature_engineer", FeatureEngineerAgent())
    graph.add_node("eda_agent", EDAAgent())
    graph.add_node("model_selection", ModelSelectionAgent())
    graph.add_node("hyperparameter_tuner", HyperparameterTunerAgent())
    graph.add_node("training_executor", TrainingExecutorAgent())
    graph.add_node("training_monitor", TrainingMonitorAgent())
    graph.add_node("metrics_aggregator", MetricsAggregatorAgent())
    graph.add_node("explainability", ExplainabilityAgent())
    graph.add_node("eval_agent", EvalAgent())
    graph.add_node("insight", InsightAgent())
    graph.add_node("report_composer", ReportComposerAgent())
    graph.add_node("error_recovery", ErrorRecoveryAgent())

    # 엔트리 포인트
    graph.set_entry_point("supervisor")

    # 고정 엣지
    graph.add_edge("data_profiler", "schema_validator")
    graph.add_edge("preprocessing_strategist", "feature_engineer")
    graph.add_edge("feature_engineer", "eda_agent")
    graph.add_edge("eda_agent", "model_selection")
    graph.add_edge("model_selection", "hyperparameter_tuner")
    graph.add_edge("hyperparameter_tuner", "training_executor")
    graph.add_edge("training_executor", "training_monitor")
    graph.add_edge("training_monitor", "metrics_aggregator")
    graph.add_edge("metrics_aggregator", "eval_agent")
    graph.add_edge("insight", "explainability")
    graph.add_edge("explainability", "report_composer")
    graph.add_edge("report_composer", END)

    # 조건부 엣지
    graph.add_conditional_edges("supervisor", route_after_supervisor,
                                {"data_profiler": "data_profiler", "error_recovery": "error_recovery"})
    graph.add_conditional_edges("schema_validator", route_after_validation,
                                {"preprocessing_strategist": "preprocessing_strategist",
                                 "error_recovery": "error_recovery"})
    graph.add_conditional_edges("eval_agent", route_after_eval,
                                {"insight": "insight",
                                 "training_executor": "training_executor",
                                 "error_recovery": "error_recovery"})
    graph.add_conditional_edges("error_recovery", route_after_error_recovery,
                                {"supervisor": "supervisor", "END": END})

    return graph


def get_pipeline_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph().compile()
    return _compiled_graph
```

### orchestrator/runner.py LangSmith 연동

```python
# LangSmith 트레이싱 설정 (환경변수 있을 때만 활성화)
def _get_callbacks():
    if not settings.langsmith_api_key:
        return []
    from langchain_core.tracers import LangChainTracer
    return [LangChainTracer(
        project_name=settings.langsmith_project,
        client=Client(api_key=settings.langsmith_api_key),
    )]
```

### Redis pub/sub 채널 구조

```
채널명: ada:pipeline:{job_id}
메시지 형식:
{
    "agent": "training_executor",
    "progress": 65,
    "ts": 1716789012.345,
    "message": "XGBoost 학습 중... (trial 23/50)"
}
```

### pipelines/base.py 전체 시그니처

```python
# pipelines/base.py
from abc import ABC, abstractmethod
from typing import Any, Optional
import numpy as np
import mlflow
from shared.config import settings


class BasePipeline(ABC):
    mlflow_run_id: Optional[str] = None

    @abstractmethod
    def train(self, X_train: Any, y_train: Any,
              model_name: str, params: dict) -> Any:
        """모델 학습 후 학습된 모델 객체 반환"""
        ...

    @abstractmethod
    def predict(self, model: Any, X: Any) -> np.ndarray:
        """예측 결과 ndarray 반환"""
        ...

    @abstractmethod
    def evaluate(self, model: Any, X_val: Any,
                 y_val: Any, task: str) -> dict:
        """평가 메트릭 dict 반환
        classification: {val_accuracy, val_f1, val_precision, val_recall}
        regression: {val_rmse, val_r2, val_mae}
        """
        ...

    def _start_mlflow_run(self, experiment_name: str,
                          tags: Optional[dict] = None) -> mlflow.ActiveRun:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        mlflow.set_experiment(experiment_name)
        return mlflow.start_run(tags=tags or {})
```

---

## 📁 생성/수정 파일 목록

```
프로젝트 루트/
├── orchestrator/
│   ├── __init__.py
│   ├── graph.py                        # LangGraph StateGraph (17노드)
│   └── runner.py                       # Celery 태스크 + Redis pub/sub
├── pipelines/
│   ├── __init__.py
│   ├── base.py                         # BasePipeline 추상 클래스
│   └── factory.py                      # PipelineFactory (카테고리별 매핑)
```

---

## 🔗 의존성 & 선행 조건

- **Day 3 완료 필수**: `shared/state.py`, `agents/base.py` 작성 완료
- **Day 5 에이전트 스텁 필요**: 실제 에이전트 구현 전이므로 모든 에이전트에 `pass` 구현 스텁 작성
  - `agents/supervisor.py`, `agents/data_profiler.py` 등 모든 에이전트 스텁 생성
- langgraph 설치 확인 (`pip show langgraph`)
- celery 설치 확인 (`pip show celery`)
- redis-py 설치 확인 (`pip show redis`)
- mlflow 설치 확인 (`pip show mlflow`)
- Redis 컨테이너 healthy 상태 확인

---

## ✔️ 완료 기준 (Done Criteria)

- [ ] `python -c "from orchestrator.graph import get_pipeline_graph; g=get_pipeline_graph(); print(len(g.get_graph().nodes))"` 출력: 17 (END 포함)
- [ ] `python -c "from orchestrator.runner import celery_app; print(celery_app.conf.broker_url)"` 성공
- [ ] Celery worker 기동: `celery -A orchestrator.runner worker --loglevel=info` 정상 시작
- [ ] `celery -A orchestrator.runner inspect ping` 응답 확인
- [ ] `python -c "from pipelines.factory import PipelineFactory; print(PipelineFactory.create('tabular_ml'))"` 성공
- [ ] `python -c "from pipelines.base import BasePipeline; print(BasePipeline.__abstractmethods__)"` 3개 추상 메서드 확인
- [ ] LangGraph 그래프 시각화: `get_pipeline_graph().get_graph().draw_mermaid()` 실행 시 mermaid 다이어그램 출력

---

## ⚠️ 주의사항 & 제약

### AGENTS.md 룰 (Day 4 적용)

- **R-001**: LangGraph 노드 추가/삭제는 반드시 A 담당자 주도 + 팀 전체 합의
- **R-005**: `PipelineState` 는 각 에이전트에서 `model_copy(update={...})` 패턴으로만 수정

### 아키텍처 제약

- LangGraph `StateGraph(PipelineState)` 에서 `PipelineState`는 Pydantic v2 모델. LangGraph 0.1.x 호환 확인 필요
- 노드 순서는 `AGENT_PROGRESS_MAP` 의 progress 값 순서와 일치해야 함
- Celery `task_acks_late=True` 설정으로 워커 다운 시 태스크 재실행 보장
- `task_time_limit` = `pipeline_timeout_min * 60` (기본 1800초). 이 시간 초과 시 Celery가 태스크 강제 종료
- `worker_prefetch_multiplier=1` 로 설정하여 워커당 동시 태스크 1개 처리 보장 (ML 학습 시 메모리 관리)

### LangSmith 연동 주의사항

- `LANGSMITH_API_KEY` 없을 때 callbacks를 빈 리스트로 대체하여 오류 방지
- LangSmith 트레이싱은 optional 기능. 없어도 파이프라인 정상 동작해야 함

### Celery 큐 설정

- 파이프라인 실행 태스크는 `pipeline` 큐에 전송
- 일반 유틸리티 태스크는 `default` 큐 사용
- worker 기동 시 반드시 두 큐 모두 소비: `-Q pipeline,default`

### 에이전트 스텁 작성 규칙

- Day 5~7 에이전트 미구현 시 NotImplementedError 대신 pass 스텁 사용
- 스텁 에이전트는 `state`를 그대로 반환하고 `next_agent` 다음 노드로 설정
- Day 4 당일에 17개 에이전트 스텁 파일 모두 생성 완료 필수

---

## 🆕 v2 확장 작업 (마스터 설계서 §3 · §4 참조)

> v2 핵심 — LangGraph를 **인터럽트-가능한 5게이트 그래프**로 재설계하고 PostgresSaver로 영속화. 또한 신규 에이전트(IntentElicitor + 5 Proposer + SelfLearning dispatch + AutoError 훅 + FineTuneExecutor + PreprocessingChoice 미니게이트)를 노드로 추가하여 **총 25 노드** 그래프를 만든다 (END 포함, error_recovery 포함).

### 1. `orchestrator/graph_v2.py` — 신규 그래프

전체 노드 목록 (25개):

```
입력층:    supervisor (1) → intent_elicitor (2) → data_profiler (3) → schema_validator (4)
G1 게이트: gate_direction (5)
EDA층:    eda_agent (6)
G2 게이트: gate_methodology (7)
전처리층: preprocessing_strategist (8) → feature_engineer (9) → preprocessing_choice (10, 조건부 미니 게이트)
G3 게이트: gate_model_strategy (11)
모델층:   model_selection (12) → hyperparameter_tuner (13) → training_executor (14) →
          training_monitor (15) → metrics_aggregator (16)
G4 게이트: gate_best_model (17)
튜닝층:   fine_tune_executor (18, 트랜스포머 선택 시만 활성)
평가층:   eval_agent (19) → explainability (20) → insight (21)
G5 게이트: gate_outputs (22)
산출물층: report_composer (23, 내부 병렬 fan-out)
종료:    self_learning_dispatch (24) → END
회복:    error_recovery (25, 조건부 진입)
```
합계: 25 노드 (END는 LangGraph 내장 종료, 노드 카운트 외).

### 2. PostgresSaver 체크포인터

```python
from langgraph.checkpoint.postgres import PostgresSaver
checkpointer = PostgresSaver.from_conn_string(settings.database_url)
checkpointer.setup()  # 1회 실행 (Day02 마이그레이션 이후)

compiled = graph.compile(
    checkpointer=checkpointer,
    interrupt_after=[
        "gate_direction", "gate_methodology", "gate_model_strategy",
        "gate_best_model", "gate_outputs",
    ],
)
```

- thread_id = job_id (1 job = 1 thread)
- `compiled.get_state(config)` 로 현재 state 조회 (대시보드/사용자 응답 처리)
- `compiled.update_state(config, {user_choice_gX: ...})` 로 응답 주입
- `compiled.stream(None, config)` 로 재개

### 3. 게이트 노드 구현 패턴

```python
# orchestrator/gates.py
from agents.proposers import AnalysisProposerAgent, MethodologyProposerAgent, \
    ModelStrategyProposerAgent, ModelComparisonReporterAgent, OutputTypeSelectorAgent

def gate_direction_node(state):
    return AnalysisProposerAgent()(state)  # BaseGateAgent.__call__이 awaiting_decision='G1' 설정

def gate_methodology_node(state): return MethodologyProposerAgent()(state)
def gate_model_strategy_node(state): return ModelStrategyProposerAgent()(state)
def gate_best_model_node(state): return ModelComparisonReporterAgent()(state)
def gate_outputs_node(state): return OutputTypeSelectorAgent()(state)
```

### 4. 라우팅 함수 v2

```python
def route_after_supervisor(state):
    if state.error: return "error_recovery"
    return "intent_elicitor"  # v1과 다름 (의도 파악 우선)

def route_after_gate_methodology(state):
    # G2 사용자 선택 후 분기 — 어떤 방법론을 골랐는지에 따라
    ch = state.user_choice_g2 or {}
    method = ch.get("method", "tabular_ml")
    # state.category 도 method에 맞게 갱신
    return "preprocessing_strategist"

def route_after_gate_best_model(state):
    # G4 선택 후 트랜스포머 튜닝 단계 진입 여부
    ch = state.user_choice_g4 or {}
    if ch.get("model_uses_transformer"):
        return "fine_tune_executor"   # LoRA/Full fine-tune
    return "eval_agent"

def route_after_gate_outputs(state):
    if not state.user_choice_g5:
        # G5 미선택 시 자동 기본 (OUT-01, OUT-02)
        state = state.model_copy(update={"user_choice_g5": [{"code": "OUT-01"}, {"code": "OUT-02"}]})
    return "report_composer"

def route_after_report_composer(state):
    # 종료 직전 자체학습 디스패치
    return "self_learning_dispatch"
```

### 5. `orchestrator/runner_v2.py` — Celery 태스크 v2

```python
@celery_app.task(name="run_pipeline", queue="pipeline")
def run_pipeline_task(job_id: str, initial_state: dict):
    config = {"configurable": {"thread_id": job_id}}
    state = PipelineStateV2(**initial_state)
    try:
        for event in compiled.stream(state, config, stream_mode="updates"):
            # 진행 상황 Redis publish
            publish_progress(job_id, event)
        # interrupt 발생 시 위 for 루프 자연 종료, state는 PostgresSaver에 남음
    except Exception as e:
        celery_app.send_task("error_capture", args=[job_id, str(e)], queue="harness")
        raise

@celery_app.task(name="resume_pipeline", queue="pipeline")
def resume_pipeline_task(job_id: str):
    config = {"configurable": {"thread_id": job_id}}
    for event in compiled.stream(None, config, stream_mode="updates"):
        publish_progress(job_id, event)
```

### 6. AgentRegistry 등록 부트스트랩

- [ ] `orchestrator/registry_bootstrap.py` 작성:
  - 컨테이너 기동 시 27개 에이전트의 메타데이터를 `agent_registry` 테이블에 UPSERT (마스터 §4.1 합계표 권위)
  - `last_heartbeat` 는 BaseAgent 가 매 호출마다 NOW()로 업데이트

### 7. 진행률 매핑 v2 (25 노드 기준)

```python
AGENT_PROGRESS_MAP_V2 = {
    "supervisor": 3, "intent_elicitor": 5, "data_profiler": 8, "schema_validator": 10,
    "gate_direction": 12, "eda_agent": 18,
    "gate_methodology": 22,
    "preprocessing_strategist": 26, "feature_engineer": 32, "preprocessing_choice": 35,
    "gate_model_strategy": 38,
    "model_selection": 42, "hyperparameter_tuner": 50,
    "training_executor": 65, "training_monitor": 70, "metrics_aggregator": 75,
    "gate_best_model": 78,
    "fine_tune_executor": 84,
    "eval_agent": 88, "explainability": 90, "insight": 93,
    "gate_outputs": 95, "report_composer": 98,
    "self_learning_dispatch": 99, "END": 100,
}
```

### 8. 완료 기준 (v2 추가)

- [ ] `len(get_pipeline_graph_v2().get_graph().nodes)` == 25 (END 제외)
- [ ] PostgresSaver 테이블(`langgraph_checkpoints`) 자동 생성 확인
- [ ] 임의 잡 시작 후 G1 interrupt 직전까지 진행되고, `compiled.get_state(config).next` 에 `('gate_direction',)` 반환 확인
- [ ] `compiled.update_state(config, {'user_choice_g1': {...}})` 후 `compiled.stream(None, config)` 로 G2까지 진행
- [ ] `SELECT count(*) FROM agent_registry WHERE last_heartbeat > NOW() - INTERVAL '1 minute';` ≥ 5 (테스트 잡 실행 시)

### 9. 주의사항 (v2)

- LangGraph 0.2+ 의 interrupt API 확인. 0.1 미만이면 업그레이드
- PostgresSaver 는 async/sync 별도. Celery 워커는 sync 사용 권장
- `interrupt_after` 노드 이름이 그래프 노드명과 정확히 일치해야 함
- 게이트 노드 자체는 빠르게 실행되고 interrupt만 트리거 — LLM 호출은 게이트 노드 안에서 수행됨

---

## 🆕 v2.2 보강 (감사 보고서 2026-05-19 반영)

> 출처: `ADA_v2_감사보고서.docx`. 본 섹션이 v2.1 본문과 충돌 시 **v2.2가 우선**한다.

### 1) LangGraph 버전 고정
- `langgraph==X.Y.Z` 의 `interrupt_after` API 가 0.1↔0.2+ 사이에서 변경됨. requirements 에 정확한 버전 핀 + 회귀 테스트.

### 2) 에이전트 플러그인 시스템
- `agents/plugins/` 디렉토리 + `importlib.metadata.entry_points` 기반 자동 로딩.
- 새 에이전트 = 파일 1개 + entry_point 등록 + agent_registry seed (Alembic revision).
- LangGraph 그래프는 부팅 시 활성 에이전트 목록을 읽어 동적 빌드.

### 3) Bulkhead — 에이전트 격리
- 모델 학습 잡(training 큐)은 `ProcessPoolExecutor` 로 별도 프로세스에서 실행. 한 잡 OOM 이 워커 전체를 잡지 않도록.
- Celery 워커 메모리 한도(`worker_max_memory_per_child=2048000`).

### 4) 이벤트 버스 도입
- Redis Streams 신설: `ada.events.job_created`, `gate_completed`, `model_trained`, `job_completed`, `job_failed`.
- SelfLearning·BackupCheck·Drift·Audit 모두 직접 호출 대신 Stream consumer 로 분리.

### 5) Celery 재시도 백오프
- `autoretry_for` + `retry_backoff=True` + `retry_backoff_max=600` 명시. 단순 max_retries=3 만으로는 부족.

### 완료 기준 추가
- [ ] `langgraph.__version__` assert 단위 테스트
- [ ] entry_points 등록만으로 새 더미 에이전트 자동 인식
- [ ] 학습 잡 OOM 시뮬레이션 → 다른 잡 영향 0
- [ ] Redis Stream consumer 단위 테스트 통과

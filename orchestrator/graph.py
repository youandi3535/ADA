"""orchestrator.graph — LangGraph v2 (26 노드: 25 일반 + auto_error_handler).

Day04 v2 §1~§4 + ADR-006 Phase 1.
PostgresSaver checkpointer 로 영속화.
"""

from __future__ import annotations

import traceback
from functools import lru_cache, wraps
from typing import Any, Callable

from ada.core.state import PipelineState
from agents.auto_error_handler import AutoErrorHandlerAgent
from agents.stubs import (
    AnalysisProposerAgent,
    DataProfilerAgent,
    EDAAgent,
    ErrorRecoveryAgent,
    EvalAgent,
    ExplainabilityAgent,
    FeatureEngineerAgent,
    FineTuneExecutorAgent,
    HyperparameterTunerAgent,
    InsightAgent,
    IntentElicitorAgent,
    MethodologyProposerAgent,
    MetricsAggregatorAgent,
    ModelComparisonReporterAgent,
    ModelSelectionAgent,
    ModelStrategyProposerAgent,
    OutputTypeSelectorAgent,
    PreprocessingChoiceAgent,
    PreprocessingStrategistAgent,
    ReportComposerAgent,
    SchemaValidatorAgent,
    SelfLearningAgent,
    SupervisorAgent,
    TrainingExecutorAgent,
    TrainingMonitorAgent,
)

try:
    from langgraph.graph import END, StateGraph
except Exception:  # pragma: no cover - langgraph 미설치 환경
    StateGraph = None  # type: ignore
    END = "END"  # type: ignore


# 게이트 노드: 동일 클래스를 그대로 사용 (BaseGate 가 interrupt 직전 상태 마킹)
GATE_NODES = {
    "gate_direction": AnalysisProposerAgent,
    "gate_methodology": MethodologyProposerAgent,
    "gate_model_strategy": ModelStrategyProposerAgent,
    "gate_best_model": ModelComparisonReporterAgent,
    "gate_outputs": OutputTypeSelectorAgent,
}

INTERRUPT_AFTER = list(GATE_NODES.keys())


# ---------------------------------------------------------------------------
# ADR-006 Phase 1 — safe_node 어댑터
# ---------------------------------------------------------------------------
def _coerce_to_pipeline_state(state) -> PipelineState:
    """LangGraph resume 시 dict/AddableValuesDict 로 복원된 state 를 PipelineState 로 변환.

    aupdate_state 후 ainvoke(None) 을 호출하면 LangGraph 가 체크포인트 값을
    그대로 dict 로 넘길 수 있다. Pydantic 속성 접근(.job_id 등)이 깨지는 문제를 방지.
    """
    if isinstance(state, PipelineState):
        return state
    try:
        raw = dict(state) if hasattr(state, "items") else vars(state)
        return PipelineState.model_validate(raw)
    except Exception:
        return state  # type: ignore[return-value]


def safe_node(agent_callable: Callable) -> Callable:
    """모든 일반 노드를 감싸는 어댑터.

    노드가 raise 한 예외에서 ``_ada_state`` 를 꺼내 state 로 반환 → 그래프는
    정상 transition 으로 진행하고, route_after_* 가 ``state.error`` 보고
    auto_error_handler 로 라우팅.

    auto_error_handler 자체는 wrap 하지 않음 (자기 호출 방지).
    """

    @wraps(agent_callable)
    async def wrapped(state):
        # resume 시 dict 로 복원된 state → PipelineState 로 보장
        state = _coerce_to_pipeline_state(state)
        # 입력 state 에 이미 error 가 있으면 스킵 (cascade 방지)
        # → 그래프가 다음 conditional_edges 에서 auto_error_handler 로 라우팅
        if getattr(state, "error", None):
            return state
        try:
            return await agent_callable(state)
        except Exception as e:
            # BaseAgent 가 _ada_state 첨부했으면 그걸 사용
            attached = getattr(e, "_ada_state", None)
            if attached is not None:
                return attached
            # 그 외 (BaseAgent 밖에서 raise) 는 직접 구성
            return state.with_update(
                error=f"{type(e).__name__}: {e}"[:2000],
                error_traceback=traceback.format_exc()[:8000],
                auto_fix_attempts=state.auto_fix_attempts + 1,
                next_agent="auto_error_handler",
            )

    return wrapped


# ---------------------------------------------------------------------------
# 라우팅 함수
# ---------------------------------------------------------------------------
def _is_attempt_exhausted(state: PipelineState) -> bool:
    """ADR-006: 자동 수정 시도 한도 초과 여부."""
    return state.auto_fix_attempts >= state.max_auto_fix_attempts


def route_after_supervisor(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        # ADR-006: 자동 수정 시도 한도 내면 auto_error_handler, 초과면 error_recovery
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    return state.next_agent or "intent_elicitor"


def route_after_auto_handler(state: PipelineState) -> str:
    """auto_error_handler 가 처리 시도한 후 결정.

    - state.error == None → 해결됨 → supervisor (재시도 시작)
    - state.error 살아있음 + 한도 미달 → error_recovery (패치 큐 적재됐거나 미해결)
    - 한도 초과 → error_recovery (사용자 안내)
    """
    if state.error is None:
        return state.next_agent or "supervisor"
    return "error_recovery"


def route_after_validation(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    if state.validation and state.validation.get("is_valid"):
        return "gate_direction"  # G1 게이트 — 분석 방향 선택
    return "error_recovery"


def route_after_feature_engineer(state: PipelineState) -> str:
    """전처리 결정 신뢰도 낮으면 미니 게이트(PreprocessingChoice), 아니면 G3로."""
    state = _coerce_to_pipeline_state(state)
    if state.preprocessing_plan and any(s.get("needs_review") for s in state.preprocessing_plan):
        return "preprocessing_choice"
    return "gate_model_strategy"  # G3 게이트 — 모델 전략 선택


def route_after_metrics(state: PipelineState) -> str:
    """metrics_aggregator 완료 후 라우팅. 에러 발생 시 error 핸들러로 우회."""
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    return "gate_best_model"


def route_after_g4(state: PipelineState) -> str:
    """G4 응답에 따라 finetune 갈지 평가로 갈지."""
    state = _coerce_to_pipeline_state(state)
    g4 = state.gate_responses.get("G4", {})
    if g4.get("user_choice", {}).get("requires_finetune"):
        return "fine_tune_executor"
    return "eval_agent"


def route_after_eval(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    if state.eval_result and state.eval_result.get("passed"):
        return "explainability"
    if state.re_loop_count < state.max_re_loop:
        return "training_executor"
    return "error_recovery"


def route_after_g5(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    # ADR-006: 마지막 게이트도 에러 체크 (insight 노드까지의 cascade 잡기)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    return "report_composer"


def route_after_report_composer(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    return "self_learning_dispatch"


def route_after_self_learning(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    return "END"


def route_after_error_recovery(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    """ADR-006 — 회복 후 라우팅.

    회복 노드의 조건부 엣지에는 'supervisor' / 'END' 두 키만 매핑돼 있다.
    state.next_agent 가 임의 노드명을 담고 있어도 미등록 키로 라우팅해
    LangGraph KeyError 가 나지 않도록 화이트리스트로 클램프한다.
    """
    if state.retry_count >= state.max_retries:
        return "END"
    if state.next_agent == "END":
        return "END"
    # supervisor / 빈값 / 그 외 임의 next_agent → supervisor 로 안전 복귀
    return "supervisor"


# ---------------------------------------------------------------------------
# 그래프 빌더
# ---------------------------------------------------------------------------
def build_graph(checkpointer: Any | None = None) -> Any:
    if StateGraph is None:
        raise RuntimeError("langgraph 가 설치되지 않았습니다. pip install langgraph==0.1.5")

    g = StateGraph(PipelineState)

    # ---- 노드 등록 (26 = 25 + auto_error_handler) -----------------------
    # ADR-006 Phase 1: safe_node 로 감싸서 예외 발생 시 state.error 자동 세팅.
    # auto_error_handler 자체는 wrap 안 함 (자기 호출 방지).
    g.add_node("supervisor", safe_node(SupervisorAgent()))
    g.add_node("intent_elicitor", safe_node(IntentElicitorAgent()))
    g.add_node("data_profiler", safe_node(DataProfilerAgent()))
    g.add_node("schema_validator", safe_node(SchemaValidatorAgent()))
    g.add_node("gate_direction", safe_node(GATE_NODES["gate_direction"]()))
    g.add_node("eda_agent", safe_node(EDAAgent()))
    g.add_node("gate_methodology", safe_node(GATE_NODES["gate_methodology"]()))
    g.add_node("preprocessing_strategist", safe_node(PreprocessingStrategistAgent()))
    g.add_node("feature_engineer", safe_node(FeatureEngineerAgent()))
    g.add_node("preprocessing_choice", safe_node(PreprocessingChoiceAgent()))
    g.add_node("gate_model_strategy", safe_node(GATE_NODES["gate_model_strategy"]()))
    g.add_node("model_selection", safe_node(ModelSelectionAgent()))
    g.add_node("hyperparameter_tuner", safe_node(HyperparameterTunerAgent(n_trials=5, timeout_per_model_sec=60)))
    g.add_node("training_executor", safe_node(TrainingExecutorAgent()))
    g.add_node("training_monitor", safe_node(TrainingMonitorAgent()))
    g.add_node("metrics_aggregator", safe_node(MetricsAggregatorAgent()))
    g.add_node("gate_best_model", safe_node(GATE_NODES["gate_best_model"]()))
    g.add_node("fine_tune_executor", safe_node(FineTuneExecutorAgent()))
    g.add_node("eval_agent", safe_node(EvalAgent()))
    g.add_node("explainability", safe_node(ExplainabilityAgent()))
    g.add_node("insight", safe_node(InsightAgent()))
    g.add_node("gate_outputs", safe_node(GATE_NODES["gate_outputs"]()))
    g.add_node("report_composer", safe_node(ReportComposerAgent()))
    g.add_node("self_learning_dispatch", safe_node(SelfLearningAgent()))
    g.add_node("error_recovery", ErrorRecoveryAgent())  # 마지막 안전망 — 감싸지 않음
    g.add_node("auto_error_handler", AutoErrorHandlerAgent())  # 자기 호출 방지로 감싸지 않음
    # (SecurityGuard 데몬은 그래프 외부에서 호출)

    g.set_entry_point("supervisor")

    # ---- 고정 엣지 -----------------------------------------------------
    g.add_edge("intent_elicitor", "data_profiler")
    g.add_edge("data_profiler", "schema_validator")
    g.add_edge("preprocessing_strategist", "feature_engineer")
    g.add_edge("preprocessing_choice", "gate_model_strategy")
    g.add_edge("gate_direction", "eda_agent")
    g.add_edge("eda_agent", "gate_methodology")
    g.add_edge("gate_methodology", "preprocessing_strategist")
    g.add_edge("gate_model_strategy", "model_selection")
    g.add_edge("model_selection", "hyperparameter_tuner")
    g.add_edge("hyperparameter_tuner", "training_executor")
    g.add_edge("training_executor", "training_monitor")
    g.add_edge("training_monitor", "metrics_aggregator")
    g.add_edge("fine_tune_executor", "eval_agent")
    g.add_edge("explainability", "insight")
    g.add_edge("insight", "gate_outputs")
    # report_composer / self_learning_dispatch 도 에러 체크 (마지막 구간 구멍 차단)

    # ---- 조건부 엣지 ---------------------------------------------------
    # ADR-006 Phase 1: 모든 error-aware 라우팅에 auto_error_handler 목적지 추가.
    g.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "intent_elicitor": "intent_elicitor",
            "data_profiler": "data_profiler",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "schema_validator",
        route_after_validation,
        {
            "gate_direction": "gate_direction",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "feature_engineer",
        route_after_feature_engineer,
        {"preprocessing_choice": "preprocessing_choice", "gate_model_strategy": "gate_model_strategy"},
    )
    g.add_conditional_edges(
        "metrics_aggregator",
        route_after_metrics,
        {
            "gate_best_model": "gate_best_model",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "gate_best_model",
        route_after_g4,
        {"fine_tune_executor": "fine_tune_executor", "eval_agent": "eval_agent"},
    )
    g.add_conditional_edges(
        "eval_agent",
        route_after_eval,
        {
            "explainability": "explainability",
            "training_executor": "training_executor",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "gate_outputs",
        route_after_g5,
        {
            "report_composer": "report_composer",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    # ADR-006 Phase 1: auto_error_handler 의 다음 목적지.
    # 해결됨 (error=None) → supervisor 재시도, 미해결 → error_recovery.
    g.add_conditional_edges(
        "auto_error_handler",
        route_after_auto_handler,
        {
            "supervisor": "supervisor",
            "error_recovery": "error_recovery",
            # supervisor 가 보낼 수 있는 다른 노드들도 가능 (state.next_agent)
            "intent_elicitor": "intent_elicitor",
            "data_profiler": "data_profiler",
        },
    )
    g.add_conditional_edges(
        "report_composer",
        route_after_report_composer,
        {
            "self_learning_dispatch": "self_learning_dispatch",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "self_learning_dispatch",
        route_after_self_learning,
        {
            "END": END,
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "error_recovery",
        route_after_error_recovery,
        {"supervisor": "supervisor", "END": END},
    )

    # ---- 컴파일 (인터럽트 + 체크포인터) -------------------------------
    compile_kwargs: dict[str, Any] = {"interrupt_after": INTERRUPT_AFTER}
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    return g.compile(**compile_kwargs)


@lru_cache(maxsize=1)
def get_pipeline_graph() -> Any:
    """싱글턴 — 운영에서는 PostgresSaver 를 주입한 그래프."""
    try:
        from orchestrator.checkpoint import get_checkpointer

        return build_graph(checkpointer=get_checkpointer())
    except Exception:
        return build_graph(checkpointer=None)

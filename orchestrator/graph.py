"""orchestrator.graph — LangGraph v2 (25 노드, 5게이트 인터럽트).

Day04 v2 §1~§4. PostgresSaver checkpointer 로 영속화.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ada.core.state import PipelineState
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
# 라우팅 함수
# ---------------------------------------------------------------------------
def route_after_supervisor(state: PipelineState) -> str:
    if state.error:
        return "error_recovery"
    return state.next_agent or "intent_elicitor"


def route_after_validation(state: PipelineState) -> str:
    if state.validation and state.validation.get("is_valid"):
        return "gate_direction"  # G1 게이트 — 분석 방향 선택
    return "error_recovery"


def route_after_feature_engineer(state: PipelineState) -> str:
    """전처리 결정 신뢰도 낮으면 미니 게이트(PreprocessingChoice), 아니면 G3로."""
    if state.preprocessing_plan and any(s.get("needs_review") for s in state.preprocessing_plan):
        return "preprocessing_choice"
    return "gate_model_strategy"  # G3 게이트 — 모델 전략 선택


def route_after_metrics(state: PipelineState) -> str:
    """ModelComparisonReporter 가 G4 게이트로 진입."""
    return "gate_best_model"


def route_after_g4(state: PipelineState) -> str:
    """G4 응답에 따라 finetune 갈지 평가로 갈지."""
    g4 = state.gate_responses.get("G4", {})
    if g4.get("user_choice", {}).get("requires_finetune"):
        return "fine_tune_executor"
    return "eval_agent"


def route_after_eval(state: PipelineState) -> str:
    if state.eval_result and state.eval_result.get("passed"):
        return "explainability"
    if state.re_loop_count < state.max_re_loop:
        return "training_executor"
    return "error_recovery"


def route_after_g5(state: PipelineState) -> str:
    return "report_composer"


def route_after_error_recovery(state: PipelineState) -> str:
    if state.retry_count >= state.max_retries:
        return "END"
    return state.next_agent or "supervisor"


# ---------------------------------------------------------------------------
# 그래프 빌더
# ---------------------------------------------------------------------------
def build_graph(checkpointer: Any | None = None) -> Any:
    if StateGraph is None:
        raise RuntimeError("langgraph 가 설치되지 않았습니다. pip install langgraph==0.1.5")

    g = StateGraph(PipelineState)

    # ---- 노드 등록 (25 = 20 일반 + 5 게이트) -----------------------------
    g.add_node("supervisor", SupervisorAgent())
    g.add_node("intent_elicitor", IntentElicitorAgent())
    g.add_node("data_profiler", DataProfilerAgent())
    g.add_node("schema_validator", SchemaValidatorAgent())
    g.add_node("gate_direction", GATE_NODES["gate_direction"]())
    g.add_node("eda_agent", EDAAgent())
    g.add_node("gate_methodology", GATE_NODES["gate_methodology"]())
    g.add_node("preprocessing_strategist", PreprocessingStrategistAgent())
    g.add_node("feature_engineer", FeatureEngineerAgent())
    g.add_node("preprocessing_choice", PreprocessingChoiceAgent())
    g.add_node("gate_model_strategy", GATE_NODES["gate_model_strategy"]())
    g.add_node("model_selection", ModelSelectionAgent())
    g.add_node("hyperparameter_tuner", HyperparameterTunerAgent())
    g.add_node("training_executor", TrainingExecutorAgent())
    g.add_node("training_monitor", TrainingMonitorAgent())
    g.add_node("metrics_aggregator", MetricsAggregatorAgent())
    g.add_node("gate_best_model", GATE_NODES["gate_best_model"]())
    g.add_node("fine_tune_executor", FineTuneExecutorAgent())
    g.add_node("eval_agent", EvalAgent())
    g.add_node("explainability", ExplainabilityAgent())
    g.add_node("insight", InsightAgent())
    g.add_node("gate_outputs", GATE_NODES["gate_outputs"]())
    g.add_node("report_composer", ReportComposerAgent())
    g.add_node("self_learning_dispatch", SelfLearningAgent())
    g.add_node("error_recovery", ErrorRecoveryAgent())
    # (SecurityGuard / AutoErrorHandler 는 데몬 — 그래프 외부에서 호출)

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
    g.add_edge("report_composer", "self_learning_dispatch")
    g.add_edge("self_learning_dispatch", END)

    # ---- 조건부 엣지 ---------------------------------------------------
    g.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {"intent_elicitor": "intent_elicitor", "data_profiler": "data_profiler", "error_recovery": "error_recovery"},
    )
    g.add_conditional_edges(
        "schema_validator",
        route_after_validation,
        {"gate_direction": "gate_direction", "error_recovery": "error_recovery"},
    )
    g.add_conditional_edges(
        "feature_engineer",
        route_after_feature_engineer,
        {"preprocessing_choice": "preprocessing_choice", "gate_model_strategy": "gate_model_strategy"},
    )
    g.add_conditional_edges(
        "metrics_aggregator",
        route_after_metrics,
        {"gate_best_model": "gate_best_model"},
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
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "gate_outputs",
        route_after_g5,
        {"report_composer": "report_composer"},
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

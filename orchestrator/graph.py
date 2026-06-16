"""orchestrator.graph — LangGraph v2 (27 노드: 26 일반 + auto_error_handler).

Day04 v2 §1~§4 + ADR-006 Phase 1.
PostgresSaver checkpointer 로 영속화.
HJ 2026-06-08: report_architect 노드 추가 (insight → report_architect → gate_outputs).
"""

from __future__ import annotations

import os
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
    ReportArchitectAgent,
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


def _agent_session_cm(agent: Any):
    """HJ 2026-06-16 — 세션 주입 대상이면 AsyncSessionLocal() CM 반환, 아니면 None.

    제어 스위치(2단):
      - 마스터 킬스위치 env ``ADA_AGENT_DB_SESSION=off`` → 전면 비활성(즉시 복귀, 워커 재시작).
      - ``agent.uses_db_session=True`` 노드만 세션을 받는다(data_profiler·self_learning 등 — additive).
      - ``agent.rag_reader=True``(KB 를 읽어 분석 결과를 바꾸는 노드)는 추가로 env ``ADA_RAG_ENRICH=on``
        일 때만 세션을 받는다(기본 off → 분석 동작 무변경, 사용자 A/B 검증 후 활성).
    """
    if os.environ.get("ADA_AGENT_DB_SESSION", "on").strip().lower() == "off":
        return None
    if not getattr(agent, "uses_db_session", False):
        return None
    if getattr(agent, "rag_reader", False) and os.environ.get("ADA_RAG_ENRICH", "off").strip().lower() not in (
        "on",
        "1",
        "true",
    ):
        return None
    try:
        from ada.db.session import AsyncSessionLocal  # noqa: WPS433

        return AsyncSessionLocal()
    except Exception:  # noqa: BLE001
        return None


def safe_node(agent_callable: Callable) -> Callable:
    """모든 일반 노드를 감싸는 어댑터.

    노드가 raise 한 예외에서 ``_ada_state`` 를 꺼내 state 로 반환 → 그래프는
    정상 transition 으로 진행하고, route_after_* 가 ``state.error`` 보고
    auto_error_handler 로 라우팅.

    HJ 2026-06-16 — uses_db_session 노드에는 전용 DB 세션을 주입한다(성공 시 commit, 예외 시
    rollback, 항상 self.session 복원). 세션 컨텍스트 자체 실패(연결 등)는 무세션으로 폴백해
    분석이 끊기지 않게 한다. commit 실패도 best-effort(분석 성공 > DB 기록).

    auto_error_handler 자체는 wrap 하지 않음 (자기 호출 방지).
    """

    @wraps(agent_callable)
    async def wrapped(state):
        state = _coerce_to_pipeline_state(state)
        if getattr(state, "error", None):
            return state

        def _handle_exc(e):
            attached = getattr(e, "_ada_state", None)
            if attached is not None:
                return attached
            return state.with_update(
                error=f"{type(e).__name__}: {e}"[:2000],
                error_traceback=traceback.format_exc()[:8000],
                auto_fix_attempts=state.auto_fix_attempts + 1,
                next_agent="auto_error_handler",
            )

        session_cm = _agent_session_cm(agent_callable)
        if session_cm is None:
            try:
                return await agent_callable(state)
            except Exception as e:
                return _handle_exc(e)

        # 세션 주입 경로
        try:
            async with session_cm as session:
                agent_callable.session = session
                try:
                    result = await agent_callable(state)
                    try:
                        await session.commit()
                    except Exception:  # noqa: BLE001 — 커밋 실패는 분석을 깨지 않는다(기록만 유실)
                        try:
                            await session.rollback()
                        except Exception:  # noqa: BLE001
                            pass
                    return result
                except Exception as e:
                    try:
                        await session.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                    return _handle_exc(e)
                finally:
                    agent_callable.session = None
        except Exception:
            # 세션 컨텍스트 자체 실패(연결 등) → 무세션으로 1회 실행해 분석을 이어간다.
            agent_callable.session = None
            try:
                return await agent_callable(state)
            except Exception as e2:
                return _handle_exc(e2)

    return wrapped


def safe_gate_node(agent_callable: Callable) -> Callable:
    """gate_outputs 전용 래퍼 — 상위 노드 에러가 있어도 반드시 실행.

    insight/explainability 실패로 state.error 가 세팅된 상태에서도
    G6 proposals 를 생성해 사용자에게 선택지를 제공한다.
    에러는 클리어 후 실행 (gate 자체 실패 시에는 다시 state.error 세팅).
    """

    @wraps(agent_callable)
    async def wrapped(state):
        state = _coerce_to_pipeline_state(state)
        if getattr(state, "error", None):
            state = state.with_update(error=None)
        try:
            return await agent_callable(state)
        except Exception as e:
            attached = getattr(e, "_ada_state", None)
            if attached is not None:
                return attached
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
    return state.auto_fix_attempts >= state.max_auto_fix_attempts


def route_after_supervisor(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    return state.next_agent or "intent_elicitor"


def route_after_auto_handler(state: PipelineState) -> str:
    if state.error is None:
        return state.next_agent or "supervisor"
    return "error_recovery"


def route_after_validation(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    # CS 2026-06-12 — schema_validator 는 검증 실패 시에도 category 를 강제
    # 변경하지 않고 warning 만 추가한 뒤 error=None + next_agent="gate_direction"
    # 으로 진행시킨다 (22accff). validation.is_valid 만 보면 이 soft-fail 케이스가
    # 무조건 error_recovery 로 빠져 "최대 자동 재시도 횟수 초과" 루프를 탔다.
    return state.next_agent or "error_recovery"


def route_after_feature_engineer(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    if state.preprocessing_plan and any(s.get("needs_review") for s in state.preprocessing_plan):
        return "preprocessing_choice"
    return "gate_model_strategy"


def route_after_metrics(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    # HJ 2026-06-13 — 4단계 baseline 리루프: metrics_aggregator 가 next_agent 를
    #   preprocessing_strategist 로 지정하면 전처리부터 재시작(전 단계 롤백, 화면은 유지).
    if state.next_agent == "preprocessing_strategist":
        return "preprocessing_strategist"
    return "gate_best_model"


def route_after_gate_best_model(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    g5 = state.gate_responses.get("G5", {})
    if g5.get("user_choice", {}).get("requires_finetune"):
        return "fine_tune_executor"
    return "eval_agent"


route_after_g4 = route_after_gate_best_model


def route_after_eval(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
    if state.error:
        if state.auto_fix_attempts >= state.max_auto_fix_attempts:
            return "error_recovery"
        return "auto_error_handler"
    _RELOOP_TARGETS = {"hyperparameter_tuner", "feature_engineer", "preprocessing_strategist"}
    if state.next_agent in _RELOOP_TARGETS:
        return state.next_agent
    return "explainability"


def route_after_g5(state: PipelineState) -> str:
    state = _coerce_to_pipeline_state(state)
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
    if state.retry_count >= state.max_retries:
        return "END"
    if state.next_agent == "END":
        return "END"
    return "supervisor"


# ---------------------------------------------------------------------------
# 그래프 빌더
# ---------------------------------------------------------------------------
def build_graph(checkpointer: Any | None = None) -> Any:
    if StateGraph is None:
        raise RuntimeError("langgraph 가 설치되지 않았습니다. pip install langgraph==0.1.5")

    g = StateGraph(PipelineState)

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
    # HJ 2026-06-08 — Phase 2 통합: ReportArchitect 가 state.report_plan 채움.
    # silent-safe (실패해도 state.error 안 세우고 gate_outputs 로 통과).
    g.add_node("report_architect", safe_node(ReportArchitectAgent()))
    g.add_node("gate_outputs", safe_gate_node(GATE_NODES["gate_outputs"]()))
    g.add_node("report_composer", safe_node(ReportComposerAgent()))
    g.add_node("self_learning_dispatch", safe_node(SelfLearningAgent()))
    g.add_node("error_recovery", ErrorRecoveryAgent())
    g.add_node("auto_error_handler", AutoErrorHandlerAgent())

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
    # HJ 2026-06-08 — insight → report_architect → gate_outputs 로 분기.
    # report_architect 는 silent-safe 로 state.error 안 세팅 → 단순 고정 엣지로 충분.
    g.add_edge("insight", "report_architect")
    g.add_edge("report_architect", "gate_outputs")

    # ---- 조건부 엣지 ---------------------------------------------------
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
        {
            "preprocessing_choice": "preprocessing_choice",
            "gate_model_strategy": "gate_model_strategy",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "metrics_aggregator",
        route_after_metrics,
        {
            "gate_best_model": "gate_best_model",
            "preprocessing_strategist": "preprocessing_strategist",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "gate_best_model",
        route_after_g4,
        {
            "fine_tune_executor": "fine_tune_executor",
            "eval_agent": "eval_agent",
            "auto_error_handler": "auto_error_handler",
            "error_recovery": "error_recovery",
        },
    )
    g.add_conditional_edges(
        "eval_agent",
        route_after_eval,
        {
            "explainability": "explainability",
            "hyperparameter_tuner": "hyperparameter_tuner",
            "feature_engineer": "feature_engineer",
            "preprocessing_strategist": "preprocessing_strategist",
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
    g.add_conditional_edges(
        "auto_error_handler",
        route_after_auto_handler,
        {
            "supervisor": "supervisor",
            "error_recovery": "error_recovery",
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

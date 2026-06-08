"""게이트 흐름 통합 테스트 — G1 → G7 회귀 방어.

본 테스트는 다음 누수를 회귀 방지한다:
    - 2026-06-04 G5→G6 catastrophic bug
      (_resume while loop 가 best_model 세팅 직후 종료해 G6 미도달)
    - _save_gate_data 의 핵심 필드 누락
    - route_after_* 의 에러 라우팅 destinations 누락
    - G3/G4 _apply_choice 미구현으로 인한 사용자 선택 무시

LangGraph / Celery / DB 미사용 — 단순 함수 단위 검증으로 빠르게 돌린다.
"""

from __future__ import annotations

import pytest

# =============================================================================
# 1) graph.py — 노드/엣지/라우팅 destinations 정합성
# =============================================================================


@pytest.mark.integration
def test_graph_builds_with_all_gates():
    """build_graph 가 5게이트 + 27노드 + 모든 conditional edge 를 무사히 구성."""
    pytest.importorskip("langgraph")
    from orchestrator.graph import GATE_NODES, INTERRUPT_AFTER, build_graph

    # 5게이트가 그래프에 등록 (G2~G6)
    assert set(GATE_NODES) == {
        "gate_direction",
        "gate_methodology",
        "gate_model_strategy",
        "gate_best_model",
        "gate_outputs",
    }
    assert set(INTERRUPT_AFTER) == set(GATE_NODES)
    # 컴파일 성공
    g = build_graph()
    nodes = list(g.get_graph().nodes) if hasattr(g, "get_graph") else getattr(g, "nodes", [])
    assert len(nodes) >= 25


@pytest.mark.integration
def test_route_after_eval_no_dead_code():
    """route_after_eval 의 unreachable `return error_recovery` 제거 회귀 방지."""
    import inspect

    from orchestrator import graph

    src = inspect.getsource(graph.route_after_eval)
    # explainability 반환 후 다른 return 이 같은 들여쓰기 레벨에 없어야 한다
    lines = [ln.rstrip() for ln in src.splitlines()]
    found_explain = False
    for ln in lines:
        if 'return "explainability"' in ln:
            found_explain = True
            continue
        # explainability 다음에 동일 들여쓰기의 return 이 또 있으면 dead code
        if found_explain and ln.startswith("    return ") and "error_recovery" in ln:
            pytest.fail("route_after_eval 에 unreachable return 이 다시 생겼다: " + ln)


@pytest.mark.integration
def test_conditional_edges_have_error_routes():
    """feature_engineer / gate_best_model 의 conditional edges 에 에러 라우팅 destinations."""
    import inspect

    from orchestrator import graph

    src = inspect.getsource(graph.build_graph)

    # feature_engineer: add_node/add_edge 등 여러 번 등장하므로 add_conditional_edges 블록을 직접 탐색
    fe_marker = "add_conditional_edges"
    fe_idx = src.find(fe_marker + '(\n        "feature_engineer"')
    assert fe_idx != -1, "feature_engineer 의 add_conditional_edges 블록을 찾을 수 없음"
    fe_section = src[fe_idx : fe_idx + 400]
    assert "auto_error_handler" in fe_section
    assert "error_recovery" in fe_section

    # gate_best_model 도 동일
    gb_marker = 'add_conditional_edges(\n        "gate_best_model"'
    gb_idx = src.find(gb_marker)
    assert gb_idx != -1, "gate_best_model 의 add_conditional_edges 블록을 찾을 수 없음"
    gb_section = src[gb_idx : gb_idx + 400]
    assert "auto_error_handler" in gb_section
    assert "error_recovery" in gb_section


# =============================================================================
# 2) gates — _apply_choice 모두 구현 + 시그니처
# =============================================================================


@pytest.mark.integration
def test_all_gates_have_apply_choice():
    """G2/G3/G4/G5/G6 모두 _apply_choice 를 BaseGate 의 default 보다 specialized 하게 보유."""
    from agents.gates._base_gate import BaseGate
    from agents.gates.analysis_proposer import AnalysisProposerAgent
    from agents.gates.methodology_proposer import MethodologyProposerAgent
    from agents.gates.model_comparison_reporter import ModelComparisonReporterAgent
    from agents.gates.model_strategy_proposer import ModelStrategyProposerAgent
    from agents.gates.output_type_selector import OutputTypeSelectorAgent

    base_apply = BaseGate._apply_choice
    for cls in (
        AnalysisProposerAgent,  # G2
        MethodologyProposerAgent,  # G3  ← 이번 세션 추가
        ModelStrategyProposerAgent,  # G4  ← 이번 세션 추가
        ModelComparisonReporterAgent,  # G5
        OutputTypeSelectorAgent,  # G6
    ):
        # 자식 클래스가 _apply_choice 를 오버라이드 했는지 확인
        assert cls._apply_choice is not base_apply, (
            f"{cls.__name__} 가 _apply_choice 를 오버라이드 안 함 → 사용자 선택 무시"
        )


@pytest.mark.integration
def test_g3_apply_choice_changes_category():
    """G3 사용자가 시계열 방법론 고르면 state.category 가 timeseries 로 변경된다."""
    from ada.core.state import PipelineState
    from agents.gates.methodology_proposer import MethodologyProposerAgent

    state = PipelineState(job_id="t1", file_id="x.csv", category="tabular_ml", user_intent="원본")
    agent = MethodologyProposerAgent()
    proposals = [
        {"id": 1, "title": "단기 시계열 예측 (LSTM/Prophet)", "rationale": "시계열 예측", "score": 0.9},
        {"id": 2, "title": "정형 ML 분류", "rationale": "분류", "score": 0.7},
    ]
    new_state = agent._apply_choice(state, {"adopted_rank": 1}, proposals)
    assert new_state.category == "timeseries"
    assert "방법론:" in (new_state.user_intent or "")


@pytest.mark.integration
def test_g4_apply_choice_seeds_model_candidates():
    """G4 사용자가 'Gradient Boosting 앙상블' 고르면 model_candidates 가 미리 채워진다."""
    from ada.core.state import PipelineState
    from agents.gates.model_strategy_proposer import ModelStrategyProposerAgent

    state = PipelineState(job_id="t1", file_id="x.csv", category="tabular_ml")
    agent = ModelStrategyProposerAgent()
    proposals = [
        {
            "id": 1,
            "title": "Gradient Boosting 앙상블",
            "models": ["XGBoost", "LightGBM", "CatBoost"],
            "rationale": "정형 데이터에 강한 3종",
            "score": 0.85,
        },
    ]
    new_state = agent._apply_choice(state, {"adopted_rank": 1}, proposals)
    assert new_state.model_candidates == ["XGBoost", "LightGBM", "CatBoost"]
    assert "모델 전략:" in (new_state.user_intent or "")
    # category_extras 에 감사용 메타데이터 기록
    assert "g4_strategy" in (new_state.category_extras.get("tabular_ml") or {})


# =============================================================================
# 3) runner — _save_gate_data 필드 + _resume while loop 종료 조건
# =============================================================================


@pytest.mark.integration
def test_save_gate_data_includes_all_required_fields():
    """프론트가 게이트 화면에서 표시하는 필드들이 모두 Redis payload 에 포함되는지."""
    import inspect

    from orchestrator import runner

    src = inspect.getsource(runner._save_gate_data)
    required_keys = (
        "proposals",
        "category",
        "target_column",
        "insights",
        "data_profile",
        "eda_summary",  # G3 이후 표시
        "best_model",  # G5 이후 표시
        "eval_result",  # G6 이후 표시
        "requested_outputs",
        "output_paths",
    )
    for key in required_keys:
        assert f'"{key}"' in src, f"_save_gate_data 가 '{key}' 를 저장하지 않음 (프론트 누락 위험)"


@pytest.mark.integration
def test_resume_loop_does_not_exit_on_best_model():
    """G5 → G6 catastrophic bug 회귀 방지.

    _resume 의 while loop 가 best_model 세팅만 보고 종료하면 안 됨
    (eval_agent / explainability / insight / gate_outputs 가 미실행 됨).
    """
    import inspect

    from orchestrator import runner

    src = inspect.getsource(runner._resume)
    # while loop 본문에 `not final_dict.get("best_model")` 이 없어야 한다
    loop_section = src.split("while (")[1].split("):")[0]
    assert "best_model" not in loop_section, (
        "_resume while loop 종료 조건에 best_model 이 다시 추가됨 → G5→G6 catastrophic bug 재발"
    )
    # output_paths 와 error 는 종료 조건에 있어야 한다
    assert "output_paths" in loop_section
    assert "error" in loop_section


# =============================================================================
# 4) training_tasks — ada.training.run 라우팅 + HEAVY_MODELS
# =============================================================================


@pytest.mark.integration
def test_training_task_registered_and_routed():
    """training_tasks 모듈이 임포트 가능하고, ada.training.run 이 training 큐로 라우팅."""
    from orchestrator.runner import celery_app
    from orchestrator.training_tasks import HEAVY_MODELS, is_heavy_model, train_model_task

    # task name
    assert train_model_task.name == "ada.training.run"
    # 라우팅 패턴
    assert celery_app.conf.task_routes["ada.training.*"]["queue"] == "training"
    # HEAVY_MODELS 셋
    expected_heavy = {
        "TabTransformer",
        "FTTransformer",
        "TabPFN",
        "Informer",
        "TFT",
        "PatchTST",
        "AutoEncoder",
        "TranAD",
        "AnomalyTransformer",
    }
    assert HEAVY_MODELS == frozenset(expected_heavy)
    assert is_heavy_model("TabTransformer") is True
    assert is_heavy_model("XGBoost") is False


@pytest.mark.integration
def test_celery_app_includes_task_modules():
    """worker 시작 시 harness_tasks / training_tasks 가 자동 import 되도록 include 설정."""
    from orchestrator.runner import celery_app

    include = list(celery_app.conf.include or [])
    assert "orchestrator.harness_tasks" in include
    assert "orchestrator.training_tasks" in include


# =============================================================================
# 5) gate_detail API — 프론트가 쓰는 응답 필드 매트릭스
# =============================================================================


@pytest.mark.integration
def test_gate_detail_returns_full_fields():
    """api/routes/pipeline.gate_detail 가 eda_summary/eval_result 까지 노출."""
    import inspect

    from api.routes import pipeline as p

    src = inspect.getsource(p.gate_detail)
    for key in (
        "category",
        "target_column",
        "insights",
        "data_profile",
        "requested_outputs",
        "best_model",
        "pipeline_status",
        "eda_summary",
        "eval_result",
    ):
        assert f'"{key}"' in src, f"gate_detail 가 '{key}' 를 응답하지 않음"


# =============================================================================
# 6) 27 에이전트 + next_agent 매트릭스
# =============================================================================


@pytest.mark.integration
def test_28_agents_registered():
    from agents.stubs import AGENT_NAME_TO_CLASS, ALL_AGENT_CLASSES

    assert len(ALL_AGENT_CLASSES) == 28
    assert len(AGENT_NAME_TO_CLASS) == 28


@pytest.mark.integration
def test_pipeline_state_has_all_referenced_fields():
    """다른 영역에서 참조하는 PipelineState 필드가 실제 정의돼 있는지."""
    from ada.core.state import PipelineState

    fields = set(PipelineState.model_fields.keys())
    required = {
        "job_id",
        "file_id",
        "category",
        "target_column",
        "user_intent",
        "user_question",
        "user_id",
        "current_gate",
        "gate_responses",
        "requested_outputs",
        "data_profile",
        "validation",
        "eda_charts",
        "eda_summary",
        "preprocessing_plan",
        "preprocessed_data_id",
        "data_card",
        "model_candidates",
        "best_params",
        "trained_models",
        "training_warnings",
        "best_model",
        "explanations",
        "eval_result",
        "insights",
        "output_paths",
        "retry_count",
        "max_retries",
        "re_loop_count",
        "max_re_loop",
        "error",
        "next_agent",
        "error_traceback",
        "auto_fix_attempts",
        "max_auto_fix_attempts",
        "kb_citations",
        "category_extras",
    }
    missing = required - fields
    assert not missing, f"PipelineState 에 누락된 필드: {missing}"

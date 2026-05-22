"""agents.stubs — 27 에이전트 canonical 등록 + ALL_AGENT_CLASSES (전수 검증 후 재구성).

본 모듈은 **단일 권위 진입점** 이다:
  - 본격 구현(agents/<name>.py) 이 있으면 그것을 그대로 re-export
  - 본격 구현이 없으면 미니멀 통과 stub 을 정의 (현재는 모두 본격 구현 보유)

LangGraph (orchestrator/graph.py) 는 본 모듈에서 27 클래스를 임포트하므로,
이 파일 한 군데만 보면 어떤 클래스가 어디로 매핑되는지 확인 가능하다.
"""

from __future__ import annotations

from agents.auto_error_handler import AutoErrorHandlerAgent
from agents.data_profiler import DataProfilerAgent
from agents.eda_agent import EDAAgent

# H 회복 (1)
from agents.error_recovery import ErrorRecoveryAgent

# E 평가·해석 (3)
from agents.eval_agent import EvalAgent
from agents.explainability import ExplainabilityAgent
from agents.feature_engineer import FeatureEngineerAgent
from agents.fine_tune_executor import FineTuneExecutorAgent

# B 의사결정 5게이트
from agents.gates.analysis_proposer import AnalysisProposerAgent
from agents.gates.methodology_proposer import MethodologyProposerAgent
from agents.gates.model_comparison_reporter import ModelComparisonReporterAgent
from agents.gates.model_strategy_proposer import ModelStrategyProposerAgent
from agents.gates.output_type_selector import OutputTypeSelectorAgent
from agents.hyperparameter_tuner import HyperparameterTunerAgent
from agents.insight import InsightAgent

# A 입력·검증 (3)
from agents.intent_elicitor import IntentElicitorAgent
from agents.metrics_aggregator import MetricsAggregatorAgent

# D 모델링 (5) + fine_tune_executor
from agents.model_selection import ModelSelectionAgent
from agents.preprocessing_choice import PreprocessingChoiceAgent

# C 전처리·EDA + 미니 게이트 (4)
from agents.preprocessing_strategist import PreprocessingStrategistAgent

# F 산출물 오케스트레이터 (1)
from agents.report_composer import ReportComposerAgent
from agents.schema_validator import SchemaValidatorAgent
from agents.security_guard import SecurityGuardAgent

# G 메타 (3)
from agents.self_learning import SelfLearningAgent

# I 슈퍼바이저 (1)
from agents.supervisor import SupervisorAgent
from agents.training_executor import TrainingExecutorAgent
from agents.training_monitor import TrainingMonitorAgent

# ---- 27 카운트 자가 검증 ----------------------------------------------------
ALL_AGENT_CLASSES = [
    SupervisorAgent,
    IntentElicitorAgent,
    DataProfilerAgent,
    SchemaValidatorAgent,
    AnalysisProposerAgent,
    MethodologyProposerAgent,
    ModelStrategyProposerAgent,
    ModelComparisonReporterAgent,
    OutputTypeSelectorAgent,
    PreprocessingStrategistAgent,
    FeatureEngineerAgent,
    EDAAgent,
    PreprocessingChoiceAgent,
    ModelSelectionAgent,
    HyperparameterTunerAgent,
    TrainingExecutorAgent,
    TrainingMonitorAgent,
    MetricsAggregatorAgent,
    FineTuneExecutorAgent,
    EvalAgent,
    ExplainabilityAgent,
    InsightAgent,
    ReportComposerAgent,
    SelfLearningAgent,
    AutoErrorHandlerAgent,
    SecurityGuardAgent,
    ErrorRecoveryAgent,
]
assert len(ALL_AGENT_CLASSES) == 27, f"expected 27 agents, got {len(ALL_AGENT_CLASSES)}"

AGENT_NAME_TO_CLASS = {cls.__name__: cls for cls in ALL_AGENT_CLASSES}
assert len(AGENT_NAME_TO_CLASS) == 27, "agent class names must be unique"

__all__ = [
    "ALL_AGENT_CLASSES",
    "AGENT_NAME_TO_CLASS",
    *(cls.__name__ for cls in ALL_AGENT_CLASSES),
]

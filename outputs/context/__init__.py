"""outputs.context — 보고서 ReportContext (13묶음) + Citation·Completeness 게이트.

Phase 1.3~1.7 — ReportArchitect/Slide·Visual Generator 의 데이터 진실원.

모듈 구조:
    schema.py            — 13묶음 dataclass + 직렬화/역직렬화
    builder.py           — PipelineState → ReportContext 정규화 (Phase 1.5)
    citation_manager.py  — ref_id 발급·색인·검증 (Phase 1.6)
    completeness.py      — 필수 묶음 검증·차단/경고 분기 (Phase 1.7)

Public re-exports (편의용 — 외부 호출자는 schema 직접 import 권장).
"""

from outputs.context.schema import (  # noqa: F401
    REPORT_CONTEXT_VERSION,
    AudienceInference,
    BaselineSet,
    BusinessKPI,
    Citation,
    CitationIndex,
    CodeArtifacts,
    CodeFile,
    DatasetProfile,
    DomainContext,
    EDAChart,
    EDAFindings,
    Evaluation,
    FeatureEngineering,
    FeatureSpec,
    GlobalImportance,
    Interpretation,
    LimitationItem,
    Limitations,
    Meta,
    ModelCandidate,
    ModelSelection,
    NotebookCell,
    PreprocessingStep,
    PreprocessingTrace,
    ReportContext,
    Training,
    TrainingRun,
)

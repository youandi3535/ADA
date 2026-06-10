"""outputs.context.schema — ReportContext 13묶음 dataclass (Phase 1.3).

분석 파이프라인 全 단계의 메타 정보를 정규화된 형태로 보관한다. Architect / Slide /
Visual Generator / Carrier / QA 모두 이 dataclass 만 참조한다 — **단일 진실원**.

설계 원칙:
    1. 모든 필드는 기본값 제공 → 부분 채움도 안전 (Architect 가 풍부도로 가중치 조정).
    2. ``to_dict() / from_dict()`` 로 PipelineState.report_context (dict) 와 양방향 변환.
    3. Pydantic 대신 dataclass — Pipeline 직렬화 오버헤드 최소화·import 비용 감소.
    4. ref_id 는 ``CitationManager`` (Phase 1.6) 가 사후 발급 — 여기서는 ``str | None``.
    5. 카테고리 4종 (tabular_ml/tabular_dl/timeseries/anomaly_detection) 모두 동일 스키마.

13묶음 (state.REPORT_CONTEXT_STAGES 와 1:1 매핑):
    ① dataset        DatasetProfile
    ② domain         DomainContext
    ③ preprocessing  PreprocessingTrace
    ④ features       FeatureEngineering
    ⑤ eda            EDAFindings
    ⑥ model_selection ModelSelection
    ⑦ training       Training
    ⑧ evaluation     Evaluation
    ⑨ interpretation Interpretation
    ⑩ limitations    Limitations
    ⑪ code           CodeArtifacts
    ⑫ meta           Meta
    ⑬ citations      CitationIndex
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Optional

# 스키마 버전 — builder/citation_manager 가 호환성 체크용
REPORT_CONTEXT_VERSION: str = "1.0.0"


# ==============================================================
# 공통 sub-structures
# ==============================================================


@dataclass
class Citation:
    """KB·웹·도메인 인용 단일 항목.

    ``DomainContext`` 의 kb_citations / web_citations 양쪽에서 사용.
    """

    source_kind: str = "kb"  # "kb" | "web" | "paper" | "benchmark"
    title: str = ""
    url: Optional[str] = None
    snippet: str = ""
    accessed_at: Optional[str] = None  # ISO8601
    ref_id: Optional[str] = None  # CitationManager 가 발급


@dataclass
class AudienceInference:
    """청중 추정 결과 — AudienceAdapter 산출, DomainContext.audience_inference."""

    level: str = "analyst"  # "c_level" | "manager" | "analyst" | "external_client"
    confidence: float = 0.5
    signals: list[str] = field(default_factory=list)  # 추정 근거 문장
    auto_inferred: bool = True


@dataclass
class PreprocessingStep:
    """전처리 단일 단계 — PreprocessingTrace.applied_steps."""

    op: str = ""  # "impute_median", "winsorize", "encode_target"
    scope: list[str] = field(default_factory=list)  # 적용 컬럼
    params: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""  # 한국어 1~2문장
    before_stats: dict[str, Any] = field(default_factory=dict)
    after_stats: dict[str, Any] = field(default_factory=dict)
    ref_id: Optional[str] = None


@dataclass
class FeatureSpec:
    """생성된 피처 — FeatureEngineering.created."""

    name: str = ""
    formula: str = ""  # 표현식 또는 step 이름
    rationale: str = ""
    importance: Optional[float] = None
    ref_id: Optional[str] = None


@dataclass
class EDAChart:
    """EDA 차트 1점 — EDAFindings.charts. 보고서 재가공 입력."""

    path: str = ""  # MinIO 원본 PNG 경로
    chart_type: str = ""  # "hist"/"box"/"scatter"/"corr_heatmap"/"ts_decompose"/...
    x: Optional[str] = None
    y: Optional[str] = None
    title_ko: str = ""
    title_en: str = ""  # ko-only 모드에선 ""
    finding: str = ""  # "X 가 Y 와 강한 양의 상관 (r=0.82)"
    callouts: list[dict[str, Any]] = field(default_factory=list)  # [{position, text}]
    severity: str = "info"  # "info" | "important" | "critical"
    numbers: list[dict[str, Any]] = field(default_factory=list)  # [{name, value}]
    ref_id: Optional[str] = None


@dataclass
class ModelCandidate:
    """모델 후보 — ModelSelection.candidates."""

    name: str = ""
    family: str = ""  # "GBM" | "DL" | "LinearReg" | ...
    why_tried: str = ""
    why_dropped: Optional[str] = None
    score: Optional[float] = None
    ref_id: Optional[str] = None


@dataclass
class BaselineSet:
    """비교 기준 묶음 — ModelSelection.baselines."""

    naive: Optional[dict[str, Any]] = None  # {name, score, ref_id}
    domain_rule: Optional[dict[str, Any]] = None  # 도메인 규칙
    previous_best: Optional[dict[str, Any]] = None  # 이전 Job 비교


@dataclass
class TrainingRun:
    """학습 단일 run — Training.runs."""

    run_id: str = ""
    model_name: str = ""
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    train_curves: Optional[dict[str, Any]] = None  # {epoch_or_iter, train_loss, val_loss}
    best_iteration: Optional[int] = None
    duration_sec: float = 0.0
    resource: dict[str, Any] = field(default_factory=dict)  # {device, memory_peak_mb, worker}
    ref_id: Optional[str] = None


@dataclass
class BusinessKPI:
    """비즈니스 임팩트 추정 — Evaluation.business_kpi. BusinessImpactQuantifier 산출."""

    name: str = ""  # "예상 월간 이탈 감소"
    unit: str = ""  # "건/월" | "원" | "%"
    estimated_value: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    confidence: str = "medium"  # "low" | "medium" | "high"
    ref_id: Optional[str] = None


@dataclass
class GlobalImportance:
    """모델 해석 — Interpretation.global_importance."""

    feature: str = ""
    importance: float = 0.0
    method: str = "shap"  # "shap" | "permutation" | "coef"
    ref_id: Optional[str] = None


@dataclass
class LimitationItem:
    """한계 항목 — Limitations.data_gaps / generalization_risk 공용 변형."""

    description: str = ""
    impact: str = "medium"  # "low" | "medium" | "high"
    mitigation: Optional[str] = None
    scenario: Optional[str] = None  # generalization_risk 전용


@dataclass
class CodeFile:
    """코드 파일 1개 — CodeArtifacts.files. redactor 통과본만 저장."""

    path: str = ""  # "pipeline.py", "model_spec.py"
    language: str = "python"
    content: str = ""  # redactor 통과본
    description_ko: str = ""
    description_en: str = ""
    ref_id: Optional[str] = None


@dataclass
class NotebookCell:
    """노트북 셀 1개 — CodeArtifacts.notebook_cells."""

    cell_type: str = "code"  # "markdown" | "code"
    source: str = ""
    outputs: Optional[list[Any]] = None
    ref_id: Optional[str] = None


# ==============================================================
# 13묶음 dataclass
# ==============================================================


@dataclass
class DatasetProfile:
    """① 데이터 프로파일 — DataProfilerAgent 적립."""

    dataset_name: str = ""
    dataset_hash: str = ""
    shape: dict[str, int] = field(default_factory=lambda: {"rows": 0, "cols": 0})
    dtypes: dict[str, str] = field(default_factory=dict)
    missing_rate: dict[str, float] = field(default_factory=dict)
    cardinality: dict[str, int] = field(default_factory=dict)
    sample_head: list[dict[str, Any]] = field(default_factory=list)
    sample_tail: Optional[list[dict[str, Any]]] = None
    numeric_stats: dict[str, dict[str, float]] = field(default_factory=dict)
    categorical_top: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    detected_target: Optional[str] = None
    detected_time_col: Optional[str] = None
    detected_id_cols: list[str] = field(default_factory=list)
    file_meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainContext:
    """② 도메인 컨텍스트 — DomainEnricher + AudienceAdapter 적립."""

    inferred_industry: Optional[str] = None
    inferred_use_case: Optional[str] = None
    kb_citations: list[Citation] = field(default_factory=list)
    web_citations: list[Citation] = field(default_factory=list)
    regulatory_hints: list[str] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    domain_benchmarks: list[dict[str, Any]] = field(default_factory=list)
    audience_inference: AudienceInference = field(default_factory=AudienceInference)
    # 도메인 해석 출처 — "user" (사용자 입력) / "auto" (자동 추론) / "mixed"
    # auto 의 경우 산출 PPT 에서 [auto-inferred] 라벨 부착 + 인용 면제.
    domain_source: str = "auto"
    # 자동 추론된 도메인 해석 텍스트 — 슬라이드 14·17 등에서 사용.
    inferred_interpretation: Optional[str] = None


@dataclass
class PreprocessingTrace:
    """③ 전처리 추적 — PreprocessingStrategist + handlers 적립."""

    applied_steps: list[PreprocessingStep] = field(default_factory=list)
    dropped_rows: dict[str, Any] = field(default_factory=dict)  # {count, reason_counts}
    schema_after: dict[str, str] = field(default_factory=dict)
    leakage_checks: list[dict[str, Any]] = field(default_factory=list)  # [{check, passed, note}]


@dataclass
class FeatureEngineering:
    """④ 피처 엔지니어링 — FeatureEngineer 적립."""

    created: list[FeatureSpec] = field(default_factory=list)
    dropped: list[dict[str, str]] = field(default_factory=list)  # [{name, reason}]
    selection_method: Optional[str] = None
    final_feature_count: int = 0
    correlation_changes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EDAFindings:
    """⑤ EDA 발견 — EDAAgent + handlers 적립."""

    charts: list[EDAChart] = field(default_factory=list)
    data_quality_issues: list[dict[str, Any]] = field(default_factory=list)
    hypothesis_tests: list[dict[str, Any]] = field(default_factory=list)
    segment_insights: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ModelSelection:
    """⑥ 모델 선정 — ModelSelection 적립."""

    search_space: dict[str, dict[str, Any]] = field(default_factory=dict)
    candidates: list[ModelCandidate] = field(default_factory=list)
    chosen: dict[str, Any] = field(default_factory=dict)  # {name, family, justification, ref_id}
    baselines: BaselineSet = field(default_factory=BaselineSet)


@dataclass
class Training:
    """⑦ 학습 — TrainingExecutor/Monitor/Tuner 적립."""

    runs: list[TrainingRun] = field(default_factory=list)
    chosen_run_id: str = ""
    tuning_summary: dict[str, Any] = field(default_factory=dict)
    mlflow_experiment: Optional[str] = None


@dataclass
class Evaluation:
    """⑧ 평가 — EvalAgent + MetricsAggregator + BusinessImpactQuantifier 적립.

    *단일 진실원* — 모든 메트릭 인용은 여기서.
    """

    primary_metric: dict[str, Any] = field(default_factory=dict)  # {name, value, direction, ref_id}
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)  # name → {value, ref_id, ci?, ...}
    per_segment: list[dict[str, Any]] = field(default_factory=list)
    confusion_matrix: Optional[dict[str, Any]] = None
    calibration: Optional[dict[str, Any]] = None
    business_kpi: list[BusinessKPI] = field(default_factory=list)
    gate_passed: bool = False
    gate_rationale: str = ""
    # 도입 판정 — 산출 PPT S2·S17·S19 가 어조 분기에 사용.
    # "adopt" (도입 권장) / "iterate" (보강 후 재시도) / "reject" (현 모델 폐기) / "" (미판정)
    verdict: str = ""
    verdict_rationale: str = ""


@dataclass
class Interpretation:
    """⑨ 해석 — Explainability 적립."""

    global_importance: list[GlobalImportance] = field(default_factory=list)
    local_examples: Optional[list[dict[str, Any]]] = None
    partial_dependence: Optional[list[dict[str, Any]]] = None
    counterfactuals: Optional[list[dict[str, Any]]] = None
    per_feature_story: dict[str, str] = field(default_factory=dict)
    segment_drivers: Optional[list[dict[str, Any]]] = None


@dataclass
class Limitations:
    """⑩ 한계 — EvalAgent self-reflection 적립."""

    data_gaps: list[LimitationItem] = field(default_factory=list)
    distribution_shift_risk: dict[str, Any] = field(default_factory=lambda: {"detected": False, "evidence": None})
    model_caveats: list[str] = field(default_factory=list)
    generalization_risk: list[LimitationItem] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    revalidation_window: str = ""


@dataclass
class CodeArtifacts:
    """⑪ 코드 산출물 — CodeArtifactExtractor 적립. Option β 의 zip 원본."""

    files: list[CodeFile] = field(default_factory=list)
    notebook_cells: list[NotebookCell] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)  # {python, key_packages}
    reproduce_command: str = ""
    redaction_report: dict[str, Any] = field(default_factory=lambda: {"redacted_count": 0, "categories": {}})


@dataclass
class Meta:
    """⑫ 메타 — Orchestrator + IntentElicitor + UI 적립."""

    job_id: str = ""
    user_intent: str = ""
    user_question: str = ""
    category: str = ""
    audience: str = "analyst"  # ②의 추정값을 final 로 이동 (재정의 없으면 동일)
    languages: list[str] = field(default_factory=lambda: ["ko"])  # 한국어 기본
    output_forms: list[str] = field(default_factory=lambda: ["pptx", "pdf", "html", "md"])
    length_hint: dict[str, list[int]] = field(default_factory=lambda: {"pptx": [10, 20]})
    business_context: Optional[str] = None
    deadline: Optional[str] = None
    generated_at: str = ""
    generation_ms_budget: Optional[int] = None
    classification: str = "Internal"  # "Public" | "Internal" | "Confidential" | "Strictly Confidential"
    skeleton_override: Optional[str] = None  # G7 에서 사용자가 강제 선택 시


@dataclass
class CitationIndex:
    """⑬ 인용 색인 — CitationManager 가 마지막 정규화.

    모든 ref_id 의 단일 색인. ``index[ref_id]`` 는 출처 메타 dict.
    """

    index: dict[str, dict[str, Any]] = field(default_factory=dict)
    unresolved_refs: list[str] = field(default_factory=list)


# ==============================================================
# Top-level container
# ==============================================================


@dataclass
class ReportContext:
    """13묶음을 묶은 top-level 컨테이너.

    ``state.report_context`` (dict) 와 ``to_dict()``/``from_dict()`` 양방향 변환.
    """

    version: str = REPORT_CONTEXT_VERSION
    dataset: DatasetProfile = field(default_factory=DatasetProfile)
    domain: DomainContext = field(default_factory=DomainContext)
    preprocessing: PreprocessingTrace = field(default_factory=PreprocessingTrace)
    features: FeatureEngineering = field(default_factory=FeatureEngineering)
    eda: EDAFindings = field(default_factory=EDAFindings)
    model_selection: ModelSelection = field(default_factory=ModelSelection)
    training: Training = field(default_factory=Training)
    evaluation: Evaluation = field(default_factory=Evaluation)
    interpretation: Interpretation = field(default_factory=Interpretation)
    limitations: Limitations = field(default_factory=Limitations)
    code: CodeArtifacts = field(default_factory=CodeArtifacts)
    meta: Meta = field(default_factory=Meta)
    citations: CitationIndex = field(default_factory=CitationIndex)

    # ----------------------------------------------------------
    # 직렬화
    # ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """state.report_context 에 저장 가능한 dict 로 변환."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "ReportContext":
        """state.report_context (dict) → ReportContext.

        누락 필드는 기본값 사용. 알 수 없는 키는 무시 (forward compatibility).
        """
        if not data:
            return cls()
        return _hydrate_dataclass(cls, data)

    # ----------------------------------------------------------
    # 조회 헬퍼
    # ----------------------------------------------------------

    def stage(self, stage_name: str) -> Any:
        """13묶음 중 하나 반환. 잘못된 키는 None."""
        if stage_name == "version":
            return self.version
        return getattr(self, stage_name, None)

    def is_empty(self) -> bool:
        """모든 묶음이 기본값인지 판단 (builder 가 초기 상태 감지용)."""
        return all(_is_default(getattr(self, f.name)) for f in fields(self) if f.name != "version")


# ==============================================================
# 직렬화 헬퍼 (모듈 내부)
# ==============================================================


def _hydrate_dataclass(cls: type, data: Any) -> Any:
    """dict → dataclass 재귀 변환.

    - dataclass 타입이면 필드별 hydrate
    - 그 외 (dict/list/primitive) 는 그대로 반환
    - 타입 힌트는 fields 의 type 으로 best-effort 추론
    """
    if not is_dataclass(cls) or not isinstance(data, dict):
        return data

    kwargs: dict[str, Any] = {}
    type_hints = _resolve_type_hints(cls)
    field_map = {f.name: f for f in fields(cls)}

    for key, value in data.items():
        if key not in field_map:
            # 알 수 없는 필드 — forward compat 위해 무시
            continue
        target_type = type_hints.get(key)
        kwargs[key] = _hydrate_value(target_type, value)

    return cls(**kwargs)


def _hydrate_value(target_type: Any, value: Any) -> Any:
    """단일 값 hydrate. dataclass / list[dataclass] 처리."""
    if value is None:
        return None

    # list[Dataclass] 처리
    origin = getattr(target_type, "__origin__", None)
    args = getattr(target_type, "__args__", ())
    if origin is list and args and isinstance(value, list):
        item_type = args[0]
        if is_dataclass(item_type):
            return [_hydrate_dataclass(item_type, v) if isinstance(v, dict) else v for v in value]
        return list(value)

    # Optional[Dataclass] / Union 처리 — NoneType 명시 제외 후 첫 dataclass 시도
    if origin is not None and args and isinstance(value, dict):
        non_none_args = [a for a in args if a is not type(None)]
        for arg in non_none_args:
            if is_dataclass(arg):
                return _hydrate_dataclass(arg, value)

    # 단일 Dataclass
    if is_dataclass(target_type) and isinstance(value, dict):
        return _hydrate_dataclass(target_type, value)

    return value


def _resolve_type_hints(cls: type) -> dict[str, Any]:
    """dataclass 의 필드 타입 힌트 해석. 실패 시 빈 dict."""
    try:
        from typing import get_type_hints

        return get_type_hints(cls)
    except Exception:
        # 일부 환경에서 forward ref 실패 가능 — fields() 의 type 으로 fallback
        return {f.name: f.type for f in fields(cls)}


def _is_default(value: Any) -> bool:
    """필드 값이 dataclass 기본값과 동일한지 best-effort 판단.

    완전 정확은 불필요 — Architect 의 풍부도 평가는 보수적이어도 안전.
    """
    if value is None:
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    if is_dataclass(value):
        return all(_is_default(getattr(value, f.name)) for f in fields(value))
    return False

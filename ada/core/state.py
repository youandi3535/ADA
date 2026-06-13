"""ada.core.state — PipelineState (LangGraph 그래프 상태).

R-005: 직접 수정 금지. ``state.model_copy(update={...})`` 패턴만 허용.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

# 4 카테고리 — v2 스코프 (메모리 ada_scope_decision)
CATEGORIES = ("tabular_ml", "tabular_dl", "timeseries", "anomaly_detection")

# 5 산출물 코드 (OUT-01/02/03/04/07)
OUTPUT_CODES = ("OUT-01", "OUT-02", "OUT-03", "OUT-04", "OUT-07")

# 5 게이트 (G1~G6 중 G1 의도 → G6 산출물)
GATES = ("G1", "G2", "G3", "G4", "G5", "G6")

# Phase 1.1 — report_context 13묶음 (Skeleton·SlideSpec 의 데이터 진실원)
# 각 묶음은 outputs/context/schema.py 의 dataclass 직렬화 형태로 저장된다.
# BaseAgent.contribute_to_context(state, stage, payload) 가 적립 진입점.
REPORT_CONTEXT_STAGES: tuple[str, ...] = (
    "dataset",  # ① DatasetProfile  ← DataProfiler
    "domain",  # ② DomainContext   ← DomainEnricher + AudienceAdapter
    "preprocessing",  # ③ PreprocessingTrace ← PreprocessingStrategist + handlers
    "features",  # ④ FeatureEngineering ← FeatureEngineer
    "eda",  # ⑤ EDAFindings    ← EDAAgent + handlers
    "model_selection",  # ⑥ ModelSelection ← ModelSelection
    "training",  # ⑦ Training       ← TrainingExecutor/Monitor/Tuner
    "evaluation",  # ⑧ Evaluation     ← EvalAgent + MetricsAggregator + BusinessImpactQuantifier
    "interpretation",  # ⑨ Interpretation ← Explainability
    "limitations",  # ⑩ Limitations    ← EvalAgent self-reflection
    "code",  # ⑪ CodeArtifacts  ← CodeArtifactExtractor (Redactor 강제)
    "meta",  # ⑫ Meta           ← Orchestrator + IntentElicitor
    "citations",  # ⑬ CitationIndex  ← CitationManager (정규화 only)
)


class PipelineState(BaseModel):
    """LangGraph 그래프 상태 모델 (Day03 §1).

    모든 에이전트가 이 상태를 입력으로 받아 새 상태를 반환한다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=False)

    # 핵심 식별자
    job_id: str
    file_id: str
    category: str
    task: str = "auto"

    # 입력 옵션
    target_column: Optional[str] = None
    user_question: Optional[str] = None
    user_intent: Optional[str] = None
    user_id: Optional[str] = None

    # 5 게이트 응답
    current_gate: Optional[str] = None
    gate_responses: dict[str, Any] = Field(default_factory=dict)
    requested_outputs: list[str] = Field(default_factory=list)
    auto_resolved_gates: list[str] = Field(default_factory=list)

    # 데이터 분석 결과
    data_profile: Optional[dict[str, Any]] = None
    validation: Optional[dict[str, Any]] = None
    preprocessing_plan: Optional[list[dict[str, Any]]] = None
    preprocessed_data_id: Optional[str] = None

    # Phase 2 (2026-06-04) — G1 데이터 파악 종합 산출물 "Data Card v1".
    # 11 섹션 dict: identity / schema / dictionary / granularity / dq_score /
    # category_target / category_specific / pii_legal / temporal_drift /
    # reproducibility / next_steps. data_profiler 가 채우고 다음 단계가 참조.
    data_card: Optional[dict[str, Any]] = None

    # EDA
    eda_charts: list[str] = Field(default_factory=list)
    # HJ-2 (2026-06-05) — 하위 호환 union. HJ EdaAgent 는 str (f-string 요약),
    # CS handlers/timeseries 는 dict (구조화된 키-값 분석 결과) 로 사용.
    # 소비측은 isinstance(eda_summary, dict) 가드 후 분기 처리 권장.
    eda_summary: Optional[dict[str, Any] | str] = None

    # G2 방법론 후보 채택 — chosen_recipe 정식 필드 (HJ-5, 2026-06-05).
    # methodology_proposer/supervisor 가 채움. CS·NY·jh 9 에이전트에서
    # getattr(state, "chosen_recipe", None) 패턴으로 안전 접근 중이었으나
    # 본 필드 추가로 타입체커·IDE 지원 확보.
    chosen_recipe: Optional[dict[str, Any]] = None

    # 모델링
    model_candidates: list[str] = Field(default_factory=list)
    best_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    trained_models: list[dict[str, Any]] = Field(default_factory=list)
    training_warnings: list[str] = Field(default_factory=list)
    best_model: Optional[dict[str, Any]] = None

    # 해석/평가
    explanations: Optional[dict[str, Any]] = None
    eval_result: Optional[dict[str, Any]] = None
    insights: Optional[str] = None

    # 산출물
    output_paths: dict[str, str] = Field(default_factory=dict)

    # 오케스트레이션 제어
    retry_count: int = 0
    max_retries: int = 3
    re_loop_count: int = 0
    max_re_loop: int = 3
    error: Optional[str] = None
    next_agent: Optional[str] = None

    # ADR-006 Auto Error Resolution (Phase 1)
    # 에러 발생 시 BaseAgent 가 traceback 캡처 + auto_error_handler 노드가 처리.
    error_traceback: Optional[str] = None
    error_classified_as: Optional[str] = None
    error_fingerprint: Optional[str] = None
    auto_fix_attempts: int = 0
    max_auto_fix_attempts: int = 2

    # 자체학습 — KB 인용 (R-501)
    kb_citations: list[str] = Field(default_factory=list)

    # 카테고리별 격리 컨테이너 (Day 0 H0-4)
    # 멤버 CS/NY/jh 가 자기 카테고리 키 안에만 쓰기 → 충돌 0건.
    category_extras: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # ==========================================================
    # 보고서 파이프라인 (Phase 1.1 — 산출물 컨설팅 퀄리티 업그레이드)
    # ----------------------------------------------------------
    # report_context : 분석 全단계의 메타 정보 (13묶음). outputs/context/schema.py
    #                  의 ReportContext dataclass 직렬화 형태.
    # report_plan    : ReportArchitect 가 만든 동적 목차 (Skeleton + SlideSpec[]).
    # report_assets  : 생성된 비주얼·텍스트의 MinIO 경로 캐시 (slide_id → assets).
    # report_citations: ref_id → source 색인 (CitationManager).
    # report_qa      : ReportQA 7축 채점 결과.
    # audience_profile: AudienceAdapter 가 추정한 청중 메타.
    #
    # 각 에이전트는 BaseAgent.contribute_to_context() 로 자기 묶음 적립.
    # 기존 필드(insights/best_model/eval_result/eda_charts 등) 와 중복되어도
    # builder.py 가 동기화하므로 안전.
    # ==========================================================
    report_context: dict[str, Any] = Field(default_factory=dict)
    report_plan: Optional[dict[str, Any]] = None
    report_assets: dict[str, Any] = Field(default_factory=dict)
    report_citations: dict[str, Any] = Field(default_factory=dict)
    report_qa: Optional[dict[str, Any]] = None
    audience_profile: Optional[dict[str, Any]] = None

    # 옵저버빌리티
    trace_id: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    # 학습 시작 시각 — TrainingMonitor 의 timeout 기준.
    # state.started_at (파이프라인 시작) 을 그대로 쓰면 retry 마다 elapsed 가 누적돼
    # 한 번 timeout 초과한 job 은 이후 모든 retry 가 즉시 실패하는 문제가 있었음.
    # TrainingExecutorAgent 가 학습 루프 진입 직전에 datetime.utcnow() 로 세팅.
    # None 이면 started_at 으로 폴백 (구 동작 호환).
    training_started_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def with_update(self, **kwargs: Any) -> "PipelineState":
        """R-005 — 직접 수정 대신 이 헬퍼를 사용한다."""
        return self.model_copy(update=kwargs)

"""ada.db.seeds — agent_registry 28행 시드.

Day02 §5 (v2 §5.5) — 28 에이전트 메타데이터 + persona 일괄 INSERT.
HJ 2026-06-08: ReportArchitectAgent 추가 (Phase 2 통합).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.models import AgentRegistry, Rule
from agents.personas import PERSONAS

# (agent_name, role, description, llm_model)
AGENT_META: list[tuple[str, str, str, str]] = [
    # I 슈퍼바이저 (1)
    ("SupervisorAgent", "supervisor", "입력 검증 및 task 분류", "claude-sonnet-4-6"),
    # A 입력·검증 (3)
    ("IntentElicitorAgent", "gate", "G1 — 자유 의도 텍스트를 구조화", "claude-sonnet-4-6"),
    ("DataProfilerAgent", "data", "데이터 프로파일링 (이미지/오디오 제거 v2)", "none"),
    ("SchemaValidatorAgent", "data", "스키마/카테고리 적합성 검증", "none"),
    # B 의사결정 5게이트
    ("AnalysisProposerAgent", "gate", "G2 — 분석 방향 3안 제시", "claude-opus-4-7"),
    ("MethodologyProposerAgent", "gate", "G3 — 정형ML/정형DL/시계열/이상탐지 방법론 제안", "claude-sonnet-4-6"),
    ("ModelStrategyProposerAgent", "gate", "G4 — 모델 전략 제안 (트랜스포머 우선)", "claude-opus-4-7"),
    ("ModelComparisonReporterAgent", "gate", "G5 — Top-3 모델 비교표", "none"),
    ("OutputTypeSelectorAgent", "gate", "G6 — 5종 산출물 추천 (OUT-01~04,07)", "claude-sonnet-4-6"),
    # C 전처리·EDA (3) + 미니게이트
    ("PreprocessingStrategistAgent", "data", "전처리 계획 (이미지/NLP 제거 v2)", "claude-sonnet-4-6"),
    ("FeatureEngineerAgent", "data", "피처 엔지니어링 실행", "none"),
    ("EDAAgent", "data", "EDA 시각화 (워드클라우드/이미지 그리드 제거 v2)", "none"),
    ("PreprocessingChoiceAgent", "gate", "전처리 자동 결정 신뢰도 낮을 때 미니 게이트", "none"),
    # D 모델링 (5) + fine_tune_executor
    ("ModelSelectionAgent", "modeling", "Top-3 후보 선정 (warm-start + 트랜스포머)", "claude-sonnet-4-6"),
    ("HyperparameterTunerAgent", "modeling", "Optuna + FLAML warm-start 탐색", "none"),
    ("TrainingExecutorAgent", "modeling", "학습 실행 (4 카테고리)", "none"),
    ("TrainingMonitorAgent", "modeling", "발산/NaN/과적합 조기 감지", "none"),
    ("MetricsAggregatorAgent", "modeling", "후보 메트릭 정규화·비교", "none"),
    ("FineTuneExecutorAgent", "modeling", "트랜스포머 최종 미세조정", "none"),
    # E 평가·해석 (3)
    ("EvalAgent", "eval", "임계치 룰 기반 출시 가능성 판정", "claude-opus-4-7"),
    ("ExplainabilityAgent", "eval", "SHAP / 시계열 분해 (Captum 백로그)", "none"),
    ("InsightAgent", "eval", "비즈니스 인사이트 (한국어 스토리텔링)", "claude-opus-4-7"),
    # F 산출물 오케스트레이터 (2) — HJ 2026-06-08: ReportArchitectAgent 추가
    (
        "ReportArchitectAgent",
        "output",
        "카테고리별 Skeleton (ML/DL/TS/Anomaly) 동적 목차 + 도메인 적응",
        "claude-opus-4-6",
    ),
    ("ReportComposerAgent", "output", "5종 산출물 fan-out + audit", "none"),
    # G 메타 (3)
    ("SelfLearningAgent", "meta", "3-Stack KB 증류 (Postgres+MinIO+pgvector)", "none"),
    ("AutoErrorHandlerAgent", "meta", "ErrorKB 매칭 → claude-cli 패치 자동 처리", "none"),
    ("SecurityGuardAgent", "meta", "LLM Guard PII / indirect injection 가드", "none"),
    # H 회복 (1)
    ("ErrorRecoveryAgent", "recovery", "최후 회복 + 사용자 친절 안내", "claude-opus-4-7"),
]

assert len(AGENT_META) == 28, f"expected 28 agents, got {len(AGENT_META)}"

# I/O 시그니처 — Day05~13 본문에서 본 형식대로 일관 유지
AGENT_IO: dict[str, dict[str, list[str]]] = {
    "SupervisorAgent": {"inputs": ["file_id", "category", "user_intent"], "outputs": ["task", "next_agent"]},
    "IntentElicitorAgent": {"inputs": ["user_intent"], "outputs": ["intent_spec"]},
    "DataProfilerAgent": {"inputs": ["file_id"], "outputs": ["profile"]},
    "SchemaValidatorAgent": {"inputs": ["profile", "category"], "outputs": ["validation"]},
    "AnalysisProposerAgent": {"inputs": ["intent_spec", "profile"], "outputs": ["proposals_3"]},
    "MethodologyProposerAgent": {"inputs": ["proposals_3"], "outputs": ["methodology"]},
    "ModelStrategyProposerAgent": {"inputs": ["methodology"], "outputs": ["strategy"]},
    "ModelComparisonReporterAgent": {"inputs": ["models"], "outputs": ["comparison"]},
    "OutputTypeSelectorAgent": {"inputs": ["intent_spec"], "outputs": ["output_codes"]},
    "PreprocessingStrategistAgent": {"inputs": ["profile", "methodology"], "outputs": ["preprocess_plan"]},
    "FeatureEngineerAgent": {"inputs": ["preprocess_plan"], "outputs": ["features"]},
    "EDAAgent": {"inputs": ["features"], "outputs": ["eda_charts"]},
    "PreprocessingChoiceAgent": {"inputs": ["candidates"], "outputs": ["chosen"]},
    "ModelSelectionAgent": {"inputs": ["features", "strategy"], "outputs": ["top3"]},
    "HyperparameterTunerAgent": {"inputs": ["top3"], "outputs": ["best_params"]},
    "TrainingExecutorAgent": {"inputs": ["features", "best_params"], "outputs": ["models"]},
    "TrainingMonitorAgent": {"inputs": ["training_state"], "outputs": ["anomaly_signal"]},
    "MetricsAggregatorAgent": {"inputs": ["models"], "outputs": ["best_model"]},
    "FineTuneExecutorAgent": {"inputs": ["best_model"], "outputs": ["finetuned"]},
    "EvalAgent": {"inputs": ["best_model", "metrics"], "outputs": ["evaluation"]},
    "ExplainabilityAgent": {"inputs": ["best_model", "features"], "outputs": ["shap_artifacts"]},
    "InsightAgent": {"inputs": ["evaluation", "shap_artifacts"], "outputs": ["insights"]},
    "ReportArchitectAgent": {"inputs": ["report_context"], "outputs": ["report_plan"]},
    "ReportComposerAgent": {"inputs": ["insights", "output_codes", "report_plan"], "outputs": ["artifacts"]},
    "SelfLearningAgent": {"inputs": ["job_id"], "outputs": ["kb_entries"]},
    "AutoErrorHandlerAgent": {"inputs": ["error_event"], "outputs": ["patch_or_escalate"]},
    "SecurityGuardAgent": {"inputs": ["request_payload"], "outputs": ["security_verdict"]},
    "ErrorRecoveryAgent": {"inputs": ["failure_log"], "outputs": ["user_message", "next_action"]},
}

CAPABILITY_MAP: dict[str, list[str]] = {
    "SupervisorAgent": ["intent_classification", "routing"],
    "IntentElicitorAgent": ["nlu", "spec_synthesis"],
    "DataProfilerAgent": ["profiling"],
    "SchemaValidatorAgent": ["schema_check"],
    "AnalysisProposerAgent": ["proposal_3way"],
    "MethodologyProposerAgent": ["methodology"],
    "ModelStrategyProposerAgent": ["model_strategy"],
    "ModelComparisonReporterAgent": ["comparison"],
    "OutputTypeSelectorAgent": ["output_routing"],
    "PreprocessingStrategistAgent": ["preprocessing"],
    "FeatureEngineerAgent": ["feature_eng"],
    "EDAAgent": ["eda"],
    "PreprocessingChoiceAgent": ["mini_gate"],
    "ModelSelectionAgent": ["model_select"],
    "HyperparameterTunerAgent": ["optuna", "flaml"],
    "TrainingExecutorAgent": ["training"],
    "TrainingMonitorAgent": ["anomaly_signal"],
    "MetricsAggregatorAgent": ["metric_normalize"],
    "FineTuneExecutorAgent": ["transformer_finetune"],
    "EvalAgent": ["quality_gate"],
    "ExplainabilityAgent": ["shap", "timeseries_decompose"],
    "InsightAgent": ["story_korean"],
    "ReportArchitectAgent": ["skeleton_picking", "narrative_design", "pyramid_validation"],
    "ReportComposerAgent": ["fan_out"],
    "SelfLearningAgent": ["kb_distill"],
    "AutoErrorHandlerAgent": ["error_match", "patch_apply"],
    "SecurityGuardAgent": ["pii_guard", "injection_block"],
    "ErrorRecoveryAgent": ["user_recovery"],
}


# ---------------------------------------------------------------------------
# Rule seeds — v2.4 까지 정의된 규칙 카탈로그 (요지)
# ---------------------------------------------------------------------------
RULE_SEED: list[dict[str, Any]] = [
    {"rule_code": "R-001", "title": "시크릿 .env 만", "category": "security"},
    {"rule_code": "R-002", "title": ".env 커밋 금지", "category": "security"},
    {"rule_code": "R-003", "title": "비루트 USER", "category": "security"},
    {"rule_code": "R-101", "title": "스키마 변경 = 마이그레이션", "category": "db"},
    {"rule_code": "R-102", "title": "JSONB는 Pydantic 검증", "category": "db"},
    {"rule_code": "R-103", "title": "PII 로그 출력 금지", "category": "data"},
    {"rule_code": "R-202", "title": "Bulkhead prefetch=1", "category": "celery"},
    {"rule_code": "R-403", "title": "트랜스포머 강제 조건부 (v2.2 완화)", "category": "model"},
    {"rule_code": "R-501", "title": "KB 인용 강제", "category": "harness"},
    {"rule_code": "R-503", "title": "record_outcome 의무", "category": "harness"},
    {"rule_code": "R-504", "title": "자동 retraction", "category": "harness"},
    {"rule_code": "R-505", "title": "decay", "category": "harness"},
    {"rule_code": "R-601", "title": "Claude CLI SDK 비동기", "category": "error"},
    {"rule_code": "R-602", "title": "claude-cli read-only", "category": "error"},
    {"rule_code": "R-703", "title": "mTLS", "category": "security"},
    {"rule_code": "R-704", "title": "모델 SHA256 무결성", "category": "security"},
    {"rule_code": "R-705", "title": "MFA", "category": "security"},
    {"rule_code": "R-706", "title": "cosign 모델 서명", "category": "security"},
    {"rule_code": "R-707", "title": "JWT RS256", "category": "security"},
    {"rule_code": "R-708", "title": "indirect injection 가드", "category": "security"},
    {"rule_code": "R-709", "title": "pybreaker 회로차단", "category": "reliability"},
    {"rule_code": "R-901", "title": "backup_catalog", "category": "backup"},
    {"rule_code": "R-902", "title": "백업 SHA256", "category": "backup"},
    {"rule_code": "R-903", "title": "Vault Raft (Dev 금지)", "category": "security"},
    {"rule_code": "R-1001", "title": "Langfuse 옵저버빌리티", "category": "obs"},
    {"rule_code": "R-1002", "title": "LLM Guard 입력 가드", "category": "security"},
    {"rule_code": "R-1003", "title": "PyOD v3 이상탐지", "category": "model"},
    {"rule_code": "R-1004", "title": "python-docx 산출물", "category": "output"},
    {"rule_code": "R-1005", "title": "Guardrails AI 스키마", "category": "security"},
    {"rule_code": "R-1006", "title": "FLAML AutoML", "category": "model"},
    {"rule_code": "R-1007", "title": "StatsForecast 시계열", "category": "model"},
    {"rule_code": "R-1008", "title": "Chart.js/Plotly 차트", "category": "output"},
]


# R-007: SYSTEM_PROMPT 변경 시 이 dict 에 버전을 bump. seeds 재실행 시 DB 에 반영됨.
_PERSONA_VERSION_BUMPS: dict[str, str] = {
    "AnalysisProposerAgent": "v2.1",  # G2: proposal 에 category/approach/target_column 필드 추가
}


async def seed_agent_registry(session: AsyncSession) -> int:
    """agent_registry 28 행 upsert. 이미 있으면 persona 업데이트만."""
    inserted = 0
    for name, role, desc, llm in AGENT_META:
        existing = await session.scalar(select(AgentRegistry).where(AgentRegistry.agent_name == name))
        persona = PERSONAS.get(name, "")
        io_spec = AGENT_IO.get(name, {"inputs": [], "outputs": []})
        caps = CAPABILITY_MAP.get(name, [])
        if existing:
            existing.persona = persona
            existing.description = desc
            existing.llm_model = llm
            existing.inputs = io_spec["inputs"]
            existing.outputs = io_spec["outputs"]
            existing.capabilities = caps
            if name in _PERSONA_VERSION_BUMPS:
                existing.persona_version = _PERSONA_VERSION_BUMPS[name]
            continue
        session.add(
            AgentRegistry(
                agent_name=name,
                role=role,
                description=desc,
                llm_model=llm,
                persona=persona,
                persona_version="v2.0",
                inputs=io_spec["inputs"],
                outputs=io_spec["outputs"],
                capabilities=caps,
            )
        )
        inserted += 1
    await session.flush()
    return inserted


async def seed_rules(session: AsyncSession) -> int:
    """rules 테이블 시드 (멱등)."""
    inserted = 0
    for r in RULE_SEED:
        existing = await session.scalar(select(Rule).where(Rule.rule_code == r["rule_code"]))
        if existing:
            continue
        session.add(
            Rule(
                rule_code=r["rule_code"],
                title=r["title"],
                category=r["category"],
                author="system",
                confidence=1.0,
                is_active=True,
            )
        )
        inserted += 1
    await session.flush()
    return inserted


async def seed_all(session: AsyncSession) -> dict[str, int]:
    a = await seed_agent_registry(session)
    r = await seed_rules(session)
    await session.commit()
    return {"agent_registry_inserted": a, "rules_inserted": r}


if __name__ == "__main__":  # CLI 진입점
    import asyncio

    from ada.db.session import AsyncSessionLocal

    async def _main() -> None:
        async with AsyncSessionLocal() as s:
            result = await seed_all(s)
            print(result)

    asyncio.run(_main())

"""outputs.context.completeness — ReportContext 완전성 게이트 (Phase 1.7).

ReportArchitect 가 보고서 목차를 짜기 전·후에 호출. ``ReportContext`` 가 보고서를
만들 만큼 충분한지 점검하고, 결과를 **차단 사유 / 경고 / 통과** 3 단계로 분류.

차단 사유 (보고서 생성 자체 차단):
    - evaluation.primary_metric 없음 → 분석 미완료
    - dataset.shape.rows == 0 → 데이터 없음
    - 미해결 ref_id 존재 (CitationManager 검증 실패)
    - 카테고리 미지정 (state.category 빈 값)
    - meta.user_intent 빈 값 (보고서 의도 불명)

경고 (생성은 진행, 영향 슬라이드만 축소·치환):
    - business_kpi 비어있음 → Executive Summary KPI 박스 → metrics 폴백
    - interpretation 비어있음 → 해석 슬라이드 스킵
    - domain.web_citations + kb_citations 모두 없음 → 도메인 벤치마크 슬라이드 스킵
    - eda.charts 0건 → 시각화 슬라이드 축소
    - limitations.data_gaps + model_caveats 모두 없음 → 한계 슬라이드 placeholder
    - code.files 비어있음 → Companion zip 미생성 안내

설계:
    - 결과는 ``CompletenessReport`` dataclass 로 통일 — QA / Architect 모두 같은 API.
    - 완전성 규칙은 카테고리·청중·skeleton 별 차등 가능 (Phase 2 확장 hook).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from outputs.context.citation_manager import CitationReport, verify_citations
from outputs.context.schema import ReportContext

# ==============================================================
# 결과 컨테이너
# ==============================================================


@dataclass
class CompletenessIssue:
    """단일 점검 결과 — 차단/경고/정보 단일 표현."""

    severity: str  # "block" | "warn" | "info"
    code: str  # 점검 코드 (예: "EVAL_PRIMARY_MISSING")
    message: str  # 사람 친화 메시지 (한국어)
    stage: str = ""  # 영향 묶음 — 빈 값이면 전역
    remediation: str = ""  # 자동 처리 안내 (carrier 가 어떻게 대응할지)


@dataclass
class CompletenessReport:
    """완전성 점검 종합 결과."""

    issues: list[CompletenessIssue] = field(default_factory=list)
    citation_report: Optional[CitationReport] = None

    @property
    def blocking(self) -> list[CompletenessIssue]:
        return [i for i in self.issues if i.severity == "block"]

    @property
    def warnings(self) -> list[CompletenessIssue]:
        return [i for i in self.issues if i.severity == "warn"]

    @property
    def can_proceed(self) -> bool:
        return not self.blocking

    def summary(self) -> dict[str, Any]:
        return {
            "can_proceed": self.can_proceed,
            "blocking_count": len(self.blocking),
            "warning_count": len(self.warnings),
            "blocking": [{"code": i.code, "message": i.message, "stage": i.stage} for i in self.blocking],
            "warnings": [{"code": i.code, "message": i.message, "stage": i.stage} for i in self.warnings],
            "citation": {
                "total": self.citation_report.total_refs if self.citation_report else 0,
                "resolved": self.citation_report.resolved if self.citation_report else 0,
                "unresolved": list(self.citation_report.unresolved) if self.citation_report else [],
                "all_resolved": self.citation_report.all_resolved if self.citation_report else True,
            },
        }


# ==============================================================
# 공개 API
# ==============================================================


def check_completeness(
    ctx: ReportContext,
    *,
    used_ref_ids: Optional[list[str]] = None,
    skeleton: Optional[str] = None,
) -> CompletenessReport:
    """ReportContext 완전성 점검.

    Args:
        ctx: 정규화된 ReportContext (builder.build_report_context 통과본 권장).
        used_ref_ids: 보고서가 실제 사용할 ref_id 들. None 이면 ref_id 검증 스킵.
        skeleton: 선택된 Skeleton 이름 — 일부 규칙은 Skeleton 마다 다름.

    Returns:
        CompletenessReport — caller 가 ``can_proceed`` / ``blocking`` 으로 분기.
    """
    report = CompletenessReport()

    # ── 차단 사유 ───────────────────────────────────────────────
    if (ctx.dataset.shape.get("rows") or 0) <= 0:
        report.issues.append(
            CompletenessIssue(
                severity="block",
                code="DATASET_EMPTY",
                message="데이터셋 행 수가 0입니다. 분석 결과가 없어 보고서 생성을 진행할 수 없습니다.",
                stage="dataset",
                remediation="DataProfiler 단계 재실행 필요.",
            )
        )

    if not ctx.evaluation.primary_metric:
        report.issues.append(
            CompletenessIssue(
                severity="block",
                code="EVAL_PRIMARY_MISSING",
                message="대표 평가 지표(primary_metric)가 없습니다. 모델 학습·평가가 완료되지 않았을 가능성이 큽니다.",
                stage="evaluation",
                remediation="EvalAgent 결과 확인 또는 재실행.",
            )
        )

    if not ctx.meta.category:
        report.issues.append(
            CompletenessIssue(
                severity="block",
                code="META_CATEGORY_MISSING",
                message="분석 카테고리가 지정되지 않았습니다.",
                stage="meta",
                remediation="DataProfiler 의 카테고리 추정 결과 확인.",
            )
        )

    if not ctx.meta.user_intent and not ctx.meta.user_question:
        report.issues.append(
            CompletenessIssue(
                severity="block",
                code="META_INTENT_MISSING",
                message="사용자 의도(user_intent)가 비어있습니다. 보고서 방향을 결정할 수 없습니다.",
                stage="meta",
                remediation="IntentElicitor 게이트 응답 확인.",
            )
        )

    # ── ref_id 검증 ─────────────────────────────────────────────
    if used_ref_ids is not None:
        cit = verify_citations(ctx, used_ref_ids)
        report.citation_report = cit
        if not cit.all_resolved:
            report.issues.append(
                CompletenessIssue(
                    severity="block",
                    code="CITATION_UNRESOLVED",
                    message=f"미해결 인용 {len(cit.unresolved)}건 — 인용 색인에 없는 ref_id 가 슬라이드에서 사용되었습니다.",
                    stage="citations",
                    remediation="CitationManager.apply_ref_ids 재실행 또는 슬라이드 인용 정리.",
                )
            )

    # ── 경고 사유 (생성은 진행) ─────────────────────────────────
    if not ctx.evaluation.business_kpi:
        report.issues.append(
            CompletenessIssue(
                severity="warn",
                code="BUSINESS_KPI_EMPTY",
                message="비즈니스 임팩트(business_kpi) 가 비어있습니다. Executive Summary KPI 카드를 메트릭으로 폴백합니다.",
                stage="evaluation",
                remediation="BusinessImpactQuantifier 미실행 — Phase 2 이후 보강.",
            )
        )

    if not (ctx.interpretation.global_importance or ctx.interpretation.per_feature_story):
        report.issues.append(
            CompletenessIssue(
                severity="warn",
                code="INTERPRETATION_EMPTY",
                message="해석(Interpretation) 데이터가 없습니다. 해석 슬라이드 또는 SHAP 인사이트 슬라이드가 스킵됩니다.",
                stage="interpretation",
                remediation="Explainability agent 결과 확인.",
            )
        )

    if not (ctx.domain.kb_citations or ctx.domain.web_citations or ctx.domain.domain_benchmarks):
        report.issues.append(
            CompletenessIssue(
                severity="warn",
                code="DOMAIN_CITATIONS_EMPTY",
                message="도메인 인용·벤치마크가 없습니다. 도메인 벤치마크 슬라이드가 스킵됩니다.",
                stage="domain",
                remediation="DomainEnricher 미실행 — Phase 2 이후 보강.",
            )
        )

    if not ctx.eda.charts:
        report.issues.append(
            CompletenessIssue(
                severity="warn",
                code="EDA_CHARTS_EMPTY",
                message="EDA 차트가 없습니다. 시각화 섹션이 축소됩니다.",
                stage="eda",
                remediation="EDAAgent 또는 카테고리 핸들러의 charts 점검.",
            )
        )

    if not (ctx.limitations.data_gaps or ctx.limitations.model_caveats or ctx.limitations.generalization_risk):
        report.issues.append(
            CompletenessIssue(
                severity="warn",
                code="LIMITATIONS_EMPTY",
                message="한계 정보가 없습니다. 한계 슬라이드는 자가검증 미흡 경고와 함께 placeholder 로 렌더됩니다.",
                stage="limitations",
                remediation="EvalAgent self-reflection 또는 명시적 한계 입력.",
            )
        )

    if not ctx.code.files:
        report.issues.append(
            CompletenessIssue(
                severity="info",
                code="CODE_ARTIFACTS_EMPTY",
                message="코드 산출물(Companion zip 용) 이 비어있습니다. HTML 사이드카 zip 이 축소됩니다.",
                stage="code",
                remediation="CodeArtifactExtractor (Phase 1.9) 실행 여부 확인.",
            )
        )

    # ── Skeleton 특화 추가 룰 ───────────────────────────────────
    if skeleton in ("Comparative",):
        if len(ctx.model_selection.candidates) < 3:
            report.issues.append(
                CompletenessIssue(
                    severity="warn",
                    code="COMPARATIVE_FEW_CANDIDATES",
                    message=f"Comparative Skeleton 은 후보 3개 이상 권장 (현재 {len(ctx.model_selection.candidates)}).",
                    stage="model_selection",
                    remediation="모델 후보 풀 확장 또는 다른 Skeleton 선택.",
                )
            )
    if skeleton in ("Diagnostic",):
        critical_eda = sum(1 for c in ctx.eda.charts if getattr(c, "severity", "info") == "critical")
        if critical_eda == 0:
            report.issues.append(
                CompletenessIssue(
                    severity="warn",
                    code="DIAGNOSTIC_NO_CRITICAL_EDA",
                    message="Diagnostic Skeleton 인데 critical severity EDA 발견이 0건입니다.",
                    stage="eda",
                    remediation="EDA finding 의 severity 메타 보강 권장.",
                )
            )
    if skeleton in ("Analysis Standard",):
        # 학술·규제형은 모든 ref_id 해결 강제 (이미 위에서 차단)
        pass

    return report


def assert_can_proceed(report: CompletenessReport) -> None:
    """차단 사유가 있으면 ``RuntimeError`` raise.

    Architect 가 Skeleton 선정·SlideSpec 생성 직전에 호출하면 보고서 생성 자체를
    차단할 수 있다. 호출자는 try/except 로 사용자 친화 메시지 전환 권장.
    """
    if report.can_proceed:
        return
    blocked = report.blocking
    msg_lines = [f"보고서 생성 차단 — 차단 사유 {len(blocked)}건:"]
    for b in blocked:
        msg_lines.append(f"  · [{b.code}] {b.message}")
    raise RuntimeError("\n".join(msg_lines))

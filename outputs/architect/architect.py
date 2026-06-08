"""outputs.architect.architect — Skeleton 선정 + ReportPlan 종합 빌더 (Phase 2 메인).

진입점: ``build_plan(ctx, output_form="pptx") -> ReportPlan``.

흐름:
    1. AudienceAdapter 로 청중 추정 → ctx.domain.audience_inference 갱신.
    2. DomainEnricher / BusinessImpactQuantifier 호출 (옵션 — 호출자가 미리 했으면 스킵).
    3. ``pick_skeleton(ctx)`` 로 Skeleton 1 개 선정.
    4. 해당 Skeleton 의 ``build(ctx, audience_profile, length_target)`` 호출.
    5. ``LengthAdjuster`` 로 10~20 hard limit 적용.
    6. Pyramid 검증 + MECE 검증 — 경고 누적.
    7. CitationManager 색인 빌드 + ref_id 적용.
    8. Completeness 게이트 — block 사유 있으면 RuntimeError.

HJ 2026-06-08 — 6종 Skeleton 삭제, ML Pitch 만 사용. 카테고리별 Skeleton
사용자 직접 추가 예정 (timeseries/anomaly/tabular_dl).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from outputs.architect.audience_adapter import adapt_audience, audience_profile
from outputs.architect.business_impact_quantifier import quantify_business_impact
from outputs.architect.domain_enricher import enrich_domain
from outputs.architect.length_adjuster import adjust_length
from outputs.architect.mece_validator import validate_mece
from outputs.architect.message_tree import validate_pyramid
from outputs.architect.plan import ReportPlan
from outputs.architect.skeletons import DEFAULT_SKELETON, SKELETON_REGISTRY
from outputs.context.citation_manager import apply_ref_ids, build_citation_index, verify_citations
from outputs.context.completeness import assert_can_proceed, check_completeness
from outputs.context.schema import ReportContext

# ==============================================================
# 공개 API
# ==============================================================


def build_plan(
    ctx: ReportContext,
    *,
    output_form: str = "pptx",
    skeleton_override: Optional[str] = None,
    kb_results: Optional[list[dict[str, Any]]] = None,
    web_results: Optional[list[dict[str, Any]]] = None,
    benchmarks: Optional[list[dict[str, Any]]] = None,
    enforce_completeness: bool = True,
) -> ReportPlan:
    """ReportPlan 종합 빌드. Architect 의 단일 진입점.

    Args:
        ctx: 정규화된 ReportContext (outputs.context.builder.build_report_context 통과본).
        output_form: 최종 출력 형식 — "pptx" | "pdf" | "html" | "md".
        skeleton_override: 사용자가 G7 에서 강제 선택한 Skeleton 이름.
        kb_results/web_results/benchmarks: DomainEnricher 입력 — None 이면 스킵.
        enforce_completeness: True 면 block 사유 발견 시 RuntimeError.

    Returns:
        완성된 ReportPlan — 슬라이드 수 [10, 20] 보장, ref_id 적용 완료.

    Raises:
        RuntimeError: completeness 차단 사유 발견 시 (enforce_completeness=True).
    """
    if kb_results or web_results or benchmarks:
        ctx = enrich_domain(ctx, kb_results=kb_results, web_results=web_results, benchmarks=benchmarks)

    ctx = quantify_business_impact(ctx)

    audience = adapt_audience(ctx)
    ctx.domain.audience_inference = audience
    ctx.meta.audience = audience.level
    profile = audience_profile(audience.level)

    skeleton_name = skeleton_override or ctx.meta.skeleton_override or pick_skeleton(ctx, profile)
    build_fn = SKELETON_REGISTRY.get(skeleton_name)
    if build_fn is None:
        # 미등록 Skeleton — DEFAULT_SKELETON 폴백 (현재 ML Pitch).
        skeleton_name = DEFAULT_SKELETON
        build_fn = SKELETON_REGISTRY[skeleton_name]

    length_range = profile.get("slide_count_range", [12, 18])
    length_target = int((length_range[0] + length_range[1]) / 2)
    plan = build_fn(ctx, profile, length_target=length_target)
    plan.output_form = output_form

    plan = adjust_length(plan, hard_min=10, hard_max=20)

    pyramid_report = validate_pyramid(plan)
    if not pyramid_report.passed:
        plan.warnings.append(
            f"pyramid_failed: orphans={len(pyramid_report.orphan_slides)}, "
            f"unreachable={len(pyramid_report.unreachable_nodes)}"
        )
    mece_report = validate_mece(plan)
    if mece_report.total_issues() > 0:
        plan.warnings.append(f"mece_issues: {mece_report.total_issues()}")

    citation_idx = build_citation_index(ctx)
    ctx = apply_ref_ids(ctx, citation_idx)
    used_refs = plan.used_ref_ids()
    citation_verdict = verify_citations(ctx, used_refs)
    if citation_verdict.unresolved:
        plan.warnings.append(f"unresolved_refs: {len(citation_verdict.unresolved)}")
    plan.citation_index = {ref_id: ctx.citations.index.get(ref_id, {}).get("source_path", "") for ref_id in used_refs}

    completeness = check_completeness(ctx, used_ref_ids=used_refs, skeleton=skeleton_name)
    if enforce_completeness and not completeness.can_proceed:
        assert_can_proceed(completeness)
    for w in completeness.warnings:
        plan.warnings.append(f"completeness_warn: {w.code}")

    plan.meta.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "architect_version": "1.0",
            "audience_confidence": audience.confidence,
            "pyramid_passed": pyramid_report.passed,
            "mece_issue_count": mece_report.total_issues(),
            "completeness": completeness.summary(),
        }
    )
    return plan


# ==============================================================
# Skeleton 선정 룰
# ==============================================================


def pick_skeleton(ctx: ReportContext, profile: dict[str, Any]) -> str:
    """ReportContext + 청중 profile 로부터 적합 Skeleton 1개 선정.

    HJ 2026-06-08 — 6종 Skeleton 삭제, ML Pitch 만 사용. 카테고리별 Skeleton
    사용자 추가 시 여기에 분기 추가.

    추가 예정 분기 (사용자가 Skeleton 파일 만든 후 SKELETON_REGISTRY 등록 + 여기 분기):
        if ctx.meta.category == "timeseries":
            return "Timeseries Pitch"
        if ctx.meta.category == "anomaly_detection":
            return "Anomaly Pitch"
        if ctx.meta.category == "tabular_dl":
            return "Tabular DL Pitch"
    """
    # 카테고리별 라우팅 (사용자가 추가할 영역) ─────────────────────
    # if ctx.meta.category == "timeseries":
    #     return "Timeseries Pitch"
    # if ctx.meta.category == "anomaly_detection":
    #     return "Anomaly Pitch"
    # if ctx.meta.category == "tabular_dl":
    #     return "Tabular DL Pitch"

    # tabular_ml + 기타 모든 카테고리 → ML Pitch (현재 유일 등록)
    return DEFAULT_SKELETON

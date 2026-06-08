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
from outputs.architect.skeletons import SKELETON_REGISTRY
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
    # 1) 도메인 보강 (옵션)
    if kb_results or web_results or benchmarks:
        ctx = enrich_domain(ctx, kb_results=kb_results, web_results=web_results, benchmarks=benchmarks)

    # 2) 비즈니스 임팩트 추정 (이미 있으면 보존)
    ctx = quantify_business_impact(ctx)

    # 3) 청중 추정
    audience = adapt_audience(ctx)
    ctx.domain.audience_inference = audience
    ctx.meta.audience = audience.level
    profile = audience_profile(audience.level)

    # 4) Skeleton 선정
    skeleton_name = skeleton_override or ctx.meta.skeleton_override or pick_skeleton(ctx, profile)
    build_fn = SKELETON_REGISTRY.get(skeleton_name)
    if build_fn is None:
        # 알 수 없는 Skeleton — SCQA fallback
        skeleton_name = "SCQA"
        build_fn = SKELETON_REGISTRY[skeleton_name]

    # 5) Skeleton build — 길이 목표는 청중 프로필
    length_range = profile.get("slide_count_range", [12, 18])
    length_target = int((length_range[0] + length_range[1]) / 2)
    plan = build_fn(ctx, profile, length_target=length_target)
    plan.output_form = output_form

    # 6) 길이 조정 (10~20 hard limit)
    plan = adjust_length(plan, hard_min=10, hard_max=20)

    # 7) Pyramid + MECE 검증 — 경고 누적
    pyramid_report = validate_pyramid(plan)
    if not pyramid_report.passed:
        plan.warnings.append(
            f"pyramid_failed: orphans={len(pyramid_report.orphan_slides)}, "
            f"unreachable={len(pyramid_report.unreachable_nodes)}"
        )
    mece_report = validate_mece(plan)
    if mece_report.total_issues() > 0:
        plan.warnings.append(f"mece_issues: {mece_report.total_issues()}")

    # 8) ref_id 색인·검증
    citation_idx = build_citation_index(ctx)
    ctx = apply_ref_ids(ctx, citation_idx)
    used_refs = plan.used_ref_ids()
    citation_verdict = verify_citations(ctx, used_refs)
    if citation_verdict.unresolved:
        plan.warnings.append(f"unresolved_refs: {len(citation_verdict.unresolved)}")
    plan.citation_index = {ref_id: ctx.citations.index.get(ref_id, {}).get("source_path", "") for ref_id in used_refs}

    # 9) Completeness 게이트
    completeness = check_completeness(ctx, used_ref_ids=used_refs, skeleton=skeleton_name)
    if enforce_completeness and not completeness.can_proceed:
        assert_can_proceed(completeness)
    # 경고는 plan 에 흡수
    for w in completeness.warnings:
        plan.warnings.append(f"completeness_warn: {w.code}")

    # 메타 마무리
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

    우선순위:
        1. 사용자 의도 키워드 (제안/비교/원인 등)
        2. 청중 레벨 (c_level → Pyramid 우선)
        3. 데이터 풍부도
        4. 카테고리 (anomaly_detection → Diagnostic 후보)
        5. 기본 SCQA
    """
    intent = (ctx.meta.user_intent or "").lower()
    biz = (ctx.meta.business_context or "").lower()
    audience_level = profile.get("level", "analyst") if isinstance(profile.get("level"), str) else "analyst"
    # profile 인자는 audience_profile() dict — level 키가 따로 있지 않으므로 ctx.meta.audience 사용
    audience_level = ctx.meta.audience or "analyst"

    # 1) 명시 의도 키워드
    intent_text = intent + " " + biz
    if any(kw in intent_text for kw in ("제안", "도입", "pitch", "투자", "솔루션")):
        return "PSI"
    if any(kw in intent_text for kw in ("비교", "vs", "선택", "평가", "후보")):
        return "Comparative"
    if any(kw in intent_text for kw in ("원인", "why", "장애", "이상 분석", "진단")):
        return "Diagnostic"
    if any(kw in intent_text for kw in ("규제", "감사", "논문", "학술", "compliance")):
        return "Analysis Standard"

    # 2) 청중 c_level → Pyramid (시간 제약)
    if audience_level == "c_level":
        return "Pyramid"

    # 3) 카테고리
    if ctx.meta.category == "anomaly_detection":
        return "Diagnostic"
    if ctx.meta.category in ("tabular_ml", "tabular_dl"):
        if len(ctx.model_selection.candidates) >= 3:
            # 후보 많고 비교 의도 있을 때
            if "최적" in intent_text or "선택" in intent_text:
                return "Comparative"

    # 4) 규제 힌트
    if ctx.domain.regulatory_hints:
        return "Analysis Standard"

    # 5) 청중 external_client → PSI 우선 (가치 어필)
    if audience_level == "external_client":
        return "PSI"

    # 기본
    return "SCQA"

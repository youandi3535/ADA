"""outputs.architect.skeletons.dl_pitch — DL Pitch Skeleton (재구성).

Tabular DL (tabular_dl) 카테고리 전용 분석 보고서 deck.
20장 골격 유지 + ml_pitch 와 동일 패턴 (ctx 기반 동적 채움 + verdict 분기) +
DL 특화 슬라이드 (Why DL · Architecture · Training Dynamics · Calibration ·
Inference Cost · MLOps Stack) 유지.

20 슬라이드 구조 (확정):
    1.  Cover                                cover
    2.  목차 (Agenda)                        agenda
    3.  Executive Summary                    exec_summary           ← verdict-aware
    4.  분석 가설                            hypothesis
    5.  Why Tabular DL?                      why_dl                 ★ DL 정당성 (ctx 기반)
    6.  기술 스택 (DL 프리셋)                p2_pain                ← manifest tabular_dl
    7.  분석 방법                            p3_alt_limits          ← method_flow (공통)
    8.  모델 아키텍처 Deep Dive              architecture_deep      ★ DL 신규
    9.  EDA · 주요 변수 1                    tech_architecture      ← EDA-1
    10. EDA · 주요 변수 2                    s3_differentiation     ← EDA-2 (또는 파생 피처)
    11. 모델 성능 + Baseline                 i1_kpi                 ← model_perf
    12. Training Dynamics                    training_dynamics      ★ DL 신규
    13. Integrated Gradients (Top 5)         eda_findings           ← shap_global 카테고리 변형
    14. 개별 사례 + Calibration              error_analysis         ← shap_cases + ECE
    15. Error CM · 진단                      insights_derived       ← error_cm 카테고리 변형
    16. 세그먼트별 성능                      as_is_to_be            ← segment
    17. Policy + Inference Cost              i3_roi                 ← policy_insight + verdict
    18. SWOT · Drift                         risk_mitigation        ← swot (ctx 기반)
    19. Roadmap + MLOps                      roadmap                ← verdict-aware Phase
    20. 감사합니다 + Q&A                     closing                ← verdict-aware

설계 원칙:
    - 모든 builder 가 ctx 에서 동적 채움 — Titanic 같은 하드코딩 X
    - verdict (adopt/iterate/reject) 에 따라 S3/S17/S19/S20 어조 자동 분기
    - skeleton_helpers 의 공통 빌더 (EDA / 파생 피처 / method flow) 재사용
    - DL 카테고리 톤은 본 파일 내부에서만 차별화 (Why DL · Training · Inference 등)

HJ 영역. 구두 협의 완료.
"""

from __future__ import annotations

from typing import Any, Optional

from outputs.architect.plan import (
    MessageNode,
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
    VisualSpec,
)
from outputs.architect.skeleton_helpers import (
    auto_label as _auto_label,
    build_derived_features_slide as _build_derived_features_slide,
    build_eda_placeholder as _build_eda_placeholder,
    build_eda_slide_from_chart as _build_eda_slide_from_chart,
    build_method_steps as _build_method_steps,
    build_method_whys as _build_method_whys,
    derived_features_richness as _derived_features_richness,
    format_pm_value as _format_pm_value,
    get_verdict_tone as _get_verdict_tone,
    select_top_eda_charts as _select_top_eda_charts,
)
from outputs.architect.substitution_manifest import (
    TechStackItem,
    is_metric_compatible,
    resolve_slide,
    resolve_tech_stack,
)
from outputs.context.schema import ReportContext
from outputs.style.text_budget import format_metric

SKELETON_NAME = "DL Pitch"


# ==============================================================
# 헬퍼 — 섹션·메트릭
# ==============================================================


def make_section(
    section_id: str,
    title: str,
    kind: str,
    divider: bool = False,
    summary: str = "",
    slides: Optional[list[SlideSpec]] = None,
) -> SectionSpec:
    return SectionSpec(
        id=section_id,
        title=title,
        kind=kind,
        divider_required=divider,
        short_summary=summary or title,
        slides=list(slides or []),
    )


def primary_metric_ref(ctx: ReportContext) -> list[str]:
    pm = ctx.evaluation.primary_metric or {}
    rid = pm.get("ref_id")
    return [rid] if rid else []


# ==============================================================
# S1 / S2 — Cover / Agenda
# ==============================================================


def build_cover(ctx: ReportContext) -> SlideSpec:
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "Tabular DL 분석 보고서").strip()
    return SlideSpec(
        id="cover",
        section_id="front_matter",
        layout="cover",
        role="meta",
        so_what="",
        title_ko=intent[:40],
        body_outline=[
            f"카테고리 · {ctx.meta.category}",
            f"데이터셋 · {ctx.dataset.dataset_name or '미지정'}",
            f"분류등급 · {ctx.meta.classification}",
        ],
        required_refs=[],
        speaker_notes_hint="제목·분석 의도·핵심 결론 미리보기.",
    )


def build_agenda(sections_titles: list[str]) -> SlideSpec:
    return SlideSpec(
        id="agenda",
        section_id="front_matter",
        layout="agenda",
        role="meta",
        so_what="본 보고서는 5개 섹션 — DL 정당성 · 솔루션 · 결과 · 임팩트 · 실행 순.",
        title_ko="목차",
        body_outline=sections_titles,
        speaker_notes_hint="섹션 흐름 안내.",
    )


# ==============================================================
# S2 (실슬롯 S3) — Executive Summary (verdict-aware)
# ==============================================================


def _build_top_findings_from_ctx(ctx: ReportContext) -> list[dict[str, Any]]:
    """S3 상단 3 KEY FINDINGS — interpretation.global_importance Top 3."""
    importance_list = list(ctx.interpretation.global_importance or [])[:3]
    findings: list[dict[str, Any]] = []
    for i, item in enumerate(importance_list):
        feature = getattr(item, "feature", "") or f"Feature {i+1}"
        value = getattr(item, "importance", None) or 0.0
        story = ctx.interpretation.per_feature_story.get(feature, "")
        findings.append({
            "label": f"FINDING {i+1:02d}",
            "feature": feature,
            "big": format_metric(float(value), "ig", as_percent=False, decimals=2),
            "sub": _auto_label(story, ctx) if story else feature,
        })
    while len(findings) < 3:
        findings.append({
            "label": f"FINDING {len(findings)+1:02d}",
            "feature": "",
            "big": "-",
            "sub": "분석 결과 적립 후 채워짐",
        })
    return findings


def _build_method_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    n_candidates = len(ctx.model_selection.candidates or [])
    n_features = ctx.features.final_feature_count or len(ctx.features.created or [])
    return [
        ("모델 선정", f"{chosen} — 후보 {n_candidates}개 비교 후 선택" if n_candidates else f"{chosen} 선정"),
        ("신규 피처", f"{n_features}개 추가" if n_features else "신규 피처 생성 없음"),
        ("검증 방식", "Early Stopping + Validation 분할 + Calibration"),
    ]


def _build_perf_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    pm = ctx.evaluation.primary_metric or {}
    pm_str = _format_pm_value(pm)
    gate = "운영 임계 통과" if ctx.evaluation.gate_passed else "운영 임계 미통과"
    rationale = ctx.evaluation.gate_rationale or gate

    baseline = ctx.model_selection.baselines.naive or {}
    baseline_str = ""
    if baseline:
        b_val = baseline.get("score")
        if b_val is not None:
            try:
                baseline_str = format_metric(float(b_val), pm.get("name", ""))
            except (TypeError, ValueError):
                baseline_str = str(b_val)
            baseline_str = f"ML {baseline_str} 대비 +{pm_str}"
        else:
            baseline_str = "Baseline 비교 완료"
    else:
        baseline_str = "Baseline 미설정"

    n_metrics = len(ctx.evaluation.metrics or {})
    balance = f"{n_metrics}-metric + Calibration" if n_metrics >= 2 else "단일 metric 평가"

    return [
        ("운영 임계", rationale),
        ("ML Baseline 대비", baseline_str),
        ("균형 · Calibration", balance),
    ]


def _build_limitation_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    gaps = list(ctx.limitations.data_gaps or [])[:3]
    items: list[tuple[str, str]] = []
    for g in gaps:
        label = getattr(g, "description", "") or "데이터 결함"
        impact = getattr(g, "impact", "") or ""
        mitigation = getattr(g, "mitigation", None) or ""
        if mitigation:
            desc = f"영향 {impact} · {mitigation}" if impact else mitigation
        else:
            desc = f"영향 {impact}" if impact else "영향 추정 필요"
        items.append((str(label), str(desc)))
    if len(items) < 3 and ctx.limitations.model_caveats:
        for cav in ctx.limitations.model_caveats[: 3 - len(items)]:
            items.append(("모델 한계", str(cav)))
    while len(items) < 3:
        items.append(("한계", "추가 분석 필요"))
    return items


def _build_exec_summary_dl(ctx: ReportContext) -> SlideSpec:
    """슬라이드 3 — Executive Summary (DL, verdict-aware)."""
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "분석 과제"
    horizon = ctx.limitations.revalidation_window or "6개월"
    pm_name = pm.get("name", "primary")
    pm_value = _format_pm_value(pm)

    tone = _get_verdict_tone(ctx)
    so_what = tone.s2_so_what_template.format(
        chosen=chosen, use_case=use_case,
        metric_name=pm_name, metric_value=pm_value, horizon=horizon,
    )

    findings = _build_top_findings_from_ctx(ctx)
    method_items = _build_method_subitems(ctx)
    perf_items = _build_perf_subitems(ctx)
    limitation_items = _build_limitation_subitems(ctx)

    body = [
        f"발견 1 · {findings[0]['feature']} {findings[0]['big']}",
        f"발견 2 · {findings[1]['feature']} {findings[1]['big']}",
        f"발견 3 · {findings[2]['feature']} {findings[2]['big']}",
        f"방법 · {method_items[0][1]}",
        f"성능 · {pm_name} {pm_value} ({tone.accent})",
    ]

    return SlideSpec(
        id="exec_summary",
        section_id="front_matter",
        layout="exec_summary_3finding_3box",
        role="claim",
        so_what=so_what,
        title_ko="Executive Summary",
        body_outline=body,
        required_refs=primary_metric_ref(ctx),
        thread_part="resolution",
        parent_message_id="root",
        visual_spec=VisualSpec(
            type="exec_summary_v32",
            title="Executive Summary",
            spec={
                "findings": findings,
                "method_items": method_items,
                "perf_items": perf_items,
                "limitation_items": limitation_items,
                "verdict": ctx.evaluation.verdict or "adopt",
                "tone_accent": tone.accent,
            },
        ),
        speaker_notes_hint=(
            "1장만 봐도 의사결정 가능. 상단 3 KEY FINDINGS = IG / Attention 으로 알아낸 것, "
            "하단 METHOD / PERFORMANCE / LIMITATION 의 ML 대비 우위 + Calibration."
        ),
    )


# ==============================================================
# S4 — Hypothesis
# ==============================================================


def _build_hypothesis(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    intent = ctx.meta.user_intent or "분석 과제"
    body = [
        "H1 · 표현학습 · Embedding/Attention 으로 비선형 신호 자동 포착",
        f"H2 · 모델 적합성 · {chosen} 가 ML Baseline 대비 {pm.get('name', '지표')} 향상",
        "H3 · 운영 안정성 · Calibration + Inference Cost 통제 가능",
    ]
    return SlideSpec(
        id="hypothesis",
        section_id="problem",
        layout="one_message",
        role="claim",
        so_what=f"본 분석 '{intent[:40]}' 의 3 가설 — 데이터로 입증 예정",
        title_ko="분석 가설",
        body_outline=body,
        thread_part="setup",
        parent_message_id="hyp_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Hypothesis · Evidence · Insight",
            caption="가설별 증거·인사이트 흐름 (검증은 후속 슬라이드)",
            spec={"layout": "hyp_evidence_insight"},
        ),
        speaker_notes_hint="3 가설 명확. 슬라이드 13~15 에서 1:1 대응.",
    )


# ==============================================================
# S5 — Why Tabular DL? (DL 정당성, ctx 기반)
# ==============================================================


def _build_why_dl(ctx: ReportContext) -> SlideSpec:
    """슬라이드 5 — Why Tabular DL? (DL 도입 정당성, ctx 기반).

    ML Baseline 의 한계 (고차원·비선형) 와 DL 의 표현학습 우위를 명시.
    ctx.dataset.cardinality / interpretation.global_importance 에서 객관 증거 추출.
    """
    cardinality = ctx.dataset.cardinality or {}
    high_card_cols = sorted(cardinality.items(), key=lambda kv: -kv[1])[:3]

    why_items: list[tuple[str, str]] = []
    if high_card_cols:
        for col, card in high_card_cols:
            why_items.append((f"{col} 고카디널리티", f"{card:,} 개 unique — one-hot 폭발"))
    else:
        why_items.append(("고차원 categorical", "ctx 적립 시 자동 표시"))

    # 비선형 신호
    top_features = list(ctx.interpretation.global_importance or [])[:3]
    if top_features:
        names = " · ".join(getattr(f, "feature", "") for f in top_features)
        why_items.append(("비선형 상호작용", f"{names} 등 변수 간 상호 신호 자동 포착"))
    else:
        why_items.append(("비선형 상호작용", "Embedding · Attention 자동 학습"))

    why_items.append(("운영 비용", "Quantization · Pruning 으로 추론 비용 통제"))

    body = [f"{k} · {v}" for k, v in why_items[:5]]
    return SlideSpec(
        id="why_dl",
        section_id="problem",
        layout="why_dl_3_pillars",
        role="claim",
        so_what="Tabular DL 도입 정당성 — 고차원·비선형·비용 통제 3축",
        title_ko="Why Tabular DL?",
        body_outline=body,
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Why Tabular DL",
            spec={"why_items": why_items[:5]},
        ),
        speaker_notes_hint="DL 도입의 *데이터적 근거* — cardinality + 비선형 상호작용.",
    )


# ==============================================================
# S6 — Tech Stack (DL 프리셋)
# ==============================================================


def _build_pain_points(ctx: ReportContext) -> SlideSpec:
    """슬라이드 6 — 기술 스택 (DL 프리셋, manifest 기반)."""
    category = ctx.meta.category or "tabular_dl"
    items: list[TechStackItem] = resolve_tech_stack(category)

    env_pkgs: dict[str, str] = {}
    if ctx.code and getattr(ctx.code, "environment", None):
        env_pkgs = ctx.code.environment.get("key_packages", {}) or {}

    stack_items: list[tuple[str, str]] = []
    for it in items:
        role = it.role
        first_token = it.name.split("/")[0].strip().split(" ")[0].strip().lower()
        for pkg, ver in env_pkgs.items():
            if pkg.lower() == first_token and ver:
                role = f"{role} · v{ver}"
                break
        stack_items.append((it.name, role))

    body = [f"{name} · {role}" for name, role in stack_items]
    py_ver = env_pkgs.get("python", "3.x")
    cuda = env_pkgs.get("cuda", "")
    runtime = f"Python {py_ver}" + (f" · CUDA {cuda}" if cuda else "")

    return SlideSpec(
        id="p2_pain",
        section_id="problem",
        layout="tech_stack_grid",
        role="evidence",
        so_what=f"본 분석은 {category} 표준 스택 ({len(stack_items)}개 도구) 으로 재현 가능 — {runtime}",
        title_ko="기술 스택",
        body_outline=body,
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_tech_stack",
            title="기술 스택",
            spec={"stack_items": stack_items, "category": category, "python_version": py_ver, "cuda_version": cuda},
        ),
        speaker_notes_hint="DL 표준 스택 (PyTorch · TabNet/FT-Transformer · IG · W&B).",
    )


# ==============================================================
# S7 — 분석 방법 (Method Flow + WHY 패널, 공통)
# ==============================================================


def _build_ml_baseline_limits(ctx: ReportContext) -> SlideSpec:
    """슬라이드 7 — 분석 방법 흐름 + WHY 패널 (Option C).

    [재구성] 'ML Baseline 한계' → 분석 방법 흐름. skeleton_helpers 의 공통 빌더 사용.
    """
    steps = _build_method_steps(ctx)
    whys = _build_method_whys(ctx)
    body = [f"단계 {i+1} · {s['label']}" for i, s in enumerate(steps)]

    return SlideSpec(
        id="p3_alt_limits",
        section_id="problem",
        layout="method_flow_with_why",
        role="evidence",
        so_what="5단계 분석 방법 — 각 단계의 *선택 이유* 와 *정량 결과* 트레이스",
        title_ko="분석 방법",
        body_outline=body[:5],
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_method_flow",
            title="분석 방법 흐름 · WHY",
            spec={"steps": steps, "whys": whys},
        ),
        speaker_notes_hint="좌측 흐름도 + 우측 WHY 카드 — 단계별 rationale 자동 추출.",
    )


# ==============================================================
# S8 — Architecture Deep Dive (DL 특화, ctx 기반)
# ==============================================================


def _build_architecture_deep(ctx: ReportContext) -> SlideSpec:
    """슬라이드 8 — 모델 아키텍처 Deep Dive (ctx 기반).

    ctx.training.runs[0] 의 hyperparameters / resource 에서 구조·파라미터 추출.
    """
    chosen = ctx.model_selection.chosen or {}
    chosen_name = chosen.get("name", "Tabular DL")
    chosen_family = chosen.get("family", "DL")

    arch_items: list[tuple[str, str]] = [("모델", f"{chosen_name} ({chosen_family})")]

    if ctx.training.runs:
        run = ctx.training.runs[0]
        hp = getattr(run, "hyperparameters", {}) or {}
        resource = getattr(run, "resource", {}) or {}

        if "n_layers" in hp:
            arch_items.append(("레이어", f"{hp['n_layers']}층"))
        if "hidden_dim" in hp or "d_model" in hp:
            dim = hp.get("hidden_dim", hp.get("d_model"))
            arch_items.append(("Hidden Dim", f"{dim}"))
        if "n_heads" in hp:
            arch_items.append(("Attention Heads", f"{hp['n_heads']}"))
        if "embedding_dim" in hp:
            arch_items.append(("Embedding Dim", f"{hp['embedding_dim']}"))
        if "n_params" in hp:
            arch_items.append(("Total Params", f"{hp['n_params']:,}"))
        device = resource.get("device", "")
        if device:
            arch_items.append(("학습 Device", str(device)))
    else:
        arch_items.append(("구조", "ctx.training.runs 적립 후 표시"))

    body = [f"{k} · {v}" for k, v in arch_items[:6]]

    return SlideSpec(
        id="architecture_deep",
        section_id="solution",
        layout="architecture_deep_dive",
        role="evidence",
        so_what=f"{chosen_name} 모델 구조 — 표현학습 메커니즘과 파라미터 분포",
        title_ko="모델 아키텍처 · Deep Dive",
        body_outline=body[:5],
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type="architecture_diagram",
            title=f"{chosen_name} 구조",
            spec={"arch_items": arch_items, "model_name": chosen_name, "family": chosen_family},
        ),
        speaker_notes_hint=(
            "DL 모델의 *구조* 명시 — Embedding / Attention / 깊이. "
            "ctx.training.runs[0].hyperparameters 에서 자동 추출."
        ),
    )


# ==============================================================
# S9 / S10 — EDA 1·2 (또는 파생 피처)
# ==============================================================


def _build_tech_architecture_combined(ctx: ReportContext) -> SlideSpec:
    """슬라이드 9 — EDA · 주요 변수 1 (ctx.eda.charts Top 1)."""
    charts = _select_top_eda_charts(ctx, n=3)
    if charts:
        return _build_eda_slide_from_chart(charts[0], "tech_architecture", 1, ctx, "eda_main_1")
    return _build_eda_placeholder("tech_architecture", 1, ctx, "eda_main_1")


def _build_differentiation(ctx: ReportContext) -> SlideSpec:
    """슬라이드 10 — 파생 피처 우선 / EDA-2 폴백."""
    if _derived_features_richness(ctx) >= 5:
        return _build_derived_features_slide(ctx, "s3_differentiation")
    charts = _select_top_eda_charts(ctx, n=3)
    if len(charts) >= 2:
        return _build_eda_slide_from_chart(charts[1], "s3_differentiation", 2, ctx, "eda_main_2")
    return _build_eda_placeholder("s3_differentiation", 2, ctx, "eda_main_2")


# ==============================================================
# S11 — Model Performance + Baseline
# ==============================================================


def _build_kpi_ml_vs_dl(ctx: ReportContext) -> SlideSpec:
    """슬라이드 11 — 모델 성능 + Baseline 비교 (실값)."""
    pm = ctx.evaluation.primary_metric or {}
    pm_name = pm.get("name", "primary")
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    category = ctx.meta.category or "tabular_dl"

    metric_ok = is_metric_compatible(category, pm_name)

    baselines = ctx.model_selection.baselines
    bars: list[dict[str, Any]] = []
    if baselines.naive:
        b = baselines.naive
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "Naive"), "value": v, "color": "muted"})
    if baselines.domain_rule:
        b = baselines.domain_rule
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "도메인 룰"), "value": v, "color": "muted"})
    if baselines.previous_best:
        b = baselines.previous_best
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "ML Best"), "value": v, "color": "muted"})
    bars.append({"label": f"{chosen} (선정)", "value": pm.get("value"), "color": "primary", "highlight": True})

    metric_lines: list[str] = []
    balance_top4: list[tuple[str, str]] = []
    for name, m in list((ctx.evaluation.metrics or {}).items())[:4]:
        val = m.get("value") if isinstance(m, dict) else None
        if val is None:
            continue
        formatted = format_metric(float(val), name)
        metric_lines.append(f"{name} {formatted}")
        balance_top4.append((name, formatted))

    body: list[str] = []
    for bar in bars[:5]:
        v = bar["value"]
        v_str = format_metric(float(v), pm_name) if isinstance(v, (int, float)) else str(v)
        body.append(f"{bar['label']} · {pm_name} {v_str}")
    if metric_lines:
        body.append("4-metric · " + " · ".join(metric_lines))

    tone = _get_verdict_tone(ctx)
    so_what = f"{chosen} 성능: {pm_name} {pm_value_str} ({tone.accent})"

    return SlideSpec(
        id="i1_kpi",
        section_id="results",
        layout="model_perf_baseline_grouped",
        role="evidence",
        so_what=so_what,
        title_ko="모델 성능 · ML vs DL",
        body_outline=body[:5],
        required_refs=primary_metric_ref(ctx),
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="v28_model_perf",
            title=f"Baseline 비교 — {pm_name}",
            spec={
                "metric": pm_name,
                "metric_value": pm.get("value"),
                "bars": bars,
                "metric_balance_top4": balance_top4,
                "metric_category_compatible": metric_ok,
                "verdict": ctx.evaluation.verdict or "",
            },
        ),
        speaker_notes_hint="ML baseline 대비 DL 의 *추가 가치* 정량화.",
    )


# ==============================================================
# S12 — Training Dynamics (DL 특화)
# ==============================================================


def _build_training_dynamics(ctx: ReportContext) -> SlideSpec:
    """슬라이드 12 — Training Dynamics (loss/acc curves, gradient, early stopping).

    ctx.training.runs[0].train_curves 에서 적립된 학습 곡선 사용.
    """
    body: list[str] = []
    spec: dict[str, Any] = {}

    if ctx.training.runs:
        run = ctx.training.runs[0]
        curves = getattr(run, "train_curves", None) or {}
        best_iter = getattr(run, "best_iteration", None)
        duration = getattr(run, "duration_sec", 0) or 0

        if curves:
            spec["curves"] = curves
            body.append("Train/Val Loss 곡선 적립 완료")
        if best_iter is not None:
            body.append(f"Best Iteration · {best_iter}")
            spec["best_iteration"] = best_iter
        if duration:
            body.append(f"학습 시간 · {duration:.1f}초")
            spec["duration_sec"] = duration

        hp = getattr(run, "hyperparameters", {}) or {}
        if "learning_rate" in hp or "lr" in hp:
            lr = hp.get("learning_rate", hp.get("lr"))
            body.append(f"Learning Rate · {lr}")
        if "batch_size" in hp:
            body.append(f"Batch Size · {hp['batch_size']}")

    if not body:
        body = ["Training Dynamics 미적립 — ctx.training.runs 채워지면 자동 반영"]

    return SlideSpec(
        id="training_dynamics",
        section_id="results",
        layout="training_dynamics",
        role="evidence",
        so_what="학습 안정성 — Loss 수렴 + Early Stopping 시점 + 자원 사용",
        title_ko="Training Dynamics",
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="training_curves",
            title="Training Dynamics",
            spec=spec,
        ),
        speaker_notes_hint="loss/acc curves + gradient norm + early stopping — DL 신뢰성 어필.",
    )


# ==============================================================
# S13 — Integrated Gradients (SHAP 카테고리 변형)
# ==============================================================


def _build_eda_with_embedding(ctx: ReportContext) -> SlideSpec:
    """슬라이드 13 — Integrated Gradients Top 5 (DL 변형).

    Top 5 importance 항목에 (파생) / (원본) 라벨 부착.
    """
    category = ctx.meta.category or "tabular_dl"
    variant = resolve_slide("shap_global", category)
    title_ko = (variant.title_ko if variant else "Integrated Gradients · Top 5")

    imps = list(ctx.interpretation.global_importance or [])[:5]
    derived_names = {
        getattr(f, "name", "") for f in (ctx.features.created or []) if getattr(f, "name", "")
    }
    items: list[dict[str, Any]] = []
    refs: list[str] = []
    for it in imps:
        feat = getattr(it, "feature", "")
        is_derived = feat in derived_names
        items.append({
            "feature": feat,
            "importance": getattr(it, "importance", 0.0),
            "method": getattr(it, "method", "ig"),
            "kind": "derived" if is_derived else "original",
        })
        rid = getattr(it, "ref_id", None)
        if rid:
            refs.append(rid)

    body = [
        f"{i+1}순위 · {it['feature']} ({'파생' if it['kind'] == 'derived' else '원본'}) · "
        f"{format_metric(float(it['importance']), 'ig', as_percent=False, decimals=2)}"
        for i, it in enumerate(items)
    ]
    if not body:
        body = ["분석 결과 적립 후 채워짐"]

    so_what = "상위 5 피처의 영향력 — Integrated Gradients 로 도출"
    if items:
        total = sum(float(it["importance"]) for it in items)
        top3 = sum(float(it["importance"]) for it in items[:3])
        if total > 0:
            ratio = top3 / total * 100
            so_what = (
                f"상위 3 피처가 영향력의 {ratio:.0f}% — "
                f"{items[0]['feature']} 이 가장 강한 신호"
            )

    return SlideSpec(
        id="eda_findings",
        section_id="results",
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body[:5],
        required_refs=refs,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_annotated_bar"),
            title=title_ko,
            spec={"items": items, "method": "integrated_gradients"},
            severity="important",
        ),
        speaker_notes_hint="DL 의 IG 는 ML 의 SHAP 와 유사 — Top 5 만 보여줌.",
    )


# ==============================================================
# S14 — 개별 사례 + Calibration (DL 변형)
# ==============================================================


def _build_error_analysis_calibration(ctx: ReportContext) -> SlideSpec:
    """슬라이드 14 — 개별 사례 (Attention Map) + Calibration (ECE).

    ctx.interpretation.local_examples 3건 + ctx.evaluation.calibration.
    """
    category = ctx.meta.category or "tabular_dl"
    variant = resolve_slide("shap_cases", category)
    title_ko = (variant.title_ko if variant else "개별 사례 · Attention + Calibration")

    locals_ = list(ctx.interpretation.local_examples or [])[:3]
    cases: list[dict[str, Any]] = []
    body: list[str] = []
    for i, ex in enumerate(locals_):
        if not isinstance(ex, dict):
            continue
        pred = ex.get("prediction", "-")
        true = ex.get("true", "-")
        contributions = ex.get("contributions", [])
        top_feats = ", ".join(
            f"{c.get('feature', '')}({c.get('value', '')})"
            for c in (contributions[:3] if isinstance(contributions, list) else [])
        )
        cases.append({
            "index": i + 1,
            "prediction": pred,
            "true": true,
            "top_contributions": contributions[:3] if isinstance(contributions, list) else [],
        })
        body.append(f"사례 {i+1} · 예측 {pred} / 실제 {true} · {top_feats}")
    while len(body) < 3:
        body.append(f"사례 {len(body)+1} · ctx 적립 후 채워짐")

    calib = ctx.evaluation.calibration or {}
    ece = calib.get("ece") if isinstance(calib, dict) else None
    if ece is not None:
        body.append(f"Calibration · ECE {ece:.3f}")

    return SlideSpec(
        id="error_analysis",
        section_id="results",
        layout=(variant.layout if variant else "one_message"),
        role="evidence",
        so_what="개별 사례 + Calibration — 모델이 *왜 그렇게 예측했나* + *확률 신뢰도*",
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="shap_cases_with_calibration",
            title=title_ko,
            spec={"cases": cases, "calibration": calib},
        ),
        speaker_notes_hint="DL 의 사례 분석 (Attention) + Reliability Diagram + ECE.",
    )


# ==============================================================
# S15 — Error CM (카테고리 적응)
# ==============================================================


def _build_insights_derived(ctx: ReportContext) -> SlideSpec:
    """슬라이드 15 — Error CM / Diagnostic."""
    category = ctx.meta.category or "tabular_dl"
    variant = resolve_slide("error_cm", category)
    title_ko = (variant.title_ko if variant else "Confusion Matrix · 오류 분석")

    cm = ctx.evaluation.confusion_matrix or {}
    body: list[str] = []

    if cm:
        tn = cm.get("tn") or cm.get("true_negative") or 0
        fp = cm.get("fp") or cm.get("false_positive") or 0
        fn = cm.get("fn") or cm.get("false_negative") or 0
        tp = cm.get("tp") or cm.get("true_positive") or 0
        total = max(1, tn + fp + fn + tp)
        body.extend([
            f"TN {tn} ({tn/total*100:.0f}%) · TP {tp} ({tp/total*100:.0f}%)",
            f"FP {fp} ({fp/total*100:.0f}%) · FN {fn} ({fn/total*100:.0f}%)",
        ])
        if fn > fp:
            body.append("미탐지(FN) > 오탐지(FP) — 임계값 낮춰 recall 우선")
        elif fp > fn:
            body.append("오탐지(FP) > 미탐지(FN) — 임계값 높여 precision 우선")
        else:
            body.append("FP / FN 균형 — 현재 임계값 적정")
    else:
        body.append("Confusion Matrix 미적립")

    return SlideSpec(
        id="insights_derived",
        section_id="results",
        layout=(variant.layout if variant else "chart_callout"),
        role="caveat",
        so_what="모델 오류 진단 — CM + 임계값 권고",
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "diagram_confusion_matrix"),
            title=title_ko,
            spec={"confusion_matrix": cm},
            severity="important",
        ),
        speaker_notes_hint="DL CM + 임계값 조정 방향.",
    )


# ==============================================================
# S16 — Segment 성능
# ==============================================================


def _build_as_is_to_be(ctx: ReportContext) -> SlideSpec:
    """슬라이드 16 — 세그먼트별 성능 비교."""
    category = ctx.meta.category or "tabular_dl"
    variant = resolve_slide("segment", category)
    title_ko = (variant.title_ko if variant else "세그먼트별 성능 비교")

    segs = list(ctx.evaluation.per_segment or [])[:6]
    body: list[str] = []
    seg_items: list[dict[str, Any]] = []
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        name = seg.get("segment") or seg.get("name") or "?"
        metric_name = seg.get("metric") or "score"
        value = seg.get("value")
        if value is None:
            continue
        formatted = format_metric(float(value), str(metric_name))
        body.append(f"{name} · {metric_name} {formatted}")
        seg_items.append({"segment": name, "metric": metric_name, "value": value})

    if not body:
        body = ["세그먼트별 성능 미적립"]

    so_what = "세그먼트별 성능 — 모든 세그먼트에서 일관성 확인"
    if len(seg_items) >= 2:
        vals = [float(s["value"]) for s in seg_items]
        gap = max(vals) - min(vals)
        if gap > 0.1:
            so_what = f"세그먼트 격차 {gap:.2f} — 일부 보완·재학습 필요"

    return SlideSpec(
        id="as_is_to_be",
        section_id="impact",
        layout=(variant.layout if variant else "one_message"),
        role="evidence",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body[:6],
        parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="segment_perf_table",
            title=title_ko,
            spec={"segments": seg_items},
        ),
        speaker_notes_hint="세그먼트별 일관성 — 격차 0.1 이상 시 보완.",
    )


# ==============================================================
# S17 — Policy + Inference Cost (verdict-aware + DL 특화)
# ==============================================================


def _build_roi_inference_cost(ctx: ReportContext) -> SlideSpec:
    """슬라이드 17 — Policy Insight + Inference Cost (verdict-aware).

    DL 특화: GPU 추론 비용 / Quantization 효과 / Latency 정보 추가.
    """
    tone = _get_verdict_tone(ctx)
    title_ko = tone.s17_section_label or "도입 정책 · 운영 룰"

    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)

    policy_items: list[tuple[str, str]] = []
    v = (ctx.evaluation.verdict or "").lower()
    if v == "adopt":
        policy_items = [
            ("운영 임계", ctx.evaluation.gate_rationale or f"{pm_value} 기반 임계 설정"),
            ("Inference", "GPU FP16 / INT8 Quantization 적용 시 비용 ↓"),
            ("모니터링", "drift · 메트릭 alarm + 재학습 트리거"),
        ]
    elif v == "iterate":
        policy_items = [
            ("보강 우선순위", "데이터 수집 확대 · 모델 구조 변경 검토"),
            ("재시도 조건", f"{pm_value} 대비 +5%p 이상 향상 시 재평가"),
            ("Owner", "분석팀 — 보강 후 재학습"),
        ]
    elif v == "reject":
        policy_items = [
            ("폐기 사유", ctx.evaluation.gate_rationale or "운영 임계 미달"),
            ("대안 권고", "ML Baseline 유지 또는 문제 재정의"),
            ("Owner", "프로덕트 · 분석팀 공동 재정의"),
        ]
    else:
        policy_items = [
            ("판정 미정", "ctx.evaluation.verdict 적립 시 자동 분기"),
            ("기본 모니터링", "drift · 메트릭 추적"),
            ("재검토", "월간"),
        ]

    body = [f"{k} · {v}" for k, v in policy_items]
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    if biz_kpi:
        body.append(f"비즈니스 KPI · {getattr(biz_kpi, 'name', '')} {getattr(biz_kpi, 'estimated_value', '')} {getattr(biz_kpi, 'unit', '')}")

    so_what = f"{chosen} 정책 — 판정: {ctx.evaluation.verdict or '미정'} + Inference 비용 통제"

    return SlideSpec(
        id="i3_roi",
        section_id="impact",
        layout="one_message",
        role="action",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="v28_policy_insight",
            title=title_ko,
            spec={
                "policy_items": policy_items,
                "verdict": ctx.evaluation.verdict or "",
                "tone_accent": tone.accent,
                "biz_kpi": (
                    {
                        "name": getattr(biz_kpi, "name", ""),
                        "value": getattr(biz_kpi, "estimated_value", ""),
                        "unit": getattr(biz_kpi, "unit", ""),
                    } if biz_kpi else None
                ),
                "dl_inference_hint": "GPU FP16 / INT8 / TorchScript / TensorRT 검토",
            },
        ),
        speaker_notes_hint="verdict 분기 + DL 특화 inference 비용 통제 메시지.",
    )


# ==============================================================
# S18 — SWOT · Drift (ctx 기반)
# ==============================================================


def _build_risk_mitigation_dl(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")

    strengths: list[str] = []
    if ctx.interpretation.global_importance:
        top_feat = ctx.interpretation.global_importance[0].feature
        strengths.append(f"강한 신호 · {top_feat} 등 핵심 변수 식별")
    if pm.get("value") is not None:
        strengths.append(f"임계 통과 · {chosen} {pm_value_str}")
    if ctx.evaluation.calibration:
        strengths.append("Calibration · ECE 적립 완료")
    if not strengths:
        strengths.append("강점 적립 후 채워짐")

    weaknesses: list[str] = []
    for g in (ctx.limitations.data_gaps or [])[:2]:
        desc = getattr(g, "description", "") or "데이터 결함"
        impact = getattr(g, "impact", "") or ""
        weaknesses.append(f"{desc}" + (f" ({impact})" if impact else ""))
    if not weaknesses:
        weaknesses.append("약점 식별 안 됨")

    opportunities: list[str] = []
    rev = ctx.limitations.revalidation_window
    if rev:
        opportunities.append(f"{rev} 후 재검증 + 신규 데이터")
    opportunities.append("Quantization · Pruning · Distillation 으로 비용 ↓")
    opportunities = opportunities[:3]

    threats: list[str] = []
    shift = ctx.limitations.distribution_shift_risk or {}
    if shift.get("detected"):
        ev = shift.get("evidence") or "분포 변화"
        threats.append(f"데이터 드리프트 · {ev}")
    for c in (ctx.limitations.model_caveats or [])[:2]:
        threats.append(f"모델 한계 · {c}")
    if not threats:
        threats.append("위협 추적 중")

    body = [
        f"S · {strengths[0]}",
        f"W · {weaknesses[0]}",
        f"O · {opportunities[0]}",
        f"T · {threats[0]}",
        "Mitigation · drift 모니터링 + Quantization 정기 평가",
    ]

    return SlideSpec(
        id="risk_mitigation",
        section_id="plan",
        layout="swot_2x2",
        role="caveat",
        so_what="SWOT 4분면 — ctx 기반 + DL 특화 (Calibration · Quantization)",
        title_ko="SWOT · Drift",
        body_outline=body[:5],
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="v28_swot_reach",
            title="SWOT · Drift",
            spec={
                "strengths": strengths[:3],
                "weaknesses": weaknesses[:3],
                "opportunities": opportunities[:3],
                "threats": threats[:3],
                "revalidation_window": rev or "",
            },
            severity="important",
        ),
        speaker_notes_hint="DL SWOT — Calibration 강점 + Quantization 기회.",
    )


# ==============================================================
# S19 — Roadmap + MLOps (verdict-aware)
# ==============================================================


def _build_roadmap_mlops(ctx: ReportContext) -> SlideSpec:
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    raw_pattern = tone.s19_phase_pattern or "Phase 1 → Phase 2 → Phase 3"
    phases = [p.strip() for p in raw_pattern.split("→") if p.strip()][:3]

    body: list[str] = []
    for i, phase in enumerate(phases):
        body.append(f"{i+1}. {phase}")

    if verdict == "adopt":
        body.extend([
            "MLOps · TorchServe / Triton 배포",
            "운영 KPI · GPU Latency · ECE · drift score",
        ])
    elif verdict == "iterate":
        body.extend([
            "보강 측정 · 데이터 규모 · cardinality 변화",
            "재평가 · 본 모델 대비 +5%p 향상 시 도입 재고려",
        ])
    else:  # reject
        body.extend([
            "대안 후보 · ML Baseline 유지 또는 새 DL 구조",
            "재학습 금지 · 현 데이터·구조로는 폐기",
        ])

    return SlideSpec(
        id="roadmap",
        section_id="plan",
        layout="roadmap_phase_kpi",
        role="action",
        so_what=f"실행 로드맵 — 판정({verdict}) 별 단계 분기 + MLOps Stack",
        title_ko="실행 로드맵 · MLOps",
        body_outline=body[:5],
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="v28_domain_mapping",
            title="실행 로드맵 · MLOps",
            spec={
                "verdict": verdict,
                "phases": phases,
                "tone_accent": tone.accent,
                "mlops_hint": "TorchServe / Triton / Quantization",
            },
        ),
        speaker_notes_hint="verdict 별 Phase + DL MLOps stack.",
    )


# ==============================================================
# S20 — Closing
# ==============================================================


def _build_closing_qna(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    if verdict == "adopt":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 도입 가능"
    elif verdict == "iterate":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 보강 후 재검토"
    else:
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 현 모델 도입 불가"

    body = [
        f"본 보고서 · {ctx.meta.user_intent or 'Tabular DL 분석'}",
        result_line,
        "Q&A — 데이터 / 모델 / 운영 정책 / Inference 비용",
    ]
    return SlideSpec(
        id="closing",
        section_id="closing",
        layout="closing",
        role="meta",
        so_what=f"본 분석 마무리 — 판정: {verdict}",
        title_ko="감사합니다",
        body_outline=body,
        visual_spec=VisualSpec(
            type="closing_simple",
            title="감사합니다",
            spec={"verdict": verdict, "tone_accent": tone.accent},
        ),
        speaker_notes_hint="Executive Summary 재인용 + Q&A.",
    )


# ==============================================================
# Build
# ==============================================================


def build(
    ctx: ReportContext,
    audience_profile: dict[str, Any],
    length_target: int = 20,
) -> ReportPlan:
    """DL Pitch Skeleton → ReportPlan (20장 고정)."""
    sections: list[SectionSpec] = []
    messages: list[MessageNode] = _build_message_tree(ctx)

    front = make_section(
        "front_matter", "Front Matter", kind="cover", divider=False,
        slides=[build_cover(ctx), _build_exec_summary_dl(ctx)],
    )
    sections.append(front)

    problem_section = make_section(
        "problem", "Section 1 — 문제 정의 & DL 정당성", kind="context", divider=True,
        slides=[
            _build_hypothesis(ctx),  # 4
            _build_why_dl(ctx),  # 5
            _build_pain_points(ctx),  # 6 (Tech Stack)
            _build_ml_baseline_limits(ctx),  # 7 (Method Flow)
        ],
    )
    sections.append(problem_section)

    solution_section = make_section(
        "solution", "Section 2 — DL 솔루션 · EDA", kind="evidence", divider=True,
        slides=[
            _build_architecture_deep(ctx),  # 8
            _build_tech_architecture_combined(ctx),  # 9 (EDA-1)
            _build_differentiation(ctx),  # 10 (EDA-2 or 파생 피처)
        ],
    )
    sections.append(solution_section)

    results_section = make_section(
        "results", "Section 3 — 분석 결과", kind="evidence", divider=True,
        slides=[
            _build_kpi_ml_vs_dl(ctx),  # 11
            _build_training_dynamics(ctx),  # 12
            _build_eda_with_embedding(ctx),  # 13 (IG global)
            _build_error_analysis_calibration(ctx),  # 14 (cases + calibration)
            _build_insights_derived(ctx),  # 15 (Error CM)
        ],
    )
    sections.append(results_section)

    impact_section = make_section(
        "impact", "Section 4 — 임팩트 · 정책", kind="recommendation", divider=True,
        slides=[_build_as_is_to_be(ctx), _build_roi_inference_cost(ctx)],
    )
    sections.append(impact_section)

    plan_section = make_section(
        "plan", "Section 5 — 리스크 & 실행", kind="recommendation", divider=False,
        slides=[_build_risk_mitigation_dl(ctx), _build_roadmap_mlops(ctx)],
    )
    sections.append(plan_section)

    closing_section = make_section(
        "closing", "Closing", kind="closing", divider=False,
        slides=[_build_closing_qna(ctx)],
    )
    sections.append(closing_section)

    sections_titles = [
        "Section 1 — 문제 정의 & DL 정당성",
        "Section 2 — DL 솔루션 · EDA",
        "Section 3 — 분석 결과",
        "Section 4 — 임팩트 · 정책",
        "Section 5 — 리스크 & 실행",
    ]
    agenda = build_agenda(sections_titles)
    sections[0].slides.insert(1, agenda)

    plan = ReportPlan(
        skeleton=SKELETON_NAME,
        audience=ctx.meta.audience or "external_client",
        output_form="pptx",
        slide_count_target=20,
        sections=sections,
        narrative_thread=NarrativeThread(
            setup=(
                f"{ctx.domain.inferred_industry or ctx.meta.category} 산업의 "
                f"{ctx.domain.inferred_use_case or ctx.meta.user_intent or '대상 과제'}"
            ),
            conflict="고차원 categorical · 비선형 상호작용 — ML 한계",
            resolution=(
                f"{(ctx.model_selection.chosen or {}).get('name', 'Tabular DL')} 의 표현학습 + "
                "Quantization 으로 운영 비용 통제"
            ),
        ),
        message_tree=messages,
        meta={"skeleton_variant": "dl_pitch_v2"},
        warnings=[],
    )
    return plan


# ==============================================================
# Message tree (verdict-aware)
# ==============================================================


def _build_message_tree(ctx: ReportContext) -> list[MessageNode]:
    chosen = (ctx.model_selection.chosen or {}).get("name", "Tabular DL")
    pm = ctx.evaluation.primary_metric or {}
    verdict = (ctx.evaluation.verdict or "").lower()
    if verdict == "iterate":
        conclusion = "보강 후 재학습 권장"
    elif verdict == "reject":
        conclusion = "현 모델 도입 불가"
    else:
        conclusion = "운영 도입 권장 + GPU Quantization 으로 비용 통제"
    root_msg = (
        f"{chosen} 로 {pm.get('name', 'primary')} {pm.get('value', '-')} 달성 — {conclusion}"
    )
    return [
        MessageNode(
            id="root",
            role="claim",
            text=root_msg,
            parent_id=None,
            children=["problem_root", "solution_root", "results_root", "impact_root", "plan_root"],
        ),
        MessageNode(id="hyp_root", role="claim", text="DL 적합성 3가설", parent_id="root", slide_ids=["hypothesis"]),
        MessageNode(
            id="problem_root", role="evidence", text="DL 정당성 + 기술 스택 + 분석 방법",
            parent_id="root", slide_ids=["why_dl", "p2_pain", "p3_alt_limits"],
        ),
        MessageNode(
            id="solution_root", role="evidence", text="DL 아키텍처 + EDA",
            parent_id="root", slide_ids=["architecture_deep", "tech_architecture", "s3_differentiation"],
        ),
        MessageNode(
            id="results_root", role="evidence", text="ML 대비 우수 + Training 안정 + Calibration",
            parent_id="root",
            slide_ids=["i1_kpi", "training_dynamics", "eda_findings", "error_analysis", "insights_derived"],
        ),
        MessageNode(
            id="impact_root", role="claim", text="비즈니스 효과 + Inference 비용",
            parent_id="root", slide_ids=["as_is_to_be", "i3_roi"],
        ),
        MessageNode(
            id="plan_root", role="action", text="단계별 실행 + MLOps Stack",
            parent_id="root", slide_ids=["risk_mitigation", "roadmap"],
        ),
    ]

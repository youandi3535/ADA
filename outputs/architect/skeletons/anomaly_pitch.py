"""outputs.architect.skeletons.anomaly_pitch — Anomaly Pitch Skeleton (재구성).

이상탐지 (anomaly_detection) 카테고리 전용 분석 보고서 deck.
20장 골격 유지 + ml/dl/ts_pitch 와 동일 패턴 (ctx 기반 동적 채움 + verdict 분기) +
이상탐지 특화 슬라이드 (Why Anomaly · Score Distribution · Reason Code ·
PR@k + Alarm Budget · Policy Threshold) 유지.

20 슬라이드 구조 (확정):
    1.  Cover                                cover
    2.  목차 (Agenda)                        agenda
    3.  Executive Summary                    exec_summary           ← verdict-aware
    4.  분석 가설                            hypothesis
    5.  Why Anomaly Detection?               why_anomaly            ★ 지도/비지도 판단 (ctx 기반)
    6.  기술 스택 (Anomaly 프리셋)           p2_pain                ← manifest anomaly_detection
    7.  분석 방법                            p3_alt_limits          ← method_flow (공통)
    8.  모델 아키텍처 Deep Dive              architecture_deep      ★ IF/LOF/AE (ctx 기반)
    9.  EDA · 정상 vs 이상 분포              tech_architecture      ← EDA-1
    10. EDA · 변수 상관 / 파생 피처          s3_differentiation     ← EDA-2 (또는 파생 피처)
    11. 탐지 성능 + Baseline                 i1_kpi                 ← model_perf (precision@k/PR-AUC)
    12. Anomaly Score Distribution           score_distribution     ★ 점수 분포 + 임계값
    13. Reason Code · 상위 5 Feature         eda_findings           ← shap_global 카테고리 변형
    14. 이상 사례 3건 · Reason Code 별       error_analysis         ← shap_cases 카테고리 변형
    15. precision@k · 알람 Budget 곡선       insights_derived       ← error_cm 카테고리 변형
    16. 정상 / 이상 클러스터 비교            as_is_to_be            ← segment 카테고리 변형
    17. 임계값 · 알람 Budget · 운영 시나리오 i3_roi                 ← policy_insight + verdict
    18. SWOT · Drift                         risk_mitigation        ← swot (ctx 기반)
    19. Roadmap + Alert Pipeline             roadmap                ← verdict-aware Phase
    20. 감사합니다 + Q&A                     closing                ← verdict-aware

설계 원칙:
    - 모든 builder 가 ctx 에서 동적 채움 — 도메인 하드코딩 X
    - verdict (adopt/iterate/reject) 에 따라 S3/S17/S19/S20 어조 자동 분기
    - skeleton_helpers 의 공통 빌더 (EDA / 파생 피처 / method flow) 재사용
    - 이상탐지 카테고리 톤은 본 파일 내부에서만 차별화 (Score Dist · PR@k · Alarm Budget 등)

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

SKELETON_NAME = "Anomaly Pitch"


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


def _anomaly_ratio(ctx: ReportContext) -> Optional[float]:
    """ctx 에서 이상 비율 (0~1) 추출. 추정 불가 시 None."""
    target = ctx.dataset.detected_target
    if not target:
        return None
    cat_top = (ctx.dataset.categorical_top or {}).get(target, [])
    if not cat_top:
        return None
    counts: list[int] = []
    for it in cat_top:
        if isinstance(it, dict):
            try:
                counts.append(int(it.get("count", it.get("freq", 0)) or 0))
            except (TypeError, ValueError):
                continue
    if len(counts) < 2 or sum(counts) <= 0:
        return None
    total = sum(counts)
    minority = min(counts)
    return minority / total


# ==============================================================
# S1 / S2 — Cover / Agenda
# ==============================================================


def build_cover(ctx: ReportContext) -> SlideSpec:
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "이상 탐지 분석 보고서").strip()
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
        so_what="본 보고서는 5개 섹션 — 이상탐지 정당성 · 솔루션 · 결과 · 임팩트 · 실행 순.",
        title_ko="목차",
        body_outline=sections_titles,
        speaker_notes_hint="섹션 흐름 안내.",
    )


# ==============================================================
# S3 — Executive Summary (verdict-aware)
# ==============================================================


def _build_top_findings_from_ctx(ctx: ReportContext) -> list[dict[str, Any]]:
    """S3 상단 3 KEY FINDINGS — interpretation.global_importance Top 3 (Reason Code)."""
    importance_list = list(ctx.interpretation.global_importance or [])[:3]
    findings: list[dict[str, Any]] = []
    for i, item in enumerate(importance_list):
        feature = getattr(item, "feature", "") or f"Feature {i+1}"
        value = getattr(item, "importance", None) or 0.0
        story = ctx.interpretation.per_feature_story.get(feature, "")
        findings.append({
            "label": f"REASON {i+1:02d}",
            "feature": feature,
            "big": format_metric(float(value), "shap", as_percent=False, decimals=2),
            "sub": _auto_label(story, ctx) if story else feature,
        })
    while len(findings) < 3:
        findings.append({
            "label": f"REASON {len(findings)+1:02d}",
            "feature": "",
            "big": "-",
            "sub": "분석 결과 적립 후 채워짐",
        })
    return findings


def _build_method_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")
    n_candidates = len(ctx.model_selection.candidates or [])
    ratio = _anomaly_ratio(ctx)
    ratio_str = f"이상 비율 {ratio*100:.2f}%" if ratio is not None else "비지도 (라벨 부족)"
    return [
        ("모델 선정", f"{chosen} — 후보 {n_candidates}개 비교" if n_candidates else f"{chosen} 선정"),
        ("학습 모드", ratio_str),
        ("임계값", "비용 비대칭 + 알람 Budget 기반 자동 조정"),
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
            baseline_str = f"룰 {baseline_str} 대비 {pm_str}"
        else:
            baseline_str = "Baseline 비교 완료"
    else:
        baseline_str = "Baseline 미설정"

    n_metrics = len(ctx.evaluation.metrics or {})
    balance = f"{n_metrics}-metric (PR@k · Recall@k · PR-AUC)" if n_metrics >= 2 else "단일 metric 평가"

    return [
        ("운영 임계", rationale),
        ("Baseline 대비", baseline_str),
        ("균형 · 알람 Budget", balance),
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


def _build_exec_summary_anomaly(ctx: ReportContext) -> SlideSpec:
    """슬라이드 3 — Executive Summary (Anomaly, verdict-aware)."""
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")
    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "이상 탐지 과제"
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
        f"Reason 1 · {findings[0]['feature']} {findings[0]['big']}",
        f"Reason 2 · {findings[1]['feature']} {findings[1]['big']}",
        f"Reason 3 · {findings[2]['feature']} {findings[2]['big']}",
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
            "1장만 봐도 의사결정 가능. 상단 3 REASON CODE = SHAP / score contribution 으로 알아낸 것, "
            "하단 METHOD / PERFORMANCE / LIMITATION 의 Baseline 대비 우위 + 알람 Budget."
        ),
    )


# ==============================================================
# S4 — Hypothesis
# ==============================================================


def _build_hypothesis(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")
    intent = ctx.meta.user_intent or "분석 과제"
    body = [
        "H1 · 라벨 부족 · 이상 비율 < 5% — Supervised 한계, 비지도/반지도 적합",
        f"H2 · 모델 적합성 · {chosen} 가 룰 Baseline 대비 {pm.get('name', '지표')} 향상",
        "H3 · 운영 임계값 · FP/FN 비용 비대칭 + 알람 Budget 기반 자동 조정",
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
# S5 — Why Anomaly Detection? (지도/비지도 판단, ctx 기반)
# ==============================================================


def _build_why_anomaly(ctx: ReportContext) -> SlideSpec:
    """슬라이드 5 — Why Anomaly Detection? (지도/비지도 판단 근거, ctx 기반).

    이상 비율 + 라벨 가용성 + class imbalance 로 비지도 학습 정당성 명시.
    ctx.dataset.categorical_top / detected_target 에서 객관 증거 추출.
    """
    ratio = _anomaly_ratio(ctx)
    target = ctx.dataset.detected_target

    why_items: list[tuple[str, str]] = []
    if ratio is not None:
        ratio_pct = ratio * 100
        if ratio_pct < 1.0:
            why_items.append((f"이상 비율 {ratio_pct:.2f}%", "극심한 imbalance — Supervised 학습 어려움"))
        elif ratio_pct < 5.0:
            why_items.append((f"이상 비율 {ratio_pct:.2f}%", "imbalance — 비지도 + 임계값 조정 적합"))
        else:
            why_items.append((f"이상 비율 {ratio_pct:.1f}%", "라벨 활용 가능 — 반지도/지도 혼합 고려"))
    else:
        why_items.append(("라벨 부족", "이상 비율 추정 불가 — 비지도 학습 디폴트"))

    # 분포 학습 정당성
    n_features = len(ctx.dataset.dtypes or {})
    if n_features:
        why_items.append(("다변량 정상 패턴", f"{n_features}개 피처 — 단일 임계값 불가능"))
    else:
        why_items.append(("다변량 정상 패턴", "분포 학습으로 신규 이상 자동 감지"))

    # 운영 임계값
    why_items.append(("운영 임계값", "FP/FN 비용 비대칭 + 알람 Budget 기반 자동 조정"))

    # 타겟 정보
    if target:
        why_items.append((f"타겟 · {target}", "이상 라벨 컬럼 확보 — PR@k 평가 가능"))

    body = [f"{k} · {v}" for k, v in why_items[:5]]
    return SlideSpec(
        id="why_anomaly",
        section_id="problem",
        layout="why_anomaly_3_pillars",
        role="claim",
        so_what="이상탐지 정당성 — 라벨 부족 · 다변량 정상 패턴 · 임계값 비용 3축",
        title_ko="Why Anomaly Detection?",
        body_outline=body,
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="custom",
            title="Why Anomaly Detection",
            spec={
                "why_items": why_items[:5],
                "anomaly_ratio": ratio,
                "target": target or "",
            },
        ),
        speaker_notes_hint="이상탐지 도입의 *데이터적 근거* — 비율 + 다변량 + 운영 임계.",
    )


# ==============================================================
# S6 — Tech Stack (Anomaly 프리셋)
# ==============================================================


def _build_pain_points(ctx: ReportContext) -> SlideSpec:
    """슬라이드 6 — 기술 스택 (Anomaly 프리셋, manifest 기반)."""
    category = ctx.meta.category or "anomaly_detection"
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
    runtime = f"Python {py_ver}"

    return SlideSpec(
        id="p2_pain",
        section_id="problem",
        layout="tech_stack_grid",
        role="evidence",
        so_what=(
            f"본 분석은 {category} 표준 스택 ({len(stack_items)}개 도구) 으로 재현 가능 — {runtime}"
        ),
        title_ko="기술 스택",
        body_outline=body,
        parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_tech_stack",
            title="기술 스택",
            spec={"stack_items": stack_items, "category": category, "python_version": py_ver},
        ),
        speaker_notes_hint=(
            "이상탐지 표준 스택 (scikit-learn · IsolationForest/LOF · AutoEncoder · ThresholdTuner)."
        ),
    )


# ==============================================================
# S7 — 분석 방법 (Method Flow + WHY 패널, 공통)
# ==============================================================


def _build_method_flow(ctx: ReportContext) -> SlideSpec:
    """슬라이드 7 — 분석 방법 흐름 + WHY 패널 (Option C)."""
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
# S8 — Architecture Deep Dive (IF/LOF/AE, ctx 기반)
# ==============================================================


def _build_architecture_deep(ctx: ReportContext) -> SlideSpec:
    """슬라이드 8 — 모델 아키텍처 Deep Dive (ctx 기반).

    ctx.training.runs[0] 의 hyperparameters / resource 에서 구조·파라미터 추출.
    IsolationForest / LOF / AutoEncoder 등의 핵심 파라미터 표시.
    """
    chosen = ctx.model_selection.chosen or {}
    chosen_name = chosen.get("name", "Anomaly Detector")
    chosen_family = chosen.get("family", "Anomaly")

    arch_items: list[tuple[str, str]] = [("모델", f"{chosen_name} ({chosen_family})")]

    if ctx.training.runs:
        run = ctx.training.runs[0]
        hp = getattr(run, "hyperparameters", {}) or {}
        resource = getattr(run, "resource", {}) or {}

        # IsolationForest 핵심 파라미터
        if "n_estimators" in hp:
            arch_items.append(("Trees", f"{hp['n_estimators']}개"))
        if "max_samples" in hp:
            arch_items.append(("Max Samples", f"{hp['max_samples']}"))
        if "contamination" in hp:
            arch_items.append(("Contamination", f"{hp['contamination']}"))
        # LOF 핵심 파라미터
        if "n_neighbors" in hp:
            arch_items.append(("k-Neighbors", f"{hp['n_neighbors']}"))
        # AutoEncoder 핵심 파라미터
        if "hidden_dim" in hp or "latent_dim" in hp:
            dim = hp.get("hidden_dim", hp.get("latent_dim"))
            arch_items.append(("Hidden / Latent Dim", f"{dim}"))
        if "n_layers" in hp:
            arch_items.append(("레이어", f"{hp['n_layers']}층"))
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
        so_what=f"{chosen_name} 모델 구조 — 이상탐지 메커니즘과 파라미터 분포",
        title_ko="모델 아키텍처 · Deep Dive",
        body_outline=body[:5],
        parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type="architecture_diagram",
            title=f"{chosen_name} 구조",
            spec={"arch_items": arch_items, "model_name": chosen_name, "family": chosen_family},
        ),
        speaker_notes_hint=(
            "이상탐지 모델의 *구조* 명시 — IF Trees / LOF k / AE Latent. "
            "ctx.training.runs[0].hyperparameters 에서 자동 추출."
        ),
    )


# ==============================================================
# S9 / S10 — EDA 1·2 (또는 파생 피처)
# ==============================================================


def _build_tech_architecture_combined(ctx: ReportContext) -> SlideSpec:
    """슬라이드 9 — EDA · 정상 vs 이상 분포 (ctx.eda.charts Top 1)."""
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
# S11 — Model Performance + Baseline (precision@k / recall@k / PR-AUC)
# ==============================================================


def _build_kpi_baseline(ctx: ReportContext) -> SlideSpec:
    """슬라이드 11 — 탐지 성능 + Baseline (precision@k / recall@k / PR-AUC).

    라벨 있을 때: precision@k / recall@k / PR-AUC.
    라벨 없을 때: 도메인 검증 (분포 분리도, score 분산 등).
    """
    pm = ctx.evaluation.primary_metric or {}
    pm_name = pm.get("name", "primary")
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")
    category = ctx.meta.category or "anomaly_detection"

    metric_ok = is_metric_compatible(category, pm_name)
    has_labels = ctx.dataset.detected_target is not None

    baselines = ctx.model_selection.baselines
    bars: list[dict[str, Any]] = []
    if baselines.naive:
        b = baselines.naive
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "룰 (Z-score)"), "value": v, "color": "muted"})
    if baselines.domain_rule:
        b = baselines.domain_rule
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "도메인 룰"), "value": v, "color": "muted"})
    if baselines.previous_best:
        b = baselines.previous_best
        v = b.get("score")
        if v is not None:
            bars.append({"label": b.get("name", "이전 최고"), "value": v, "color": "muted"})
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
        body.append("균형 · " + " · ".join(metric_lines))
    if not has_labels:
        body.append("라벨 부족 — 도메인 검증 / 분포 분리도로 보조 평가")

    tone = _get_verdict_tone(ctx)
    so_what = f"{chosen} 성능: {pm_name} {pm_value_str} ({tone.accent})"

    return SlideSpec(
        id="i1_kpi",
        section_id="results",
        layout="model_perf_baseline_grouped",
        role="evidence",
        so_what=so_what,
        title_ko="탐지 성능 · Baseline 비교",
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
                "has_labels": has_labels,
                "verdict": ctx.evaluation.verdict or "",
            },
        ),
        speaker_notes_hint=(
            "라벨 있으면 PR@k / Recall@k / PR-AUC. 없으면 도메인 검증 + 분포 분리도."
        ),
    )


# ==============================================================
# S12 — Anomaly Score Distribution (이상탐지 특화)
# ==============================================================


def _build_score_distribution(ctx: ReportContext) -> SlideSpec:
    """슬라이드 12 — Anomaly Score Distribution + 임계값 후보.

    ctx.evaluation.calibration 의 score 히스토그램 + 임계값 후보 시각화.
    """
    body: list[str] = []
    spec: dict[str, Any] = {}

    calib = ctx.evaluation.calibration or {}
    if isinstance(calib, dict) and calib:
        spec["calibration"] = calib
        normal_peak = calib.get("normal_peak")
        anomaly_peak = calib.get("anomaly_peak")
        bhatt = calib.get("bhattacharyya")
        thresholds = calib.get("thresholds")

        if normal_peak is not None and anomaly_peak is not None:
            body.append(f"정상 평균 score {normal_peak:.2f} · 이상 평균 score {anomaly_peak:.2f}")
        if bhatt is not None:
            body.append(f"Bhattacharyya 거리 {bhatt:.2f} — 분포 분리도 (높을수록 좋음)")
        if isinstance(thresholds, dict) and thresholds:
            t_str = " · ".join(f"{k} {v}" for k, v in list(thresholds.items())[:3])
            body.append(f"임계값 후보 · {t_str}")
            spec["thresholds"] = thresholds

    # 알람 budget
    pm = ctx.evaluation.primary_metric or {}
    pm_value = pm.get("value")
    if pm_value is not None:
        body.append(f"운영 성능 · {pm.get('name', 'primary')} {_format_pm_value(pm)}")

    if not body:
        body = ["Score Distribution 미적립 — ctx.evaluation.calibration 채워지면 자동 반영"]

    return SlideSpec(
        id="score_distribution",
        section_id="results",
        layout="score_distribution",
        role="evidence",
        so_what="정상 vs 이상 score 분포 분리도 — 운영 임계값 자동 결정 가능",
        title_ko="Anomaly Score Distribution",
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="chart_score_distribution",
            title="Score Distribution — 정상 vs 이상",
            spec=spec,
            severity="important",
        ),
        speaker_notes_hint=(
            "★ 이상탐지 핵심 시각화 — 분포 분리도가 모델 품질의 직관적 지표."
        ),
    )


# ==============================================================
# S13 — Reason Code (SHAP global 카테고리 변형)
# ==============================================================


def _build_reason_code(ctx: ReportContext) -> SlideSpec:
    """슬라이드 13 — Reason Code · 상위 5 Feature (Anomaly 변형).

    Top 5 importance 항목에 (파생) / (원본) 라벨 부착.
    """
    category = ctx.meta.category or "anomaly_detection"
    variant = resolve_slide("shap_global", category)
    title_ko = (variant.title_ko if variant else "Reason Code · 상위 5 Feature")

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
            "method": getattr(it, "method", "shap"),
            "kind": "derived" if is_derived else "original",
        })
        rid = getattr(it, "ref_id", None)
        if rid:
            refs.append(rid)

    body = [
        f"{i+1}순위 · {it['feature']} ({'파생' if it['kind'] == 'derived' else '원본'}) · "
        f"{format_metric(float(it['importance']), 'shap', as_percent=False, decimals=2)}"
        for i, it in enumerate(items)
    ]
    if not body:
        body = ["분석 결과 적립 후 채워짐"]

    so_what = "상위 5 Reason Code — 이상 결정의 근거 피처"
    if items:
        total = sum(float(it["importance"]) for it in items)
        top3 = sum(float(it["importance"]) for it in items[:3])
        if total > 0:
            ratio = top3 / total * 100
            so_what = (
                f"상위 3 Reason Code 가 이상 결정의 {ratio:.0f}% — "
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
            spec={"items": items, "method": "reason_code"},
            severity="important",
        ),
        speaker_notes_hint="이상탐지 의 Reason Code — Top 5 만 보여줌. 도메인 룰 backup 가능.",
    )


# ==============================================================
# S14 — 이상 사례 3건 (SHAP cases 카테고리 변형)
# ==============================================================


def _build_anomaly_cases(ctx: ReportContext) -> SlideSpec:
    """슬라이드 14 — 이상 사례 3건 · Reason Code 별 (Anomaly 변형).

    ctx.interpretation.local_examples 3건 + 각 사례의 reason code.
    """
    category = ctx.meta.category or "anomaly_detection"
    variant = resolve_slide("shap_cases", category)
    title_ko = (variant.title_ko if variant else "이상 사례 3건 · Reason Code 별")

    locals_ = list(ctx.interpretation.local_examples or [])[:3]
    cases: list[dict[str, Any]] = []
    body: list[str] = []
    for i, ex in enumerate(locals_):
        if not isinstance(ex, dict):
            continue
        score = ex.get("anomaly_score") or ex.get("prediction", "-")
        true = ex.get("true", "-")
        contributions = ex.get("contributions", [])
        top_feats = ", ".join(
            f"{c.get('feature', '')}({c.get('value', '')})"
            for c in (contributions[:3] if isinstance(contributions, list) else [])
        )
        cases.append({
            "index": i + 1,
            "anomaly_score": score,
            "true": true,
            "top_contributions": contributions[:3] if isinstance(contributions, list) else [],
        })
        body.append(f"사례 {i+1} · score {score} / 실제 {true} · {top_feats}")
    while len(body) < 3:
        body.append(f"사례 {len(body)+1} · ctx 적립 후 채워짐")

    return SlideSpec(
        id="error_analysis",
        section_id="results",
        layout=(variant.layout if variant else "one_message"),
        role="evidence",
        so_what="이상 사례 3건 — 각 사례의 *왜 이상인가* Reason Code 추적",
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="anomaly_cases_with_reason",
            title=title_ko,
            spec={"cases": cases},
        ),
        speaker_notes_hint="이상탐지 의 사례 분석 — 각 케이스의 Reason Code 별 trace.",
    )


# ==============================================================
# S15 — precision@k 곡선 · 알람 Budget (Error CM 카테고리 변형)
# ==============================================================


def _build_pk_alarm_curve(ctx: ReportContext) -> SlideSpec:
    """슬라이드 15 — precision@k 곡선 + 알람 Budget 곡선 (Anomaly 변형)."""
    category = ctx.meta.category or "anomaly_detection"
    variant = resolve_slide("error_cm", category)
    title_ko = (variant.title_ko if variant else "precision@k 곡선 · 알람 Budget 곡선")

    body: list[str] = []
    spec: dict[str, Any] = {}

    # PR@k 시리즈는 metrics 안에 들어올 수도 있음
    metrics = ctx.evaluation.metrics or {}
    for name, m in metrics.items():
        if not isinstance(m, dict):
            continue
        n_low = name.lower()
        if "precision_at_k" in n_low or "pr@k" in n_low or "pk_curve" in n_low:
            series = m.get("series") or m.get("curve")
            if series:
                spec["pk_curve"] = series
                body.append("precision@k 곡선 적립 완료 — k 별 정밀도 추세")
        if "alarm_budget" in n_low or "budget" in n_low:
            series = m.get("series") or m.get("curve")
            if series:
                spec["alarm_budget_curve"] = series
                body.append("알람 Budget 곡선 적립 완료 — 임계값 별 알람 수 추세")

    # Confusion matrix 도 보조로 사용 (라벨 있을 때)
    cm = ctx.evaluation.confusion_matrix or {}
    if cm:
        spec["confusion_matrix"] = cm
        tp = cm.get("tp") or cm.get("true_positive") or 0
        fp = cm.get("fp") or cm.get("false_positive") or 0
        fn = cm.get("fn") or cm.get("false_negative") or 0
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        body.append(f"Precision {precision:.2f} · Recall {recall:.2f}")
        if fp > fn:
            body.append("오탐(FP) > 미탐(FN) — 알람 Budget 압박, 임계값 ↑")
        elif fn > fp:
            body.append("미탐(FN) > 오탐(FP) — Recall 우선, 임계값 ↓")

    if not body:
        body = ["precision@k / 알람 Budget 곡선 미적립"]

    return SlideSpec(
        id="insights_derived",
        section_id="results",
        layout=(variant.layout if variant else "chart_callout"),
        role="caveat",
        so_what="precision@k + 알람 Budget — 운영 임계값과 알람 부하 trade-off",
        title_ko=title_ko,
        body_outline=body[:5],
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_pk_alarm_budget"),
            title=title_ko,
            spec=spec,
            severity="important",
        ),
        speaker_notes_hint="precision@k 곡선 + 알람 Budget 곡선 = 운영 임계값 결정의 양 축.",
    )


# ==============================================================
# S16 — 정상 / 이상 클러스터 비교 (Segment 카테고리 변형)
# ==============================================================


def _build_cluster_compare(ctx: ReportContext) -> SlideSpec:
    """슬라이드 16 — 정상 vs 이상 클러스터 비교."""
    category = ctx.meta.category or "anomaly_detection"
    variant = resolve_slide("segment", category)
    title_ko = (variant.title_ko if variant else "정상 / 이상 클러스터 비교")

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
        body = ["클러스터 비교 미적립 — ctx.evaluation.per_segment 채워지면 자동 반영"]

    so_what = "정상 vs 이상 클러스터 — 분포 분리 + 세그먼트별 일관성"
    if len(seg_items) >= 2:
        vals = [float(s["value"]) for s in seg_items]
        gap = max(vals) - min(vals)
        if gap > 0.1:
            so_what = f"클러스터 격차 {gap:.2f} — 일부 세그먼트 임계값 재조정 필요"

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
            type="cluster_compare_table",
            title=title_ko,
            spec={"segments": seg_items},
        ),
        speaker_notes_hint="정상/이상 클러스터의 분리도 + 세그먼트별 일관성.",
    )


# ==============================================================
# S17 — Policy · 임계값 · 알람 Budget (verdict-aware + 이상탐지 특화)
# ==============================================================


def _build_policy_threshold(ctx: ReportContext) -> SlideSpec:
    """슬라이드 17 — 임계값 · 알람 Budget · 운영 시나리오 (verdict-aware).

    이상탐지 특화: 임계값 후보 + 알람 Budget + FP/FN 비용 비대칭.
    """
    tone = _get_verdict_tone(ctx)
    title_ko = tone.s17_section_label or "임계값 · 알람 Budget · 운영 시나리오"

    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)

    policy_items: list[tuple[str, str]] = []
    v = (ctx.evaluation.verdict or "").lower()
    if v == "adopt":
        policy_items = [
            ("운영 임계값", ctx.evaluation.gate_rationale or "비용 최적 + 알람 Budget 기반"),
            ("알람 Pipeline", "실시간 score → Tier 별 자동/수동 처리"),
            ("모니터링", "drift · 분포 shift · PR@k 정기 재평가"),
        ]
    elif v == "iterate":
        policy_items = [
            ("보강 우선순위", "이상 라벨 수집 확대 · 신규 피처 추가 검토"),
            ("재시도 조건", f"{pm_value} 대비 +5%p 이상 향상 시 재평가"),
            ("Owner", "분석팀 — 보강 후 재학습"),
        ]
    elif v == "reject":
        policy_items = [
            ("폐기 사유", ctx.evaluation.gate_rationale or "운영 임계 미달"),
            ("대안 권고", "룰 Baseline 유지 또는 다른 모델 family 탐색"),
            ("Owner", "프로덕트 · 분석팀 공동 재정의"),
        ]
    else:
        policy_items = [
            ("판정 미정", "ctx.evaluation.verdict 적립 시 자동 분기"),
            ("기본 모니터링", "drift · score 분포 추적"),
            ("재검토", "월간"),
        ]

    # 임계값 후보 (calibration 에서 가져옴)
    calib = ctx.evaluation.calibration or {}
    thresholds = calib.get("thresholds") if isinstance(calib, dict) else None
    if isinstance(thresholds, dict) and thresholds:
        t_str = " · ".join(f"{k} {v}" for k, v in list(thresholds.items())[:3])
        policy_items.append(("임계값 후보", t_str))

    body = [f"{k} · {v}" for k, v in policy_items[:5]]
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    if biz_kpi:
        body.append(
            f"비즈니스 KPI · {getattr(biz_kpi, 'name', '')} "
            f"{getattr(biz_kpi, 'estimated_value', '')} {getattr(biz_kpi, 'unit', '')}"
        )

    so_what = f"{chosen} 운영 정책 — 판정: {ctx.evaluation.verdict or '미정'} + 임계값/알람 Budget"

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
                "thresholds": thresholds if isinstance(thresholds, dict) else None,
                "anomaly_policy_hint": "임계값 · 알람 Budget · FP/FN 비용 비대칭",
            },
        ),
        speaker_notes_hint="verdict 분기 + 이상탐지 특화 임계값 · 알람 Budget 메시지.",
    )


# ==============================================================
# S18 — SWOT · Drift (ctx 기반)
# ==============================================================


def _build_risk_mitigation_anomaly(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")

    strengths: list[str] = []
    if ctx.interpretation.global_importance:
        top_feat = ctx.interpretation.global_importance[0].feature
        strengths.append(f"강한 신호 · {top_feat} 등 Reason Code 식별")
    if pm.get("value") is not None:
        strengths.append(f"임계 통과 · {chosen} {pm_value_str}")
    if ctx.evaluation.calibration:
        strengths.append("Score 분포 분리도 적립 완료")
    if not strengths:
        strengths.append("강점 적립 후 채워짐")

    weaknesses: list[str] = []
    ratio = _anomaly_ratio(ctx)
    if ratio is not None and ratio < 0.01:
        weaknesses.append(f"극심 imbalance · 이상 비율 {ratio*100:.2f}% — PR 평가 어려움")
    for g in (ctx.limitations.data_gaps or [])[:2]:
        desc = getattr(g, "description", "") or "데이터 결함"
        impact = getattr(g, "impact", "") or ""
        weaknesses.append(f"{desc}" + (f" ({impact})" if impact else ""))
    if not weaknesses:
        weaknesses.append("약점 식별 안 됨")

    opportunities: list[str] = []
    rev = ctx.limitations.revalidation_window
    if rev:
        opportunities.append(f"{rev} 후 재검증 + 신규 라벨")
    opportunities.append("Active Learning · 검토 결과 피드백 학습")
    opportunities.append("Ensemble (IF + LOF + AE) · Multi-method agreement")
    opportunities = opportunities[:3]

    threats: list[str] = []
    shift = ctx.limitations.distribution_shift_risk or {}
    if shift.get("detected"):
        ev = shift.get("evidence") or "분포 변화"
        threats.append(f"Concept Drift · {ev}")
    threats.append("Alert fatigue · 임계값 낮으면 검토 부하 폭주")
    threats.append("Adversarial · 공격자가 정상처럼 위장")
    for c in (ctx.limitations.model_caveats or [])[:1]:
        threats.append(f"모델 한계 · {c}")
    threats = threats[:3]
    if not threats:
        threats.append("위협 추적 중")

    body = [
        f"S · {strengths[0]}",
        f"W · {weaknesses[0]}",
        f"O · {opportunities[0]}",
        f"T · {threats[0]}",
        "Mitigation · drift 모니터링 + Ensemble 다층 방어 + 주간 분포 점검",
    ]

    return SlideSpec(
        id="risk_mitigation",
        section_id="plan",
        layout="swot_2x2",
        role="caveat",
        so_what="SWOT 4분면 — ctx 기반 + 이상탐지 특화 (Drift · Alert fatigue · Adversarial)",
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
        speaker_notes_hint="이상탐지 SWOT — Drift / Alert fatigue / Adversarial 위협 명시.",
    )


# ==============================================================
# S19 — Roadmap + Alert Pipeline (verdict-aware)
# ==============================================================


def _build_roadmap_alert(ctx: ReportContext) -> SlideSpec:
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    raw_pattern = tone.s19_phase_pattern or "Phase 1 → Phase 2 → Phase 3"
    phases = [p.strip() for p in raw_pattern.split("→") if p.strip()][:3]

    body: list[str] = []
    for i, phase in enumerate(phases):
        body.append(f"{i+1}. {phase}")

    if verdict == "adopt":
        body.extend([
            "Alert Pipeline · 실시간 score → Tier 별 자동/수동 처리",
            "운영 KPI · PR@k · 알람 Budget · drift score",
        ])
    elif verdict == "iterate":
        body.extend([
            "보강 측정 · 이상 라벨 수집 · 신규 피처 추가",
            "재평가 · 본 모델 대비 +5%p 향상 시 도입 재고려",
        ])
    else:  # reject
        body.extend([
            "대안 후보 · 룰 Baseline 유지 또는 새 모델 family",
            "재학습 금지 · 현 데이터·구조로는 폐기",
        ])

    return SlideSpec(
        id="roadmap",
        section_id="plan",
        layout="roadmap_phase_kpi",
        role="action",
        so_what=f"실행 로드맵 — 판정({verdict}) 별 단계 분기 + Alert Pipeline",
        title_ko="실행 로드맵 · Alert Pipeline",
        body_outline=body[:5],
        parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="v28_domain_mapping",
            title="실행 로드맵 · Alert Pipeline",
            spec={
                "verdict": verdict,
                "phases": phases,
                "tone_accent": tone.accent,
                "alert_pipeline_hint": "실시간 score · 일/주/월 cadence · Multi-tier alert",
            },
        ),
        speaker_notes_hint="verdict 별 Phase + 이상탐지 Alert Pipeline 다층 cadence.",
    )


# ==============================================================
# S20 — Closing
# ==============================================================


def _build_closing_qna(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    if verdict == "adopt":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 도입 가능"
    elif verdict == "iterate":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 보강 후 재검토"
    else:
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 현 모델 도입 불가"

    body = [
        f"본 보고서 · {ctx.meta.user_intent or '이상 탐지 분석'}",
        result_line,
        "Q&A — 데이터 / 모델 / 임계값 / Alert Pipeline / Drift",
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
    """Anomaly Pitch Skeleton → ReportPlan (20장 고정)."""
    sections: list[SectionSpec] = []
    messages: list[MessageNode] = _build_message_tree(ctx)

    front = make_section(
        "front_matter", "Front Matter", kind="cover", divider=False,
        slides=[build_cover(ctx), _build_exec_summary_anomaly(ctx)],
    )
    sections.append(front)

    problem_section = make_section(
        "problem", "Section 1 - Problem", kind="context", divider=True,
        slides=[
            _build_hypothesis(ctx),
            _build_why_anomaly(ctx),
            _build_pain_points(ctx),
            _build_method_flow(ctx),
        ],
    )
    sections.append(problem_section)

    solution_section = make_section(
        "solution", "Section 2 - Solution", kind="evidence", divider=True,
        slides=[
            _build_architecture_deep(ctx),
            _build_tech_architecture_combined(ctx),
            _build_differentiation(ctx),
        ],
    )
    sections.append(solution_section)

    results_section = make_section(
        "results", "Section 3 - Results", kind="evidence", divider=True,
        slides=[
            _build_kpi_baseline(ctx),
            _build_score_distribution(ctx),
            _build_reason_code(ctx),
            _build_anomaly_cases(ctx),
            _build_pk_alarm_curve(ctx),
        ],
    )
    sections.append(results_section)

    impact_section = make_section(
        "impact", "Section 4 - Impact", kind="recommendation", divider=True,
        slides=[_build_cluster_compare(ctx), _build_policy_threshold(ctx)],
    )
    sections.append(impact_section)

    plan_section = make_section(
        "plan", "Section 5 - Plan", kind="recommendation", divider=False,
        slides=[_build_risk_mitigation_anomaly(ctx), _build_roadmap_alert(ctx)],
    )
    sections.append(plan_section)

    closing_section = make_section(
        "closing", "Closing", kind="closing", divider=False,
        slides=[_build_closing_qna(ctx)],
    )
    sections.append(closing_section)

    sections_titles = [
        "Section 1 - 문제 정의 & 이상탐지 정당성",
        "Section 2 - 이상탐지 솔루션 · EDA",
        "Section 3 - 분석 결과",
        "Section 4 - 임팩트 · 정책",
        "Section 5 - 리스크 & 실행",
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
                f"{ctx.domain.inferred_use_case or ctx.meta.user_intent or '이상 탐지 과제'}"
            ),
            conflict="라벨 부족 · 다변량 정상 패턴 · 임계값 비용 비대칭",
            resolution=(
                f"{(ctx.model_selection.chosen or {}).get('name', 'Anomaly Detector')} 의 분포 학습 + "
                "Threshold/Budget 운영 정책 + Reason Code"
            ),
        ),
        message_tree=messages,
        meta={"skeleton_variant": "anomaly_pitch_v2"},
        warnings=[],
    )
    return plan


# ==============================================================
# Message tree (verdict-aware)
# ==============================================================


def _build_message_tree(ctx: ReportContext) -> list[MessageNode]:
    chosen = (ctx.model_selection.chosen or {}).get("name", "Anomaly Detector")
    pm = ctx.evaluation.primary_metric or {}
    verdict = (ctx.evaluation.verdict or "").lower()
    if verdict == "iterate":
        conclusion = "보강 후 재학습 권장"
    elif verdict == "reject":
        conclusion = "현 모델 도입 불가"
    else:
        conclusion = "운영 도입 권장 + Alert Pipeline + Drift 모니터링"
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
        MessageNode(id="hyp_root", role="claim", text="이상탐지 적합성 3가설", parent_id="root", slide_ids=["hypothesis"]),
        MessageNode(
            id="problem_root", role="evidence", text="이상탐지 정당성 + 기술 스택 + 분석 방법",
            parent_id="root", slide_ids=["why_anomaly", "p2_pain", "p3_alt_limits"],
        ),
        MessageNode(
            id="solution_root", role="evidence", text="이상탐지 아키텍처 + EDA",
            parent_id="root", slide_ids=["architecture_deep", "tech_architecture", "s3_differentiation"],
        ),
        MessageNode(
            id="results_root", role="evidence", text="Baseline 대비 우수 + Score 분포 + Reason Code + PR@k",
            parent_id="root",
            slide_ids=["i1_kpi", "score_distribution", "eda_findings", "error_analysis", "insights_derived"],
        ),
        MessageNode(
            id="impact_root", role="claim", text="비즈니스 효과 + 임계값/알람 정책",
            parent_id="root", slide_ids=["as_is_to_be", "i3_roi"],
        ),
        MessageNode(
            id="plan_root", role="action", text="단계별 실행 + Alert Pipeline",
            parent_id="root", slide_ids=["risk_mitigation", "roadmap"],
        ),
    ]

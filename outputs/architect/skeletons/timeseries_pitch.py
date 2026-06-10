"""outputs.architect.skeletons.timeseries_pitch — Timeseries Pitch Skeleton (재구성).

Timeseries (timeseries) 카테고리 전용 분석 보고서 deck.
20장 골격 유지 + ml_pitch / dl_pitch 와 동일 패턴 (ctx 기반 + verdict 분기) +
시계열 특화 (Why TS · STL · Forecast Plot · Residual + PI Coverage · ACF/PACF ·
Long-horizon Decay · Forecast Refresh).

20 슬라이드 구조:
    1.  Cover                                cover
    2.  목차                                 agenda
    3.  Executive Summary                    exec_summary           ← verdict-aware
    4.  분석 가설 (시계열 적합성)             hypothesis
    5.  Why 시계열 모델?                     why_timeseries         ★ TS 정당성
    6.  기술 스택 (TS 프리셋)                p2_pain                ← manifest timeseries
    7.  분석 방법                            p3_alt_limits          ← method_flow
    8.  모델 아키텍처 (Prophet/N-BEATS/ARIMA) architecture_deep      ★ TS 신규
    9.  시간축 · 트렌드                      tech_architecture      ← EDA-1
    10. 계절 분해 또는 파생 피처              s3_differentiation
    11. 모델 성능 · Backtest 비교             i1_kpi
    12. Forecast Plot + PI                   forecast_plot          ★ TS 신규
    13. 시점별 영향도 · Lag Importance        eda_findings           ← shap_global TS 변형
    14. Residual + PI Coverage                error_analysis         ★ TS 특화
    15. ACF/PACF · 잔차 진단                 insights_derived       ← error_cm TS 변형
    16. 계절·시간대·요일별 성능               as_is_to_be            ← segment TS 변형
    17. Policy + Long-horizon Decay           i3_roi                 ← verdict
    18. SWOT + Drift/Holiday                  risk_mitigation        ← swot (ctx)
    19. Roadmap + Forecast Refresh            roadmap                ← verdict
    20. 감사합니다                            closing                ← verdict
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

SKELETON_NAME = "Timeseries Pitch"


def make_section(
    section_id: str, title: str, kind: str, divider: bool = False,
    summary: str = "", slides: Optional[list[SlideSpec]] = None,
) -> SectionSpec:
    return SectionSpec(
        id=section_id, title=title, kind=kind, divider_required=divider,
        short_summary=summary or title, slides=list(slides or []),
    )


def primary_metric_ref(ctx: ReportContext) -> list[str]:
    pm = ctx.evaluation.primary_metric or {}
    rid = pm.get("ref_id")
    return [rid] if rid else []


def build_cover(ctx: ReportContext) -> SlideSpec:
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "시계열 분석 보고서").strip()
    return SlideSpec(
        id="cover", section_id="front_matter", layout="cover", role="meta",
        so_what="", title_ko=intent[:40],
        body_outline=[
            f"카테고리 · {ctx.meta.category}",
            f"데이터셋 · {ctx.dataset.dataset_name or '미지정'}",
            f"분류등급 · {ctx.meta.classification}",
        ],
        required_refs=[],
        speaker_notes_hint="제목·시계열 분석 의도·핵심 결론 미리보기.",
    )


def build_agenda(sections_titles: list[str]) -> SlideSpec:
    return SlideSpec(
        id="agenda", section_id="front_matter", layout="agenda", role="meta",
        so_what="본 보고서는 5개 섹션 — 시계열 정당성 · 솔루션 · 결과 · 임팩트 · 실행.",
        title_ko="목차", body_outline=sections_titles,
        speaker_notes_hint="섹션 흐름 안내.",
    )


# ==============================================================
# S3 Exec Summary (verdict-aware)
# ==============================================================


def _build_top_findings_from_ctx(ctx: ReportContext) -> list[dict[str, Any]]:
    importance_list = list(ctx.interpretation.global_importance or [])[:3]
    findings: list[dict[str, Any]] = []
    for i, item in enumerate(importance_list):
        feature = getattr(item, "feature", "") or f"Lag/Reg {i+1}"
        value = getattr(item, "importance", None) or 0.0
        story = ctx.interpretation.per_feature_story.get(feature, "")
        findings.append({
            "label": f"FINDING {i+1:02d}",
            "feature": feature,
            "big": format_metric(float(value), "lag_imp", as_percent=False, decimals=2),
            "sub": _auto_label(story, ctx) if story else feature,
        })
    while len(findings) < 3:
        findings.append({
            "label": f"FINDING {len(findings)+1:02d}",
            "feature": "", "big": "-", "sub": "분석 결과 적립 후 채워짐",
        })
    return findings


def _build_method_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")
    n_features = ctx.features.final_feature_count or len(ctx.features.created or [])
    horizon = ctx.limitations.revalidation_window or "일별"
    return [
        ("모델 선정", f"{chosen} — 시계열 특성에 맞는 구조"),
        ("Lag · Calendar 피처", f"{n_features}개" if n_features else "미생성"),
        ("검증 방식", f"Walk-Forward / Rolling Origin · refresh {horizon}"),
    ]


def _build_perf_subitems(ctx: ReportContext) -> list[tuple[str, str]]:
    pm = ctx.evaluation.primary_metric or {}
    rationale = ctx.evaluation.gate_rationale or (
        "운영 임계 통과" if ctx.evaluation.gate_passed else "운영 임계 미통과"
    )
    baseline = ctx.model_selection.baselines.naive or {}
    baseline_str = ""
    if baseline:
        b_val = baseline.get("score")
        if b_val is not None:
            try:
                baseline_str = format_metric(float(b_val), pm.get("name", ""))
            except (TypeError, ValueError):
                baseline_str = str(b_val)
            baseline_str = f"Naive {baseline_str} 대비 우수"
        else:
            baseline_str = "Baseline 비교 완료"
    else:
        baseline_str = "Baseline 미설정"

    calib = ctx.evaluation.calibration or {}
    coverage = calib.get("coverage") if isinstance(calib, dict) else None
    coverage_str = f"PI80 coverage {coverage:.1%}" if coverage is not None else "PI Coverage 미적립"

    return [
        ("운영 임계", rationale),
        ("Baseline 대비", baseline_str),
        ("PI Coverage", coverage_str),
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


def _build_exec_summary_ts(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")
    use_case = ctx.domain.inferred_use_case or ctx.meta.user_intent or "시계열 예측"
    horizon = ctx.limitations.revalidation_window or "일별"
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
        id="exec_summary", section_id="front_matter",
        layout="exec_summary_3finding_3box", role="claim",
        so_what=so_what, title_ko="Executive Summary",
        body_outline=body, required_refs=primary_metric_ref(ctx),
        thread_part="resolution", parent_message_id="root",
        visual_spec=VisualSpec(
            type="exec_summary_v32", title="Executive Summary",
            spec={
                "findings": findings,
                "method_items": method_items,
                "perf_items": perf_items,
                "limitation_items": limitation_items,
                "verdict": ctx.evaluation.verdict or "adopt",
                "tone_accent": tone.accent,
            },
        ),
        speaker_notes_hint="시계열 PI Coverage 가 핵심 신뢰 지표.",
    )


# ==============================================================
# S4 Hypothesis
# ==============================================================


def _build_hypothesis(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")
    intent = ctx.meta.user_intent or "시계열 예측"
    body = [
        "H1 · 트렌드 지속 · 추세 신호가 미래에도 유효",
        "H2 · 계절성 · 일·주·연 단위 패턴이 예측 신호",
        f"H3 · 모델 적합성 · {chosen} 가 Naive Baseline 대비 {pm.get('name', '지표')} 향상",
    ]
    return SlideSpec(
        id="hypothesis", section_id="problem",
        layout="one_message", role="claim",
        so_what=f"본 분석 '{intent[:40]}' 의 3 가설 — 시계열 특성 기반",
        title_ko="분석 가설 · 시계열 적합성",
        body_outline=body, thread_part="setup", parent_message_id="hyp_root",
        visual_spec=VisualSpec(
            type="custom", title="Hypothesis · Evidence · Insight",
            spec={"layout": "hyp_evidence_insight"},
        ),
        speaker_notes_hint="시계열 가설 3개.",
    )


# ==============================================================
# S5 Why TS
# ==============================================================


def _build_why_timeseries(ctx: ReportContext) -> SlideSpec:
    rows = ctx.dataset.shape.get("rows", 0)
    time_col = ctx.dataset.detected_time_col or "시간 컬럼"

    why_items: list[tuple[str, str]] = []
    if rows:
        why_items.append(("시계열 길이", f"{rows:,} 시점 — 통계 신뢰 확보"))
    else:
        why_items.append(("시계열 길이", "ctx 적립 후 표시"))
    why_items.append(("시간 컬럼", f"{time_col} · 시간 정렬 보장"))

    missing = ctx.dataset.missing_rate or {}
    if missing:
        max_missing = max(missing.values()) if missing else 0
        if max_missing > 0:
            why_items.append(("결측 처리", f"최대 결측률 {max_missing*100:.1f}% — 보간 적용"))

    n_regressors = len(ctx.features.created or [])
    if n_regressors:
        why_items.append(("외생변수", f"{n_regressors}개 · Calendar · Lag 피처"))

    why_items.append(("Forecast Refresh", "분기·월별 재학습으로 drift 대응"))

    body = [f"{k} · {v}" for k, v in why_items[:5]]
    return SlideSpec(
        id="why_timeseries", section_id="problem",
        layout="why_ts_pillars", role="claim",
        so_what="시계열 모델 도입 정당성 — 길이·결측·외생·refresh 4축",
        title_ko="Why 시계열 모델?",
        body_outline=body, parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="custom", title="Why Timeseries",
            spec={"why_items": why_items[:5]},
        ),
        speaker_notes_hint="TS 모델의 데이터적 정당성.",
    )


# ==============================================================
# S6 Tech Stack
# ==============================================================


def _build_pain_points(ctx: ReportContext) -> SlideSpec:
    category = ctx.meta.category or "timeseries"
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

    return SlideSpec(
        id="p2_pain", section_id="problem",
        layout="tech_stack_grid", role="evidence",
        so_what=f"본 분석은 {category} 표준 스택 ({len(stack_items)}개) — Python {py_ver}",
        title_ko="기술 스택",
        body_outline=body, parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_tech_stack", title="기술 스택",
            spec={"stack_items": stack_items, "category": category, "python_version": py_ver},
        ),
        speaker_notes_hint="시계열 표준 스택 (statsmodels · Prophet/N-BEATS · MLflow).",
    )


# ==============================================================
# S7 분석 방법
# ==============================================================


def _build_baseline_limits(ctx: ReportContext) -> SlideSpec:
    steps = _build_method_steps(ctx)
    whys = _build_method_whys(ctx)
    body = [f"단계 {i+1} · {s['label']}" for i, s in enumerate(steps)]

    return SlideSpec(
        id="p3_alt_limits", section_id="problem",
        layout="method_flow_with_why", role="evidence",
        so_what="5단계 분석 방법 — 시간 정렬 + Walk-Forward Backtest",
        title_ko="분석 방법",
        body_outline=body[:5], parent_message_id="problem_root",
        visual_spec=VisualSpec(
            type="v28_method_flow", title="분석 방법 흐름 · WHY",
            spec={"steps": steps, "whys": whys},
        ),
        speaker_notes_hint="좌측 흐름도 + 우측 WHY 카드.",
    )


# ==============================================================
# S8 Architecture Deep
# ==============================================================


def _build_architecture_deep(ctx: ReportContext) -> SlideSpec:
    chosen = ctx.model_selection.chosen or {}
    chosen_name = chosen.get("name", "시계열 모델")
    chosen_family = chosen.get("family", "Forecasting")

    arch_items: list[tuple[str, str]] = [("모델", f"{chosen_name} ({chosen_family})")]

    if ctx.training.runs:
        run = ctx.training.runs[0]
        hp = getattr(run, "hyperparameters", {}) or {}
        if "seasonality" in hp:
            arch_items.append(("계절성", str(hp["seasonality"])))
        if "horizon" in hp:
            arch_items.append(("Forecast Horizon", f"{hp['horizon']}"))
        if "lookback" in hp or "context_length" in hp:
            lookback = hp.get("lookback", hp.get("context_length"))
            arch_items.append(("Lookback", f"{lookback}"))
        if "n_lags" in hp:
            arch_items.append(("Lag Features", f"{hp['n_lags']}"))
        for key in ("changepoint_prior_scale", "seasonality_prior_scale"):
            if key in hp:
                arch_items.append((key, f"{hp[key]}"))
    else:
        arch_items.append(("구조", "ctx.training.runs 적립 후 표시"))

    body = [f"{k} · {v}" for k, v in arch_items[:6]]

    return SlideSpec(
        id="architecture_deep", section_id="solution",
        layout="architecture_deep_dive", role="evidence",
        so_what=f"{chosen_name} 시계열 구조 — horizon · lookback · 계절성",
        title_ko="모델 아키텍처 · Deep Dive",
        body_outline=body[:5], parent_message_id="solution_root",
        visual_spec=VisualSpec(
            type="architecture_diagram", title=f"{chosen_name} 구조",
            spec={"arch_items": arch_items, "model_name": chosen_name, "family": chosen_family},
        ),
        speaker_notes_hint="TS 모델 구조 — horizon · lookback · 계절성 prior.",
    )


# ==============================================================
# S9 / S10 EDA
# ==============================================================


def _build_tech_architecture_combined(ctx: ReportContext) -> SlideSpec:
    charts = _select_top_eda_charts(ctx, n=3)
    if charts:
        return _build_eda_slide_from_chart(charts[0], "tech_architecture", 1, ctx, "eda_main_1")
    return _build_eda_placeholder("tech_architecture", 1, ctx, "eda_main_1")


def _build_differentiation(ctx: ReportContext) -> SlideSpec:
    if _derived_features_richness(ctx) >= 5:
        return _build_derived_features_slide(ctx, "s3_differentiation")
    charts = _select_top_eda_charts(ctx, n=3)
    if len(charts) >= 2:
        return _build_eda_slide_from_chart(charts[1], "s3_differentiation", 2, ctx, "eda_main_2")
    return _build_eda_placeholder("s3_differentiation", 2, ctx, "eda_main_2")


# ==============================================================
# S11 Model Perf / Backtest
# ==============================================================


def _build_kpi_backtest(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_name = pm.get("name", "primary")
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")
    category = ctx.meta.category or "timeseries"

    metric_ok = is_metric_compatible(category, pm_name)

    baselines = ctx.model_selection.baselines
    bars: list[dict[str, Any]] = []
    for b in [baselines.naive, baselines.domain_rule, baselines.previous_best]:
        if b:
            v = b.get("score")
            if v is not None:
                bars.append({"label": b.get("name", "Baseline"), "value": v, "color": "muted"})
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
        body.append("Metrics · " + " · ".join(metric_lines))

    tone = _get_verdict_tone(ctx)
    so_what = f"{chosen} Backtest 성능: {pm_name} {pm_value_str} ({tone.accent})"

    return SlideSpec(
        id="i1_kpi", section_id="results",
        layout="model_perf_baseline_grouped", role="evidence",
        so_what=so_what, title_ko="예측 성능 · Backtest 비교",
        body_outline=body[:5], required_refs=primary_metric_ref(ctx),
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="v28_model_perf", title=f"Backtest — {pm_name}",
            spec={
                "metric": pm_name, "metric_value": pm.get("value"),
                "bars": bars, "metric_balance_top4": balance_top4,
                "metric_category_compatible": metric_ok,
                "verdict": ctx.evaluation.verdict or "",
            },
        ),
        speaker_notes_hint="Walk-Forward / Rolling Origin Backtest 결과.",
    )


# ==============================================================
# S12 Forecast Plot (TS 특화)
# ==============================================================


def _build_forecast_plot(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_value_str = _format_pm_value(pm)
    calib = ctx.evaluation.calibration or {}
    coverage = calib.get("coverage") if isinstance(calib, dict) else None
    pi_width = calib.get("pi_width") if isinstance(calib, dict) else None
    horizon_decay = calib.get("horizon_decay") if isinstance(calib, dict) else None

    body: list[str] = [f"메트릭 · {pm.get('name', 'mae')} {pm_value_str}"]
    if coverage is not None:
        body.append(f"PI80 Coverage · {coverage:.1%}")
    if pi_width is not None:
        body.append(f"평균 PI Width · {pi_width:.2f}")
    if horizon_decay is not None:
        body.append(f"Long-horizon Decay · {horizon_decay:.1%}")
    if not body[1:]:
        body.append("PI Coverage 미적립")

    return SlideSpec(
        id="forecast_plot", section_id="results",
        layout="forecast_with_pi", role="evidence",
        so_what="예측 신뢰성 — PI Coverage 가 목표(80%) 와 일치 시 신뢰 가능",
        title_ko="Forecast Plot · 실측 vs 예측 + PI",
        body_outline=body[:5], parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="forecast_with_interval", title="Forecast Plot",
            spec={"calibration": calib, "horizon_decay": horizon_decay},
        ),
        speaker_notes_hint="실측·예측·PI80·PI95 4-layer.",
    )


# ==============================================================
# S13 시점별 영향도
# ==============================================================


def _build_stl_decomposition(ctx: ReportContext) -> SlideSpec:
    category = ctx.meta.category or "timeseries"
    variant = resolve_slide("shap_global", category)
    title_ko = (variant.title_ko if variant else "시점별 영향도 · Lag/외생변수")

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
            "method": getattr(it, "method", "lag_importance"),
            "kind": "derived" if is_derived else "original",
        })
        rid = getattr(it, "ref_id", None)
        if rid:
            refs.append(rid)

    body = [
        f"{i+1}순위 · {it['feature']} ({'파생' if it['kind'] == 'derived' else '원본'}) · "
        f"{format_metric(float(it['importance']), 'lag_imp', as_percent=False, decimals=2)}"
        for i, it in enumerate(items)
    ]
    if not body:
        body = ["분석 결과 적립 후 채워짐"]

    so_what = "시점별 영향도 — Lag / Calendar / 외생변수 신호"
    if items:
        so_what = f"{items[0]['feature']} 이 가장 강한 시점 영향 — 핵심 변수"

    return SlideSpec(
        id="eda_findings", section_id="results",
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence", so_what=so_what, title_ko=title_ko,
        body_outline=body[:5], required_refs=refs,
        parent_message_id="results_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_annotated_bar"),
            title=title_ko,
            spec={"items": items, "method": "lag_importance"},
            severity="important",
        ),
        speaker_notes_hint="TS SHAP = Lag Importance / 외생변수 기여.",
    )


# ==============================================================
# S14 Residual + PI Coverage
# ==============================================================


def _build_residual_pi_coverage(ctx: ReportContext) -> SlideSpec:
    category = ctx.meta.category or "timeseries"
    variant = resolve_slide("shap_cases", category)
    title_ko = (variant.title_ko if variant else "잔차 분포 · PI Coverage")

    calib = ctx.evaluation.calibration or {}
    body: list[str] = []
    if isinstance(calib, dict):
        if "coverage" in calib:
            body.append(f"PI80 Coverage · {calib['coverage']:.1%} (목표 80%)")
        if "pi_width" in calib:
            body.append(f"평균 PI Width · {calib['pi_width']:.2f}")
        if "residual_mean" in calib:
            body.append(f"Residual mean · {calib['residual_mean']:.3f}")
        if "residual_std" in calib:
            body.append(f"Residual std · {calib['residual_std']:.3f}")
        if "horizon_decay" in calib:
            body.append(f"Long-horizon Decay · {calib['horizon_decay']:.1%}")
    if not body:
        body = ["Calibration 미적립"]

    return SlideSpec(
        id="error_analysis", section_id="results",
        layout=(variant.layout if variant else "one_message"),
        role="caveat",
        so_what="잔차 + PI Coverage — 예측 신뢰도 + long-horizon 안정성",
        title_ko=title_ko,
        body_outline=body[:5], parent_message_id="results_root",
        visual_spec=VisualSpec(
            type="residual_and_pi", title=title_ko,
            spec={"calibration": calib},
        ),
        speaker_notes_hint="Residual + Coverage 가 TS 신뢰성 핵심.",
    )


# ==============================================================
# S15 ACF/PACF · 잔차 진단
# ==============================================================


def _build_insights_derived(ctx: ReportContext) -> SlideSpec:
    category = ctx.meta.category or "timeseries"
    variant = resolve_slide("error_cm", category)
    title_ko = (variant.title_ko if variant else "잔차 진단 · ACF/PACF")

    calib = ctx.evaluation.calibration or {}
    body: list[str] = []
    if isinstance(calib, dict):
        if "ljung_box_pvalue" in calib:
            pv = calib["ljung_box_pvalue"]
            body.append(f"Ljung-Box p-value · {pv:.3f} (>0.05 면 white noise)")
        if "acf_residual_max" in calib:
            body.append(f"ACF Residual 최대값 · {calib['acf_residual_max']:.3f}")
        if "qq_correlation" in calib:
            body.append(f"Q-Q correlation · {calib['qq_correlation']:.3f}")
    if not body:
        body = ["잔차 진단 미적립"]

    return SlideSpec(
        id="insights_derived", section_id="results",
        layout=(variant.layout if variant else "chart_callout"),
        role="caveat",
        so_what="잔차 white noise 검증 — 모델이 모든 신호 활용했는지",
        title_ko=title_ko,
        body_outline=body[:5], parent_message_id="results_root",
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_residual_diag"),
            title=title_ko, spec={"calibration": calib}, severity="important",
        ),
        speaker_notes_hint="ACF residual / Q-Q plot — white noise 검증.",
    )


# ==============================================================
# S16 세그먼트별 성능
# ==============================================================


def _build_as_is_to_be(ctx: ReportContext) -> SlideSpec:
    category = ctx.meta.category or "timeseries"
    variant = resolve_slide("segment", category)
    title_ko = (variant.title_ko if variant else "계절 · 시간대 · 요일별 성능 차이")

    segs = list(ctx.evaluation.per_segment or [])[:6]
    body: list[str] = []
    seg_items: list[dict[str, Any]] = []
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        name = seg.get("segment") or seg.get("name") or "?"
        metric_name = seg.get("metric") or "mae"
        value = seg.get("value")
        if value is None:
            continue
        formatted = format_metric(float(value), str(metric_name))
        body.append(f"{name} · {metric_name} {formatted}")
        seg_items.append({"segment": name, "metric": metric_name, "value": value})

    if not body:
        body = ["계절·시간대별 성능 미적립"]

    so_what = "계절·시간대별 성능 — 일관성 또는 특정 구간 보강 필요성"
    if len(seg_items) >= 2:
        vals = [float(s["value"]) for s in seg_items]
        gap = max(vals) - min(vals)
        if gap > 0.1:
            so_what = f"세그먼트 격차 {gap:.2f} — 일부 구간 보완 필요"

    return SlideSpec(
        id="as_is_to_be", section_id="impact",
        layout=(variant.layout if variant else "one_message"),
        role="evidence", so_what=so_what, title_ko=title_ko,
        body_outline=body[:6], parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="segment_perf_table", title=title_ko,
            spec={"segments": seg_items},
        ),
        speaker_notes_hint="계절·시간대 — 격차 0.1 이상 시 보완.",
    )


# ==============================================================
# S17 Policy + Long-horizon (verdict)
# ==============================================================


def _build_roi_long_horizon(ctx: ReportContext) -> SlideSpec:
    tone = _get_verdict_tone(ctx)
    title_ko = tone.s17_section_label or "예측 구간 기반 운영 · 안전재고 · 임계"

    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)

    policy_items: list[tuple[str, str]] = []
    v = (ctx.evaluation.verdict or "").lower()
    if v == "adopt":
        policy_items = [
            ("운영 임계", ctx.evaluation.gate_rationale or f"{pm_value} 기반 임계"),
            ("안전재고", "PI 상한 기반 안전재고 — 결품 비용 통제"),
            ("재학습", "drift 감지 + 주기적 refresh"),
        ]
    elif v == "iterate":
        policy_items = [
            ("보강 우선순위", "외생변수 추가 · horizon 조정"),
            ("재시도 조건", f"{pm_value} 대비 +5%p 향상 시 재평가"),
            ("Owner", "분석팀"),
        ]
    elif v == "reject":
        policy_items = [
            ("폐기 사유", ctx.evaluation.gate_rationale or "운영 임계 미달"),
            ("대안 권고", "Naive baseline 유지 또는 문제 재정의"),
            ("Owner", "프로덕트 · 분석팀 공동"),
        ]
    else:
        policy_items = [
            ("판정 미정", "verdict 적립 시 자동 분기"),
            ("기본 모니터링", "drift · MAE · PI Coverage"),
            ("재검토", "월간"),
        ]

    body = [f"{k} · {v}" for k, v in policy_items]
    biz_kpi = ctx.evaluation.business_kpi[0] if ctx.evaluation.business_kpi else None
    if biz_kpi:
        body.append(f"비즈니스 KPI · {getattr(biz_kpi, 'name', '')} {getattr(biz_kpi, 'estimated_value', '')} {getattr(biz_kpi, 'unit', '')}")

    so_what = f"{chosen} 정책 — 판정: {ctx.evaluation.verdict or '미정'} + Long-horizon 통제"

    return SlideSpec(
        id="i3_roi", section_id="impact",
        layout="one_message", role="action",
        so_what=so_what, title_ko=title_ko,
        body_outline=body[:5], parent_message_id="impact_root",
        visual_spec=VisualSpec(
            type="v28_policy_insight", title=title_ko,
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
                "ts_horizon_hint": "Long-horizon decay 시 horizon 단축 또는 refresh 주기 단축",
            },
        ),
        speaker_notes_hint="verdict 분기 + TS 특화 (PI · Long-horizon).",
    )


# ==============================================================
# S18 SWOT
# ==============================================================


def _build_risk_mitigation_ts(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_value_str = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")

    strengths: list[str] = []
    if ctx.interpretation.global_importance:
        top_feat = ctx.interpretation.global_importance[0].feature
        strengths.append(f"강한 시계열 신호 · {top_feat}")
    if pm.get("value") is not None:
        strengths.append(f"Backtest 통과 · {chosen} {pm_value_str}")
    calib = ctx.evaluation.calibration or {}
    if isinstance(calib, dict) and calib.get("coverage") is not None:
        strengths.append(f"PI Coverage {calib['coverage']:.1%} 안정")
    if not strengths:
        strengths.append("강점 적립 후 채워짐")

    weaknesses: list[str] = []
    for g in (ctx.limitations.data_gaps or [])[:2]:
        desc = getattr(g, "description", "") or "데이터 결함"
        impact = getattr(g, "impact", "") or ""
        weaknesses.append(f"{desc}" + (f" ({impact})" if impact else ""))
    if isinstance(calib, dict) and calib.get("horizon_decay") is not None:
        weaknesses.append(f"Long-horizon Decay · {calib['horizon_decay']:.1%}")
    if not weaknesses:
        weaknesses.append("약점 식별 안 됨")

    opportunities: list[str] = []
    rev = ctx.limitations.revalidation_window
    if rev:
        opportunities.append(f"{rev} refresh — drift 흡수")
    opportunities.append("Holiday · 외부 이벤트 캘린더 통합")
    opportunities = opportunities[:3]

    threats: list[str] = []
    shift = ctx.limitations.distribution_shift_risk or {}
    if shift.get("detected"):
        ev = shift.get("evidence") or "분포 변화"
        threats.append(f"데이터 드리프트 · {ev}")
    threats.append("Holiday / 비정기 이벤트 — 모델 성능 저하 가능")
    for c in (ctx.limitations.model_caveats or [])[:1]:
        threats.append(f"모델 한계 · {c}")
    threats = threats[:3]

    body = [
        f"S · {strengths[0]}",
        f"W · {weaknesses[0]}",
        f"O · {opportunities[0]}",
        f"T · {threats[0]}",
        "Mitigation · refresh + Holiday calendar + PI 모니터링",
    ]

    return SlideSpec(
        id="risk_mitigation", section_id="plan",
        layout="swot_2x2", role="caveat",
        so_what="SWOT 4분면 — TS 특화 (Drift · Holiday · Long-horizon · PI)",
        title_ko="SWOT · Drift",
        body_outline=body[:5], parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="v28_swot_reach", title="SWOT · Drift",
            spec={
                "strengths": strengths[:3], "weaknesses": weaknesses[:3],
                "opportunities": opportunities[:3], "threats": threats[:3],
                "revalidation_window": rev or "",
            },
            severity="important",
        ),
        speaker_notes_hint="TS SWOT — PI 강점 + Long-horizon / Holiday 위협.",
    )


# ==============================================================
# S19 Roadmap + Forecast Refresh (verdict)
# ==============================================================


def _build_roadmap_forecast_refresh(ctx: ReportContext) -> SlideSpec:
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    raw_pattern = tone.s19_phase_pattern or "Phase 1 → Phase 2 → Phase 3"
    phases = [p.strip() for p in raw_pattern.split("→") if p.strip()][:3]

    body: list[str] = [f"{i+1}. {phase}" for i, phase in enumerate(phases)]

    if verdict == "adopt":
        body.extend([
            "Forecast Refresh · 일·주·월 자동 재학습 cadence",
            "운영 KPI · MAE · PI Coverage · drift score",
        ])
    elif verdict == "iterate":
        body.extend([
            "보강 측정 · 외생변수·horizon 변화",
            "재평가 · 본 모델 대비 +5%p 향상 시 도입 재고려",
        ])
    else:
        body.extend([
            "대안 후보 · Naive baseline 유지 또는 새 모델",
            "재학습 금지 · 현 데이터로는 폐기",
        ])

    return SlideSpec(
        id="roadmap", section_id="plan",
        layout="roadmap_phase_kpi", role="action",
        so_what=f"실행 로드맵 — 판정({verdict}) 별 + Forecast Refresh",
        title_ko="실행 로드맵 · Forecast Refresh",
        body_outline=body[:5], parent_message_id="plan_root",
        visual_spec=VisualSpec(
            type="v28_domain_mapping", title="실행 로드맵 · Forecast Refresh",
            spec={
                "verdict": verdict, "phases": phases,
                "tone_accent": tone.accent,
                "ts_refresh_hint": "일·주·월 자동 재학습 cadence",
            },
        ),
        speaker_notes_hint="verdict 별 Phase + TS Refresh cadence.",
    )


# ==============================================================
# S20 Closing
# ==============================================================


def _build_closing_qna(ctx: ReportContext) -> SlideSpec:
    pm = ctx.evaluation.primary_metric or {}
    pm_value = _format_pm_value(pm)
    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")
    tone = _get_verdict_tone(ctx)
    verdict = (ctx.evaluation.verdict or "").lower() or "adopt"

    if verdict == "adopt":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 도입 가능"
    elif verdict == "iterate":
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 보강 후 재검토"
    else:
        result_line = f"결론 · {chosen} {pm.get('name', '')} {pm_value} — 현 모델 도입 불가"

    body = [
        f"본 보고서 · {ctx.meta.user_intent or '시계열 예측'}",
        result_line,
        "Q&A — 데이터 / 모델 / PI / Long-horizon / Refresh",
    ]
    return SlideSpec(
        id="closing", section_id="closing", layout="closing", role="meta",
        so_what=f"본 분석 마무리 — 판정: {verdict}",
        title_ko="감사합니다", body_outline=body,
        visual_spec=VisualSpec(
            type="closing_simple", title="감사합니다",
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
    sections: list[SectionSpec] = []
    messages: list[MessageNode] = _build_message_tree(ctx)

    front = make_section(
        "front_matter", "Front Matter", kind="cover", divider=False,
        slides=[build_cover(ctx), _build_exec_summary_ts(ctx)],
    )
    sections.append(front)

    problem_section = make_section(
        "problem", "Section 1 — 시계열 정당성 & 방법", kind="context", divider=True,
        slides=[
            _build_hypothesis(ctx),
            _build_why_timeseries(ctx),
            _build_pain_points(ctx),
            _build_baseline_limits(ctx),
        ],
    )
    sections.append(problem_section)

    solution_section = make_section(
        "solution", "Section 2 — 모델 · EDA", kind="evidence", divider=True,
        slides=[
            _build_architecture_deep(ctx),
            _build_tech_architecture_combined(ctx),
            _build_differentiation(ctx),
        ],
    )
    sections.append(solution_section)

    results_section = make_section(
        "results", "Section 3 — 분석 결과", kind="evidence", divider=True,
        slides=[
            _build_kpi_backtest(ctx),
            _build_forecast_plot(ctx),
            _build_stl_decomposition(ctx),
            _build_residual_pi_coverage(ctx),
            _build_insights_derived(ctx),
        ],
    )
    sections.append(results_section)

    impact_section = make_section(
        "impact", "Section 4 — 임팩트 · 정책", kind="recommendation", divider=True,
        slides=[_build_as_is_to_be(ctx), _build_roi_long_horizon(ctx)],
    )
    sections.append(impact_section)

    plan_section = make_section(
        "plan", "Section 5 — 리스크 & 실행", kind="recommendation", divider=False,
        slides=[_build_risk_mitigation_ts(ctx), _build_roadmap_forecast_refresh(ctx)],
    )
    sections.append(plan_section)

    closing_section = make_section(
        "closing", "Closing", kind="closing", divider=False,
        slides=[_build_closing_qna(ctx)],
    )
    sections.append(closing_section)

    sections_titles = [
        "Section 1 — 시계열 정당성 & 방법",
        "Section 2 — 모델 · EDA",
        "Section 3 — 분석 결과 (Forecast · Residual · PI)",
        "Section 4 — 임팩트 · 정책",
        "Section 5 — 리스크 & 실행 + Refresh",
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
                f"{ctx.domain.inferred_use_case or ctx.meta.user_intent or '시계열 예측'}"
            ),
            conflict="Naive · 통계 baseline 한계 — 트렌드·계절성·외생변수 통합 부족",
            resolution=(
                f"{(ctx.model_selection.chosen or {}).get('name', '시계열 모델')} 으로 "
                "PI Coverage 확보 + Long-horizon decay 통제"
            ),
        ),
        message_tree=messages,
        meta={"skeleton_variant": "timeseries_pitch_v2"},
        warnings=[],
    )
    return plan


# ==============================================================
# Message tree (verdict-aware)
# ==============================================================


def _build_message_tree(ctx: ReportContext) -> list[MessageNode]:
    chosen = (ctx.model_selection.chosen or {}).get("name", "시계열 모델")
    pm = ctx.evaluation.primary_metric or {}
    verdict = (ctx.evaluation.verdict or "").lower()
    if verdict == "iterate":
        conclusion = "보강 후 재학습 권장"
    elif verdict == "reject":
        conclusion = "현 모델 도입 불가"
    else:
        conclusion = "운영 도입 권장 + Forecast Refresh 정기 실행"
    root_msg = (
        f"{chosen} 로 {pm.get('name', 'primary')} {pm.get('value', '-')} 달성 — {conclusion}"
    )
    return [
        MessageNode(
            id="root", role="claim", text=root_msg, parent_id=None,
            children=["problem_root", "solution_root", "results_root", "impact_root", "plan_root"],
        ),
        MessageNode(id="hyp_root", role="claim", text="시계열 적합성 3가설",
                    parent_id="root", slide_ids=["hypothesis"]),
        MessageNode(id="problem_root", role="evidence", text="시계열 정당성 + 스택 + 방법",
                    parent_id="root", slide_ids=["why_timeseries", "p2_pain", "p3_alt_limits"]),
        MessageNode(id="solution_root", role="evidence", text="모델 + EDA",
                    parent_id="root",
                    slide_ids=["architecture_deep", "tech_architecture", "s3_differentiation"]),
        MessageNode(id="results_root", role="evidence", text="Backtest + Forecast + Residual + PI",
                    parent_id="root",
                    slide_ids=["i1_kpi", "forecast_plot", "eda_findings", "error_analysis", "insights_derived"]),
        MessageNode(id="impact_root", role="claim", text="임팩트 + Long-horizon 정책",
                    parent_id="root", slide_ids=["as_is_to_be", "i3_roi"]),
        MessageNode(id="plan_root", role="action", text="단계별 실행 + Forecast Refresh",
                    parent_id="root", slide_ids=["risk_mitigation", "roadmap"]),
    ]

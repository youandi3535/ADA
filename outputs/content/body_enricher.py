"""outputs.content.body_enricher - data-driven body content fill.

When no LLM caller is injected (psuedo mode), slide body_outline is enriched
from ReportContext data: metrics, model details, dataset stats, category
specifics, preprocessing steps, etc.

This is a *deterministic* enrichment - same ctx always produces same body.
"""

from __future__ import annotations

from outputs.architect.plan import ReportPlan, SlideSpec
from outputs.context.schema import ReportContext


def enrich_plan_bodies(plan: ReportPlan, ctx: ReportContext) -> None:
    """In-place enrich body_outline for every slide that has thin content."""
    for sec in plan.sections:
        for sl in sec.slides:
            if sl.role == "meta":
                continue
            _enrich_one(sl, ctx)


def _enrich_one(sl: SlideSpec, ctx: ReportContext) -> None:
    """Enrich a single slide based on its id/section."""
    sid = sl.id or ""

    # Situation / context
    if sid in ("s_situation", "p1_market", "decision_context", "background", "symptoms"):
        sl.body_outline = _situation_body(ctx)
        return

    # Complication / problem
    if sid in ("c_complication", "p2_pain", "data_source"):
        sl.body_outline = _problem_body(ctx)
        return

    # Question
    if sid in ("q_question", "criteria"):
        sl.body_outline = _question_body(ctx)
        return

    # Answer / conclusion
    if sid in ("a_answer", "conclusion", "rec_options", "root_cause"):
        sl.body_outline = _answer_body(ctx)
        return

    # Data / preprocessing
    if sid in ("e1_data_preproc", "method_pre", "method_model", "s1_overview"):
        sl.body_outline = _data_preproc_body(ctx)
        return

    # EDA findings
    if sid.startswith("e2_eda") or sid == "result_eda" or sid == "evidence_h1":
        sl.body_outline = _eda_body(ctx)
        return

    # Model comparison
    if sid in ("e3_model_comparison", "matrix", "p3_alt_limits", "alternatives"):
        sl.body_outline = _model_comparison_body(ctx)
        return

    # Performance
    if sid in ("e4_performance", "result_primary", "reason_perf", "evidence_h2", "i1_kpi"):
        sl.body_outline = _performance_body(ctx)
        return

    # Interpretation
    if sid in ("e5_interpretation", "result_interp", "reason_trust"):
        sl.body_outline = _interpretation_body(ctx)
        return

    # Action / recommendation
    if sid in ("action_recommendations", "i2_before_after", "i3_roi", "short_term", "long_term"):
        sl.body_outline = _action_body(ctx)
        return

    # Limitations
    if sid in ("limitations", "risk", "risk_mitigation", "residual_risk"):
        sl.body_outline = _limitations_body(ctx)
        return

    # Tech architecture / stack stay as-is (already strong)

    # Fallback: if body is too thin, fill with category-aware default
    if len(sl.body_outline) <= 2:
        sl.body_outline = _default_body(ctx, sl)


# ==============================================================
# Content builders - return list[str] of 3-6 bullets
# ==============================================================


def _situation_body(ctx: ReportContext) -> list[str]:
    ds = ctx.dataset
    dom = ctx.domain
    rows = ds.shape.get("rows", 0)
    cols = ds.shape.get("cols", 0)
    industry = dom.inferred_industry or _category_label(ctx.meta.category)
    use_case = dom.inferred_use_case or ctx.meta.user_intent or "본 과제"
    return [
        f"산업 영역  ·  {industry}",
        f"분석 과제  ·  {use_case}",
        f"데이터 규모  ·  {rows:,} 행 × {cols} 컬럼",
        f"분석 카테고리  ·  {_category_label(ctx.meta.category)}",
        f"대상 타깃  ·  {ds.detected_target or '비지도/이상탐지'}",
    ]


def _problem_body(ctx: ReportContext) -> list[str]:
    issues = ctx.eda.data_quality_issues or []
    lines = []
    for it in issues[:3]:
        lines.append(f"품질 이슈  ·  {it.get('issue', '검증 필요')} (영향 {it.get('severity', 'medium')})")
    # Always add structural challenges
    n_miss = sum(1 for r in ctx.dataset.missing_rate.values() if r > 0.05)
    if n_miss:
        lines.append(f"결측률 5% 이상 변수  ·  {n_miss}개")
    leak = [c for c in ctx.preprocessing.leakage_checks if not c.get("passed", True)]
    if leak:
        lines.append(f"누설 의심  ·  {len(leak)}건 추가 검증 필요")
    if not lines:
        lines = [
            "기존 방식의 한계  ·  수작업 일관성 부족, 재현성 미흡",
            "분석 리드타임  ·  평균 3~6주 (산업 통상치)",
            "운영 환경 적용  ·  검증·해석·문서화 별도 필요",
        ]
    return lines[:5]


def _question_body(ctx: ReportContext) -> list[str]:
    intent = ctx.meta.user_intent or ctx.meta.user_question or "분석 의도"
    return [
        f"핵심 질문  ·  {intent}",
        f"분석 단위  ·  {_unit_of_analysis(ctx)}",
        f"대상 타깃  ·  {ctx.dataset.detected_target or '비지도 학습 대상'}",
        f"평가 기준  ·  {_primary_metric_label(ctx)} + 보조 지표 다수",
        f"제약 조건  ·  {ctx.meta.business_context or '명시된 제약 없음 (분류 등급 ' + ctx.meta.classification + ')'}",
    ]


def _answer_body(ctx: ReportContext) -> list[str]:
    chosen = ctx.model_selection.chosen or {}
    pm = ctx.evaluation.primary_metric or {}
    name = chosen.get("name", "-")
    family = chosen.get("family", "")
    rationale = (chosen.get("justification") or "최우선 후보로 선정")[:120]
    metric_line = f"{pm.get('name', '대표지표')} {pm.get('value', '-')}"
    lines = [
        f"선정 모델  ·  {name} ({family})" if family else f"선정 모델  ·  {name}",
        f"핵심 성과  ·  {metric_line} 달성",
        f"선정 근거  ·  {rationale}",
    ]
    if ctx.evaluation.business_kpi:
        kpi = ctx.evaluation.business_kpi[0]
        lines.append(f"기대 효과  ·  {kpi.name} {kpi.estimated_value} {kpi.unit}")
    lines.append("후속 근거  ·  Evidence 섹션의 데이터·해석으로 단계별 제시")
    return lines


def _data_preproc_body(ctx: ReportContext) -> list[str]:
    ds = ctx.dataset
    steps = ctx.preprocessing.applied_steps or []
    feat_count = ctx.features.final_feature_count or ds.shape.get("cols", 0)
    lines = [
        f"원본 데이터  ·  {ds.shape.get('rows', 0):,} 행 × {ds.shape.get('cols', 0)} 컬럼",
    ]
    if steps:
        ops = ", ".join(s.op for s in steps[:5] if s.op)
        lines.append(f"전처리 단계 {len(steps)}개  ·  {ops}")
    else:
        lines.append("전처리  ·  자동 추정 (impute · scale · encode)")
    lines.append(f"최종 피처 수  ·  {feat_count} 개")
    if ds.detected_target:
        lines.append(f"타깃 변수  ·  {ds.detected_target}")
    if ds.detected_time_col:
        lines.append(f"시간축  ·  {ds.detected_time_col}")
    return lines[:5]


def _eda_body(ctx: ReportContext) -> list[str]:
    charts = ctx.eda.charts or []
    findings = [c.finding for c in charts if c.finding][:3]
    seg = ctx.eda.segment_insights or []
    lines = []
    for f in findings:
        lines.append(f"발견  ·  {f}")
    if not lines and charts:
        lines.append(f"EDA 차트 {len(charts)}종 분석 완료")
    for s in seg[:2]:
        lines.append(f"세그먼트  ·  {s.get('segment_def', '구간')} (lift {s.get('lift_pct', 0)}%)")
    if not lines:
        n_num = sum(1 for v in ctx.dataset.numeric_stats)
        n_cat = ctx.dataset.shape.get("cols", 0) - n_num
        lines = [
            f"수치형 변수  ·  {n_num}개의 분포·상관 분석",
            f"범주형 변수  ·  {n_cat}개의 카디널리티·빈도 분석",
            "이상치 탐지  ·  IQR·Z-score 기준 자동 검출",
        ]
    return lines[:4]


def _model_comparison_body(ctx: ReportContext) -> list[str]:
    cands = ctx.model_selection.candidates or []
    chosen = (ctx.model_selection.chosen or {}).get("name", "-")
    lines = []
    for c in cands[:4]:
        marker = "  ★" if c.name == chosen else "   "
        lines.append(f"{marker}{c.name}  ·  {c.family or '모델 family'}  ·  {(c.why_tried or '후보 풀에서 선정')[:40]}")
    if not lines:
        lines = ["후보 모델 식별 진행 중"]
    lines.append(f"선정 결과  ·  {chosen} (가중 합 1위)")
    return lines[:5]


def _performance_body(ctx: ReportContext) -> list[str]:
    metrics = ctx.evaluation.metrics or {}
    pm = ctx.evaluation.primary_metric or {}
    lines = []
    if pm:
        lines.append(f"대표 지표  ·  {pm.get('name')} = {pm.get('value')} ({pm.get('direction', '')})")
    for k, m in list(metrics.items())[:5]:
        v = m.get("value")
        v_str = f"{v:.4f}" if isinstance(v, float) and abs(v) < 1 else f"{v}"
        if k != pm.get("name"):
            lines.append(f"{k}  ·  {v_str}")
    if not lines:
        lines = ["성능 평가 진행 중 - 지표 산출 후 보강"]
    return lines[:6]


def _interpretation_body(ctx: ReportContext) -> list[str]:
    imps = ctx.interpretation.global_importance or []
    lines = []
    for i, imp in enumerate(imps[:3]):
        lines.append(f"Top {i + 1}  ·  {imp.feature}  ({imp.method} {imp.importance:.3f})")
    stories = ctx.interpretation.per_feature_story or {}
    for feat, story in list(stories.items())[:2]:
        lines.append(f"{feat}  ·  {story[:80]}")
    if not lines:
        lines = [
            "SHAP/permutation 기반 상위 피처 식별 진행 중",
            "각 피처의 영향 방향·크기·신뢰도 분석",
            "도메인 해석 결합으로 의사결정 근거 확보",
        ]
    return lines[:4]


def _action_body(ctx: ReportContext) -> list[str]:
    kpis = ctx.evaluation.business_kpi or []
    lines = []
    for kpi in kpis[:3]:
        lines.append(f"{kpi.name}  ·  {kpi.estimated_value} {kpi.unit}  ({kpi.confidence} 신뢰도)")
    if not lines:
        lines = [
            "1단계 (0~30일)  ·  파일럿 운영, 핵심 지표 모니터링 설정",
            "2단계 (30~90일)  ·  운영 환경 단계 배포, 세그먼트별 검증",
            "3단계 (90일+)  ·  분기 재학습 자동화, 도메인 피드백 반영",
        ]
    if ctx.limitations.revalidation_window:
        lines.append(f"재검증 주기  ·  {ctx.limitations.revalidation_window}")
    return lines[:5]


def _limitations_body(ctx: ReportContext) -> list[str]:
    lims = ctx.limitations
    lines = []
    for g in lims.data_gaps[:2]:
        lines.append(f"데이터 한계  ·  {g.description} (영향 {g.impact})")
    for c in lims.model_caveats[:2]:
        lines.append(f"모델 한계  ·  {c}")
    for r in lims.generalization_risk[:2]:
        lines.append(f"일반화 리스크  ·  {r.description}  → 대응 {r.mitigation or '검토 필요'}")
    if not lines:
        lines = [
            "표본 대표성  ·  특정 세그먼트 표본 부족 가능",
            "분포 변화 리스크  ·  운영 환경에서 입력 분포 drift 모니터링 필요",
            "해석 안정성  ·  학습 시점과 추론 시점 동질성 가정",
            "재학습 주기  ·  분기 1회 또는 성능 하락 임계 도달 시",
        ]
    return lines[:5]


def _default_body(ctx: ReportContext, sl: SlideSpec) -> list[str]:
    """Fallback - use existing so_what + category-aware notes."""
    notes = [sl.so_what] if sl.so_what else []
    notes.append(f"카테고리  ·  {_category_label(ctx.meta.category)}")
    if ctx.evaluation.primary_metric:
        pm = ctx.evaluation.primary_metric
        notes.append(f"대표 지표  ·  {pm.get('name')} {pm.get('value')}")
    return notes[:4]


# ==============================================================
# Helpers
# ==============================================================


def _category_label(cat: str) -> str:
    return {
        "tabular_ml": "정형 데이터 ML",
        "tabular_dl": "정형 데이터 DL",
        "timeseries": "시계열 예측",
        "anomaly_detection": "이상 탐지",
    }.get(cat, cat or "기타")


def _primary_metric_label(ctx: ReportContext) -> str:
    pm = ctx.evaluation.primary_metric or {}
    return pm.get("name", "주요 평가 지표")


def _unit_of_analysis(ctx: ReportContext) -> str:
    if ctx.meta.category == "timeseries":
        return f"시간 단위 ({ctx.dataset.detected_time_col or 'time'})"
    if ctx.meta.category == "anomaly_detection":
        return "관측 단위 (anomaly score)"
    return f"행 단위 ({ctx.dataset.shape.get('rows', 0):,}건)"

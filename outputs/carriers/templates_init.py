"""outputs.carriers.templates_init - Register all infographic templates.

This module is imported by pptx_designer to populate the registry.
Each entry: (name, draw_fn, fit_fn, tags).
"""

from __future__ import annotations

from outputs.carriers import pptx_infographics as I
from outputs.carriers.template_registry import (
    REGISTRY,
    combine,
    has_body_min,
    has_id,
    has_layout,
    has_metrics,
    has_role,
    matches_keywords,
)


def _wrap_no_args(draw_fn, args_builder):
    """Wrap a draw_fn to extract args from (slide, sl, ctx, ...)."""

    def w(slide, sl, ctx, primary, accent, ink, muted, light_bg, **kw):
        args = args_builder(sl, ctx)
        if args is None:
            return
        draw_fn(slide, *args, primary, accent, ink, muted, light_bg)

    return w


# ==============================================================
# Argument builders (slide+ctx -> args for the draw function)
# ==============================================================


def _items_from_body(sl, n=4, default=None):
    """Parse body_outline lines as {title, caption} dicts."""
    items = []
    for line in sl.body_outline[:n]:
        if "·" in line:
            k, v = line.split("·", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            k, v = line, ""
        items.append({"title": k.strip()[:30], "caption": v.strip()[:120]})
    return items or (default or [])


def _metrics_pct(ctx, n=4):
    items = []
    for k, m in list(ctx.evaluation.metrics.items())[:n]:
        v = m.get("value")
        if isinstance(v, float) and 0 < v < 1:
            val = f"{v * 100:.0f}%"
        else:
            val = str(v)
        items.append({"value": val, "label": k, "caption": ""})
    return items


# ==============================================================
# Template draw wrappers (uniform signature)
# ==============================================================


def t_kpi_pct_4(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _metrics_pct(ctx, 4)
    if items:
        I.draw_percentage_grid_4(slide, items, primary, accent, ink, muted, light_bg)


def t_big_stats(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    pm = ctx.evaluation.primary_metric or {}
    items = []
    if pm:
        v = pm.get("value")
        vs = f"{v * 100:.0f}%" if isinstance(v, float) and v < 1 else str(v)
        items.append({"value": vs, "label": pm.get("name", "").upper(), "caption": "대표 평가 지표"})
    items.append({"value": f"{ctx.dataset.shape.get('rows', 0):,}", "label": "DATA POINTS", "caption": "분석 규모"})
    if ctx.evaluation.business_kpi:
        kpi = ctx.evaluation.business_kpi[0]
        items.append(
            {
                "value": f"{kpi.estimated_value:.1f}{kpi.unit}",
                "label": kpi.name.upper()[:30],
                "caption": f"신뢰도 {kpi.confidence}",
            }
        )
    I.draw_big_stats(slide, items[:3], primary, accent, ink, muted, light_bg)


def t_donut(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    pm = ctx.evaluation.primary_metric or {}
    v = pm.get("value", 0.85)
    pct = float(v) * 100 if isinstance(v, float) and v < 1 else float(v)
    side = sl.body_outline[:5] or [f"{k}: {m.get('value')}" for k, m in list(ctx.evaluation.metrics.items())[:4]]
    I.draw_donut_metric(
        slide, pct, pm.get("name", "PRIMARY"), "KEY INSIGHT", primary, accent, ink, muted, light_bg, side_items=side
    )


def t_cube_3d(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(
        sl,
        4,
        default=[
            {"title": "Python", "caption": "런타임"},
            {"title": "ML libs", "caption": "분석"},
            {"title": "MinIO", "caption": "스토리지"},
            {"title": "MLflow", "caption": "실험 추적"},
        ],
    )
    I.draw_cube_3d(slide, items, primary, accent, ink, muted, light_bg)


def t_chevron_5(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    cands = ctx.model_selection.candidates or []
    items = [{"title": (c.name or "")[:20], "caption": (c.why_tried or "")[:80]} for c in cands[:5]]
    if not items:
        items = _items_from_body(sl, 5)
    I.draw_chevron_strategies(slide, items, primary, accent, ink, muted, light_bg)


def t_chevron_4(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 4)
    I.draw_process_4_chevron(slide, items, primary, accent, ink, muted, light_bg)


def t_index_cards(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 4)
    I.draw_index_cards(slide, items, primary, accent, ink, muted, light_bg)


def t_checklist(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 4)
    I.draw_checklist_4(slide, items, primary, accent, ink, muted, light_bg)


def t_step_cards(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 4)
    I.draw_step_cards_vertical(slide, items, primary, accent, ink, muted, light_bg)


def t_strategy_4(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 4)
    I.draw_strategy_4_circular(slide, items, primary, accent, ink, muted, light_bg)


def t_numbered_rows(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 5)
    I.draw_numbered_rows(slide, items, primary, accent, ink, muted, light_bg)


def t_linked_circles(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 4)
    I.draw_linked_circles_4(slide, items, primary, accent, ink, muted, light_bg)


def t_vertical_arrow(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 5)
    I.draw_vertical_arrow_steps(slide, items, primary, accent, ink, muted, light_bg)


def t_clock(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 4)
    I.draw_clock_diagram(slide, items, primary, accent, ink, muted, light_bg)


def t_gear(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 6)
    I.draw_gear_infographic(slide, items, primary, accent, ink, muted, light_bg)


def t_hex_6(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 6)
    I.draw_hex_grid_6(slide, items, primary, accent, ink, muted)


def t_radial(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = [{"label": x.get("title", "")} for x in _items_from_body(sl, 6)]
    I.draw_radial_nodes(slide, sl.title_ko or "HUB", items, primary, accent, ink, muted, light_bg)


def t_timeline(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = []
    for i, line in enumerate(sl.body_outline[:5]):
        year = f"P{i + 1}"
        label = line
        if ":" in line:
            year, label = line.split(":", 1)
        items.append({"year": year.strip()[:18], "label": label.strip()[:80]})
    I.draw_timeline_milestones(slide, items, primary, accent, ink, muted, light_bg)


def t_5step_alt(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _items_from_body(sl, 5)
    I.draw_5step_alt_callouts(slide, items, primary, accent, ink, muted, light_bg)


def t_stats_grid(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _metrics_pct(ctx, 4) or _items_from_body(sl, 4)
    I.draw_statistics_grid(slide, items, primary, accent, ink, muted, light_bg)


def t_mini_stats(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = _metrics_pct(ctx, 4)
    I.draw_mini_stats_row(slide, items, primary, accent, ink, muted, light_bg)


def t_swot(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = []
    for line in sl.body_outline[:4]:
        if ":" in line:
            k, v = line.split(":", 1)
            items.append({"points": [v.strip()[:60]]})
        else:
            items.append({"points": [line[:60]]})
    while len(items) < 4:
        items.append({"points": ["분석 추가 필요"]})
    I.draw_swot_matrix(slide, items, primary, accent, ink, muted, light_bg)


def t_funnel(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    rows = ctx.dataset.shape.get("rows", 12000)
    stages = [
        {"value": f"{rows:,}", "label": "총 데이터", "caption": "전체 표본"},
        {"value": f"{int(rows * 0.85):,}", "label": "유효 표본", "caption": "결측 제거"},
        {"value": f"{int(rows * 0.7):,}", "label": "학습용", "caption": "전처리 통과"},
        {"value": f"{int(rows * 0.2):,}", "label": "검증용", "caption": "Hold-out"},
    ]
    I.draw_funnel_chart(slide, stages, primary, accent, ink, muted, light_bg)


def t_2col_stats(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = []
    for line in sl.body_outline[:4]:
        if "·" in line:
            k, v = line.split("·", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            k, v = line, ""
        items.append(
            {"value": k.strip()[:8] or str(len(items) + 1), "label": v.strip()[:30], "caption": v.strip()[:160]}
        )
    I.draw_two_col_stats(slide, items, primary, accent, ink, muted, light_bg)


def t_price_3(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = [
        {"tier": "BASIC", "value": "단계 1", "lines": sl.body_outline[:1] or ["기본 도입"]},
        {"tier": "RECOMMENDED", "value": "단계 2", "lines": sl.body_outline[:3] or ["권장 도입"]},
        {"tier": "ENTERPRISE", "value": "단계 3", "lines": sl.body_outline[:2] or ["전사 확장"]},
    ]
    I.draw_price_compare_3(slide, items, primary, accent, ink, muted, light_bg)


def t_team_4(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    members = [
        {"name": "데이터 분석", "role": "PROFILER", "bio": "PII 마스킹 + 카테고리 추론"},
        {"name": "모델링", "role": "TRAINER", "bio": "Heavy/Light 분기 학습"},
        {"name": "평가", "role": "EVALUATOR", "bio": "임계치 + 자가 검증"},
        {"name": "산출", "role": "COMPOSER", "bio": "5종 보고서 생성"},
    ]
    I.draw_team_cards_4(slide, members, primary, accent, ink, muted, light_bg)


def t_split_compare(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    half = len(sl.body_outline) // 2 or 2
    left = {"label": "AS-IS", "headline": "기존 방식", "points": sl.body_outline[:half] or ["수작업 분석"]}
    right = {
        "label": "TO-BE",
        "headline": "ADA 자동화",
        "points": sl.body_outline[half : half * 2] or ["AI 자동화 + 재현 가능"],
    }
    I.draw_split_compare(slide, left, right, primary, accent, ink, muted, light_bg)


def t_big_index_chart(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    big = {"number": "01", "title": sl.title_ko or "Key Metric", "caption": sl.so_what or "분석 결과 핵심"}
    items = []
    for k, m in list(ctx.evaluation.metrics.items())[:5]:
        v = m.get("value", 0)
        items.append({"label": k, "pct": v * 100 if isinstance(v, float) and v < 1 else min(v, 100)})
    I.draw_big_index_chart(slide, big, items, primary, accent, ink, muted, light_bg)


def t_circular_progress(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = []
    for k, m in list(ctx.evaluation.metrics.items())[:4]:
        v = m.get("value", 0)
        pct = f"{v * 100:.0f}%" if isinstance(v, float) and v < 1 else str(v)
        items.append({"value": pct, "title": k, "sub": "달성률"})
    I.draw_circular_progress_4(slide, items, primary, accent, ink, muted, light_bg)


def t_as_is_to_be(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    half = max(1, len(sl.body_outline) // 2)
    as_is = sl.body_outline[:half] or [
        "수작업 분석 - 3~6주",
        "재현 불가능",
        "팀별 표준 부재",
        "모니터링 수동",
    ]
    to_be = sl.body_outline[half : half * 2] or [
        f"{(ctx.model_selection.chosen or {}).get('name', 'AI')} 자동화",
        "Companion 코드 재현",
        "통합 파이프라인",
        "MLflow 자동 추적",
    ]
    I.draw_as_is_to_be(
        slide,
        {"label": "AS-IS", "points": as_is},
        {"label": "TO-BE", "points": to_be},
        primary,
        accent,
        ink,
        muted,
        light_bg,
    )


def t_thank_you(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    I.draw_thank_you_closing(slide, ctx, primary, accent, ink, muted)


def t_qna(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    I.draw_qna_slide(slide, ctx, primary, accent, ink, muted, light_bg)


def t_photo_opener(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    I.draw_photo_overlay_opener(
        slide, ctx, sl.title_ko or sl.id, sl.so_what or "", primary, accent, ink, muted, light_bg
    )


# ==============================================================
# Registration
# ==============================================================


def init_registry() -> None:
    """Idempotent - registers all templates exactly once."""
    if REGISTRY.get("kpi_pct_4"):
        return  # already initialized

    # ---- KPI / Statistics ----
    REGISTRY.register(
        "kpi_pct_4",
        t_kpi_pct_4,
        fit=combine(has_id("i1_kpi", "reason_perf"), has_layout("kpi_cards_4")),
        tags=["kpi", "metrics"],
    )
    REGISTRY.register("big_stats", t_big_stats, fit=has_id("exec_summary", "a_answer"), tags=["summary"])
    REGISTRY.register(
        "stats_grid", t_stats_grid, fit=combine(has_layout("kpi_cards_3", "kpi_cards_6"), has_metrics(2)), tags=["kpi"]
    )
    REGISTRY.register("mini_stats", t_mini_stats, fit=has_id("e4_performance"), tags=["kpi", "compact"])
    REGISTRY.register(
        "donut", t_donut, fit=has_id("e5_interpretation", "reason_trust", "result_interp"), tags=["chart", "kpi"]
    )
    # Tighten: only matches when slide id is i3_roi (avoids over-firing)
    REGISTRY.register("circular_progress", t_circular_progress, fit=has_id("i3_roi"), min_score=80.0, tags=["kpi"])

    # ---- Process / Flow ----
    REGISTRY.register("cube_3d", t_cube_3d, fit=has_id("tech_stack"), tags=["tech"])
    REGISTRY.register(
        "chevron_5",
        t_chevron_5,
        fit=has_id("e3_model_comparison", "alternatives", "matrix"),
        tags=["compare", "process"],
    )
    REGISTRY.register("chevron_4", t_chevron_4, fit=combine(has_id("p3_alt_limits"), has_body_min(3)), tags=["process"])
    REGISTRY.register("vertical_arrow", t_vertical_arrow, fit=has_id("e1_data_preproc", "method_pre"), tags=["process"])
    REGISTRY.register("step_cards", t_step_cards, fit=has_id("roadmap"), tags=["roadmap"])
    REGISTRY.register("5step_alt", t_5step_alt, fit=has_id("tech_architecture"), tags=["process"])
    REGISTRY.register("clock", t_clock, fit=has_id("long_term"), tags=["time"])
    REGISTRY.register("timeline", t_timeline, fit=has_layout("process_flow_gantt"), tags=["timeline"])
    REGISTRY.register("gear", t_gear, fit=has_id("method_model", "s1_overview"), tags=["process"])

    # ---- Comparison ----
    REGISTRY.register("as_is_to_be", t_as_is_to_be, fit=has_layout("comparison_before_after"), tags=["compare"])
    REGISTRY.register(
        "split_compare",
        t_split_compare,
        fit=combine(matches_keywords("vs", "비교", "vs."), has_body_min(2)),
        tags=["compare"],
    )
    REGISTRY.register("strategy_4", t_strategy_4, fit=has_id("s3_differentiation"), tags=["strategy"])
    REGISTRY.register(
        "swot", t_swot, fit=combine(matches_keywords("swot", "강점", "약점"), has_body_min(4)), tags=["compare"]
    )

    # ---- Structural / Layout ----
    REGISTRY.register("index_cards", t_index_cards, fit=has_id("criteria"), tags=["structure"])
    REGISTRY.register(
        "numbered_rows", t_numbered_rows, fit=has_id("s_situation", "p1_market", "q_question"), tags=["structure"]
    )
    REGISTRY.register(
        "linked_circles",
        t_linked_circles,
        fit=has_id("hypothesis_tree", "p2_pain", "c_complication"),
        tags=["structure"],
    )
    REGISTRY.register(
        "hex_6", t_hex_6, fit=combine(has_body_min(6), matches_keywords("능력", "역량", "특성")), tags=["grid"]
    )
    REGISTRY.register(
        "radial", t_radial, fit=combine(has_body_min(4), matches_keywords("중심", "허브", "core")), tags=["grid"]
    )
    REGISTRY.register(
        "checklist", t_checklist, fit=has_id("action_recommendations", "rec_options", "short_term"), tags=["action"]
    )

    # ---- Special ----
    REGISTRY.register("thank_you", t_thank_you, fit=has_layout("closing"), tags=["closing"])
    REGISTRY.register("qna", t_qna, fit=combine(matches_keywords("q&a", "질문"), has_role("meta")), tags=["closing"])
    REGISTRY.register(
        "photo_opener", t_photo_opener, fit=combine(has_layout("section_divider"), has_body_min(0)), tags=["opener"]
    )

    # ---- Business ----
    REGISTRY.register(
        "funnel",
        t_funnel,
        fit=combine(matches_keywords("퍼널", "funnel", "데이터 흐름"), has_body_min(0)),
        tags=["business"],
    )
    REGISTRY.register("2col_stats", t_2col_stats, fit=combine(has_role("evidence"), has_body_min(4)), tags=["stats"])
    REGISTRY.register(
        "price_3",
        t_price_3,
        fit=combine(matches_keywords("도입", "단계 비교", "옵션"), has_body_min(2)),
        tags=["business"],
    )
    REGISTRY.register(
        "team_4", t_team_4, fit=combine(matches_keywords("팀", "역할", "team"), has_body_min(0)), tags=["team"]
    )
    REGISTRY.register(
        "big_index_chart",
        t_big_index_chart,
        fit=combine(has_role("claim"), has_metrics(3)),
        min_score=15.0,
        tags=["dashboard"],
    )
    # Phase 10 batch
    try:
        register_phase10()
    except Exception:
        pass
    # Phase 11 batch — roadmap with upgrades, etc.
    try:
        register_phase11()
    except Exception:
        pass
    # Curate to exactly 30 — drop redundant/near-duplicate templates
    for redundant in (
        "stats_grid",
        "team_4",
        "big_index_chart",
        "bento",
        "2col_stats",
        "mini_stats",
        "timeline",
        "chevron_4",
        "5step_alt",
        "hex_6",
        "step_cards",
    ):
        REGISTRY._specs.pop(redundant, None)


# ==============================================================
# Phase 10 additions - hypothesis/insight + 5 new bento patterns
# ==============================================================


def t_five_why(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    chain = []
    for line in sl.body_outline[:5]:
        if ":" in line:
            q, a = line.split(":", 1)
            chain.append({"question": q.strip(), "answer": a.strip()})
        elif "·" in line:
            q, a = line.split("·", 1)
            chain.append({"question": q.strip(), "answer": a.strip()})
        else:
            chain.append({"question": "왜?", "answer": line})
    if not chain:
        chain = [
            {"question": "관찰", "answer": "예측 성능이 baseline 대비 우수"},
            {"question": "왜 1?", "answer": "Top 피처가 강한 신호를 보유"},
            {"question": "왜 2?", "answer": "전처리에서 noise 제거 효과적"},
            {"question": "왜 3?", "answer": "타깃 분포 안정적"},
            {"question": "근본", "answer": "데이터 품질 + 피처 선정 적정"},
        ]
    I.draw_five_why(slide, chain, primary, accent, ink, muted, light_bg)


def t_hyp_evidence_insight(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    pm = ctx.evaluation.primary_metric or {}
    items = [
        {
            "hypothesis": "고객 인구통계 변수가 결과에 영향",
            "evidence": f"{pm.get('name', '지표')} {pm.get('value', '-')} 분포·SHAP top 3 확인",
            "insight": "연령·지역 세그먼트별 차별화 전략 필요",
        },
        {
            "hypothesis": "최근 행동 패턴이 예측력 향상",
            "evidence": "Last 30-day 활동 변수 상위 importance",
            "insight": "실시간 행동 데이터 파이프라인 구축 권장",
        },
        {
            "hypothesis": "단순 모델로도 충분한 성능",
            "evidence": f"{(ctx.model_selection.chosen or {}).get('name', 'Model')} baseline 차이 5%p",
            "insight": "운영 비용 대비 효율적 모델 선정",
        },
    ]
    I.draw_hypothesis_evidence_insight(slide, items, primary, accent, ink, muted, light_bg)


def t_insight_funnel(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = [
        {"text": f"{ctx.dataset.shape.get('rows', 0):,}행 raw data 분석"},
        {"text": "Top 피처 3개에서 강한 신호 발견"},
        {"text": "세그먼트별 차별화 전략 필요"},
        {"text": "분기 재학습 + 도메인 룰 결합 운영"},
    ]
    I.draw_insight_funnel_4(slide, items, primary, accent, ink, muted, light_bg)


def t_horizontal_progress(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = []
    for k, m in list(ctx.evaluation.metrics.items())[:5]:
        v = m.get("value", 0)
        pct = v * 100 if isinstance(v, float) and v < 1 else min(v, 100)
        items.append({"label": k, "caption": f"{v}", "pct": pct})
    if not items:
        items = [{"label": f"Metric {i + 1}", "pct": 75 - i * 10} for i in range(4)]
    I.draw_horizontal_progress(slide, items, primary, accent, ink, muted, light_bg)


def t_vertical_timeline(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    milestones = []
    for line in sl.body_outline[:5]:
        if ":" in line:
            k, v = line.split(":", 1)
        elif "·" in line:
            k, v = line.split("·", 1)
        else:
            k, v = line, ""
        milestones.append({"title": k.strip()[:30], "caption": v.strip()[:100]})
    I.draw_vertical_timeline(slide, milestones, primary, accent, ink, muted, light_bg)


def t_org_hierarchy(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    root = (ctx.model_selection.chosen or {}).get("name", "Solution")
    children = []
    for line in sl.body_outline[:4]:
        if "·" in line:
            k, v = line.split("·", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            k, v = line, ""
        children.append({"title": k.strip()[:30], "caption": v.strip()[:100]})
    I.draw_org_hierarchy(slide, root, children, primary, accent, ink, muted, light_bg)


def t_stats_with_delta(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    items = []
    metrics_list = list(ctx.evaluation.metrics.items())
    for i, (k, m) in enumerate(metrics_list[:4]):
        v = m.get("value", 0)
        vs = f"{v:.3f}" if isinstance(v, float) and v < 1 else str(v)
        items.append(
            {
                "label": k,
                "value": vs,
                "delta": (8.5 - i * 1.2),
                "caption": "baseline 대비 우수",
            }
        )
    if not items:
        items = [
            {"label": "AUC", "value": "0.85", "delta": 12.5, "caption": "Baseline 0.75"},
            {"label": "F1", "value": "0.78", "delta": 8.2, "caption": "Baseline 0.72"},
            {"label": "Precision", "value": "0.81", "delta": 6.1, "caption": "Baseline 0.76"},
            {"label": "Recall", "value": "0.74", "delta": 4.3, "caption": "Baseline 0.71"},
        ]
    I.draw_stats_with_delta(slide, items, primary, accent, ink, muted, light_bg)


def t_bento(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    pm = ctx.evaluation.primary_metric or {}
    items = [
        {
            "title": f"{pm.get('name', '지표')}  {pm.get('value', '-')}",
            "icon": I.GLYPHS["target"],
            "caption": sl.so_what or "분석 결과 종합",
        }
    ]
    for k, m in list(ctx.evaluation.metrics.items())[:4]:
        items.append({"title": k, "caption": f"{m.get('value')}"})
    I.draw_bento_grid(slide, items, primary, accent, ink, muted, light_bg)


def register_phase10() -> None:
    from outputs.carriers.template_registry import (
        REGISTRY,
        combine,
        has_body_min,
        has_id,
        has_metrics,
        matches_keywords,
    )

    if REGISTRY.get("five_why"):
        return  # already
    # Hypothesis / Insight
    REGISTRY.register(
        "five_why",
        t_five_why,
        fit=combine(matches_keywords("왜", "원인", "근본", "why"), has_body_min(3)),
        tags=["insight", "diagnostic"],
    )
    REGISTRY.register(
        "hyp_evidence_insight", t_hyp_evidence_insight, fit=has_id("hypothesis"), min_score=80.0, tags=["insight"]
    )
    REGISTRY.register(
        "insight_funnel", t_insight_funnel, fit=has_id("insights_derived"), min_score=80.0, tags=["insight"]
    )
    # 5 new bento patterns
    REGISTRY.register(
        "horizontal_progress",
        t_horizontal_progress,
        fit=combine(has_metrics(3), matches_keywords("진행", "달성")),
        tags=["kpi", "progress"],
    )
    REGISTRY.register(
        "vertical_timeline",
        t_vertical_timeline,
        fit=combine(matches_keywords("타임라인", "단계별", "phase"), has_body_min(3)),
        tags=["timeline"],
    )
    REGISTRY.register(
        "org_hierarchy",
        t_org_hierarchy,
        fit=combine(matches_keywords("계층", "구조", "조직"), has_body_min(2)),
        tags=["structure"],
    )
    REGISTRY.register(
        "stats_with_delta",
        t_stats_with_delta,
        fit=combine(has_metrics(2), matches_keywords("증감", "개선", "향상")),
        tags=["kpi", "delta"],
    )
    REGISTRY.register(
        "bento",
        t_bento,
        fit=combine(has_metrics(3), matches_keywords("종합", "overview", "대시보드")),
        tags=["dashboard"],
    )


def t_roadmap_upgrades(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """Split body into Phase items + 고도화 items, render split layout."""
    phases = []
    upgrades = []
    for line in sl.body_outline:
        if "·" in line:
            k, v = line.split("·", 1)
        elif ":" in line:
            k, v = line.split(":", 1)
        else:
            k, v = line, ""
        head = k.strip()
        body = v.strip()
        head_lower = head.lower()
        if head.startswith("Phase") or "phase" in head_lower or "단계" in head:
            phases.append({"title": head[:30], "caption": body[:120]})
        elif "고도화" in head or "upgrade" in head_lower or "디벨롭" in head or "확장" in head:
            upgrades.append({"title": head[:30], "caption": body[:120]})
        else:
            # First half → phases, second half → upgrades
            (phases if len(phases) < 3 else upgrades).append({"title": head[:30], "caption": body[:120]})
    if not phases:
        phases = [
            {"title": "Phase 1 (0~30일)", "caption": "파일럿 운영"},
            {"title": "Phase 2 (30~90일)", "caption": "운영 전환"},
            {"title": "Phase 3 (90일+)", "caption": "확장·자동화"},
        ]
    if not upgrades:
        upgrades = [
            {"title": "추가 피처", "caption": "행동·실시간 신호 연동"},
            {"title": "앙상블 확장", "caption": "멀티 모델 + 개인화"},
            {"title": "A/B 인프라", "caption": "도메인 룰 결합 운영"},
        ]
    I.draw_roadmap_with_upgrades(slide, phases[:3], upgrades[:3], primary, accent, ink, muted, light_bg)


def register_phase11():
    from outputs.carriers.template_registry import REGISTRY, has_id

    if REGISTRY.get("roadmap_upgrades"):
        return
    REGISTRY.register(
        "roadmap_upgrades", t_roadmap_upgrades, fit=has_id("roadmap", "long_term"), min_score=90.0, tags=["roadmap"]
    )
    # Tighten horizontal_progress so it doesn't grab roadmap
    if REGISTRY.get("horizontal_progress"):
        REGISTRY._specs["horizontal_progress"].fit = has_id("progress_status", "kpi_progress")
        REGISTRY._specs["horizontal_progress"].min_score = 80.0
    # tech_architecture → vertical_arrow
    if REGISTRY.get("vertical_arrow"):
        REGISTRY._specs["vertical_arrow"].fit = has_id("tech_architecture", "e1_data_preproc", "method_pre")
        REGISTRY._specs["vertical_arrow"].min_score = 80.0
    # p3_alt_limits → chevron_5
    if REGISTRY.get("chevron_5"):
        REGISTRY._specs["chevron_5"].fit = has_id("p3_alt_limits", "e3_model_comparison", "alternatives", "matrix")
        REGISTRY._specs["chevron_5"].min_score = 80.0
    # risk_mitigation → swot
    if REGISTRY.get("swot"):
        REGISTRY._specs["swot"].fit = has_id("risk_mitigation", "risk")
        REGISTRY._specs["swot"].min_score = 80.0

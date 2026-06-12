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
    # jh 2026-06-11 — confidence=low 인 휴리스틱 KPI 는 Exec Summary 대형 숫자로
    # 부적합 (창작 수치 노출 위험). high/medium 만 채택.
    _solid_kpis = [k for k in (ctx.evaluation.business_kpi or []) if k.confidence != "low"]
    if _solid_kpis:
        kpi = _solid_kpis[0]
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


def _clip_sentence(s: str, limit: int = 80) -> str:
    """문장·구 경계에서 절단 — '데이터 ar' 식 단어 중간 절단 방지 (jh 2026-06-12)."""
    s = str(s or "").strip()
    if len(s) <= limit:
        return s
    cut = s[:limit]
    for sep in (". ", " — ", " · ", ", ", " "):
        idx = cut.rfind(sep)
        if idx >= int(limit * 0.5):
            return cut[:idx].rstrip(" .,·—") + "…"
    return cut.rstrip() + "…"


def t_chevron_5(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    cands = ctx.model_selection.candidates or []
    caps = [str(getattr(c, "why_tried", "") or "") for c in cands[:5]]
    # jh 2026-06-12 — 후보 전원이 동일한 전역 선정 사유를 공유하면 (운영 실측)
    # 같은 문장 N회 반복 대신 후보 고유 정보 (family·score) 로 캡션 구성.
    if cands and len(set(caps)) <= 1:
        items = []
        for c in cands[:5]:
            bits = []
            fam = str(getattr(c, "family", "") or "")
            sc = getattr(c, "score", None)
            if fam:
                bits.append(fam)
            if isinstance(sc, (int, float)):
                bits.append(f"score {sc:.3f}")
            items.append({"title": (c.name or "")[:20], "caption": " · ".join(bits) or "후보 모델"})
    else:
        items = [
            {"title": (c.name or "")[:20], "caption": _clip_sentence(cap, 80)}
            for c, cap in zip(cands[:5], caps)
        ]
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
    # jh 2026-06-12 — [:60] 절단 제거: 카피라이터 페어 bullet 이 draw 의
    # 2층(헤드라인 46 + 세부 70) 분할에 닿기 전에 잘려 "다중 지표 임" 류
    # 토막 문장이 나오던 결함. 길이 제어는 draw_swot_matrix 가 담당.
    items = []
    for line in sl.body_outline[:4]:
        items.append({"points": [str(line).strip()[:130]]})
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
    # jh 2026-06-12 — register_phase11 은 정의가 없는 좀비 호출이었음 (NameError 를
    # except 가 삼켜 roadmap_with_upgrades 등이 영영 미등록). phase12 에서 정식 등록.
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

    # Phase 12 — 수작업 견본 덱 레이아웃 이식 (2026-06-11 jh, 카탈로그 보강)
    try:
        register_phase12()
    except Exception:
        pass


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
    """jh 2026-06-12 — 하드코딩 보일러플레이트("Last 30-day 활동 변수" 등 데이터와
    무관한 문구가 S4 에 그대로 출력) 제거. 카피라이터 재료(body_outline) 우선,
    없으면 실데이터(SHAP·primary_metric) 기반 폴백."""
    import re

    items = []
    for line in (sl.body_outline or [])[:3]:
        # jh 2026-06-12 — "H1 · 제목 · 문장" 형식에서 가설 칸에 "H1" 만 들어가던 결함:
        # H1/01 류 라벨 토큰을 먼저 제거하고, 3분할 실패 시 2분할(제목 · 문장—결과) 처리.
        s = re.sub(r"^[-\s]*[HQ]?\d+\s*[·.:]\s*", "", str(line)).strip()
        parts = [p.strip() for p in re.split(r"\s+—\s+", s, maxsplit=2)]
        if len(parts) < 3:
            parts = [p.strip() for p in s.split("·", 2)]
        if len(parts) == 3 and all(parts):
            items.append({"hypothesis": parts[0], "evidence": parts[1], "insight": parts[2]})
        elif len(parts) == 2 and all(parts):
            head, rest = parts
            sub = [p.strip() for p in re.split(r"\s+—\s+", rest, maxsplit=1)]
            items.append({
                "hypothesis": head,
                "evidence": sub[0],
                "insight": sub[1] if len(sub) > 1 else "",
            })

    if not items:
        pm = ctx.evaluation.primary_metric or {}
        gi = ctx.interpretation.global_importance or []
        chosen_name = (ctx.model_selection.chosen or {}).get("name", "Model")
        top3 = [g for g in gi[:3]]
        if top3:
            for g in top3:
                items.append({
                    "hypothesis": f"{g.feature} 가 결정적 신호",
                    "evidence": f"SHAP importance {float(g.importance):.2f}",
                    "insight": f"{g.feature} 기준 세그먼트 분해 검토 권장",
                })
        else:
            items = [
                {
                    "hypothesis": "상위 피처가 결과를 좌우",
                    "evidence": f"{pm.get('name', '지표')} {pm.get('value', '-')} · SHAP top 3 확인 필요",
                    "insight": "피처 중요도 적립 후 세그먼트 전략 수립",
                },
                {
                    "hypothesis": f"{chosen_name} 이 후보 중 최적",
                    "evidence": f"{pm.get('name', '지표')} {pm.get('value', '-')} 로 후보 중 1위",
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
        # jh 2026-06-12 — has_metrics(2) 단독이 모든 슬라이드에서 60점을 줘
        # EDA 슬라이드 (S8) 까지 후보에 올라 제목↔본문 불일치 유발 → 성능 슬라이드 한정
        fit=combine(
            has_id("i1_kpi", "e4_performance", "model_perf", "reason_perf"),
            matches_keywords("성능", "baseline", "지표 비교"),
        ),
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


# ==============================================================
# Phase 12 — 수작업 견본 덱 레이아웃 이식 (2026-06-11 jh)
# 견본: 2026-06-10 수정본 20장. 기하는 실측 좌표 기반 (pptx_infographics).
# ==============================================================


def _split_label(line: str, fallback: str = "") -> tuple[str, str]:
    """bullet "라벨 · 설명" / "라벨: 설명" → (label, text). 구분자 없으면 (fallback, 전체)."""
    s = str(line).strip()
    for sep in (" · ", "·", " — ", ": "):
        if sep in s:
            a, b = s.split(sep, 1)
            if 0 < len(a.strip()) <= 24:
                return a.strip(), b.strip()
    return fallback, s


def t_chart_key_insights(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """견본 주력 레이아웃 — 차트 (좌 60%) + KEY INSIGHTS 패널 (우 40%).

    draw 코드는 legacy ``_draw_chart_callout`` 재사용 — 기존엔 레지스트리 미등록이라
    REGISTRY 가 다른 템플릿으로 가로채 도달 불가였음 (카탈로그 보강 ②).
    """
    from outputs.carriers.pptx_designer import _draw_chart_callout
    from outputs.visuals.render import render_visual_to_png

    _draw_chart_callout(slide, sl, ctx, primary, accent, ink, muted, light_bg, render_visual_to_png)


def t_solution_overview(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """견본 S8 — 좌: 파이프라인 3단계 / 우: 모델·입력·출력·검증 스펙."""
    specs = []
    for line in sl.body_outline[:4]:
        label, text = _split_label(line, fallback=f"항목 {len(specs) + 1}")
        specs.append({"label": label, "text": text})

    step_labels = ("INPUT", "MODEL", "OUTPUT")
    step_keys = (("입력", "데이터", "피처"), ("모델",), ("출력", "예측", "결과"))
    steps = []
    for lab, keys in zip(step_labels, step_keys):
        match = next((s for s in specs if any(k in s["label"] for k in keys)), None)
        steps.append({"label": lab, "text": (match or {}).get("text", "")[:70]})

    chosen = ctx.model_selection.chosen or {}
    # jh 2026-06-12 — so_what 은 헤더 부제로 이미 출력됨. caption 재사용 시
    # 같은 문장이 두 번 찍히던 결함 (S6) → 견본의 고정 파이프라인 캡션 사용.
    caption = f"Solution Pipeline — 입력 → {chosen.get('name', '모델')} → 출력"
    I.draw_solution_overview(slide, caption[:60], steps, specs, primary, accent, ink, muted, light_bg)


def t_lineage_2col(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """견본 S9 — 좌: lineage 단계 바 4 / 우: 보충 카드 3."""
    parsed = [
        dict(zip(("label", "text"), _split_label(line, fallback=f"단계 {i + 1}")))
        for i, line in enumerate(sl.body_outline[:7])
    ]
    bars, cards = parsed[:4], parsed[4:7]
    if not cards and sl.so_what:
        cards = [{"label": "핵심", "text": sl.so_what}]
    I.draw_lineage_2col(slide, bars, cards, primary, accent, ink, muted, light_bg)


def t_exec_summary_v32(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """목표치 덱 S3 — Executive Summary (3 FINDING + METHOD/PERF/LIMITATION).

    재료: sl.visual_spec.spec (skeleton _build_exec_summary_ml 이 적립).
    """
    vs = getattr(sl, "visual_spec", None)
    spec = dict(getattr(vs, "spec", None) or {})
    findings = spec.get("findings") or []
    # jh 2026-06-12 — skeleton 빌드 시점에 interpretation 이 비어 findings 가
    # placeholder("-") 로 굳던 결함 → carrier 시점 ctx 에서 재구성 (안전망)
    _placeholder = (not findings) or all(
        str((f or {}).get("big", "-")) in ("-", "") for f in findings
    )
    if _placeholder:
        gi = list(ctx.interpretation.global_importance or [])[:3]
        if gi:
            # jh 2026-06-12 — 인사이트 중심 (사용자 지시): 순위 나열 대신
            # 비교 맥락(점유율·배수)과 의미를 담은 sub 구성.
            _tot = sum(float(g.importance) for g in gi) or 1.0
            findings = []
            for i, g in enumerate(gi):
                _imp = float(g.importance)
                _share = _imp / _tot
                if i == 0 and len(gi) > 1:
                    _rel = f"2위 {gi[1].feature} 의 {_imp / max(float(gi[1].importance), 1e-9):.1f}배 — 지배적 신호"
                elif i > 0:
                    _rel = f"1위 {gi[0].feature} 대비 {_imp / max(float(gi[0].importance), 1e-9):.0%} 수준 보조 신호"
                else:
                    _rel = "단일 핵심 신호"
                findings.append({
                    "label": f"FINDING {i + 1:02d}",
                    "feature": str(g.feature),
                    "big": f"{_imp:.2f}",
                    "sub": f"상위 3개 영향의 {_share:.0%}\n{_rel}",
                })

    pm = ctx.evaluation.primary_metric or {}
    pm_v = pm.get("value")
    if isinstance(pm_v, float) and pm_v < 1:
        perf_head = f"{pm_v:.3f}"
    else:
        perf_head = str(pm_v if pm_v is not None else "-")

    method_items = list(spec.get("method_items") or [])
    perf_items = list(spec.get("perf_items") or [])
    limitation_items = list(spec.get("limitation_items") or [])

    def _lines(pairs):
        out = []
        for p in pairs[:3]:
            try:
                k, v = p
                out.append(str(v) if str(v) else str(k))
            except Exception:
                out.append(str(p))
        return out

    method_head = (ctx.model_selection.chosen or {}).get("name", "선정 모델")

    # jh 2026-06-12 — LIMITATION 이 "추가 분석 필요"×3 placeholder 로 나가던 결함:
    # ctx.limitations 미적립 시 실데이터(취약 세그먼트·FN·결측)로 자동 구성.
    _lim_placeholder = (not limitation_items) or all(
        "추가 분석" in str(p) for p in limitation_items
    )
    if _lim_placeholder:
        auto_lims: list[tuple[str, str]] = []
        try:
            segs = sorted(
                [s for s in (ctx.evaluation.per_segment or []) if isinstance(s, dict) and s.get("value") is not None],
                key=lambda s: float(s["value"]),
            )
            if segs:
                auto_lims.append((
                    "취약 세그먼트",
                    f"{segs[0].get('segment', '?')} accuracy {float(segs[0]['value']):.0%} — 보강 대상",
                ))
        except Exception:
            pass
        try:
            cm = ctx.evaluation.confusion_matrix or {}
            fn_, fp_ = int(cm.get("fn") or 0), int(cm.get("fp") or 0)
            if fn_:
                auto_lims.append(("미탐(FN)", f"{fn_}건 — 오탐({fp_}건) 대비 주요 오류 유형"))
        except Exception:
            pass
        try:
            mr = ctx.dataset.missing_rate or {}
            top_miss = sorted(mr.items(), key=lambda kv: -float(kv[1]))[:1]
            if top_miss and float(top_miss[0][1]) > 0.3:
                auto_lims.append((
                    f"{top_miss[0][0]} 결측",
                    f"{float(top_miss[0][1]):.0%} — 정보 손실, 파생·보강 여지",
                ))
        except Exception:
            pass
        if auto_lims:
            limitation_items = auto_lims[:3]

    limit_head = "한계"
    if limitation_items:
        try:
            limit_head = str(limitation_items[0][0])
        except Exception:
            limit_head = str(limitation_items[0])

    boxes = [
        ("METHOD", method_head, _lines(method_items)),
        ("PERFORMANCE", perf_head, _lines(perf_items)),
        ("LIMITATION", limit_head, _lines(limitation_items)),
    ]
    I.draw_exec_summary_v32(slide, findings, boxes, primary, accent, ink, muted, light_bg)


def t_method_5step(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """S7 분석 방법 — 5단계 노드 + 캡션 (목표치 S7 구성).

    jh 2026-06-12 — v28_method_flow spec 은 렌더러가 없어 chevron(모델 3장 껍데기)
    으로 새던 결함. spec.steps/whys 재료를 5step 노드로 직접 배치.
    """
    vs = getattr(sl, "visual_spec", None)
    spec = dict(getattr(vs, "spec", None) or {})
    steps = list(spec.get("steps") or [])
    whys = list(spec.get("whys") or [])

    def _txt(v) -> str:
        """문자열만 수용 — bool/숫자가 캡션에 'False' 로 찍히던 결함 가드."""
        return v.strip() if isinstance(v, str) else ""

    items = []
    for i, s in enumerate(steps[:5]):
        if not isinstance(s, dict):
            s = {"label": str(s)}
        label = _txt(s.get("label")) or _txt(s.get("title")) or f"단계 {i + 1}"
        cap = _txt(s.get("caption")) or _txt(s.get("what")) or _txt(s.get("why")) or _txt(s.get("result"))
        if not cap and i < len(whys) and isinstance(whys[i], dict):
            cap = _txt(whys[i].get("why")) or _txt(whys[i].get("what"))
        # rationale 원문이 길면 첫 문장만 (절단면 노출 방지)
        if len(cap) > 70:
            for sep in (". ", " — ", ": "):
                idx = cap.find(sep, 25)
                if 0 < idx < 70:
                    cap = cap[:idx].rstrip(".")
                    break
            else:
                cap = cap[:68].rstrip() + "…"
        # draw_5step_alt_callouts 는 "title" 키를 읽음 (label 로 넘기면 "STEP n" 폴백)
        items.append({"title": label[:20], "label": label[:20], "caption": cap})
    if not items:
        items = _items_from_body(sl, 5)
    I.draw_5step_alt_callouts(slide, items, primary, accent, ink, muted, light_bg)


def t_policy_steps(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """S17 도입 정책 — 정책 항목 세로 카드 (운영임계/모니터링/Owner...).

    jh 2026-06-12 — 정책 재료가 멀쩡한데 percentage_grid(같은 달성률 4번)가
    가로채던 결함. policy_items 를 step 카드로 직접 배치.
    """
    vs = getattr(sl, "visual_spec", None)
    spec = dict(getattr(vs, "spec", None) or {})
    pairs = list(spec.get("policy_items") or [])
    items = []
    for p in pairs[:5]:
        try:
            k, v = p
            items.append({"title": str(k)[:30], "caption": str(v)[:120]})
        except Exception:
            items.append({"title": str(p)[:30], "caption": ""})
    biz = spec.get("biz_kpi")
    if isinstance(biz, dict) and biz.get("name"):
        items.append({
            "title": "비즈니스 KPI",
            "caption": f"{biz.get('name', '')} {biz.get('estimated_value', '')}{biz.get('unit', '')}",
        })
    if not items:
        items = _items_from_body(sl, 4)
    I.draw_step_cards_vertical(slide, items[:4], primary, accent, ink, muted, light_bg)


def t_roadmap_upgrades(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """S19 실행 로드맵 — PHASE 3 + UPGRADE 3 (목표치 S19 구성).

    jh 2026-06-12 — draw_roadmap_with_upgrades 가 미등록(좀비 phase11)이라
    구이미지 코드로만 그려지고 UPGRADE 가 1개에 머물던 결함. 정식 등록 +
    실데이터 기반 고도화 카드 3종 구성.
    """
    import re

    vs = getattr(sl, "visual_spec", None)
    spec = dict(getattr(vs, "spec", None) or {})
    raw_phases = [str(p) for p in (spec.get("phases") or []) if str(p).strip()]

    body = list(getattr(sl, "body_outline", None) or [])
    # body: "1. Phase ..." 단계 줄 + 모니터링/재학습 줄
    caps = [
        re.sub(r"^\d+\.\s*", "", b) for b in body if re.match(r"^\d+\.\s*", str(b))
    ]
    extra = [b for b in body if not re.match(r"^\d+\.\s*", str(b))]

    phases = []
    for i, ph in enumerate((raw_phases or caps or ["Phase 1", "Phase 2", "Phase 3"])[:3]):
        cap = ""
        if i < len(caps) and raw_phases:
            cap = caps[i]
        elif i < len(extra):
            cap = str(extra[i])
        phases.append({"title": str(ph)[:28], "caption": str(cap)[:80]})

    # UPGRADE 3종 — 실데이터 기반 (재학습 / 취약 세그먼트 보강 / 앙상블)
    upgrades = []
    _re_line = next((str(b) for b in extra if "재학습" in str(b)), "")
    upgrades.append({
        "title": "재학습 트리거",
        "caption": _re_line.split("·", 1)[-1].strip() if _re_line else "분기별 정기 또는 drift > 0.1 시 자동 재학습",
    })
    try:
        segs = sorted(
            [s for s in (ctx.evaluation.per_segment or []) if isinstance(s, dict) and s.get("value") is not None],
            key=lambda s: float(s["value"]),
        )
        if segs:
            upgrades.append({
                "title": "취약 세그먼트 보강",
                "caption": f"{segs[0].get('segment', '?')} (acc {float(segs[0]['value']):.2f}) 구간 피처 보강·재검증",
            })
    except Exception:
        pass
    if len(upgrades) < 2:
        upgrades.append({"title": "피처 보강", "caption": "결측 상위 변수 파생·외부 데이터 결합 검토"})
    chosen = (ctx.model_selection.chosen or {}).get("name", "")
    upgrades.append({
        "title": "모델 앙상블",
        "caption": f"{chosen or '선정 모델'} + 차점 후보 stacking 으로 추가 향상 여지",
    })
    I.draw_roadmap_with_upgrades(slide, phases, upgrades[:3], primary, accent, ink, muted, light_bg)


def t_icon_columns(slide, sl, ctx, primary, accent, ink, muted, light_bg):
    """견본 S15 — 2~4 컬럼 종합 (TAG + 라벨 + 글리프 + 본문)."""
    tags = ("DATA", "PATTERN", "MODEL", "ACTION")
    glyphs = ("data", "chart", "settings", "target")
    items = []
    for i, line in enumerate(sl.body_outline[:4]):
        label, text = _split_label(line, fallback=tags[i].title())
        items.append({"tag": tags[i], "label": label, "glyph": glyphs[i], "text": text})
    I.draw_icon_columns(slide, items, primary, accent, ink, muted, light_bg)


def register_phase12() -> None:
    from outputs.carriers.template_registry import (
        REGISTRY,
        combine,
        has_body_min,
        has_id,
        matches_keywords,
    )

    if REGISTRY.get("chart_key_insights"):
        return

    def fit_chart_key_insights(sl, c):
        # 차트 (visual_spec) 가 있어야 의미 있는 레이아웃
        if not getattr(sl, "visual_spec", None):
            return 0.0
        # jh 2026-06-12 — CM(S15)은 수치만 있으면 히트맵을 직접 그리므로 고정 라우팅
        # (디자이너가 비차트 템플릿을 골라 S15 가 텍스트만 남던 변동성 차단)
        if getattr(sl, "id", "") == "insights_derived":
            return 96.0
        if getattr(sl, "layout", "") == "chart_callout":
            return 85.0
        return 70.0 if getattr(sl, "role", "") == "evidence" else 55.0

    REGISTRY.register(
        "chart_key_insights",
        t_chart_key_insights,
        fit=fit_chart_key_insights,
        tags=["chart", "evidence", "insights"],
    )
    REGISTRY.register(
        "solution_overview",
        t_solution_overview,
        fit=combine(
            matches_keywords("솔루션", "파이프라인", "모델 구성", "solution"),
            has_body_min(3),
            mode="sum",
        ),
        min_score=60.0,
        tags=["solution", "architecture"],
    )
    REGISTRY.register(
        "lineage_2col",
        t_lineage_2col,
        fit=combine(
            matches_keywords("아키텍처", "lineage", "데이터 흐름", "전처리 흐름"),
            has_body_min(4),
            mode="sum",
        ),
        min_score=60.0,
        tags=["architecture", "flow"],
    )
    def fit_icon_columns(sl, c):
        # jh 2026-06-12 — 인사이트 종합 장은 고정 라우팅
        if getattr(sl, "id", "") == "insight_synthesis":
            return 96.0
        base = combine(
            matches_keywords("가설 입증", "인사이트", "의의", "종합", "발견"),
            has_body_min(2),
            mode="sum",
        )
        return base(sl, c)

    REGISTRY.register(
        "icon_columns",
        t_icon_columns,
        fit=fit_icon_columns,
        min_score=60.0,
        tags=["insight", "summary", "columns"],
    )

    # jh 2026-06-12 — 목표치 덱 S3 이식: Executive Summary 전용 레이아웃.
    # skeleton 이 exec_summary_v32 visual_spec (findings/method/perf/limitation)
    # 을 만들고 있었으나 carrier 템플릿이 없어 big_stats 로 폴백되던 결함.
    def fit_exec_summary(sl, c):
        vs = getattr(sl, "visual_spec", None)
        if getattr(vs, "type", "") == "exec_summary_v32":
            return 98.0
        if getattr(sl, "id", "") == "exec_summary":
            return 90.0
        return 0.0

    REGISTRY.register(
        "exec_summary_v32",
        t_exec_summary_v32,
        fit=fit_exec_summary,
        min_score=85.0,
        tags=["summary", "executive"],
    )

    # jh 2026-06-12 — 재료는 있는데 잘못된 템플릿이 가로채던 3장 (S7·S17·S19)
    # 슬라이드 id 고정 매칭으로 결정적 라우팅 (디자이너 LLM 변동성 차단).
    REGISTRY.register(
        "method_5step",
        t_method_5step,
        fit=has_id("p3_alt_limits"),
        min_score=80.0,
        tags=["method", "process"],
    )
    REGISTRY.register(
        "policy_steps",
        t_policy_steps,
        fit=has_id("i3_roi"),
        min_score=80.0,
        tags=["policy", "action"],
    )
    REGISTRY.register(
        "roadmap_upgrades",
        t_roadmap_upgrades,
        fit=has_id("roadmap"),
        min_score=80.0,
        tags=["roadmap", "action"],
    )

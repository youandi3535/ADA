"""outputs.architect.skeletons.report_skeleton — 데이터 분석 종합 보고서 Skeleton.

기존 ``*_pitch.py`` (설득용 발표 deck) 와 달리, **문서형 종합 보고서**를 생성한다.
같은 ``ReportContext`` (13묶음) 를 입력받되, 목차를 분석 절차 순서로 전개:

    §1 표지            (front_matter, cover)        ← carrier 가 자체 헤더 렌더 (스킵됨)
    §2 Executive Summary                             ← narrative_thread 로 carrier 자동 렌더
    §3 데이터 개요·변수정의   (data_overview, context)
    §4 데이터 품질·전처리     (quality_prep, evidence)
    §5 탐색적 데이터 분석     (eda, evidence)
    §6 모델 선정·평가 결과    (model_result, evidence)
    §7 결론 및 권고          (conclusion, recommendation)

설계 원칙:
    - 덱(pitch) 과 목적 분리: "설득" 이 아니라 "망라적 기록·재현". 중립 서술.
    - 신형 엔진 재사용: 표/바/KPI 는 outputs.visuals.render 가 그림. 폰트·팔레트 공유.
    - silent-safe: ctx 묶음이 비어도 해당 섹션은 빈 채로 두거나 스킵 (carrier 가 빈 섹션 처리).
    - §7 결론은 (a) 합성 방식 — insights/limitations/interpretation 을 조합, 별도 LLM 호출 없음.

NY (HJ 위임) 2026-06 — PDF OUT-02 보고서 레시피. carrier 직접 호출 경로용 (build_plan 우회).
"""

from __future__ import annotations

from typing import Any, Optional

from outputs.architect.plan import (
    NarrativeThread,
    ReportPlan,
    SectionSpec,
    SlideSpec,
    VisualSpec,
)
from outputs.context.schema import ReportContext

SKELETON_NAME = "Report"

# 길이 가드 — 변수정의표·전처리표·EDA 차트 폭주 방지 (cap)
_MAX_DICT_ROWS = 30
_MAX_PREP_ROWS = 12
_MAX_EDA_SLIDES = 4
_MAX_BODY = 6


# ==============================================================
# 포맷 헬퍼
# ==============================================================
def _fv(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}" if 0 < abs(v) < 1 else f"{v:,.2f}"
    return str(v)


def _pct(v: Any) -> str:
    try:
        return f"{float(v) * 100:.1f}%"
    except Exception:
        return "-"


def make_section(
    section_id: str,
    title: str,
    kind: str,
    slides: list[SlideSpec],
    summary: str = "",
) -> SectionSpec:
    return SectionSpec(
        id=section_id,
        title=title,
        kind=kind,
        divider_required=False,
        short_summary=summary or title,
        slides=slides,
    )


# ==============================================================
# 섹션 빌더 — 각 섹션이 ctx 의 어떤 묶음을 읽는지 1:1
# ==============================================================
def _build_cover(ctx: ReportContext) -> SectionSpec:
    intent = (ctx.meta.user_intent or ctx.meta.user_question or "데이터 분석 종합 보고서").strip()
    cover = SlideSpec(
        id="cover",
        section_id="front_matter",
        layout="cover",
        role="meta",
        title_ko=intent[:40],
        body_outline=[
            f"카테고리: {ctx.meta.category or '-'}",
            f"데이터셋: {ctx.dataset.dataset_name or '미지정'}",
            f"분류등급: {ctx.meta.classification}",
        ],
    )
    return make_section("front_matter", "표지", "cover", [cover])


def _data_dictionary_visual(ctx: ReportContext) -> Optional[VisualSpec]:
    """§3 변수정의 표 — dataset.dtypes + missing_rate + domain.glossary."""
    dtypes = ctx.dataset.dtypes or {}
    if not dtypes:
        return None
    missing = ctx.dataset.missing_rate or {}
    glossary = (ctx.domain.glossary or {}) if ctx.domain else {}
    rows: list[list[str]] = []
    for col, dt in list(dtypes.items())[:_MAX_DICT_ROWS]:
        rows.append([str(col), str(dt), _pct(missing.get(col, 0)), str(glossary.get(col, ""))[:30]])
    return VisualSpec(
        type="table_feature_matrix",
        title="변수 정의서",
        caption="컬럼별 타입·결측률·의미",
        spec={"columns": ["변수", "타입", "결측률", "의미"], "rows": rows},
    )


def _build_data_overview(ctx: ReportContext) -> SectionSpec:
    ds = ctx.dataset
    shape = ds.shape or {}
    n_rows, n_cols = shape.get("rows", 0), shape.get("cols", 0)
    target = ds.detected_target or "-"
    # 결측 상위 3
    missing = ds.missing_rate or {}
    top_missing = sorted(missing.items(), key=lambda kv: -kv[1])[:3]
    miss_txt = ", ".join(f"{c} {_pct(r)}" for c, r in top_missing if r > 0) or "결측 없음"
    body = [
        f"데이터 규모: {n_rows:,}행 × {n_cols}열",
        f"분석 타깃: {target}",
        f"결측 상위: {miss_txt}",
    ]
    slide = SlideSpec(
        id="data_overview",
        section_id="data_overview",
        layout="comparison_table",
        role="evidence",
        so_what=f"{n_rows:,}건 {n_cols}개 변수 데이터로, 타깃 '{target}' 예측 분석을 수행한다",
        title_ko="데이터 개요 및 변수 정의",
        body_outline=body,
        visual_spec=_data_dictionary_visual(ctx),
    )
    return make_section("data_overview", "1. 데이터 개요", "context", [slide])


def _preprocessing_visual(ctx: ReportContext) -> Optional[VisualSpec]:
    steps = (ctx.preprocessing.applied_steps or []) if ctx.preprocessing else []
    if not steps:
        return None
    rows: list[list[str]] = []
    for i, st in enumerate(steps[:_MAX_PREP_ROWS], 1):
        op = getattr(st, "op", "") or (st.get("op", "") if isinstance(st, dict) else "")
        scope = getattr(st, "scope", None) or (st.get("scope", []) if isinstance(st, dict) else [])
        rationale = getattr(st, "rationale", "") or (st.get("rationale", "") if isinstance(st, dict) else "")
        rows.append([str(i), str(op), ", ".join(map(str, scope))[:24], str(rationale)[:40]])
    return VisualSpec(
        type="table_feature_matrix",
        title="전처리 단계",
        caption="적용 순서·대상·근거",
        spec={"columns": ["#", "단계", "대상", "근거"], "rows": rows},
    )


def _build_quality_prep(ctx: ReportContext) -> SectionSpec:
    issues = (ctx.eda.data_quality_issues or []) if ctx.eda else []
    body: list[str] = []
    for it in issues[:_MAX_BODY]:
        if isinstance(it, dict):
            body.append(f"{it.get('issue', '품질 이슈')} (심각도: {it.get('severity', 'medium')})")
    if not body:
        body = ["식별된 데이터 품질 이슈 없음"]
    slide = SlideSpec(
        id="quality_prep",
        section_id="quality_prep",
        layout="comparison_table",
        role="evidence",
        so_what="결측·이상치를 점검하고 모델 입력에 적합하도록 전처리를 적용했다",
        title_ko="데이터 품질 및 전처리",
        body_outline=body,
        visual_spec=_preprocessing_visual(ctx),
    )
    return make_section("quality_prep", "2. 데이터 품질·전처리", "evidence", [slide])


def _build_eda(ctx: ReportContext) -> Optional[SectionSpec]:
    charts = (ctx.eda.charts or []) if ctx.eda else []
    slides: list[SlideSpec] = []
    for idx, ch in enumerate(charts[:_MAX_EDA_SLIDES]):
        title_ko = getattr(ch, "title_ko", "") or f"탐색 분석 {idx + 1}"
        finding = getattr(ch, "finding", "") or ""
        numbers = getattr(ch, "numbers", None) or []
        items = [(str(d.get("name", "")), d.get("value", 0)) for d in numbers if isinstance(d, dict)]
        vs = None
        if items:
            vs = VisualSpec(type="chart_bar", title=title_ko, caption=finding[:60], spec={"items": items})
        slides.append(
            SlideSpec(
                id=f"eda_{idx}",
                section_id="eda",
                layout="chart_callout",
                role="evidence",
                so_what=finding[:90],
                title_ko=title_ko,
                body_outline=[finding] if finding else [],
                visual_spec=vs,
            )
        )
    if not slides:
        return None
    return make_section("eda", "3. 탐색적 데이터 분석 (EDA)", "evidence", slides)


def _build_model_result(ctx: ReportContext) -> SectionSpec:
    ms = ctx.model_selection
    ev = ctx.evaluation
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    # 모델 비교 바 — candidates score
    cand_items = []
    for c in (ms.candidates or []) if ms else []:
        name = getattr(c, "name", "") or (c.get("name", "") if isinstance(c, dict) else "")
        score = getattr(c, "score", None)
        if score is None and isinstance(c, dict):
            score = c.get("score")
        if name and score is not None:
            cand_items.append((str(name), float(score)))
    metrics = (ev.metrics or {}) if ev else {}
    metric_body = [f"{k}: {_fv(m.get('value'))}" for k, m in list(metrics.items())[:_MAX_BODY]]
    slides: list[SlideSpec] = []
    slides.append(
        SlideSpec(
            id="model_compare",
            section_id="model_result",
            layout="chart_callout",
            role="evidence",
            so_what=f"후보 모델 비교 결과 '{chosen}' 이 최적 성능을 보였다",
            title_ko="모델 선정 및 성능",
            body_outline=([f"선정 모델: {chosen}"] + metric_body) or [f"선정 모델: {chosen}"],
            visual_spec=(
                VisualSpec(type="chart_bar", title="후보 모델 비교 (ROC-AUC)", spec={"items": cand_items})
                if cand_items
                else None
            ),
        )
    )
    # 변수 중요도 바
    gi = (ctx.interpretation.global_importance or []) if ctx.interpretation else []
    imp_items = []
    for g in gi[:6]:
        feat = getattr(g, "feature", "") or (g.get("feature", "") if isinstance(g, dict) else "")
        imp = getattr(g, "importance", None)
        if imp is None and isinstance(g, dict):
            imp = g.get("importance")
        if feat and imp is not None:
            imp_items.append((str(feat), float(imp)))
    if imp_items:
        top_feats = ", ".join(f for f, _ in imp_items[:3])
        slides.append(
            SlideSpec(
                id="feat_importance",
                section_id="model_result",
                layout="chart_callout",
                role="evidence",
                so_what=f"예측에 가장 크게 기여한 변수는 {top_feats} 순이다",
                title_ko="변수 중요도",
                body_outline=[f"상위 기여 변수: {top_feats}"],
                visual_spec=VisualSpec(type="chart_bar", title="변수 중요도", spec={"items": imp_items}),
            )
        )
    return make_section("model_result", "4. 모델 선정 및 평가", "evidence", slides)


def _build_conclusion(ctx: ReportContext) -> SectionSpec:
    """§7 결론·권고 — (a) 합성: chosen + metric + limitations + interpretation."""
    ms = ctx.model_selection
    ev = ctx.evaluation
    chosen = (ms.chosen or {}).get("name", "-") if ms else "-"
    pm = (ev.primary_metric or {}) if ev else {}
    pm_txt = f"{pm.get('name', '주요지표')} {_fv(pm.get('value'))}" if pm else "-"

    body: list[str] = [f"결론: '{chosen}' 모델이 {pm_txt} 수준으로 타깃을 예측한다"]
    # 권고 — interpretation per_feature_story 또는 global_importance 기반
    gi = (ctx.interpretation.global_importance or []) if ctx.interpretation else []
    if gi:
        top = getattr(gi[0], "feature", "") or (gi[0].get("feature", "") if isinstance(gi[0], dict) else "")
        if top:
            body.append(f"권고: 핵심 변수 '{top}' 중심의 추가 수집·피처 강화 시 성능 개선 여지")
    body.append("권고: 운영 적용 시 정기 재학습으로 분포 변화 대응")
    # 한계 — limitations
    lims = ctx.limitations
    caveats = (getattr(lims, "model_caveats", None) or []) if lims else []
    for cav in caveats[:2]:
        body.append(f"한계: {cav}")
    gaps = (getattr(lims, "data_gaps", None) or []) if lims else []
    for g in gaps[:1]:
        desc = getattr(g, "description", "") or (g.get("description", "") if isinstance(g, dict) else "")
        if desc:
            body.append(f"한계: {desc}")

    slide = SlideSpec(
        id="conclusion",
        section_id="conclusion",
        layout="one_message",
        role="action",
        so_what=f"'{chosen}' 모델 도입 시 {pm_txt} 수준의 예측 성능을 기대할 수 있다",
        title_ko="결론 및 권고",
        body_outline=body[: _MAX_BODY + 2],
    )
    return make_section("conclusion", "5. 결론 및 권고", "recommendation", [slide])


# ==============================================================
# Main builder
# ==============================================================
def build(
    ctx: ReportContext,
    audience_profile: Optional[dict[str, Any]] = None,
    length_target: int = 12,
) -> ReportPlan:
    """Report Skeleton → ReportPlan (문서형 종합 보고서).

    pitch skeleton 과 달리 슬라이드 수 강제 없음 — 섹션이 곧 보고서 챕터.
    carrier(pdf_carrier) 가 cover/agenda 메타를 스킵하고 자체 헤더를 렌더하므로,
    실 내용은 §3~§7 섹션에 담긴다.
    """
    ds = ctx.dataset
    shape = ds.shape or {}
    n_rows = shape.get("rows", 0)
    target = ds.detected_target or "타깃"
    chosen = (ctx.model_selection.chosen or {}).get("name", "-") if ctx.model_selection else "-"
    pm = (ctx.evaluation.primary_metric or {}) if ctx.evaluation else {}
    pm_txt = f"{pm.get('name', '주요지표')}={_fv(pm.get('value'))}" if pm else "-"

    # 품질 이슈 요약 (narrative conflict 용)
    issues = (ctx.eda.data_quality_issues or []) if ctx.eda else []
    issue_txt = "; ".join(str(it.get("issue", "")) for it in issues[:2] if isinstance(it, dict)) or "데이터 품질 점검 완료"

    narrative = NarrativeThread(
        setup=f"{ds.dataset_name or '데이터셋'}({n_rows:,}행)을 대상으로 '{target}' 예측 분석을 수행했다.",
        conflict=f"분석 과정에서 {issue_txt} 등 전처리가 필요한 이슈를 확인했다.",
        resolution=f"전처리 후 모델을 학습한 결과 '{chosen}' 모델이 {pm_txt} 로 최적 성능을 보였다.",
    )

    sections: list[SectionSpec] = [_build_cover(ctx)]
    sections.append(_build_data_overview(ctx))
    sections.append(_build_quality_prep(ctx))
    eda = _build_eda(ctx)
    if eda is not None:
        sections.append(eda)
    sections.append(_build_model_result(ctx))
    sections.append(_build_conclusion(ctx))

    plan = ReportPlan(
        skeleton=SKELETON_NAME,
        audience=(audience_profile or {}).get("level", "analyst") if audience_profile else "analyst",
        output_form="pdf",
        slide_count_target=sum(len(s.slides) for s in sections),
        sections=sections,
        narrative_thread=narrative,
        meta={"skeleton": SKELETON_NAME, "report_mode": True},
    )
    return plan

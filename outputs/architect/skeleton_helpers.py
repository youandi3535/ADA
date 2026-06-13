"""outputs.architect.skeleton_helpers — 카테고리 무관 공통 슬라이드 헬퍼.

ml_pitch / dl_pitch / timeseries_pitch / anomaly_pitch 4개 skeleton 이
공통으로 사용하는 generic 빌더·포매터·텍스트 헬퍼 모음.

* 카테고리 자동 적응 — substitution_manifest 의 resolve_slide / resolve_tech_stack /
  resolve_verdict_tone 를 호출하여 카테고리별 변형은 모두 매니페스트에서 흡수.
* 단위 일관성 — format_metric / format_delta 로 모든 수치 표기 통일.
* 자동 추론 라벨 — domain_source='auto' 인 경우 [auto-inferred] 마커 자동 부착.

본 모듈은 *공통 골격* 만 다루며 카테고리별 *고유 톤* (ML 도메인 프로필 등) 은
각 skeleton 안에 유지.
"""

from __future__ import annotations

from typing import Any, Optional

from outputs.architect.plan import SlideSpec, VisualSpec
from outputs.architect.substitution_manifest import (
    VerdictTone,
    resolve_slide,
    resolve_verdict_tone,
)
from outputs.context.schema import ReportContext
from outputs.style.text_budget import format_delta, format_metric

# ==============================================================
# 1) verdict / 자동 도메인 라벨
# ==============================================================


def get_verdict_tone(ctx: ReportContext) -> VerdictTone:
    """ctx.evaluation.verdict → VerdictTone (미정/미지원 시 adopt 폴백)."""
    v = getattr(ctx.evaluation, "verdict", "") or ""
    return resolve_verdict_tone(v)


def is_auto_domain(ctx: ReportContext) -> bool:
    """도메인 해석이 *자동 추론* 인지 여부."""
    src = getattr(ctx.domain, "domain_source", "auto") or "auto"
    return src.strip().lower() == "auto"


def auto_label(text: str, ctx: ReportContext) -> str:
    """자동 추론 도메인 텍스트에 ``[auto-inferred]`` 마커 부착 (인용 면제 표시)."""
    if not text:
        return text
    if not is_auto_domain(ctx):
        return text
    marker = "[auto-inferred]"
    if marker in text:
        return text
    return f"{text} {marker}"


# ==============================================================
# 2) 단위 일관 포매터
# ==============================================================


def format_pm_value(pm: dict[str, Any]) -> str:
    """primary_metric 값을 format_metric 으로 안전 포매팅."""
    name = pm.get("name", "primary")
    raw = pm.get("value")
    if raw is None:
        return "-"
    try:
        return format_metric(float(raw), str(name))
    except (TypeError, ValueError):
        return str(raw)


# ==============================================================
# 3) Dataset / Target 요약
# ==============================================================


def summarize_dtypes(ctx: ReportContext) -> str:
    """dataset.dtypes 의 numeric/categorical/text 카운트 1줄 요약."""
    dtypes = ctx.dataset.dtypes or {}
    if not dtypes:
        return "타입 정보 없음"
    num_count = sum(
        1 for v in dtypes.values()
        if str(v).lower() in {"int", "int64", "float", "float64", "number", "numeric"}
    )
    cat_count = sum(
        1 for v in dtypes.values()
        if str(v).lower() in {"object", "category", "categorical", "str", "string"}
    )
    other = len(dtypes) - num_count - cat_count
    parts: list[str] = []
    if num_count:
        parts.append(f"수치 {num_count}")
    if cat_count:
        parts.append(f"범주 {cat_count}")
    if other:
        parts.append(f"기타 {other}")
    return " · ".join(parts)


def _safe_value(item: Any) -> str:
    """categorical_top 항목에서 value 안전 추출."""
    if isinstance(item, dict):
        return str(item.get("value", item.get("name", "?")))
    if isinstance(item, (list, tuple)) and len(item) >= 1:
        return str(item[0])
    return str(item)


def _safe_count(item: Any) -> int:
    """categorical_top 항목에서 count 안전 추출."""
    if isinstance(item, dict):
        try:
            return int(item.get("count", item.get("freq", 0)) or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        try:
            return int(item[1])
        except (TypeError, ValueError):
            return 0
    return 0


def summarize_target(ctx: ReportContext) -> str:
    """dataset.detected_target 의 분포 요약."""
    target = ctx.dataset.detected_target
    if not target:
        return "타겟 미감지"
    cat_top = (ctx.dataset.categorical_top or {}).get(target, [])
    if cat_top:
        total = sum(_safe_count(it) for it in cat_top) or 1
        parts: list[str] = []
        for it in cat_top[:3]:
            val = _safe_value(it)
            cnt = _safe_count(it)
            parts.append(f"{val} {cnt/total*100:.1f}%")
        return " · ".join(parts) if parts else f"{target} (분포 미산출)"
    num_stats = (ctx.dataset.numeric_stats or {}).get(target, {})
    if num_stats:
        mean = num_stats.get("mean")
        std = num_stats.get("std")
        if mean is not None and std is not None:
            return f"{target} 평균 {mean:.2f} ± {std:.2f}"
    return f"타겟 {target}"


# ==============================================================
# 4) EDA 차트 선정 + KEY INSIGHTS 추출
# ==============================================================


def select_top_eda_charts(ctx: ReportContext, n: int = 3) -> list[Any]:
    """Top N EDAChart 선정 — severity → finding 길이 → 입력 순서."""
    charts = list(ctx.eda.charts or [])
    if not charts:
        return []
    sev_order = {"critical": 0, "important": 1, "info": 2}
    indexed = [(i, c) for i, c in enumerate(charts)]
    indexed.sort(key=lambda t: (
        sev_order.get(getattr(t[1], "severity", "info"), 2),
        -len(getattr(t[1], "finding", "") or ""),
        t[0],
    ))
    return [c for _, c in indexed[:n]]


def eda_key_insights(chart: Any, ctx: ReportContext) -> list[str]:
    """EDAChart 의 callouts·numbers·finding 을 KEY INSIGHTS 5줄로."""
    insights: list[str] = []
    for callout in (getattr(chart, "callouts", None) or [])[:5]:
        if isinstance(callout, dict):
            text = callout.get("text", "") or ""
        else:
            text = str(callout)
        if text:
            insights.append(auto_label(text, ctx))
    if not insights:
        for num in (getattr(chart, "numbers", None) or [])[:5]:
            if isinstance(num, dict):
                name = num.get("name", "")
                val = num.get("value", "")
                if name or val:
                    insights.append(f"{name} {val}")
    finding = getattr(chart, "finding", "") or ""
    if finding and finding not in insights:
        insights.append(auto_label(finding, ctx))
    return insights[:5]


def build_eda_slide_from_chart(
    chart: Any,
    slide_id: str,
    slide_index: int,
    ctx: ReportContext,
    role_key: str,
    section_id: str = "solution",
    parent_message_id: Optional[str] = "solution_root",
) -> SlideSpec:
    """단일 EDAChart → chart_callout SlideSpec.

    substitution_manifest.resolve_slide(role_key, category) 로 title 변형 적응.
    section_id / parent_message_id 는 호출 측 skeleton 에서 override.
    """
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide(role_key, category)

    feature = getattr(chart, "x", None) or getattr(chart, "title_ko", "") or f"Feature {slide_index}"
    # 2026-06-11 jh — 핸들러 meta 의 구체 제목 (예: "결측률 상위 피처") 이 있으면
    # manifest 의 generic 제목 ("EDA · 주요 변수 N") 보다 우선.
    _chart_title = getattr(chart, "title_ko", "") or ""
    title_ko = (
        (f"EDA · {_chart_title}" if _chart_title else "")
        or (variant.title_ko if variant else None)
        or f"EDA · {feature}"
    )
    finding = getattr(chart, "finding", "") or ""
    so_what = auto_label(finding, ctx) if finding else f"{feature} 의 핵심 분포·패턴 발견"

    insights = eda_key_insights(chart, ctx)
    body = insights if insights else [f"{feature} — 분석 결과 적립 후 채워짐"]

    chart_type = getattr(chart, "chart_type", "") or (
        variant.visual_type if variant else "chart_annotated_bar"
    )
    ref_id = getattr(chart, "ref_id", None)

    sp = SlideSpec(
        id=slide_id,
        section_id=section_id,
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence",
        so_what=so_what,
        title_ko=title_ko,
        body_outline=body,
        parent_message_id=parent_message_id,
        required_refs=[ref_id] if ref_id else [],
        visual_spec=VisualSpec(
            type=chart_type,
            title=title_ko,
            spec={
                "chart_path": getattr(chart, "path", "") or "",
                "x": getattr(chart, "x", None),
                "y": getattr(chart, "y", None),
                "numbers": list(getattr(chart, "numbers", None) or []),
                "callouts": list(getattr(chart, "callouts", None) or []),
                "severity": getattr(chart, "severity", "info"),
            },
        ),
        speaker_notes_hint=(
            f"EDA #{slide_index} — {feature}. finding: {finding[:80]}. "
            "KEY INSIGHTS 는 callouts → numbers → finding 순서로 자동 채워짐."
        ),
    )
    # jh 2026-06-12 — EDA 슬라이드는 차트+KEY INSIGHTS 고정 (LLM 디자이너가
    # body 의 "74.2% vs 18.9%" 의 'vs' 를 보고 split_compare 로 가로채던 결함 차단).
    sp.preferred_template = "chart_key_insights"
    return sp


def build_eda_placeholder(
    slide_id: str,
    slide_index: int,
    ctx: ReportContext,
    role_key: str,
    section_id: str = "solution",
    parent_message_id: Optional[str] = "solution_root",
) -> SlideSpec:
    """ctx.eda.charts 가 빈 경우의 placeholder."""
    category = ctx.meta.category or "tabular_ml"
    variant = resolve_slide(role_key, category)
    title_ko = (variant.title_ko if variant else f"EDA · 슬라이드 {slide_index}")
    return SlideSpec(
        id=slide_id,
        section_id=section_id,
        layout=(variant.layout if variant else "chart_callout"),
        role="evidence",
        so_what=f"EDA {slide_index} — 분석 결과 적립 후 채워짐",
        title_ko=title_ko,
        body_outline=["분석 결과 적립 후 채워짐"],
        parent_message_id=parent_message_id,
        visual_spec=VisualSpec(
            type=(variant.visual_type if variant else "chart_annotated_bar"),
            title=title_ko,
            spec={"chart_path": "", "placeholder": True},
        ),
        speaker_notes_hint=f"EDA #{slide_index} placeholder — ctx.eda.charts 적립 시 자동 채워짐.",
    )


# ==============================================================
# 5) 파생 피처
# ==============================================================


def derived_features_richness(ctx: ReportContext) -> int:
    """파생 피처의 *정보 풍부도* 점수 (name 1 + rationale 2 + formula 2 + importance 1)."""
    feats = list(ctx.features.created or [])
    if not feats:
        return 0
    score = 0
    for f in feats:
        score += 1
        if getattr(f, "rationale", "") or "":
            score += 2
        if getattr(f, "formula", "") or "":
            score += 2
        if getattr(f, "importance", None) is not None:
            score += 1
    return score


def build_derived_features_slide(
    ctx: ReportContext,
    slide_id: str,
    section_id: str = "solution",
    parent_message_id: Optional[str] = "solution_root",
) -> SlideSpec:
    """파생 피처 표 슬라이드 — name / formula / rationale / importance + dropped."""
    feats = list(ctx.features.created or [])[:6]
    items: list[dict[str, Any]] = []
    body: list[str] = []
    for f in feats:
        name = getattr(f, "name", "") or "?"
        formula = getattr(f, "formula", "") or ""
        rationale = getattr(f, "rationale", "") or ""
        importance = getattr(f, "importance", None)
        items.append({
            "name": name,
            "formula": formula,
            "rationale": rationale,
            "importance": importance,
        })
        imp_str = ""
        if importance is not None:
            try:
                imp_str = f" · {format_metric(float(importance), 'shap', as_percent=False, decimals=2)}"
            except (TypeError, ValueError):
                pass
        body.append(f"{name}{imp_str}" + (f" · {rationale}" if rationale else ""))

    dropped = list(ctx.features.dropped or [])[:3]
    dropped_items: list[dict[str, str]] = []
    for d in dropped:
        if isinstance(d, dict):
            dropped_items.append({
                "name": str(d.get("name", "")),
                "reason": str(d.get("reason", "")),
            })

    return SlideSpec(
        id=slide_id,
        section_id=section_id,
        layout="derived_features_table",
        role="evidence",
        so_what=(
            f"파생 피처 {len(items)}개 — 각 피처의 *공식·근거·중요도* 트레이스"
            + (f" (시도 후 폐기 {len(dropped_items)}개)" if dropped_items else "")
        ),
        title_ko="파생 피처 엔지니어링",
        body_outline=body[:5],
        parent_message_id=parent_message_id,
        visual_spec=VisualSpec(
            type="v28_derived_features",
            title="파생 피처 엔지니어링",
            spec={
                "features": items,
                "dropped": dropped_items,
                "selection_method": ctx.features.selection_method or "",
                "final_count": ctx.features.final_feature_count or len(items),
            },
        ),
        speaker_notes_hint=(
            "파생 피처 표 — name / formula / rationale / importance. "
            "EDA-Extra 슬롯이 풍부도 점수 ≥ 5 이면 본 슬라이드로 전환."
        ),
    )


# ==============================================================
# 6) Method Flow (분석 방법 단계 + WHY 카드) — 공통
# ==============================================================


def build_method_steps(ctx: ReportContext) -> list[dict[str, str]]:
    """분석 방법 흐름의 5 단계 — 좌측 미니 흐름도 입력."""
    steps: list[dict[str, str]] = []
    pp_steps = list(ctx.preprocessing.applied_steps or [])
    if pp_steps:
        steps.append({"label": f"전처리 ({len(pp_steps)}단계)", "kind": "preprocessing"})
    feats = list(ctx.features.created or [])
    if feats:
        steps.append({"label": f"신규 피처 {len(feats)}개", "kind": "feature"})
    chosen_name = (ctx.model_selection.chosen or {}).get("name") or ""
    if chosen_name:
        steps.append({"label": f"모델 {chosen_name}", "kind": "model"})
    if ctx.training.runs:
        steps.append({"label": "학습 · 튜닝", "kind": "training"})
    if ctx.evaluation.primary_metric:
        steps.append({"label": "평가 · 검증", "kind": "evaluation"})
    if not steps:
        steps = [
            {"label": "1 · 전처리", "kind": "preprocessing"},
            {"label": "2 · 피처 엔지니어링", "kind": "feature"},
            {"label": "3 · 모델 선정", "kind": "model"},
            {"label": "4 · 학습", "kind": "training"},
            {"label": "5 · 평가", "kind": "evaluation"},
        ]
    return steps[:5]


def build_method_whys(ctx: ReportContext) -> list[dict[str, str]]:
    """우측 WHY 카드 4개 — (header, what, why, result)."""
    cards: list[dict[str, str]] = []

    # ① 전처리
    for ps in (ctx.preprocessing.applied_steps or [])[:1]:
        op = getattr(ps, "op", "") or "전처리"
        scope = ", ".join(getattr(ps, "scope", []) or [])
        rationale = getattr(ps, "rationale", "") or ""
        before = getattr(ps, "before_stats", {}) or {}
        after = getattr(ps, "after_stats", {}) or {}
        what = f"{op}" + (f" · {scope}" if scope else "")
        result = ""
        for key in ("missing_rate", "missing", "std", "mean"):
            if key in before and key in after:
                result = f"{key}: {before[key]} → {after[key]}"
                break
        if not result:
            result = "before / after 통계 적립 완료"
        cards.append({
            "header": f"단계 1 · {op}",
            "what": what,
            "why": rationale or "데이터 분포 보강 — 모델 학습 안정성 향상",
            "result": result,
        })

    # ② 피처 엔지니어링
    feats = list(ctx.features.created or [])
    if feats:
        top = feats[:3]
        names = " · ".join(getattr(f, "name", "") or "" for f in top)
        rationale = next(
            (getattr(f, "rationale", "") for f in top if getattr(f, "rationale", "")),
            "",
        )
        cards.append({
            "header": f"단계 2 · 신규 피처 {len(feats)}개",
            "what": names or f"피처 {len(feats)}개 추가",
            "why": rationale or "비선형·상호작용 신호 포착 — 단일 변수로 못 잡는 패턴",
            "result": f"최종 피처 수 {ctx.features.final_feature_count or len(feats)}",
        })

    # ③ 모델 선정
    chosen = ctx.model_selection.chosen or {}
    chosen_name = chosen.get("name") or ""
    if chosen_name:
        justification = chosen.get("justification") or ""
        candidates = ctx.model_selection.candidates or []
        result_lines: list[str] = []
        for c in candidates[:2]:
            c_name = getattr(c, "name", "")
            c_score = getattr(c, "score", None)
            if c_name and c_score is not None:
                result_lines.append(f"{c_name} {c_score:.3f}")
        result = " / ".join(result_lines) if result_lines else (
            f"후보 {len(candidates)}개 비교 후 선택"
        )
        cards.append({
            "header": "단계 3 · 모델 선정",
            "what": chosen_name,
            "why": justification or "후보 모델 비교 — 본 데이터 특성에 가장 적합",
            "result": result,
        })

    # ④ 검증 방식
    runs = ctx.training.runs or []
    baseline = ctx.model_selection.baselines.naive or {}
    pm = ctx.evaluation.primary_metric or {}
    if runs or pm or baseline:
        split = "80/20 hold-out + Baseline 직접 비교"
        if runs:
            hp = getattr(runs[0], "hyperparameters", {}) or {}
            split = str(hp.get("split", split))
        result = ""
        if baseline and pm:
            b_score = baseline.get("score")
            p_val = pm.get("value")
            if b_score is not None and p_val is not None:
                try:
                    delta = float(p_val) - float(b_score)
                    result = (
                        f"룰 {format_metric(float(b_score), pm.get('name', ''))} → "
                        f"모델 {format_metric(float(p_val), pm.get('name', ''))} "
                        f"({format_delta(delta * 100 if abs(delta) <= 1.5 else delta, unit='%p')})"
                    )
                except (TypeError, ValueError):
                    pass
        cards.append({
            "header": "단계 4 · 검증 방식",
            "what": split,
            "why": "모델의 *추가 가치* 정량화 — Baseline 직접 비교로 향상폭 측정",
            "result": result or "Baseline 비교 완료",
        })

    while len(cards) < 4:
        i = len(cards) + 1
        cards.append({
            "header": f"단계 {i} · 추가 분석",
            "what": "ctx 적립 후 채워짐",
            "why": "분석 결과 기록 진행 중",
            "result": "-",
        })
    return cards[:4]


__all__ = [
    # verdict / 도메인
    "get_verdict_tone",
    "is_auto_domain",
    "auto_label",
    # 포매터
    "format_pm_value",
    # dataset 요약
    "summarize_dtypes",
    "summarize_target",
    # EDA
    "select_top_eda_charts",
    "eda_key_insights",
    "build_eda_slide_from_chart",
    "build_eda_placeholder",
    # 파생 피처
    "derived_features_richness",
    "build_derived_features_slide",
    # method flow
    "build_method_steps",
    "build_method_whys",
]

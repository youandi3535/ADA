"""tests.integration.test_skeleton_regression — 4 카테고리 skeleton 회귀 게이트.

Step 5-3 (anomaly_pitch 동적 포팅) 직후 4 카테고리 skeleton (ml/dl/timeseries/anomaly)
의 ``build()`` 가 동일한 *불변식* 을 유지하는지 단일 진실원으로 검증.

검증 매트릭스 (16 케이스):
    {tabular_ml, tabular_dl, timeseries, anomaly_detection}
      × {empty ctx, rich+adopt, rich+iterate, rich+reject}

불변식:
    1) ``build()`` 가 항상 20 슬라이드 생성 (front 3 + section 1~5 + closing 1)
    2) 필수 slot ID 존재 — cover · agenda · exec_summary · roadmap · closing
    3) 메시지 트리는 root + 5개 서브 root (problem/solution/results/impact/plan)
    4) verdict 분기 — adopt vs iterate vs reject 의 S3 so_what 가 달라야 함
    5) 카테고리 매니페스트 — Tech Stack 슬라이드의 첫 항목이 카테고리 프리셋과 일치
    6) Auto-inferred 라벨 — domain_source=='auto' 일 때만 ``[auto-inferred]`` 마커 부착

HJ 영역 (tests/integration/). 구두 협의 완료.
"""

from __future__ import annotations

from typing import Any

import pytest

from outputs.architect.plan import ReportPlan, SlideSpec
from outputs.architect.skeletons import (
    anomaly_pitch,
    dl_pitch,
    ml_pitch,
    timeseries_pitch,
)
from outputs.architect.substitution_manifest import resolve_tech_stack
from tests.integration._skeleton_ctx_factory import make_empty_ctx, make_rich_ctx

# 카테고리 ↔ skeleton 모듈 매핑
_CATEGORIES: dict[str, Any] = {
    "tabular_ml": ml_pitch,
    "tabular_dl": dl_pitch,
    "timeseries": timeseries_pitch,
    "anomaly_detection": anomaly_pitch,
}

_VERDICTS = ("adopt", "iterate", "reject")


# ==============================================================
# 헬퍼
# ==============================================================


def _all_slides(plan: ReportPlan) -> list[SlideSpec]:
    """ReportPlan 의 모든 슬라이드를 평탄화."""
    return [sl for sec in plan.sections for sl in sec.slides]


def _slide_ids(plan: ReportPlan) -> set[str]:
    return {sl.id for sl in _all_slides(plan)}


def _find_slide(plan: ReportPlan, slide_id: str) -> SlideSpec:
    for sl in _all_slides(plan):
        if sl.id == slide_id:
            return sl
    raise AssertionError(f"slide '{slide_id}' missing from plan")


# ==============================================================
# 1) 슬라이드 개수 불변식 — 16 케이스
# ==============================================================


@pytest.mark.integration
@pytest.mark.parametrize("category", list(_CATEGORIES))
def test_empty_ctx_yields_20_slides(category: str) -> None:
    """빈 ctx 라도 placeholder 빌더 경로로 20장 생성."""
    ctx = make_empty_ctx(category)
    plan = _CATEGORIES[category].build(ctx, {})
    total = sum(len(sec.slides) for sec in plan.sections)
    assert total == 20, f"{category}: expected 20 slides, got {total}"


@pytest.mark.integration
@pytest.mark.parametrize("category", list(_CATEGORIES))
@pytest.mark.parametrize("verdict", _VERDICTS)
def test_rich_ctx_yields_20_slides(category: str, verdict: str) -> None:
    """풍부 ctx + verdict 3분기 모두 20장 유지."""
    ctx = make_rich_ctx(category, verdict)
    plan = _CATEGORIES[category].build(ctx, {})
    total = sum(len(sec.slides) for sec in plan.sections)
    assert total == 20, f"{category}/{verdict}: expected 20 slides, got {total}"


# ==============================================================
# 2) 필수 slot ID — 모든 카테고리 공통
# ==============================================================


_REQUIRED_SLIDE_IDS = {
    "cover", "agenda", "exec_summary", "hypothesis", "p3_alt_limits",
    "i1_kpi", "eda_findings", "error_analysis", "insights_derived",
    "as_is_to_be", "i3_roi", "risk_mitigation", "roadmap", "closing",
}

# jh 2026-06-12 — ml_pitch S5+S6 병합으로 p2_pain 슬롯이 insight_synthesis 로 대체.
# 그 외 3 카테고리는 p2_pain(Tech Stack) 유지 → 카테고리별 추가 필수 슬롯.
_CATEGORY_EXTRA_SLOT = {
    "tabular_ml": "insight_synthesis",
    "tabular_dl": "p2_pain",
    "timeseries": "p2_pain",
    "anomaly_detection": "p2_pain",
}


@pytest.mark.integration
@pytest.mark.parametrize("category", list(_CATEGORIES))
def test_required_slot_ids_present(category: str) -> None:
    """4 카테고리 모두 공통 slot ID + 카테고리별 추가 슬롯이 채워져 있어야 함."""
    ctx = make_rich_ctx(category, "adopt")
    plan = _CATEGORIES[category].build(ctx, {})
    ids = _slide_ids(plan)
    required = _REQUIRED_SLIDE_IDS | {_CATEGORY_EXTRA_SLOT[category]}
    missing = required - ids
    assert not missing, f"{category}: missing slot IDs {sorted(missing)}"


# ==============================================================
# 3) 메시지 트리 — root + 5 서브 root
# ==============================================================


_REQUIRED_MESSAGE_NODES = {"root", "problem_root", "solution_root", "results_root", "impact_root", "plan_root"}


@pytest.mark.integration
@pytest.mark.parametrize("category", list(_CATEGORIES))
def test_message_tree_has_root_and_subroots(category: str) -> None:
    ctx = make_rich_ctx(category, "adopt")
    plan = _CATEGORIES[category].build(ctx, {})
    msg_ids = {m.id for m in plan.message_tree}
    missing = _REQUIRED_MESSAGE_NODES - msg_ids
    assert not missing, f"{category}: message_tree missing {sorted(missing)}"


# ==============================================================
# 4) verdict 분기 — S3 so_what / S20 결론
# ==============================================================


@pytest.mark.integration
@pytest.mark.parametrize("category", list(_CATEGORIES))
def test_verdict_changes_exec_summary_so_what(category: str) -> None:
    """3 verdict 가 exec_summary.so_what 에서 서로 달라야 함."""
    so_whats: dict[str, str] = {}
    for v in _VERDICTS:
        ctx = make_rich_ctx(category, v)
        plan = _CATEGORIES[category].build(ctx, {})
        so_whats[v] = _find_slide(plan, "exec_summary").so_what or ""
    # 모두 비어 있지 않고, 모두 서로 달라야 함
    assert all(so_whats.values()), f"{category}: empty so_what in {so_whats}"
    assert len(set(so_whats.values())) == 3, (
        f"{category}: expected 3 distinct so_whats, got {so_whats}"
    )


@pytest.mark.integration
@pytest.mark.parametrize("category", list(_CATEGORIES))
def test_verdict_reject_closing_signals_no_adopt(category: str) -> None:
    """verdict=reject 일 때 closing body 에 '불가' / '폐기' 시그널이 있어야 함."""
    ctx = make_rich_ctx(category, "reject")
    plan = _CATEGORIES[category].build(ctx, {})
    closing = _find_slide(plan, "closing")
    body_joined = " ".join(closing.body_outline)
    assert any(token in body_joined for token in ("불가", "폐기", "거절", "재정의")), (
        f"{category}/reject: closing body lacks reject signal — {body_joined}"
    )


# ==============================================================
# 5) Tech Stack 매니페스트 — 카테고리 프리셋과 일치
# ==============================================================


@pytest.mark.integration
@pytest.mark.parametrize("category", list(_CATEGORIES))
def test_tech_stack_uses_category_manifest_preset(category: str) -> None:
    """Tech Stack 슬라이드 body 의 첫 항목이 카테고리 매니페스트 프리셋과 일치.

    jh 2026-06-12 — ml_pitch 는 S5+S6 병합으로 Tech Stack 이 p1_market(데이터·도구)
    슬라이드로 이동. 그 외 3 카테고리는 p2_pain 에 배치.
    """
    ctx = make_rich_ctx(category, "adopt")
    plan = _CATEGORIES[category].build(ctx, {})
    preset = resolve_tech_stack(category)
    assert preset, f"manifest preset missing for {category}"
    preset_first_name = preset[0].name

    tech_slide_id = "p1_market" if category == "tabular_ml" else "p2_pain"
    slide = _find_slide(plan, tech_slide_id)
    body_joined = " ".join(slide.body_outline)
    assert preset_first_name in body_joined, (
        f"{category}: tech stack '{preset_first_name}' missing in {tech_slide_id} body — {body_joined}"
    )


# ==============================================================
# 6) Auto-inferred 라벨 — domain_source 별 분기
# ==============================================================


@pytest.mark.integration
@pytest.mark.parametrize("category", ["tabular_dl", "timeseries", "anomaly_detection"])
def test_auto_inferred_label_only_when_domain_source_auto(category: str) -> None:
    """domain_source='auto' 일 때만 EDA so_what 에 [auto-inferred] 마커 부착.

    user 소스일 때는 마커 미부착 — 자동/수동 분기 회귀 게이트.
    ml_pitch 는 EDA 슬라이드 ID 가 다른 구조라 제외 (별도 회귀로 커버).
    """
    # user — 마커 미부착
    ctx_user = make_rich_ctx(category, "adopt")
    plan_user = _CATEGORIES[category].build(ctx_user, {})
    eda_slides_user = [
        sl for sl in _all_slides(plan_user) if sl.id in {"tech_architecture", "s3_differentiation"}
    ]
    user_joined = " ".join((sl.so_what or "") for sl in eda_slides_user)
    assert "[auto-inferred]" not in user_joined, (
        f"{category}: user 소스인데 [auto-inferred] 부착됨 — {user_joined}"
    )

    # auto — 마커 부착 (단, EDA chart.finding 이 비어있지 않을 때만)
    ctx_auto = make_rich_ctx(category, "adopt")
    ctx_auto.domain.domain_source = "auto"
    plan_auto = _CATEGORIES[category].build(ctx_auto, {})
    eda_slides_auto = [
        sl for sl in _all_slides(plan_auto) if sl.id in {"tech_architecture", "s3_differentiation"}
    ]
    auto_joined = " ".join((sl.so_what or "") for sl in eda_slides_auto)
    # EDA chart 의 finding 가 채워져 있으므로 적어도 1 슬라이드는 마커가 붙어야 함
    assert "[auto-inferred]" in auto_joined, (
        f"{category}: auto 소스인데 [auto-inferred] 마커 미부착 — {auto_joined}"
    )


# ==============================================================
# 7) ReportPlan meta — skeleton_variant 표기
# ==============================================================


_EXPECTED_VARIANT = {
    "tabular_dl": "dl_pitch_v2",
    "timeseries": "timeseries_pitch_v2",
    "anomaly_detection": "anomaly_pitch_v2",
    # ml_pitch 는 별도 variant 키 사용 — 본 회귀에선 존재만 확인
}


@pytest.mark.integration
@pytest.mark.parametrize("category", ["tabular_dl", "timeseries", "anomaly_detection"])
def test_report_plan_meta_skeleton_variant(category: str) -> None:
    ctx = make_rich_ctx(category, "adopt")
    plan = _CATEGORIES[category].build(ctx, {})
    variant = plan.meta.get("skeleton_variant")
    assert variant == _EXPECTED_VARIANT[category], (
        f"{category}: expected variant {_EXPECTED_VARIANT[category]}, got {variant}"
    )

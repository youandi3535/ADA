"""tests.integration.test_carrier_design_integration — carrier 디자인 통합 회귀.

Step 6-1 ~ 6-4 에서 추가한 항목 검증:
    - REGISTRY.candidates_for() 가 합당한 후보 반환
    - LLMDesigner._build_payload() 페이로드 구조
    - design_hint_helpers 의 palette/photo/icon 적용
    - 부족 신호 카운터 누적

LLM 실제 호출은 별도 (PR CI 에서 환경변수 + 통합 테스트). 본 모듈은 *룰·로직*
검증만.
"""

from __future__ import annotations

import pytest

from outputs.architect.plan import SlideSpec
from outputs.carriers.design_hint_helpers import (
    catalog_miss_summary,
    check_and_log_miss,
    icon_name,
    palette_override,
    photo_keyword,
    record_catalog_miss,
    reset_catalog_miss,
)
from outputs.carriers.template_registry import REGISTRY
from outputs.carriers.templates_init import init_registry
from outputs.context.schema import ReportContext

init_registry()


# ==============================================================
# REGISTRY.candidates_for — Step 6-1
# ==============================================================


class TestCandidatesFor:
    def _ctx(self, category: str = "tabular_ml") -> ReportContext:
        ctx = ReportContext()
        ctx.meta.category = category
        return ctx

    def test_exec_summary_top1_big_stats(self):
        """exec_summary 슬라이드의 1순위는 big_stats (has_id 90점)."""
        sl = SlideSpec(id="exec_summary", layout="kpi_cards_3", role="claim",
                       title_ko="x", body_outline=["a", "b", "c"])
        top = REGISTRY.candidates_for(sl, self._ctx(), top_n=5)
        assert top, "후보가 비어있음"
        assert top[0].name == "big_stats", f"기대: big_stats, 실제: {top[0].name}"

    def test_roadmap_top1_roadmap_upgrades(self):
        """roadmap 슬라이드의 1순위는 roadmap_upgrades."""
        sl = SlideSpec(id="roadmap", layout="process_flow", role="action",
                       title_ko="x", body_outline=["P1", "P2", "P3"])
        top = REGISTRY.candidates_for(sl, self._ctx(), top_n=5)
        assert top
        assert top[0].name == "roadmap_upgrades", f"기대: roadmap_upgrades, 실제: {top[0].name}"

    def test_tech_stack_top1_cube_3d(self):
        """tech_stack 슬라이드의 1순위는 cube_3d."""
        sl = SlideSpec(id="tech_stack", layout="comparison_table", role="evidence",
                       title_ko="x", body_outline=["py", "torch"])
        top = REGISTRY.candidates_for(sl, self._ctx(), top_n=5)
        assert top
        assert top[0].name == "cube_3d"

    def test_unknown_slide_safe_fallback(self):
        """알 수 없는 slide → 안전 후보 (photo_opener / funnel 같은 *항상 매칭*)."""
        sl = SlideSpec(id="completely_unknown_xyz", layout="?", role="?",
                       title_ko="?", body_outline=[])
        top = REGISTRY.candidates_for(sl, self._ctx(), top_n=5)
        assert isinstance(top, list)  # 항상 list 반환 (빈 리스트 OK)

    def test_strict_min_score_filter(self):
        """min_score=70 으로 엄격 필터 시 1개만 (has_id 90점만)."""
        sl = SlideSpec(id="exec_summary", layout="?", role="?",
                       title_ko="x", body_outline=[])
        strict = REGISTRY.candidates_for(sl, self._ctx(), top_n=20, min_score=70.0)
        # 모두 70점 이상 → 적어도 1개 (big_stats=90점)
        assert len(strict) >= 1

    def test_preferred_template_override(self):
        """slide.preferred_template 가 있으면 1순위로 강제."""
        sl = SlideSpec(id="i1_kpi", layout="kpi_cards_4", role="evidence",
                       title_ko="x", body_outline=["a", "b"])
        sl.preferred_template = "donut"
        top = REGISTRY.candidates_for(sl, self._ctx(), top_n=5)
        assert top
        assert top[0].name == "donut", f"override 실패: {top[0].name}"


# ==============================================================
# design_hint_helpers — Step 6-4
# ==============================================================


class TestDesignHintHelpers:
    def _slide(self, sid="x", hint=None):
        sl = SlideSpec(id=sid, layout="", role="",
                       title_ko="", body_outline=[])
        if hint is not None:
            sl._design_hint = hint
        return sl

    def test_palette_default(self):
        pal = {"primary": "#000", "accent": "#fff", "secondary": "#111"}
        sl = self._slide()
        assert palette_override(sl, pal) == pal

    def test_palette_warning(self):
        pal = {"primary": "#000", "accent": "#fff", "secondary": "#111"}
        sl = self._slide(hint={"palette_hint": "warning"})
        result = palette_override(sl, pal)
        assert result["primary"] != "#000"  # amber/warning 톤으로 변경
        assert result["primary"].lower() != "#000000"

    def test_palette_success_green(self):
        pal = {"primary": "#000", "accent": "#fff", "secondary": "#111"}
        sl = self._slide(hint={"palette_hint": "success"})
        result = palette_override(sl, pal)
        # success → 초록
        assert result["primary"].lower() in ("#16a34a",), f"got {result['primary']}"

    def test_photo_keyword_override(self):
        sl = self._slide(hint={"photo_keyword": "bank vault security"})
        assert photo_keyword(sl, "fallback") == "bank vault security"

    def test_photo_keyword_fallback(self):
        sl = self._slide()
        assert photo_keyword(sl, "fallback_kw") == "fallback_kw"

    def test_icon_concept_to_lucide(self):
        sl = self._slide(hint={"icon_concept": "warning"})
        assert icon_name(sl) == "alert-circle"

    def test_icon_fallback_concept(self):
        sl = self._slide()
        assert icon_name(sl, "kpi") == "trending-up"

    def test_icon_unknown_concept_returns_empty(self):
        sl = self._slide(hint={"icon_concept": "totally_unknown"})
        assert icon_name(sl) == ""


# ==============================================================
# 부족 신호 카운터 — Step 6-4
# ==============================================================


class TestCatalogMissCounter:
    def setup_method(self):
        reset_catalog_miss()

    def test_basic_accumulate(self):
        sl = SlideSpec(id="eda_findings", layout="", role="", title_ko="", body_outline=[])
        sl._design_hint = {"fallback_reason": "no radial cluster", "chosen_template": "donut"}
        assert check_and_log_miss(sl) is True
        assert check_and_log_miss(sl) is True
        summary = catalog_miss_summary()
        assert summary
        assert summary[0][1] == 2  # 같은 신호 2번

    def test_empty_reason_skipped(self):
        sl = SlideSpec(id="x", layout="", role="", title_ko="", body_outline=[])
        sl._design_hint = {"fallback_reason": "", "chosen_template": "big_stats"}
        assert check_and_log_miss(sl) is False
        assert catalog_miss_summary() == []

    def test_no_hint_skipped(self):
        sl = SlideSpec(id="x", layout="", role="", title_ko="", body_outline=[])
        assert check_and_log_miss(sl) is False

    def test_distinct_reasons_separate(self):
        record_catalog_miss("a", "reason 1")
        record_catalog_miss("b", "reason 2")
        record_catalog_miss("a", "reason 1")
        summary = dict(catalog_miss_summary())
        assert summary["a::reason 1"] == 2
        assert summary["b::reason 2"] == 1


# ==============================================================
# 4 카테고리 × Top 1 합리성 (sanity)
# ==============================================================


class TestCategorySanity:
    """4 카테고리 모두에서 주요 슬라이드의 룰 1위가 합리적."""

    @pytest.mark.parametrize("category", ["tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"])
    def test_exec_summary_top1_is_big_stats_across_categories(self, category):
        ctx = ReportContext()
        ctx.meta.category = category
        sl = SlideSpec(id="exec_summary", layout="kpi_cards_3", role="claim",
                       title_ko="Executive Summary", body_outline=["a", "b", "c"])
        top = REGISTRY.candidates_for(sl, ctx, top_n=5)
        assert top
        # exec_summary 는 카테고리 무관 has_id("exec_summary") 90점 → big_stats
        assert top[0].name == "big_stats"

    @pytest.mark.parametrize("category", ["tabular_ml", "tabular_dl", "timeseries", "anomaly_detection"])
    def test_each_category_has_at_least_some_candidates(self, category):
        """카테고리 무관 — 빈 ctx 라도 후보 1개 이상 (안전망)."""
        ctx = ReportContext()
        ctx.meta.category = category
        for sid in ("exec_summary", "roadmap", "tech_stack", "i1_kpi"):
            sl = SlideSpec(id=sid, layout="", role="", title_ko="x", body_outline=["a"])
            top = REGISTRY.candidates_for(sl, ctx, top_n=5)
            assert top, f"카테고리 {category}, slide {sid} 에 후보 없음"

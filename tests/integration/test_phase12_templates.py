"""tests.integration.test_phase12_templates — 카탈로그 보강 (Phase 12) 회귀.

견본 덱 레이아웃 이식 4종: chart_key_insights (legacy 등록) +
solution_overview / lineage_2col / icon_columns (신규).
"""

from __future__ import annotations

import pytest
from pptx import Presentation
from pptx.util import Cm

from outputs.architect.plan import SlideSpec, VisualSpec
from outputs.carriers.template_registry import REGISTRY
from outputs.carriers.templates_init import _split_label, init_registry
from outputs.context.schema import ReportContext

PALETTE = ("#0F4C81", "#2E86AB", "#0B1F33", "#5B7C99", "#F4F7FA")  # primary/accent/ink/muted/light_bg


def _blank_slide():
    prs = Presentation()
    prs.slide_width = Cm(33.867)
    prs.slide_height = Cm(19.05)
    return prs.slides.add_slide(prs.slide_layouts[6]), prs


def _slide_spec(**kw):
    base = dict(id="s", layout="", role="", title_ko="제목", so_what="주장", body_outline=[])
    base.update(kw)
    return SlideSpec(**base)


class TestRegistration:
    def test_phase12_registered(self):
        init_registry()
        for name in ("chart_key_insights", "solution_overview", "lineage_2col", "icon_columns"):
            assert REGISTRY.get(name) is not None, f"{name} 미등록"

    def test_chart_key_insights_requires_visual(self):
        init_registry()
        spec = REGISTRY.get("chart_key_insights")
        ctx = ReportContext()
        no_visual = _slide_spec(layout="chart_callout")
        assert spec.fit(no_visual, ctx) == 0.0
        with_visual = _slide_spec(
            layout="chart_callout", visual_spec=VisualSpec(type="chart_annotated_bar", title="t", spec={})
        )
        assert spec.fit(with_visual, ctx) >= 85.0

    def test_chart_key_insights_evidence_fallback(self):
        init_registry()
        spec = REGISTRY.get("chart_key_insights")
        ctx = ReportContext()
        sl = _slide_spec(role="evidence", visual_spec=VisualSpec(type="x", title="t", spec={}))
        assert spec.fit(sl, ctx) >= 70.0


class TestSplitLabel:
    def test_middle_dot(self):
        assert _split_label("모델 · CatBoost 채택") == ("모델", "CatBoost 채택")

    def test_colon(self):
        assert _split_label("검증: 80/20 split") == ("검증", "80/20 split")

    def test_no_separator_uses_fallback(self):
        label, text = _split_label("구분자가 없는 문장", fallback="항목 1")
        assert label == "항목 1"
        assert text == "구분자가 없는 문장"

    def test_overlong_label_not_split(self):
        long_head = "라" * 30 + " · 본문"
        label, text = _split_label(long_head, fallback="F")
        assert label == "F"  # 24자 초과 라벨은 라벨로 안 봄


class TestSmokeRender:
    """blank slide 에 그려서 예외 없는지 + shape 생성 확인."""

    def _ctx(self):
        ctx = ReportContext()
        ctx.model_selection.chosen = {"name": "CatBoost"}
        return ctx

    def test_solution_overview(self):
        init_registry()
        slide, _ = _blank_slide()
        sl = _slide_spec(
            body_outline=["모델 · CatBoost GBM", "입력 피처 · 14개", "출력 · 생존 확률 + SHAP", "검증 · 80/20 split"]
        )
        REGISTRY.get("solution_overview").draw(slide, sl, self._ctx(), *PALETTE)
        assert len(slide.shapes) >= 8

    def test_lineage_2col(self):
        init_registry()
        slide, _ = _blank_slide()
        sl = _slide_spec(
            body_outline=[
                "원본 · 891행 CSV", "전처리 · 결측 대치", "피처 · 14개 생성", "모델 · CatBoost 학습",
                "범주형 · 별도 인코딩", "파생 · Title 추출",
            ]
        )
        REGISTRY.get("lineage_2col").draw(slide, sl, self._ctx(), *PALETTE)
        assert len(slide.shapes) >= 10

    def test_icon_columns(self):
        init_registry()
        slide, _ = _blank_slide()
        sl = _slide_spec(body_outline=["데이터 · 891명 학습", "패턴 · 성별 55%p", "모델 · 0.788 달성", "액션 · 정책 제언"])
        REGISTRY.get("icon_columns").draw(slide, sl, self._ctx(), *PALETTE)
        assert len(slide.shapes) >= 12

    def test_icon_columns_two_items_ok(self):
        init_registry()
        slide, _ = _blank_slide()
        sl = _slide_spec(body_outline=["하나 · 첫째", "둘 · 둘째"])
        REGISTRY.get("icon_columns").draw(slide, sl, self._ctx(), *PALETTE)
        assert len(slide.shapes) >= 6

    def test_chart_key_insights_no_visual_no_crash(self):
        """visual_spec 없어도 (fit 상 안 오지만) draw 가 예외 없이 패널만 그림."""
        init_registry()
        slide, _ = _blank_slide()
        sl = _slide_spec(body_outline=["인사이트 1", "인사이트 2"])
        REGISTRY.get("chart_key_insights").draw(slide, sl, self._ctx(), *PALETTE)
        assert len(slide.shapes) >= 3

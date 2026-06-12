"""tests.integration.test_step7_draw_integration — Step 7-1/7-2/7-3 통합 회귀.

draw 함수가 design_hint 를 *실제로 우선* 적용하는지 검증.

검증 항목:
    - palette_override 가 _draw_slide 진입부에서 호출되는지 (정적 코드 확인)
    - _icon_name_for_sl 이 design_icon_name 우선 사용 (sl._design_hint.icon_concept)
    - _draw_cover 가 photo_keyword 를 fallback=user_intent 로 호출
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from outputs.architect.plan import SlideSpec
from outputs.carriers.pptx_designer import _icon_name_for_sl
from outputs.context.schema import ReportContext

# ==============================================================
# Step 7-1 — palette_override 단일 진입점 (정적 확인)
# ==============================================================


def test_draw_slide_calls_palette_override_at_entry():
    """_draw_slide 진입부에서 palette_override 호출하는지 정적 확인."""
    from outputs.carriers import pptx_designer as m

    src = open(m.__file__, encoding="utf-8").read()
    # _draw_slide 본문 내부에 palette_override 호출
    assert "_overridden = palette_override(" in src, \
        "palette_override 호출이 _draw_slide 진입부에 없음"
    assert "check_and_log_miss(sl)" in src, \
        "부족 신호 카운터 호출 누락"


# ==============================================================
# Step 7-2 — _draw_cover 의 photo_keyword 통합 (정적 확인)
# ==============================================================


def test_draw_cover_uses_photo_keyword_with_user_intent_fallback():
    """_draw_cover 가 photo_keyword 호출 + user_intent 폴백을 유지하는지.

    jh 2026-06-12 — cover 견본 상향(c7f24ad) 후 시그니처 변경:
    photo_keyword(sl, fallback="") + get_cover_image("cover", photo_kw or user_intent).
    """
    from outputs.carriers import pptx_designer as m

    src = open(m.__file__, encoding="utf-8").read()
    assert "photo_keyword(sl," in src, \
        "_draw_cover 에 photo_keyword 통합 누락"
    # user_intent 가 photo_kw 폴백으로 유지되는지
    assert "photo_kw or user_intent" in src, \
        "_draw_cover 의 user_intent 폴백 누락"


# ==============================================================
# Step 7-3 — _icon_name_for_sl 의 design_icon_name 우선
# ==============================================================


class TestIconNamePriority:
    def _slide(self, sid="x", hint=None):
        sl = SlideSpec(id=sid, layout="", role="", title_ko="", body_outline=[])
        if hint is not None:
            sl._design_hint = hint
        return sl

    def test_hint_icon_concept_wins(self):
        """design_hint.icon_concept 가 있으면 그게 우선."""
        sl = self._slide(sid="eda_findings", hint={"icon_concept": "warning"})
        result = _icon_name_for_sl(sl)
        # design_icon_name("warning") → "alert-circle"
        assert result == "alert-circle", f"got {result!r}"

    def test_no_hint_falls_back_to_icon_for_slide(self):
        """힌트 없으면 icon_for_slide (slide_id 기반) 로 폴백."""
        sl = self._slide(sid="exec_summary")  # 힌트 없음
        result = _icon_name_for_sl(sl)
        # icon_for_slide 가 빈 문자열 또는 lucide name 반환
        assert isinstance(result, str)

    def test_unknown_concept_falls_back(self):
        """매핑 안 되는 concept 면 fallback 으로 진행."""
        sl = self._slide(sid="exec_summary", hint={"icon_concept": "_totally_unknown_xyz_"})
        result = _icon_name_for_sl(sl)
        assert isinstance(result, str)


# ==============================================================
# Step 7-1 — palette 실제 override 효과 (런타임)
# ==============================================================


class TestPaletteOverrideRuntime:
    """palette_override 가 실제 색을 바꾸는지."""

    def test_warning_hint_changes_primary(self):
        from outputs.carriers.design_hint_helpers import palette_override

        sl = SlideSpec(id="x", layout="", role="", title_ko="", body_outline=[])
        sl._design_hint = {"palette_hint": "warning"}

        default = {"primary": "#0F172A", "accent": "#0EA5E9", "secondary": "#1E293B"}
        result = palette_override(sl, default)
        # warning → amber 톤
        assert result["primary"].lower() != "#0f172a"
        assert result["primary"].lower() == "#d97706"

    def test_no_hint_keeps_default(self):
        from outputs.carriers.design_hint_helpers import palette_override

        sl = SlideSpec(id="x", layout="", role="", title_ko="", body_outline=[])
        default = {"primary": "#0F172A", "accent": "#0EA5E9", "secondary": "#1E293B"}
        assert palette_override(sl, default) == default


# ==============================================================
# 2026-06-11 운영 사고 회귀 — LLMDesigner 인스턴스화 가능 여부
# ==============================================================


class TestLLMDesignerInstantiable:
    """LLMDesigner 가 실제로 인스턴스화돼야 함.

    사고 경위: BaseAgent 의 abstract ``__call__`` 미구현 → ``LLMDesigner()`` 가
    TypeError → ``generate_pptx_designed`` 의 except 가 삼킴 → 무로그 룰 폴백.
    기존 회귀 75개가 전부 정적 확인·헬퍼 단위라 인스턴스화를 한 번도 안 해서 놓침.
    """

    def test_designer_instantiates(self):
        from outputs.carriers.llm_designer import LLMDesigner

        designer = LLMDesigner()  # abstract 미구현이면 여기서 TypeError
        assert designer.model_name
        assert designer.use_anthropic_api is True

    def test_call_is_passthrough(self):
        """__call__ 은 그래프 노드가 아니므로 state 를 변경 없이 반환."""
        import asyncio

        from outputs.carriers.llm_designer import LLMDesigner

        designer = LLMDesigner()
        sentinel = object()
        assert asyncio.run(designer(sentinel)) is sentinel

    def test_parse_json_lenient_extracts_wrapped_json(self):
        """한국어 가드로 인한 'JSON 앞뒤 잡설' 케이스에서 JSON 블록 추출."""
        from outputs.carriers.llm_designer import LLMDesigner

        d = LLMDesigner()
        wrapped = '다음과 같이 선택했습니다.\n{"chosen_template": "kpi_cards", "nested": {"a": 1}}\n이상입니다.'
        parsed = d._parse_json_lenient(wrapped)
        assert parsed == {"chosen_template": "kpi_cards", "nested": {"a": 1}}

    def test_parse_json_lenient_truncated_returns_none(self):
        """max_tokens 절단으로 닫히지 않은 JSON 은 None (폴백 경로)."""
        from outputs.carriers.llm_designer import LLMDesigner

        d = LLMDesigner()
        assert d._parse_json_lenient('{"chosen_template": "kpi_cards", "palette') is None
        assert d._parse_json_lenient("") is None

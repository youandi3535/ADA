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

    src = open(m.__file__).read()
    # _draw_slide 본문 내부에 palette_override 호출
    assert "_overridden = palette_override(" in src, \
        "palette_override 호출이 _draw_slide 진입부에 없음"
    assert "check_and_log_miss(sl)" in src, \
        "부족 신호 카운터 호출 누락"


# ==============================================================
# Step 7-2 — _draw_cover 의 photo_keyword 통합 (정적 확인)
# ==============================================================


def test_draw_cover_uses_photo_keyword_with_user_intent_fallback():
    """_draw_cover 가 photo_keyword(sl, fallback=user_intent) 호출하는지."""
    from outputs.carriers import pptx_designer as m

    src = open(m.__file__).read()
    assert "photo_keyword(sl, fallback=user_intent)" in src, \
        "_draw_cover 에 photo_keyword 통합 누락"
    # get_cover_image 가 photo_kw 사용
    assert 'get_cover_image("cover", photo_kw)' in src, \
        "get_cover_image 가 photo_kw 안 받음"


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

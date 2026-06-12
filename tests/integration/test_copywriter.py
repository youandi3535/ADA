"""tests.integration.test_copywriter — Phase 3 카피라이터 회귀 (LLM 비호출 부분).

2026-06-11 사고 교훈 반영: 인스턴스화 테스트 필수.
"""

from __future__ import annotations

import asyncio

from outputs.carriers.llm_copywriter import _SKIP_LAYOUTS, LLMCopywriter


class TestInstantiable:
    def test_instantiates(self):
        w = LLMCopywriter()
        assert w.model_name
        assert w.use_anthropic_api is True

    def test_call_is_passthrough(self):
        w = LLMCopywriter()
        sentinel = object()
        assert asyncio.run(w(sentinel)) is sentinel

    def test_skip_layouts_cover_fixed_slides(self):
        assert "cover" in _SKIP_LAYOUTS
        assert "agenda" in _SKIP_LAYOUTS
        assert "closing" in _SKIP_LAYOUTS


class TestValidate:
    def _payload(self, body_n=3):
        return {
            "slides": [
                {
                    "id": "s1",
                    "role": "evidence",
                    "layout": "chart_callout",
                    "draft": {
                        "title_ko": "EDA · 주요 변수 1",
                        "so_what": "Feature 1 의 핵심 분포·패턴 발견",
                        "body_outline": [f"b{i}" for i in range(body_n)],
                    },
                }
            ],
            "data": {"evaluation": {"metrics": {"val_accuracy": 0.788}}, "n": 55},
        }

    def _targets(self):
        class _Sl:
            id = "s1"

        return [_Sl()]

    def test_accepts_valid_fill(self):
        w = LLMCopywriter()
        out = w._validate(
            {
                "s1": {
                    "title_ko": "성별이 최대 생존 결정 변수",
                    "so_what": "val_accuracy 0.788 — 격차 55%p 가 핵심 신호",
                    "body_outline": ["여성 vs 남성 격차 55%p", "val_accuracy 0.788", "보강 필요"],
                }
            },
            self._payload(),
            self._targets(),
        )
        assert out["s1"]["title_ko"].startswith("성별")
        assert len(out["s1"]["body_outline"]) == 3

    def test_accepts_expanded_bullets(self):
        """2026-06-12 — 초안 3개여도 재료가 있으면 5개까지 확장 허용."""
        w = LLMCopywriter()
        out = w._validate(
            {"s1": {"body_outline": [f"사실 {i} — 시사점 {i}" for i in range(5)]}},
            self._payload(body_n=3),
            self._targets(),
        )
        assert len(out["s1"]["body_outline"]) == 5

    def test_rejects_too_many_bullets(self):
        """6개 이상은 박스 초과 위험 — 기각 (초안 유지)."""
        w = LLMCopywriter()
        out = w._validate(
            {"s1": {"body_outline": [f"b{i}" for i in range(6)]}},
            self._payload(body_n=3),
            self._targets(),
        )
        assert "body_outline" not in out.get("s1", {})

    def test_rejects_single_bullet(self):
        w = LLMCopywriter()
        out = w._validate(
            {"s1": {"body_outline": ["하나뿐"]}},
            self._payload(body_n=3),
            self._targets(),
        )
        assert "body_outline" not in out.get("s1", {})

    def test_rejects_overlong_title(self):
        w = LLMCopywriter()
        out = w._validate(
            {"s1": {"title_ko": "가" * 60}},
            self._payload(),
            self._targets(),
        )
        assert "title_ko" not in out.get("s1", {})

    def test_unknown_slide_id_ignored(self):
        w = LLMCopywriter()
        out = w._validate(
            {"ghost": {"title_ko": "유령"}},
            self._payload(),
            self._targets(),
        )
        assert out == {}


class TestLenientParse:
    def test_wrapped_json(self):
        w = LLMCopywriter()
        parsed = w._parse_json_lenient('서론입니다.\n{"slides": {"s1": {"title_ko": "제목"}}}\n끝.')
        assert parsed["slides"]["s1"]["title_ko"] == "제목"

    def test_truncated_returns_none(self):
        w = LLMCopywriter()
        assert w._parse_json_lenient('{"slides": {"s1"') is None

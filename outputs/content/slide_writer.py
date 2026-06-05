"""outputs.content.slide_writer — SlideContentGenerator (Phase 3 메인).

ReportPlan 의 SlideSpec 들을 받아 본문 콘텐츠 (so_what 보강·body 작성·visual_spec 보강)
를 생성. LLM caller 를 주입 가능 — 없으면 템플릿 폴백 (이미 build 시점에 채워진 내용).

진입점:
    ``SlideContentGenerator(llm_caller=...).write(plan, ctx)``

작동 순서:
    1. Terminology 구축 + 사전 normalize.
    2. 각 슬라이드에 대해:
       a. LLM 있으면 콘텐츠 보강 호출 (실패 시 폴백).
       b. tone_calibrator 로 종결어미·길이 조정.
       c. so_what_scorer 로 점검 → 실패 시 LLM retry 1회.
       d. visual_selector 로 visual_spec.type 보강.
    3. speaker_notes 일괄 생성.
    4. qa_anticipator 로 백업 슬라이드 5개 추가.

LLM caller 시그니처:
    Callable[[str, str], str]  — (system_prompt, user_prompt) → response_text
    또는 None (의사 모드).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Optional

from outputs.architect.audience_adapter import audience_profile
from outputs.architect.plan import ReportPlan, SlideSpec, VisualSpec
from outputs.content.qa_anticipator import anticipate_questions, attach_backup_section
from outputs.content.so_what_scorer import score_so_what
from outputs.content.speaker_notes import apply_to_plan as apply_speaker_notes
from outputs.content.terminology import apply_to_plan as apply_terminology, build_terminology
from outputs.content.tone_calibrator import (
    calibrate_body_outline,
    calibrate_so_what,
)
from outputs.context.schema import ReportContext
from outputs.visuals.selector import select_visual_type

# ==============================================================
# LLM caller 타입
# ==============================================================

# (system_prompt, user_prompt) -> response_text
LLMCaller = Callable[[str, str], str]


# ==============================================================
# 결과
# ==============================================================


@dataclass
class WriteReport:
    """write() 결과 요약."""

    total_slides: int = 0
    so_what_pass: int = 0
    so_what_fail: int = 0
    llm_calls: int = 0
    llm_failures: int = 0
    backup_slides: int = 0
    terminology_normalizations: int = 0

    def to_dict(self) -> dict:
        return {
            "total_slides": self.total_slides,
            "so_what_pass": self.so_what_pass,
            "so_what_fail": self.so_what_fail,
            "llm_calls": self.llm_calls,
            "llm_failures": self.llm_failures,
            "backup_slides": self.backup_slides,
            "terminology_normalizations": self.terminology_normalizations,
        }


# ==============================================================
# Generator
# ==============================================================


class SlideContentGenerator:
    """슬라이드 콘텐츠 작가.

    Args:
        llm_caller: (system, user) → text. None 이면 의사 모드 (build 시 채워진 내용 그대로 사용).
    """

    def __init__(self, llm_caller: Optional[LLMCaller] = None) -> None:
        # If no caller injected, auto-detect from settings:
        #   1) use_ollama_for_analysis=True → make_ollama_caller (qwen2.5:7b)
        #   2) anthropic_api_key set → make_anthropic_caller
        #   3) else: None (pseudo mode — Skeleton placeholders only)
        if llm_caller is None:
            try:
                from ada.core.config import settings
                from outputs.content.llm_adapters import (
                    make_anthropic_caller,
                    make_ollama_caller,
                )

                if getattr(settings, "use_ollama_for_analysis", False):
                    llm_caller = make_ollama_caller(
                        model=getattr(settings, "ollama_model_analysis", "qwen2.5:7b"),
                        base_url=getattr(settings, "ollama_base_url", "http://localhost:11434"),
                    )
                elif settings.anthropic_api_key:
                    llm_caller = make_anthropic_caller(api_key=settings.anthropic_api_key)
            except Exception:
                pass
        self.llm_caller = llm_caller

    # ---------------------------------------------------------- public

    def write(self, plan: ReportPlan, ctx: ReportContext) -> WriteReport:
        """ReportPlan in-place 콘텐츠 보강. WriteReport 반환."""
        report = WriteReport(total_slides=plan.slide_count())
        profile = audience_profile(plan.audience or "analyst")

        # 0) Data-driven body enrichment - data-fill thin slides first
        try:
            from outputs.content.body_enricher import enrich_plan_bodies

            enrich_plan_bodies(plan, ctx)
        except Exception:
            pass

        # 1) Terminology
        term = build_terminology(ctx)
        apply_terminology(plan, term)
        report.terminology_normalizations = len(term.aliases)

        # 2) 슬라이드별 보강
        for sl in plan.all_slides():
            if sl.role == "meta":
                continue
            self._enhance_one(sl, ctx, profile, report)

        # 3) Speaker notes
        apply_speaker_notes(plan, ctx, profile)

        # 4) Backup slides
        candidates = anticipate_questions(plan, ctx)
        attach_backup_section(plan, candidates)
        report.backup_slides = len(candidates)

        # 5) 최종 So-What 통계
        for sl in plan.all_slides():
            if sl.role == "meta":
                continue
            s = score_so_what(sl.so_what)
            if s.passed:
                report.so_what_pass += 1
            else:
                report.so_what_fail += 1

        return report

    # ---------------------------------------------------------- internal

    def _enhance_one(
        self,
        slide: SlideSpec,
        ctx: ReportContext,
        profile: dict[str, Any],
        report: WriteReport,
    ) -> None:
        # (a) LLM 보강 시도
        if self.llm_caller is not None:
            new_so_what, new_body = self._llm_enhance(slide, ctx, profile, report)
            if new_so_what:
                slide.so_what = new_so_what
            if new_body:
                slide.body_outline = new_body

        # (b) tone calibration
        slide.so_what = calibrate_so_what(slide.so_what, profile)
        slide.body_outline = calibrate_body_outline(slide.body_outline, profile)

        # (c) So-What 점검 → 실패 시 LLM retry 1회
        verdict = score_so_what(slide.so_what)
        if not verdict.passed and self.llm_caller is not None:
            retried = self._llm_retry_so_what(slide, verdict.violations, report)
            if retried:
                slide.so_what = calibrate_so_what(retried, profile)

        # (d) visual type 보강
        if slide.visual_spec is None:
            slide.visual_spec = VisualSpec(type=select_visual_type(slide, ctx))
        elif not slide.visual_spec.type:
            slide.visual_spec.type = select_visual_type(slide, ctx)

    # ---------------------------------------------------------- LLM helpers

    def _llm_enhance(
        self,
        slide: SlideSpec,
        ctx: ReportContext,
        profile: dict[str, Any],
        report: WriteReport,
    ) -> tuple[str, list[str]]:
        """LLM 으로 so_what + body 재작성 시도. 실패 시 빈 값 반환 (build 본문 유지)."""
        sys = self._build_system_prompt(profile)
        usr = self._build_user_prompt(slide, ctx)
        try:
            report.llm_calls += 1
            raw = self.llm_caller(sys, usr)  # type: ignore[misc]
            parsed = _parse_json_safe(raw)
            if not isinstance(parsed, dict):
                return "", []
            so_what = str(parsed.get("so_what", "")).strip()
            body = parsed.get("body_outline", [])
            if not isinstance(body, list):
                body = []
            body = [str(x) for x in body][:5]
            return so_what, body
        except Exception:
            report.llm_failures += 1
            return "", []

    def _llm_retry_so_what(self, slide: SlideSpec, violations: list[str], report: WriteReport) -> str:
        """So-What 위반 사유 알리고 1회 재생성."""
        sys = (
            "You are a senior consulting writer. "
            "Rewrite the slide So-What in Korean (25-45 chars), "
            "include at least one number, no overpromise words (최적·완벽·최고), "
            "no vague words (다양한·여러·많은), no questions. End with a period."
        )
        usr = f'Slide: {slide.title_ko}\nCurrent: {slide.so_what}\nViolations: {violations}\nReturn JSON: {{"so_what": "..."}}'
        try:
            report.llm_calls += 1
            raw = self.llm_caller(sys, usr)  # type: ignore[misc]
            parsed = _parse_json_safe(raw)
            if isinstance(parsed, dict):
                return str(parsed.get("so_what", "")).strip()
        except Exception:
            report.llm_failures += 1
        return ""

    def _build_system_prompt(self, profile: dict[str, Any]) -> str:
        return (
            "You are a senior consulting writer (McKinsey/BCG style). "
            f"Audience tone: {profile.get('tone', '분석적')}. "
            f"Korean endings: {profile.get('endings_ko', '합니다')}. "
            f"Emphasis: {', '.join(profile.get('emphasis', []))}. "
            f"Max body words: {profile.get('max_body_words', 70)}. "
            'Return ONLY JSON: {"so_what": "<25-45 char Korean conclusion with at least 1 number>", '
            '"body_outline": ["<bullet 1>", "<bullet 2>", "<bullet 3>"]}'
        )

    def _build_user_prompt(self, slide: SlideSpec, ctx: ReportContext) -> str:
        pm = ctx.evaluation.primary_metric or {}
        chosen = ctx.model_selection.chosen or {}
        payload = {
            "slide_id": slide.id,
            "section": slide.section_id,
            "title_ko": slide.title_ko,
            "layout": slide.layout,
            "role": slide.role,
            "current_so_what": slide.so_what,
            "current_body": slide.body_outline,
            "thread_part": slide.thread_part,
            "context": {
                "category": ctx.meta.category,
                "user_intent": ctx.meta.user_intent,
                "chosen_model": chosen.get("name"),
                "primary_metric": pm,
                "industry": ctx.domain.inferred_industry,
            },
        }
        return json.dumps(payload, ensure_ascii=False)[:3500]


def _parse_json_safe(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) > 1:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except Exception:
        return None

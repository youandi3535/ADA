"""outputs.carriers.llm_designer — LLM 기반 슬라이드 디자인 선택기.

`pptx_designer._draw_slide` 가 호출. 후보 N개 + ctx 요약 + slide 메타 를 받아
LLM 한테 *어떤 카탈로그 디자인이 이 데이터·분석방향에 가장 어울리나* 판단시킴.

설계 원칙:
    - 룰 (REGISTRY.candidates_for) 이 점수로 *후보 N개* 추려서 LLM 에 넘김
    - LLM 은 *그 중 1개* 선택 + 색·사진·아이콘 힌트 함께 반환
    - LLM 실패 시 *휴리스틱 1위* 로 폴백 (안전)
    - 카탈로그에 적합 디자인 없으면 ``fallback_reason`` 로깅 → 다음 PR 에서 사람이 추가

호출 흐름:
    pptx_designer._draw_slide(slide, ctx)
      → REGISTRY.candidates_for(slide, ctx, top_n=7)  # 후보 추출 (룰)
      → LLMDesigner().pick_design(slide, ctx, candidates)  # LLM 1개 선택
      → 선택된 TemplateSpec.draw(...) 호출

HJ 영역. carrier 측 LLM 진입점.
"""

from __future__ import annotations

import json
from typing import Any

from agents.base import BaseAgent
from outputs.architect.plan import SlideSpec
from outputs.context.schema import ReportContext

# ==============================================================
# LLM 프롬프트
# ==============================================================

_SYSTEM_PROMPT = """\
You are a presentation design curator for an analytics report (Korean).
Given (1) slide metadata, (2) data signals from the analysis, and (3) a list of
candidate design templates with scores, choose ONE template that best
expresses the *data and analysis direction* for this slide.

Guidance:
- Favor templates whose shape matches the data pattern (e.g. flow → process,
  comparison → side-by-side, distribution → chart, single ratio → donut).
- Consider verdict (adopt/iterate/reject) — adopt favors confident displays,
  reject favors cautious/dimmed designs.
- Consider domain — fraud/security may use warning colors, finance may use blue.
- Prefer richer designs (with photo/illustration) for cover/section divider,
  minimal for dense data slides.
- If NO candidate fits well, choose the closest and explain in fallback_reason.

Return STRICT JSON only:
{
  "chosen_template": "<name from candidates>",
  "palette_hint": "default|warning|success|monochrome",
  "photo_keyword": "<2-4 English keywords for stock photo. MUST describe the DATA's subject domain (e.g. Titanic survival -> 'ocean ship vintage', retail sales -> 'retail store shelves'). NEVER generic business/office/people imagery. Empty if no domain noun applies.>",
  "icon_concept": "<one concept name like 'kpi', 'warning', 'data', or empty>",
  "fallback_reason": "<empty if good fit, else 1-line reason this is suboptimal>"
}
"""


# ==============================================================
# Designer
# ==============================================================


class LLMDesigner(BaseAgent):
    """슬라이드 1장당 LLM 디자인 선택 1회."""

    uses_llm = True
    model_name = "claude-haiku-4-5-20251001"  # 빠르고 저렴 — 디자인 선택은 가벼운 판단
    use_anthropic_api = True

    async def __call__(self, state: Any) -> Any:  # pragma: no cover — 그래프 노드 아님
        """LLMDesigner 는 파이프라인 노드가 아님 — ``pick_design`` 전용 유틸 에이전트.

        BaseAgent 의 abstract ``__call__`` 충족용. state 를 변경 없이 반환.
        (2026-06-11 운영 사고: 미구현 → 인스턴스화 TypeError → 조용히 룰 폴백)
        """
        return state

    async def pick_design(
        self,
        slide: SlideSpec,
        ctx: ReportContext,
        candidates: list[Any],  # list[TemplateSpec]
    ) -> dict[str, Any]:
        """후보 중 1개 선택 + 디자인 힌트 반환.

        실패 시 폴백 — candidates[0] (룰 1위) + 빈 힌트.

        Returns:
            {
                "chosen_template": str,         # candidate 이름
                "palette_hint": str,            # default/warning/success/monochrome
                "photo_keyword": str,           # 검색어
                "icon_concept": str,            # 'kpi', 'warning' 등
                "fallback_reason": str,         # 빈 문자열이면 좋은 매칭, 아니면 부족 신호
                "_source": "llm" | "fallback",  # 디버그
            }
        """
        if not candidates:
            return {
                "chosen_template": "",
                "palette_hint": "default",
                "photo_keyword": "",
                "icon_concept": "",
                "fallback_reason": "no candidates available",
                "_source": "fallback",
            }

        # 후보 1개뿐이면 LLM 호출 스킵
        if len(candidates) == 1:
            return {
                "chosen_template": candidates[0].name,
                "palette_hint": "default",
                "photo_keyword": "",
                "icon_concept": "",
                "fallback_reason": "",
                "_source": "fallback",  # 호출 안 했으므로
            }

        payload = self._build_payload(slide, ctx, candidates)
        candidate_names = {c.name for c in candidates}

        try:
            raw = await self._call_llm(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                # 2026-06-11 — 400 에서 실전 페이로드 (후보 7 + 한국어 fallback_reason)
                # 응답이 중간 절단 → 18/18 JSON 파싱 실패. 여유 있게 상향.
                max_tokens=800,
                temperature=0.3,
                json_mode=True,
            )
        except Exception as e:
            self.logger.warning("designer_llm_failed", error=str(e), slide_id=slide.id)
            return self._fallback(candidates, reason=f"llm_call_failed: {e}")

        parsed = self._parse_json_lenient(raw)
        if not isinstance(parsed, dict):
            # 원문 머리를 남겨야 다음 진단이 즉시 가능 (2026-06-11 침묵 사고 교훈)
            self.logger.warning(
                "designer_llm_unparsable",
                slide_id=slide.id,
                raw_head=(raw or "")[:200],
            )
            return self._fallback(candidates, reason="llm_returned_invalid_json")

        chosen = str(parsed.get("chosen_template", "")).strip()
        if chosen not in candidate_names:
            self.logger.warning(
                "designer_llm_chose_invalid",
                slide_id=slide.id,
                chosen=chosen,
                candidates=list(candidate_names),
            )
            return self._fallback(candidates, reason=f"llm_chose_out_of_set: {chosen}")

        result = {
            "chosen_template": chosen,
            "palette_hint": str(parsed.get("palette_hint", "default") or "default"),
            "photo_keyword": str(parsed.get("photo_keyword", "") or "").strip(),
            "icon_concept": str(parsed.get("icon_concept", "") or "").strip(),
            "fallback_reason": str(parsed.get("fallback_reason", "") or "").strip(),
            "_source": "llm",
        }

        # 부족 신호 로깅 — Step 6-4 에서 더 자세히 다룸
        if result["fallback_reason"]:
            self.logger.info(
                "designer_catalog_miss_hint",
                slide_id=slide.id,
                chosen=chosen,
                reason=result["fallback_reason"],
            )

        return result

    # ------------------------------------------------------------------

    def _build_payload(
        self,
        slide: SlideSpec,
        ctx: ReportContext,
        candidates: list[Any],
    ) -> dict[str, Any]:
        """LLM 프롬프트의 *데이터 신호* 부분 구성."""
        pm = ctx.evaluation.primary_metric or {}
        return {
            "slide": {
                "id": slide.id,
                "title_ko": slide.title_ko or "",
                "so_what": slide.so_what or "",
                "role": slide.role or "",
                "layout_hint": slide.layout or "",
                "visual_type_hint": getattr(slide.visual_spec, "type", "") if slide.visual_spec else "",
                "body_outline": list(slide.body_outline or [])[:5],
            },
            "ctx_signals": {
                "category": ctx.meta.category or "",
                "user_intent": (ctx.meta.user_intent or "")[:100],
                "audience": ctx.meta.audience or "",
                "domain_industry": (getattr(ctx.domain, "inferred_industry", "") or "")[:80],
                "domain_use_case": (getattr(ctx.domain, "inferred_use_case", "") or "")[:80],
                "verdict": ctx.evaluation.verdict or "",
                "primary_metric_name": pm.get("name", ""),
                "primary_metric_value": pm.get("value"),
                "gate_passed": ctx.evaluation.gate_passed,
                "n_metrics": len(ctx.evaluation.metrics or {}),
                "n_features_created": len(ctx.features.created or []),
                "n_eda_charts": len(ctx.eda.charts or []),
            },
            "candidates": [
                {
                    "name": c.name,
                    "tags": list(c.tags or []),
                }
                for c in candidates
            ],
        }

    def _parse_json_lenient(self, text: str) -> Any:
        """JSON 앞뒤 잡설·코드펜스가 섞여도 첫 번째 균형 잡힌 {...} 블록을 추출.

        한국어 가드가 system prompt 에 자동 부착되면서 모델이 JSON 앞에
        한국어 설명을 붙이는 케이스 방어 (2026-06-11).
        """
        parsed = self._parse_json(text)
        if isinstance(parsed, dict):
            return parsed
        if not text:
            return None
        start = text.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except Exception:
                            break
            start = text.find("{", start + 1)
        return None

    def _fallback(self, candidates: list[Any], reason: str) -> dict[str, Any]:
        """LLM 실패 시 휴리스틱 1위 사용."""
        return {
            "chosen_template": candidates[0].name,
            "palette_hint": "default",
            "photo_keyword": "",
            "icon_concept": "",
            "fallback_reason": reason,
            "_source": "fallback",
        }


__all__ = ["LLMDesigner"]

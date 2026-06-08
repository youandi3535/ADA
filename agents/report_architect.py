"""agents.report_architect — ReportArchitectAgent (Phase 2 통합 노드).

G6 진입 전 호출돼 `state.report_plan` 을 채운다.

흐름:
    1. outputs/context/builder.build_report_context(state) → ReportContext (dataclass)
    2. LLM (Anthropic API, claude-opus-4-6) 으로 Skeleton 1종 선정
       — 휴리스틱 pick_skeleton() 결과를 후보로 제시하고 LLM 이 채택/재선택
       — 실패 시 휴리스틱 결과 그대로 사용
    3. outputs/architect.architect.build_plan(ctx, skeleton_override=...) → ReportPlan
    4. state.report_plan = plan.to_dict() 저장
    5. next_agent="gate_outputs"

설계 원칙:
    - silent-safe: LLM/플랜 빌드 실패 시 state.error 세팅하지 않고 next 로 진행.
      report_plan=None 이면 carrier 가 legacy 폴백 (V2 → V1) 작동.
    - 추가 LLM 의존성 최소화: skeleton 선정 1회만. narrative/refinement 는 차후 확장.

HJ 단독 영역 (시스템 노드).
"""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

# 허용 Skeleton — outputs/architect/skeletons/__init__.py 의 SKELETON_REGISTRY 키와 동기.
ALLOWED_SKELETONS: tuple[str, ...] = (
    "SCQA",
    "PSI",
    "Pyramid",
    "Comparative",
    "Diagnostic",
    "Analysis Standard",
)

SYSTEM_PROMPT = """당신은 컨설팅 보고서 설계자입니다.
주어진 분석 컨텍스트(청중·의도·데이터·모델 결과)를 보고
6 종 Skeleton 중 가장 적합한 1 개를 선정하세요.

Skeleton 가이드:
- SCQA: 일반 분석 보고서 (Situation→Complication→Question→Answer). 기본.
- PSI: 제안/도입/투자 발표 (Problem→Solution→Impact). 가치 어필 강함.
- Pyramid: C-level 임원 대상 시간 제약 (결론 먼저, 근거 트리).
- Comparative: 후보 비교/선택/평가 (모델 vs 모델, 옵션 vs 옵션).
- Diagnostic: 원인 분석·이상 진단 (Why→Root cause→Fix).
- Analysis Standard: 규제·감사·논문·학술 (재현성·완전성 강조).

응답은 반드시 JSON 한 개:
{"skeleton": "<6 종 중 하나>", "reason": "<2~3 문장 한국어 근거>"}
"""


class ReportArchitectAgent(BaseAgent):
    """Skeleton 선정 + ReportPlan 빌드 노드."""

    uses_llm = True
    model_name = "claude-opus-4-6"
    use_anthropic_api = True

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            # 1) ReportContext 정규화
            try:
                from outputs.context.builder import build_report_context

                ctx = build_report_context(state)
            except Exception as e:  # noqa: BLE001
                self.logger.warning("architect_ctx_build_failed", error=str(e))
                # plan 없이 다음 단계로 — carrier 가 legacy 폴백
                return state.with_update(next_agent="gate_outputs")

            # 2) Skeleton 선정 — 휴리스틱 → LLM override
            try:
                from outputs.architect.architect import pick_skeleton
                from outputs.architect.audience_adapter import audience_profile

                profile = audience_profile(ctx.meta.audience or "analyst")
                heuristic = pick_skeleton(ctx, profile)
            except Exception as e:  # noqa: BLE001
                self.logger.warning("architect_heuristic_failed", error=str(e))
                heuristic = "SCQA"
                profile = {}

            skeleton = await self._llm_pick_skeleton(ctx, heuristic) or heuristic
            if skeleton not in ALLOWED_SKELETONS:
                self.logger.warning("architect_invalid_skeleton", picked=skeleton, fallback=heuristic)
                skeleton = heuristic

            # 3) ReportPlan 빌드
            try:
                from outputs.architect.architect import build_plan

                plan = build_plan(
                    ctx,
                    output_form="pptx",
                    skeleton_override=skeleton,
                    enforce_completeness=False,  # 차단 대신 warnings 로 흡수
                )
                self.logger.info(
                    "architect_plan_built",
                    skeleton=skeleton,
                    sections=len(plan.sections),
                    slides=sum(len(s.slides) for s in plan.sections),
                    warnings=len(plan.warnings),
                )
                return state.with_update(
                    report_plan=plan.to_dict(),
                    next_agent="gate_outputs",
                )
            except Exception as e:  # noqa: BLE001
                # 빌드 실패해도 G6 흐름은 막지 않음 — carrier 가 legacy 폴백
                self.logger.warning("architect_plan_failed", skeleton=skeleton, error=str(e))
                return state.with_update(next_agent="gate_outputs")

    # ------------------------------------------------------------------
    async def _llm_pick_skeleton(self, ctx: Any, heuristic: str) -> str | None:
        """LLM 으로 Skeleton 재선정. 실패 시 None 반환 → 휴리스틱 사용."""
        payload = {
            "category": getattr(ctx.meta, "category", None),
            "audience": getattr(ctx.meta, "audience", None),
            "user_intent": getattr(ctx.meta, "user_intent", None),
            "business_context": getattr(ctx.meta, "business_context", None),
            "regulatory_hints": list(getattr(ctx.domain, "regulatory_hints", []) or []),
            "n_model_candidates": len(getattr(ctx.model_selection, "candidates", []) or []),
            "heuristic_recommendation": heuristic,
            "allowed_skeletons": list(ALLOWED_SKELETONS),
        }
        try:
            raw = await self._call_llm(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=400,
                temperature=0.2,
                json_mode=True,
            )
        except Exception as e:  # noqa: BLE001
            self.logger.warning("architect_llm_failed", error=str(e))
            return None
        parsed = self._parse_json(raw)
        if not isinstance(parsed, dict):
            return None
        skel = parsed.get("skeleton")
        if not isinstance(skel, str):
            return None
        skel = skel.strip()
        if skel not in ALLOWED_SKELETONS:
            return None
        self.logger.info(
            "architect_llm_picked",
            skeleton=skel,
            heuristic=heuristic,
            agreed=(skel == heuristic),
        )
        return skel

"""agents.report_architect — ReportArchitectAgent (Phase 2 통합 노드).

G6 진입 전 호출돼 `state.report_plan` 을 채운다.

흐름:
    1. outputs/context/builder.build_report_context(state) → ReportContext (dataclass)
    2. Skeleton 선정 — outputs.architect.architect.pick_skeleton(ctx) 호출
       — 카테고리별 라우팅 (현재 ML Pitch 만, 추가 시 pick_skeleton 분기 확장)
       — ALLOWED_SKELETONS 2개 이상일 때만 LLM 으로 override 시도
    3. outputs/architect.architect.build_plan(ctx, skeleton_override=...) → ReportPlan
    4. state.report_plan = plan.to_dict() 저장
    5. next_agent="gate_outputs"

설계 원칙:
    - silent-safe: LLM/플랜 빌드 실패 시 state.error 세팅하지 않고 next 로 진행.
      report_plan=None 이면 carrier 가 legacy 폴백 (V2 → V1) 작동.
    - 단일 Skeleton 시 LLM 호출 스킵 — 비용 절감 + 응답 시간 단축.

HJ 2026-06-08 — Skeleton 4종 완성 (ML · DL · Timeseries · Anomaly Pitch). 4 카테고리
모두 자체 skeleton. Anomaly Pitch 는 6 도메인 (fraud/industrial_iot/system_logs/
security/quality_control/medical) 자동 적응.
HJ 단독 영역 (시스템 노드).
"""

from __future__ import annotations

import json
from typing import Any

from ada.core.state import PipelineState
from agents.base import BaseAgent

# 허용 Skeleton — outputs/architect/skeletons/__init__.py 의 SKELETON_REGISTRY 키와 동기.
ALLOWED_SKELETONS: tuple[str, ...] = ("ML Pitch", "DL Pitch", "Timeseries Pitch", "Anomaly Pitch")

SYSTEM_PROMPT = """당신은 컨설팅 보고서 설계자입니다.
주어진 분석 컨텍스트(카테고리·청중·의도·데이터·모델 결과)를 보고
허용된 Skeleton 중 가장 적합한 1 개를 선정하세요.

Skeleton 가이드:
- ML Pitch: tabular_ml 카테고리 전용 (20장 고정).
            Cover · ExecSummary · Agenda + 본문 16장 + Closing.
            Action Title + MECE + Baseline 비교 + Error Analysis + Monitoring KPI 표준.

- DL Pitch: tabular_dl 카테고리 전용 (20장 고정).
            Cover · Agenda · ExecSummary + 본문 16장 + Closing.
            DL 특화 (Why DL · Architecture Deep · Training Dynamics · Calibration
            · Inference Cost · MLOps Stack) 표준.

- Timeseries Pitch: timeseries 카테고리 전용 (20장 고정).
            Cover · Agenda · ExecSummary + 본문 16장 + Closing.
            시계열 특화 (Why 시계열 · Forecast Plot · STL Decomposition · PI Coverage
            · Long-horizon Decay · Forecast Refresh) 표준.

- Anomaly Pitch: anomaly_detection 카테고리 전용 (20장 + 6 도메인 자동 적응).
            Cover · Agenda · ExecSummary + 본문 16장 + Closing.
            이상탐지 특화 (Why Anomaly · Score Distribution · PR-AUC · Threshold Tuning
            · FAR · Root Cause · Drift) 표준. 도메인 (fraud/industrial_iot/system_logs/
            security/quality_control/medical) 자동 텍스트 적응.

선택 룰:
- ctx.meta.category == "tabular_ml" 이면 ML Pitch 우선
- ctx.meta.category == "tabular_dl" 이면 DL Pitch 우선
- ctx.meta.category == "timeseries" 이면 Timeseries Pitch 우선
- ctx.meta.category == "anomaly_detection" 이면 Anomaly Pitch 우선
- 그 외 카테고리는 heuristic_recommendation 따름

응답은 반드시 JSON 한 개:
{"skeleton": "<허용 목록 중 하나>", "reason": "<2~3 문장 한국어 근거>"}
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
                return state.with_update(next_agent="gate_outputs")

            # 2) Skeleton 선정 — 휴리스틱 (단일 Skeleton 이면 LLM 스킵)
            try:
                from outputs.architect.architect import pick_skeleton
                from outputs.architect.audience_adapter import audience_profile

                profile = audience_profile(ctx.meta.audience or "analyst")
                heuristic = pick_skeleton(ctx, profile)
            except Exception as e:  # noqa: BLE001
                self.logger.warning("architect_heuristic_failed", error=str(e))
                heuristic = "ML Pitch"
                profile = {}

            if len(ALLOWED_SKELETONS) > 1:
                skeleton = await self._llm_pick_skeleton(ctx, heuristic) or heuristic
            else:
                # 단일 Skeleton — LLM 호출 불필요
                skeleton = heuristic
                self.logger.info("architect_single_skeleton_skip_llm", skeleton=skeleton)

            if skeleton not in ALLOWED_SKELETONS:
                self.logger.warning("architect_invalid_skeleton", picked=skeleton, fallback=heuristic)
                skeleton = heuristic if heuristic in ALLOWED_SKELETONS else ALLOWED_SKELETONS[0]

            # 3) ReportPlan 빌드
            try:
                from outputs.architect.architect import build_plan

                plan = build_plan(
                    ctx,
                    output_form="pptx",
                    skeleton_override=skeleton,
                    enforce_completeness=False,
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
                self.logger.warning("architect_plan_failed", skeleton=skeleton, error=str(e))
                return state.with_update(next_agent="gate_outputs")

    # ------------------------------------------------------------------
    async def _llm_pick_skeleton(self, ctx: Any, heuristic: str) -> str | None:
        """LLM 으로 Skeleton 재선정 (ALLOWED_SKELETONS ≥ 2 일 때만 호출됨).

        실패 시 None 반환 → 휴리스틱 사용.
        """
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

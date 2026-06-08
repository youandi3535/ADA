"""outputs.ppt_v2 — OUT-01 V2: Architect-driven PPT (Phase 2).

기존 ``outputs/ppt.py::PresentationGenerator`` (V1) 는 고정 10 슬라이드 단순 PPT.
V2 는 ``state.report_plan`` (ReportArchitect 가 생성한 동적 목차) 을 받아
``outputs/carriers/pptx_carrier.generate_pptx`` 로 렌더링.

폴백 정책 (silent-safe):
    1. state.report_plan 없음           → V1 으로 폴백 (legacy 동작 보존)
    2. report_plan 있으나 carrier 실패  → V1 으로 폴백
    3. V1 도 예외                       → ReportComposer 가 catch (None path)

HJ 2026-06-08 — Phase 2 통합.
"""

from __future__ import annotations

from typing import Any

from outputs.base import OutputGenerator, reattach_pii
from outputs.ppt import PresentationGenerator as _LegacyPresentationGenerator


class PresentationGeneratorV2(OutputGenerator):
    """Architect 기반 PPT 생성기 (OUT-01 V2)."""

    output_code = "OUT-01"
    extension = "pptx"

    def generate(
        self,
        *,
        insights: str,
        best_model: dict[str, Any],
        eda_charts: list[str],
        category: str,
        user_intent: str,
        eval_result: dict[str, Any] | None,
        state: Any = None,
    ) -> str:
        # ADR-008 L2 — PII 마스킹 (carrier 호출 전).
        # V1 폴백 시 V1 의 generate() 가 자체 reattach 하므로 중복 호출되지만,
        # PIIAnonymizer.reattach 는 idempotent.
        insights = reattach_pii(state, insights)
        user_intent = reattach_pii(state, user_intent)
        if eval_result:
            eval_result = {**eval_result, "rationale": reattach_pii(state, eval_result.get("rationale"))}

        # 1) report_plan 유무 체크
        plan_dict = None
        if state is not None:
            try:
                plan_dict = getattr(state, "report_plan", None)
            except Exception:  # noqa: BLE001
                plan_dict = None

        if not plan_dict:
            # state.report_plan 없음 → 휴리스틱 폴백 작동 안 함, 즉시 V1
            return self._fallback_v1(
                insights=insights,
                best_model=best_model,
                eda_charts=eda_charts,
                category=category,
                user_intent=user_intent,
                eval_result=eval_result,
                state=state,
            )

        # 2) Architect carrier 시도
        try:
            from outputs.architect.plan import ReportPlan
            from outputs.carriers.pptx_carrier import generate_pptx
            from outputs.context.builder import build_report_context

            plan = ReportPlan.from_dict(plan_dict)
            ctx = build_report_context(state)

            local = self._tmp()
            generate_pptx(plan, ctx, local)
            return self._upload(local)
        except Exception as e:  # noqa: BLE001
            self.logger_warn("ppt_v2_carrier_failed", str(e))
            return self._fallback_v1(
                insights=insights,
                best_model=best_model,
                eda_charts=eda_charts,
                category=category,
                user_intent=user_intent,
                eval_result=eval_result,
                state=state,
            )

    # ------------------------------------------------------------------
    def _fallback_v1(self, **kwargs: Any) -> str:
        """V1 PresentationGenerator 위임. 동일 job_id·output_code 유지."""
        legacy = _LegacyPresentationGenerator(self.job_id)
        return legacy.generate(**kwargs)

    # ------------------------------------------------------------------
    def logger_warn(self, event: str, msg: str) -> None:
        """경량 로깅 — base.OutputGenerator 에 logger 없으니 print + structlog 시도."""
        try:
            from ada.core.logger import get_logger

            get_logger("PresentationGeneratorV2").warning(event, error=msg)
        except Exception:  # noqa: BLE001
            pass

"""agents.report_composer — Day 0 dispatcher 패턴. ADR-008 L2 state 전달."""

from __future__ import annotations

import asyncio
import inspect
import uuid as _uuid
from typing import Any

import agents.handlers.anomaly  # noqa: F401
import agents.handlers.tabular  # noqa: F401
import agents.handlers.timeseries  # noqa: F401
from ada.core.state import PipelineState
from agents.base import BaseAgent
from agents.handlers import get_handler
from outputs import GENERATORS


# HJ 2026-06-11 — G6 모달 라이브 피드용.
def _safe_publish_stage_partial(job_id: str | None, partial: dict) -> None:
    if not job_id or not isinstance(partial, dict) or not partial:
        return
    try:
        from orchestrator.runner import publish_stage_partial as _psp

        _psp(job_id, partial)
    except Exception:  # noqa: BLE001
        pass


_OUTPUT_KO: dict[str, str] = {
    "OUT-01": "PPT",
    "OUT-02": "PDF 보고서",
    "OUT-03": "발표 대본",
    "OUT-04": "HTML 대시보드",
    "OUT-07": "인사이트 요약",
}


class ReportComposerAgent(BaseAgent):
    uses_llm = False

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            requested = state.requested_outputs or list(GENERATORS.keys())

            # HJ 2026-06-11 — G6 모달 라이브 피드: 리포트 합성 시작 status.
            try:
                _req_ko = [_OUTPUT_KO.get(c, c) for c in requested]
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g6_phase": "report_composer_start",
                        "g6_status": f"리포트 합성 중 — {len(requested)}종 산출물 ({', '.join(_req_ko)})",
                        "report_total": len(requested),
                        "report_requested": _req_ko,
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.debug("g6_partial_start_failed", error=str(e))

            extras: dict[str, Any] = {}
            assets_handler = get_handler(state.category, "assets")
            if assets_handler is not None:
                try:
                    extras = assets_handler(state) or {}
                except Exception as e:
                    self.logger.warning("report_extras_failed", category=state.category, error=str(e))

            cat_extras = {**state.category_extras}
            cat_extras.setdefault(state.category, {}).update(extras)

            # HJ 2026-06-12 (jh 대행) — assets 차트 (CM·SHAP·calibration) 가 carrier 에
            # 배달되도록 병합본 state 를 generator 에 전달. 기존엔 원본 state 가 넘어가
            # output_extras 산출물이 PPT 에 도달하지 못했음 (S15 빈 화면 원인).
            state_for_gen = state.with_update(category_extras=cat_extras)

            results: dict[str, str] = {}

            async def _gen(code: str) -> tuple[str, str | None]:
                try:
                    gen_cls = GENERATORS.get(code)
                    if gen_cls is None:
                        return code, None
                    gen = gen_cls(state.job_id)
                    # ADR-008 L2 — state 전달 (carrier 가 _pii mapping 으로 reattach).
                    # 미수신 carrier 호환을 위해 inspect.signature 분기.
                    sig = inspect.signature(gen.generate)
                    kwargs: dict[str, Any] = dict(
                        insights=state.insights or "",
                        best_model=state.best_model or {},
                        eda_charts=state.eda_charts,
                        category=state.category,
                        user_intent=state.user_intent or state.user_question or "",
                        eval_result=state.eval_result,
                    )
                    if "state" in sig.parameters:
                        kwargs["state"] = state_for_gen
                    path = await asyncio.to_thread(gen.generate, **kwargs)
                    return code, path
                except Exception as e:
                    self.logger.warning("output_failed", code=code, error=str(e))
                    return code, None

            done = await asyncio.gather(*[_gen(c) for c in requested])

            # NOTE: 그래프 노드는 세션 주입 없이 생성돼 self.session=None 이므로 아래 _save_output_row
            #   는 워커에서 실제로 실행되지 않는다. Output 행/Job.requested_outputs 의 DB 영속화는
            #   orchestrator.runner._persist_outputs_to_db 가 완료 시점에 중앙에서 수행한다(재진행=교체).
            for code, path in done:
                if path:
                    results[code] = path
                    if self.session is not None:
                        await self._save_output_row(state.job_id, code, path)

            # HJ 2026-06-11 — G6 모달 라이브 피드: 완료 status + 산출물별 자연어 인사이트.
            # G2 의 eda_insights 패턴 — 산출물별 결과를 한 줄씩 publish.
            try:
                _done_ko = [_OUTPUT_KO.get(c, c) for c in results.keys()]
                _g6_insights: list[str] = []
                # 산출물별 성공/실패 표시
                for code in requested:
                    ko = _OUTPUT_KO.get(code, code)
                    if code in results:
                        _g6_insights.append(f"산출물 생성: {ko} ✓ 완료")
                    else:
                        _g6_insights.append(f"산출물 생성: {ko} ✗ 실패")
                # 종합 요약 한 줄
                _g6_insights.append(
                    f"종합: 요청 {len(requested)}종 중 {len(results)}종 생성 완료 "
                    f"({(len(results) / max(len(requested), 1) * 100):.0f}%)"
                )
                # HJ 2026-06-13 — 산출물 결과 윤색은 단순 작업이라 Ollama+백그라운드로 (토큰 절약 + 즉시 전진).
                #   산출물 생성 자체는 _gen()이 수행, 윤색은 성공/실패 목록에 해석 붙이는 보조라 품질 무영향.
                self._spawn_insight_polish(
                    list(_g6_insights),
                    backend="ollama",
                    context="G6 산출물 합성",
                    job_id=state.job_id,
                    key="g6_output_insights",
                )
                _safe_publish_stage_partial(
                    state.job_id,
                    {
                        "g6_phase": "report_composer_done",
                        "g6_status": f"리포트 합성 완료 — {len(results)}/{len(requested)} 산출물 생성",
                        "report_done_count": len(results),
                        "report_done_names": _done_ko,
                        "g6_output_insights": _g6_insights,
                    },
                )
            except Exception as e:  # noqa: BLE001
                self.logger.debug("g6_partial_done_failed", error=str(e))

            return state.with_update(
                output_paths=results, category_extras=cat_extras, next_agent="self_learning_dispatch"
            )

    async def _save_output_row(self, job_id: str, code: str, minio_path: str) -> None:
        try:
            from ada.db.models import Output

            self.session.add(
                Output(
                    job_id=_uuid.UUID(job_id),
                    output_code=code,
                    minio_path=minio_path,
                )
            )
            await self.session.flush()
        except Exception as e:
            self.logger.warning("output_db_save_failed", error=str(e))

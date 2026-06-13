"""agents.base — BaseAgent 추상 클래스 (Day03 §4).

R-003 모든 에이전트는 이 클래스를 상속한다.
R-004 LLM 호출은 ``_call_llm()`` 헬퍼만 사용.
"""

from __future__ import annotations

import abc
import asyncio
import json
import re
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.breaker import get_breaker
from ada.core.config import settings
from ada.core.logger import bind_context, get_logger, log_agent_run
from ada.core.state import REPORT_CONTEXT_STAGES, PipelineState
from agents.personas import get_persona

# HJ 2026-06-09 G1 단축 T — module-level stop 토큰 (Ollama 호출 공통).
# γ streaming 호출에서도 동일 사용.
_OLLAMA_STOP_TOKENS: list[str] = [
    "```",  # markdown fence
    "\n```",
    "\n\n참고:",
    "\n\n설명:",
    "\n\nNote:",
    "\n\nExplanation:",
    "</s>",  # Qwen EOS
]


# ---------------------------------------------------------------------------
# HJ 2026-06-13 — 백그라운드 인사이트 윤색 (critical path 제거).
# ---------------------------------------------------------------------------
# G4 등에서 _dynamic_insights(Claude 윤색)를 `await` 하면 다음 agent 전진이
# 윤색(최대 30초)만큼 막힌다. 윤색 결과는 모달 표시 전용(job_id+key 주면
# _dynamic_insights 내부가 직접 publish)이라 다음 agent 입력이 아니므로,
# `create_task` 로 백그라운드 실행하고 파이프라인은 즉시 전진시킨다.
# event loop 생명주기 안전을 위해 모듈 레벨 set 으로 task 를 보관하고,
# orchestrator.runner._invoke/_resume 가 게이트 인터럽트 직전에
# drain_background_insights() 로 회수(미완 윤색을 모달에 마저 반영).
_BACKGROUND_INSIGHT_TASKS: "set[asyncio.Task]" = set()


async def drain_background_insights(timeout: float = 25.0) -> None:
    """백그라운드 윤색 task 들을 timeout 내에서 회수(best-effort).

    게이트 도달 시점에 호출 — 남은 Claude 윤색이 모달에 마저 반영되도록 한다.
    timeout 초과분은 그대로 백그라운드 진행(다음 폴링에서 모달 갱신).
    """
    pending = {t for t in _BACKGROUND_INSIGHT_TASKS if not t.done()}
    if not pending:
        return
    try:
        await asyncio.wait(pending, timeout=timeout)
    except Exception:  # noqa: BLE001
        pass


class BaseAgent(abc.ABC):
    """모든 에이전트의 공통 베이스."""

    model_name: str = "claude-sonnet-4-6"
    uses_llm: bool = True
    # True 로 설정한 에이전트는 use_ollama_for_analysis 설정과 무관하게
    # Anthropic API 를 우선 사용한다 (G4 모델 전략 이후 단계).
    use_anthropic_api: bool = False

    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        self.session = session
        self.logger = get_logger(self.__class__.__name__)
        self.persona = get_persona(self.__class__.__name__)
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0
        self._anthropic: Any = None
        self._current_job_id: Optional[str] = None

    @abc.abstractmethod
    async def __call__(self, state: PipelineState) -> PipelineState:
        """진입점."""

    @staticmethod
    def _agent_progress_key(class_name: str) -> str:
        """ClassName → snake_case key for AGENT_PROGRESS_MAP."""
        name = class_name.removesuffix("Agent")
        return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

    # ==============================================================
    # Phase 1.2 — ReportContext 적립 표준 진입점
    # --------------------------------------------------------------
    # 모든 에이전트는 자기 stage 에 contribute_to_context() 로 적립.
    # 13묶음 stage 키는 ada.core.state.REPORT_CONTEXT_STAGES 가 진실원.
    # ==============================================================

    def contribute_to_context(
        self,
        state: PipelineState,
        stage: str,
        payload: dict[str, Any],
        *,
        merge: bool = True,
    ) -> PipelineState:
        """``state.report_context[stage]`` 에 payload 적립.

        Args:
            state: 현재 파이프라인 상태.
            stage: ``REPORT_CONTEXT_STAGES`` 중 하나.
            payload: stage 에 저장할 dict. ``None``/비-dict 면 무시 (warning 만).
            merge: ``True`` 면 기존 stage dict 와 shallow merge (기본),
                   ``False`` 면 통째 교체.

        Returns:
            새 ``PipelineState`` (R-005 준수). 입력 state 는 변경하지 않음.

        Notes:
            - stage 가 잘못된 경우 warning 만 남기고 원본 state 반환 (silent-safe).
            - 본 hook 은 의무가 아니라 권장 — 호출 안 해도 carrier 는 동작.
            - ``builder.py`` 가 state 의 기존 필드(best_model 등)와 동기화하므로
              중복 적립도 안전.
        """
        if stage not in REPORT_CONTEXT_STAGES:
            try:
                self.logger.warning(
                    "contribute_invalid_stage",
                    stage=stage,
                    valid=REPORT_CONTEXT_STAGES,
                )
            except Exception:
                pass
            return state
        if not isinstance(payload, dict):
            try:
                self.logger.warning(
                    "contribute_payload_not_dict",
                    stage=stage,
                    type=type(payload).__name__,
                )
            except Exception:
                pass
            return state

        ctx = dict(state.report_context or {})
        current = ctx.get(stage)
        if merge and isinstance(current, dict):
            ctx[stage] = {**current, **payload}
        else:
            ctx[stage] = dict(payload)
        return state.with_update(report_context=ctx)

    def append_to_context_list(
        self,
        state: PipelineState,
        stage: str,
        sub_key: str,
        items: list[Any],
    ) -> PipelineState:
        """``state.report_context[stage][sub_key]`` 리스트에 ``items`` extend.

        ``stage`` 가 dict 가 아니거나 ``sub_key`` 가 list 가 아니면 자동 초기화.
        """
        if stage not in REPORT_CONTEXT_STAGES:
            try:
                self.logger.warning("append_invalid_stage", stage=stage)
            except Exception:
                pass
            return state
        if not isinstance(items, list):
            items = [items]

        ctx = dict(state.report_context or {})
        bucket = ctx.get(stage)
        if not isinstance(bucket, dict):
            bucket = {}
        existing = bucket.get(sub_key)
        if not isinstance(existing, list):
            existing = []
        bucket[sub_key] = [*existing, *items]
        ctx[stage] = bucket
        return state.with_update(report_context=ctx)

    @asynccontextmanager
    async def log_agent_run(self, state: PipelineState) -> AsyncIterator[None]:
        from ada.db.models import AgentRun
        from ada.observability.metrics import (
            get_kb_citation_count,
            reset_kb_citation_counter,
        )

        bind_context(job_id=state.job_id, agent_name=self.__class__.__name__)
        self._current_job_id = state.job_id
        # Day 11 — per-agent KB 인용 카운터 리셋 (KP9 측정용)
        reset_kb_citation_counter()

        # phase 단위 진행률 발행 — start 시점.
        # 호환을 위해 기존 AGENT_PROGRESS_MAP/publish_progress 사용. end 는 finally 블록에서.
        self._progress_agent_key: str | None = None
        try:
            from orchestrator.runner import AGENT_PHASE_MAP, agent_phase_progress, publish_progress

            key = self._agent_progress_key(self.__class__.__name__)
            if key in AGENT_PHASE_MAP and state.job_id:
                self._progress_agent_key = key
                publish_progress(state.job_id, key, progress=agent_phase_progress(key, "start"))
        except Exception:
            pass

        start = time.perf_counter()
        run_id = uuid.uuid4()
        if self.session is not None:
            self.session.add(
                AgentRun(
                    id=run_id,
                    job_id=uuid.UUID(state.job_id) if isinstance(state.job_id, str) else state.job_id,
                    agent_name=self.__class__.__name__,
                    status="running",
                    gate=state.current_gate,
                    was_re_loop=state.re_loop_count > 0,
                )
            )
            await self.session.flush()

        status = "completed"
        error: Optional[str] = None
        try:
            yield
        except Exception as e:
            status = "failed"
            error = f"{type(e).__name__}: {e}"[:2000]
            try:
                e._ada_state = state.with_update(
                    error=error,
                    error_traceback=traceback.format_exc()[:8000],
                    auto_fix_attempts=state.auto_fix_attempts + 1,
                    next_agent="auto_error_handler",
                )
            except Exception:
                pass
            raise
        finally:
            # phase='end' 발행 — agent 완전 종료 시점 (성공·실패 모두). 진행률이 다음 agent
            # 시작 직전까지 그 agent 의 end 값을 유지하도록 보장.
            if status == "completed" and self._progress_agent_key and state.job_id:
                try:
                    from orchestrator.runner import agent_phase_progress, publish_progress

                    publish_progress(
                        state.job_id,
                        self._progress_agent_key,
                        progress=agent_phase_progress(self._progress_agent_key, "end"),
                    )
                except Exception:
                    pass
            duration_ms = int((time.perf_counter() - start) * 1000)
            log_agent_run(
                job_id=state.job_id,
                agent_name=self.__class__.__name__,
                status=status,
                duration_ms=duration_ms,
                input_tokens=self._last_input_tokens,
                output_tokens=self._last_output_tokens,
                error=error,
            )
            try:
                from ada.observability.metrics import record_agent_run

                err_type = None
                if status == "failed" and error:
                    err_type = error.split(":", 1)[0]
                record_agent_run(self.__class__.__name__, duration_ms / 1000.0, err_type)
            except Exception:
                pass
            # Day 11 — per-agent KB 인용 횟수 (KP9 정확도)
            kb_count = get_kb_citation_count()
            if self.session is not None:
                row = await self.session.get(AgentRun, run_id)
                if row is not None:
                    row.status = status
                    row.duration_ms = duration_ms
                    row.input_tokens = self._last_input_tokens
                    row.output_tokens = self._last_output_tokens
                    row.error = error
                    if kb_count > 0:
                        existing = row.payload if isinstance(row.payload, dict) else {}
                        existing["kb_citations"] = kb_count
                        row.payload = existing
                    await self.session.flush()

    async def _call_llm(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        model_name: Optional[str] = None,
        json_mode: bool = False,
        on_partial: Any = None,  # Callable[[str], None] — Ollama streaming 시만 활용
        force_backend: Optional[str] = None,  # "ollama"|"anthropic" 강제 (None=기본 라우팅)
        track_progress: bool = True,  # False 면 진행률 보간·llm_end publish 생략(보조 호출용)
    ) -> str:
        prefix = f"{self.persona}\n\n" if self.persona else ""
        full_system = prefix + system_prompt
        # 한국어 가드 자동 부착 — qwen2.5:7b 중국어 응답 차단 (전 에이전트 일괄 적용).
        try:
            from ada.core.lang_guard import with_korean_guard

            full_system = with_korean_guard(full_system)
        except Exception:
            pass

        # LLM 호출 시작 시점 phase='llm_start' 발행 + 호출 중 매초 보간 task 가동.
        # 호출 시간이 데이터·모델에 따라 가변이므로, llm_start→llm_end 사이를 elapsed/예측 시간
        # 비례로 매초 갱신 → 클라이언트는 진짜 시간 비례 진행률을 본다.
        interp_task = None
        agent_key = getattr(self, "_progress_agent_key", None)
        job_id = getattr(self, "_current_job_id", None)
        if track_progress and agent_key and job_id:
            interp_task = await self._start_llm_progress_interp(agent_key, job_id)
        # Routing 결정:
        #   1. use_anthropic_api=True 에이전트 (G4 모델 전략 이후) → Anthropic API 우선
        #   2. use_ollama_for_analysis=True 면 Ollama (qwen2.5:7b 기본 — 서버 성능 한계)
        #   3. anthropic_api_key 있으면 Anthropic API
        #   4. fallback: Claude CLI
        # HJ 2026-06-11 — force_backend 로 단계별 백엔드 강제 (G1~3 Ollama / G4~6 Claude).
        if force_backend == "ollama":
            use_ollama = True
        elif force_backend == "anthropic":
            use_ollama = False
        else:
            force_anthropic = self.use_anthropic_api and bool(settings.anthropic_api_key)
            use_ollama = getattr(settings, "use_ollama_for_analysis", False) and not force_anthropic
        try:
            if use_ollama:
                # HJ 2026-06-09 G1 단축 γ — on_partial 콜백이 있으면 streaming 사용
                if on_partial is not None:
                    text = await self._call_llm_ollama_streaming(
                        system_prompt=full_system,
                        user_prompt=user_prompt,
                        on_partial=on_partial,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                else:
                    text = await self._call_llm_ollama(
                        system_prompt=full_system,
                        user_prompt=user_prompt,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
            elif settings.anthropic_api_key:
                text = await self._call_llm_api(
                    system_prompt=full_system,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model_name=model_name,
                )
            else:
                text = await self._call_llm_cli(
                    system_prompt=full_system,
                    user_prompt=user_prompt,
                    max_tokens=max_tokens,
                )
        finally:
            # 보간 task 중지 + llm_end 발행 (성공·실패 모두).
            if interp_task is not None:
                interp_task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(interp_task), timeout=2.0)
                except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                    pass
            if track_progress and agent_key and job_id:
                try:
                    from orchestrator.runner import agent_phase_progress, publish_progress

                    publish_progress(job_id, agent_key, progress=agent_phase_progress(agent_key, "llm_end"))
                except Exception:
                    pass

        if json_mode:
            text = self._strip_md_fence(text)
        # HJ 2026-06-09 — 한국어 강제 가드 (응답 수신 후 한자 자동 제거).
        # with_korean_guard (system prompt) + 응답 단계 strip 의 이중 안전망.
        # qwen2.5:7b 가 가끔 한자 섞어 응답하는 경우 (영문 컬럼명 입력 등) 대응.
        # 한자 발견 시: 로그 경고 + strip_cjk_han 으로 한자만 제거 (한국어 문장 보존).
        try:
            from ada.core.lang_guard import contains_cjk_han, count_cjk_han, strip_cjk_han

            if text and contains_cjk_han(text):
                n_han = count_cjk_han(text)
                self.logger.warning(
                    "llm_response_contained_cjk_han_stripped",
                    agent=self.__class__.__name__,
                    han_count=n_han,
                    sample=text[:100],
                )
                text = strip_cjk_han(text)
        except Exception:  # noqa: BLE001
            # 가드 실패해도 본 흐름 영향 없음
            pass
        return text

    async def _start_llm_progress_interp(self, agent_key: str, job_id: str):
        """LLM 호출 도중 매초 llm_start→llm_end 사이를 보간 publish 하는 background task.

        예상 시간(eta)은 EWMA 기반 동적 학습: 같은 agent 의 직전 LLM 호출 시간을 가중평균하여
        다음 호출 eta 로 사용 → 데이터 크기/모델 변화에 자동 적응. 첫 호출은 보수적 기본값(15s).
        보간이 llm_end 초과는 하지 않도록 cap.
        """
        import asyncio as _aio

        from orchestrator.runner import agent_phase_progress, publish_progress

        # class 변수로 EWMA 통계 보존 (워커 프로세스 lifetime)
        cls = type(self)
        if not hasattr(cls, "_llm_eta_ewma"):
            cls._llm_eta_ewma = {}  # type: ignore[attr-defined]
        eta = cls._llm_eta_ewma.get(agent_key, 15.0)  # type: ignore[attr-defined]

        lo_pct = agent_phase_progress(agent_key, "llm_start")
        hi_pct = agent_phase_progress(agent_key, "llm_end")
        publish_progress(job_id, agent_key, progress=lo_pct)
        self._llm_call_started_at = time.perf_counter()

        async def _loop() -> None:
            try:
                while True:
                    await _aio.sleep(1.0)
                    elapsed = time.perf_counter() - self._llm_call_started_at
                    ratio = min(1.0, elapsed / max(1.0, eta))
                    pct = int(lo_pct + (hi_pct - lo_pct) * ratio)
                    pct = max(lo_pct, min(hi_pct, pct))
                    try:
                        publish_progress(job_id, agent_key, progress=pct)
                    except Exception:
                        pass
            except _aio.CancelledError:
                # 실제 호출 시간으로 EWMA 갱신
                actual = time.perf_counter() - self._llm_call_started_at
                prev = cls._llm_eta_ewma.get(agent_key, actual)  # type: ignore[attr-defined]
                cls._llm_eta_ewma[agent_key] = 0.3 * actual + 0.7 * prev  # type: ignore[attr-defined]
                raise

        return _aio.create_task(_loop())

    async def _call_llm_api(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
        temperature: float,
        model_name: Optional[str],
    ) -> str:
        import anthropic

        from ada.core.langfuse_client import track_llm

        if self._anthropic is None:
            # 요청 타임아웃 필수 — 없으면 SDK 기본(~10분)으로 호출이 멈춰 파이프라인 전체가 hang.
            self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key, timeout=30.0, max_retries=1)

        breaker = get_breaker("anthropic", fail_max=3, reset_timeout=30)
        actual_model = model_name or self.model_name

        async def _do_call() -> Any:
            return await self._anthropic.messages.create(
                model=actual_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

        with track_llm(
            name=self.__class__.__name__,
            model=actual_model,
            job_id=getattr(self, "_current_job_id", None),
            agent=self.__class__.__name__,
        ) as span:
            try:
                resp = await breaker.call(_do_call) if asyncio.iscoroutinefunction(breaker.call) else await _do_call()
            except Exception as e:
                self.logger.error("llm_api_call_failed", error=str(e))
                if span is not None and hasattr(span, "update"):
                    try:
                        span.update(level="ERROR", status_message=str(e)[:200])
                    except Exception:
                        pass
                raise

            usage = getattr(resp, "usage", None)
            self._last_input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
            self._last_output_tokens = getattr(usage, "output_tokens", 0) if usage else 0

            if span is not None and hasattr(span, "update"):
                try:
                    span.update(
                        metadata={
                            "input_tokens": self._last_input_tokens,
                            "output_tokens": self._last_output_tokens,
                        },
                    )
                except Exception:
                    pass

            try:
                from ada.observability.metrics import record_llm_tokens

                record_llm_tokens(
                    actual_model,
                    self._last_input_tokens,
                    self._last_output_tokens,
                )
            except Exception:
                pass

        text = ""
        for blk in resp.content:
            if getattr(blk, "type", None) == "text":
                text += blk.text
        return text

    async def _call_llm_ollama(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Ollama /api/chat 호출 (asyncio.to_thread + urllib).

        분석 파이프라인 전 과정에서 사용. settings.ollama_model_analysis 기본 = qwen2.5:7b
        (서버·로컬 PC 성능 한계로 14b 미사용).
        Anthropic API 와 동일한 (system, user) → text 시그니처 유지.
        """
        import json as _json
        import urllib.error as _ue
        import urllib.request as _ur

        base_url = settings.ollama_base_url.rstrip("/")
        model = settings.ollama_model_analysis

        # HJ 2026-06-09 — G1 단축 T: stop 토큰은 module-level _OLLAMA_STOP_TOKENS 사용.
        payload = _json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                # HJ 2026-06-11 — 모델을 30분 메모리 상주시켜 G1→G2→G3 간 재로드(콜드스타트) 방지.
                #   콜드스타트가 G2 재작성 타임아웃의 주원인 → 워밍 유지로 후속 호출 대폭 단축.
                "keep_alive": "30m",
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": 0.9,
                    "num_gpu": getattr(settings, "ollama_num_gpu", 0),
                    "num_thread": getattr(settings, "ollama_num_thread", 8),
                    "stop": _OLLAMA_STOP_TOKENS,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")

        from ada.core.langfuse_client import track_llm

        def _do_call() -> str:
            req = _ur.Request(
                f"{base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with _ur.urlopen(req, timeout=180) as resp:
                    data = _json.loads(resp.read())
                # HJ 2026-06-12 — Ollama 네이티브 타이밍 메트릭 로깅 (병목 진단).
                #   load=콜드스타트(모델 로딩), prompt_eval=입력 처리, eval=토큰 생성.
                #   나노초→밀리초 환산. 어느 구간이 wall-clock 을 먹는지 식별용.
                try:
                    _ns = 1_000_000  # ns→ms
                    _ec = int(data.get("eval_count", 0) or 0)
                    _ed = int(data.get("eval_duration", 0) or 0)
                    self.logger.info(
                        "ollama_timing",
                        agent=self.__class__.__name__,
                        model=model,
                        total_ms=round(int(data.get("total_duration", 0) or 0) / _ns, 1),
                        load_ms=round(int(data.get("load_duration", 0) or 0) / _ns, 1),
                        prompt_eval_ms=round(int(data.get("prompt_eval_duration", 0) or 0) / _ns, 1),
                        prompt_tokens=int(data.get("prompt_eval_count", 0) or 0),
                        eval_ms=round(_ed / _ns, 1),
                        eval_tokens=_ec,
                        tok_per_sec=round(_ec / (_ed / 1_000_000_000), 1) if _ed > 0 else 0.0,
                    )
                except Exception:  # noqa: BLE001
                    pass
                return data.get("message", {}).get("content", "") or ""
            except (_ue.URLError, TimeoutError, OSError, ValueError) as e:
                self.logger.error("ollama_call_failed", error=str(e), model=model)
                raise

        with track_llm(
            name=self.__class__.__name__,
            model=model,
            job_id=getattr(self, "_current_job_id", None),
            agent=self.__class__.__name__,
        ) as span:
            try:
                text = await asyncio.to_thread(_do_call)
            except Exception as e:
                if span is not None and hasattr(span, "update"):
                    try:
                        span.update(level="ERROR", status_message=str(e)[:200])
                    except Exception:
                        pass
                raise
            self._last_input_tokens = (len(system_prompt) + len(user_prompt)) // 4
            self._last_output_tokens = len(text) // 4
            if span is not None and hasattr(span, "update"):
                try:
                    span.update(
                        metadata={
                            "input_tokens_est": self._last_input_tokens,
                            "output_tokens_est": self._last_output_tokens,
                            "backend": "ollama",
                        }
                    )
                except Exception:
                    pass
            try:
                from ada.observability.metrics import record_llm_tokens

                record_llm_tokens(model, self._last_input_tokens, self._last_output_tokens)
            except Exception:
                pass
        return text

    async def _call_llm_ollama_streaming(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        on_partial: Any,  # Callable[[str], None]
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """HJ 2026-06-09 G1 단축 γ — Ollama streaming 호출 + partial 콜백.

        Ollama /api/chat 의 stream=true 로 토큰 단위 응답 받음. 매 chunk 도착 시점에
        on_partial(누적 텍스트) 호출. 호출자는 누적 텍스트에서 필드 등장 시점을 감지해
        Redis publish 등 수행. 최종 누적 텍스트 반환.

        누수 방지:
          - HTTP 연결: `with urlopen` 자동 close
          - on_partial 예외: try/except 로 본 흐름 보호
          - timeout 180s + breaker 패턴 미적용 (streaming 은 breaker 호환 안 함, 명시적 timeout)
          - chunk 단위 메모리 누적: 도메인 응답 ~3KB, 안전
        """
        import json as _json
        import urllib.error as _ue
        import urllib.request as _ur

        base_url = settings.ollama_base_url.rstrip("/")
        model = settings.ollama_model_analysis
        payload = _json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": True,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": temperature,
                    "top_p": 0.9,
                    "num_gpu": getattr(settings, "ollama_num_gpu", 0),
                    "num_thread": getattr(settings, "ollama_num_thread", 8),
                    "stop": _OLLAMA_STOP_TOKENS,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")

        from ada.core.langfuse_client import track_llm

        def _do_stream() -> str:
            accumulated = ""
            req = _ur.Request(
                f"{base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with _ur.urlopen(req, timeout=180) as resp:
                    for raw_line in resp:
                        if not raw_line:
                            continue
                        line_str = raw_line.decode("utf-8", errors="replace").strip()
                        if not line_str:
                            continue
                        try:
                            chunk = _json.loads(line_str)
                        except Exception:
                            continue
                        # Ollama chunk: {"message":{"role":"assistant","content":"..."},"done":false}
                        msg = chunk.get("message") or {}
                        content = msg.get("content", "") or ""
                        if content:
                            accumulated += content
                            try:
                                on_partial(accumulated)
                            except Exception as cb_e:  # noqa: BLE001
                                self.logger.warning("ollama_stream_callback_failed", error=str(cb_e))
                        if chunk.get("done"):
                            break
            except (_ue.URLError, TimeoutError, OSError, ValueError) as e:
                self.logger.error("ollama_stream_failed", error=str(e), model=model)
                raise
            return accumulated

        with track_llm(
            name=self.__class__.__name__,
            model=model,
            job_id=getattr(self, "_current_job_id", None),
            agent=self.__class__.__name__,
        ) as span:
            try:
                text = await asyncio.to_thread(_do_stream)
            except Exception as e:
                if span is not None and hasattr(span, "update"):
                    try:
                        span.update(level="ERROR", status_message=str(e)[:200])
                    except Exception:
                        pass
                raise
            self._last_input_tokens = (len(system_prompt) + len(user_prompt)) // 4
            self._last_output_tokens = len(text) // 4
            if span is not None and hasattr(span, "update"):
                try:
                    span.update(
                        metadata={
                            "input_tokens_est": self._last_input_tokens,
                            "output_tokens_est": self._last_output_tokens,
                            "backend": "ollama_streaming",
                        }
                    )
                except Exception:
                    pass
            try:
                from ada.observability.metrics import record_llm_tokens

                record_llm_tokens(model, self._last_input_tokens, self._last_output_tokens)
            except Exception:
                pass
        return text

    async def _call_llm_cli(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        import json as _json
        import shutil
        import subprocess

        if shutil.which("claude") is None:
            raise RuntimeError(
                "Claude CLI missing. `npm install -g @anthropic-ai/claude-code` or set ANTHROPIC_API_KEY."
            )
        prompt = f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"

        def _run() -> str:
            proc = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "1"],
                capture_output=True,
                text=True,
                timeout=45,
            )
            return proc.stdout

        breaker = get_breaker("claude_cli", fail_max=3, reset_timeout=60)
        try:
            raw = await asyncio.to_thread(breaker.call, _run)
        except Exception as e:
            self.logger.error("llm_cli_call_failed", error=str(e))
            raise
        try:
            data = _json.loads(raw)
            return data.get("result") or data.get("content") or raw
        except Exception:
            return raw.strip()

    @staticmethod
    def _strip_md_fence(text: str) -> str:
        return re.sub(r"^```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.MULTILINE)

    def _parse_json(self, text: str) -> Any:
        text = self._strip_md_fence(text)
        try:
            return json.loads(text)
        except Exception:
            return None

    def _spawn_insight_polish(
        self,
        lines: list[str],
        *,
        backend: str = "claude",
        context: str = "",
        job_id: str | None = None,
        key: str | None = None,
    ) -> None:
        """HJ 2026-06-13 — `_dynamic_insights` 를 백그라운드로 실행(critical path 제거).

        규칙 기반 lines 의 즉시 발행 + Claude 윤색 후 교체 발행은 모두
        `_dynamic_insights` 가 job_id+key 로 수행하므로, 본 헬퍼는 그 코루틴을
        `create_task` 로 던지고 즉시 반환한다 → 다음 agent 가 윤색을 기다리지 않는다.
        실행 중인 event loop 가 없거나 job_id/key 가 없으면 발행 의미가 없어 no-op.
        회수는 ``drain_background_insights()`` 가 게이트 인터럽트 직전에 담당.
        """
        if not job_id or not key or not lines:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._dynamic_insights(lines, backend=backend, context=context, job_id=job_id, key=key))
        _BACKGROUND_INSIGHT_TASKS.add(task)
        task.add_done_callback(_BACKGROUND_INSIGHT_TASKS.discard)

    async def _dynamic_insights(
        self,
        lines: list[str],
        *,
        backend: str = "ollama",
        context: str = "",
        job_id: str | None = None,
        key: str | None = None,
        timeout_s: float | None = None,
    ) -> list[str]:
        """규칙 기반 인사이트를 LLM 으로 항목별 동적 재작성 (HJ 2026-06-11 v2).

        사실 헤더(라벨·컬럼·수치)는 보존, "—" 뒤 해석부만 항목별로 새로 생성.
        job_id+key 가 있으면 (1) 템플릿 즉시 발행(모달 빈칸 방지) → (2) LLM 재작성 →
        (3) 결과 재발행(교체). 진행바 보간은 track_progress=False 로 끔(진행바 꼬임 방지).
        출력은 작은 모델도 잘 맞추는 `번호|해석` 한 줄 포맷 + 관대한 파싱, 백엔드별 넉넉한
        타임아웃. 실패·누락은 항목 단위 원본 유지(무중단). G1~3 ollama / G4~6 claude.
        """
        if not lines or not isinstance(lines, list):
            return lines

        # 업그레이드 안내: 기존 "현재 작업" 상태줄(*_status)을 재활용 — 멘트만 바꾸면 됨.
        status_key = (key.split("_", 1)[0] + "_status") if key else None
        upgrade_msg = "✨ 1차 분석 먼저 표시 · 더 정밀한 해석으로 2차 분석 업그레이드하는 중…"

        def _publish(plines, status=None):
            if not job_id or not key:
                return
            payload = {key: plines}
            if status is not None and status_key:
                payload[status_key] = status
            try:
                from orchestrator.runner import publish_stage_partial as _psp

                _psp(job_id, payload)
            except Exception:  # noqa: BLE001
                pass

        _publish(lines, status=upgrade_msg)  # (1) 템플릿 즉시 발행 + 업그레이드 안내

        sep = " — "
        headers = []
        order = []
        prompt_items = []
        for i, ln in enumerate(lines):
            s = ln if isinstance(ln, str) else str(ln)
            head = s.split(sep, 1)[0] if sep in s else s
            old = s.split(sep, 1)[1] if sep in s else ""
            headers.append(head)
            n = len(order) + 1
            order.append(i)
            prompt_items.append(f"{n}) 사실: {head}" + (f" / 기존해석: {old}" if old else ""))

        system_prompt = (
            "당신은 머신러닝 데이터·모델 분석을 한국어로 해설하는 전문가입니다. "
            "각 항목의 '사실'(라벨·컬럼·수치)에 근거해, 모델링에 도움이 되는 구체적 "
            "해석/권장을 항목마다 한 문장으로 새로 작성합니다.\n"
            "출력 형식(엄수): 한 줄에 하나씩 `번호|해석문`. "
            "예) `1|Pclass는 상관 0.34로 중간 근접 약신호라 교호작용 피처로 보강 여지가 큽니다.`\n"
            "규칙: (1) 번호는 입력과 동일. (2) 사실의 수치를 새로 만들거나 바꾸지 말 것. "
            "(3) 항목마다 표현·권장이 서로 겹치지 않게. (4) 한 문장 100자 이내. "
            "(5) `번호|해석` 외 머리말·마크다운·코드펜스 금지."
        )
        user_prompt = (
            (f"분석 맥락: {context}\n" if context else "")
            + f"총 {len(prompt_items)}개 항목. 각 번호마다 한 줄씩 `번호|해석`:\n"
            + "\n".join(prompt_items)
        )

        fb = "anthropic" if backend in ("claude", "anthropic") else "ollama"
        if timeout_s is None:
            if fb == "anthropic":
                timeout_s = 30.0
            else:
                # HJ 2026-06-11 — ollama(qwen 7B·CPU)는 항목 많을수록 + 콜드스타트로 느림.
                #   고정 60s 는 G2(8항목)에서 자주 타임아웃 → 템플릿 폴백 버그. 항목수 비례로
                #   넉넉히 잡되 urlopen(180s) 안쪽으로 상한. 8항목=160s, 4항목=80s(최소).
                timeout_s = min(165.0, max(80.0, len(prompt_items) * 20.0))

        try:
            raw = await asyncio.wait_for(
                self._call_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=max(256, min(1600, len(prompt_items) * 120)),
                    temperature=0.5,
                    force_backend=fb,
                    track_progress=False,
                ),
                timeout=timeout_s,
            )
        except Exception as e:  # noqa: BLE001 — 타임아웃·호출실패 모두 원본 유지
            try:
                self.logger.warning("dynamic_insights_llm_failed", error=str(e)[:200], backend=fb, n=len(prompt_items))
            except Exception:
                pass
            return lines

        raw = self._strip_md_fence(raw or "")
        new_tails = {}
        plain = []
        for ln in raw.splitlines():
            t = ln.strip()
            if not t:
                continue
            matched = False
            for ssep in ("|", ")", ":"):
                if ssep in t:
                    left, _, right = t.partition(ssep)
                    left = left.strip().lstrip("([").strip()
                    if left.isdigit():
                        pos = int(left)
                        txt = right.strip().strip("|)-—: ").strip()
                        if 1 <= pos <= len(order) and len(txt) >= 4:
                            new_tails[order[pos - 1]] = txt
                            matched = True
                    break
            if not matched:
                plain.append(t)
        if not new_tails and len(plain) == len(order):
            for k, t in enumerate(plain):
                tt = t.strip("|)-—: ").strip()
                if len(tt) >= 4:
                    new_tails[order[k]] = tt

        if not new_tails:
            return lines

        out = []
        for i, ln in enumerate(lines):
            t = new_tails.get(i, "").strip()
            if len(t) < 4:
                out.append(ln)
                continue
            if len(t) > 180:
                t = t[:178] + "…"
            out.append(headers[i] + sep + t)

        if out != lines:
            # (3) 위→아래 순차 교체 — 한 항목씩 발행해 모달이 순서대로 채워지게(꼬임 방지).
            cur = list(lines)
            for idx in range(len(out)):
                cur[idx] = out[idx]
                _publish(cur)
                if idx < len(out) - 1:
                    try:
                        await asyncio.sleep(0.25)
                    except Exception:  # noqa: BLE001
                        pass
        return out

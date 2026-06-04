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
from ada.core.state import PipelineState
from agents.personas import get_persona


class BaseAgent(abc.ABC):
    """모든 에이전트의 공통 베이스."""

    model_name: str = "claude-sonnet-4-6"
    uses_llm: bool = True

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
    ) -> str:
        prefix = f"{self.persona}\n\n" if self.persona else ""
        full_system = prefix + system_prompt

        # LLM 호출 시작 시점 phase='llm_start' 발행 + 호출 중 매초 보간 task 가동.
        # 호출 시간이 데이터·모델에 따라 가변이므로, llm_start→llm_end 사이를 elapsed/예측 시간
        # 비례로 매초 갱신 → 클라이언트는 진짜 시간 비례 진행률을 본다.
        interp_task = None
        agent_key = getattr(self, "_progress_agent_key", None)
        job_id = getattr(self, "_current_job_id", None)
        if agent_key and job_id:
            interp_task = await self._start_llm_progress_interp(agent_key, job_id)
        try:
            if settings.anthropic_api_key:
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
                    await interp_task
                except (asyncio.CancelledError, Exception):
                    pass
            if agent_key and job_id:
                try:
                    from orchestrator.runner import agent_phase_progress, publish_progress

                    publish_progress(job_id, agent_key, progress=agent_phase_progress(agent_key, "llm_end"))
                except Exception:
                    pass

        if json_mode:
            text = self._strip_md_fence(text)
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

    async def _call_llm_cli(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        import asyncio
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
        except json.JSONDecodeError as e:
            self.logger.error("json_parse_failed", error=str(e), text_head=text[:200])
            raise

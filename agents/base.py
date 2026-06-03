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

        if json_mode:
            text = self._strip_md_fence(text)
        return text

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

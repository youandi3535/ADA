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
    """모든 에이전트의 공통 베이스.

    - 페르소나 자동 주입 (persona prefix 시스템 프롬프트)
    - agent_runs 기록 (log_agent_run 컨텍스트 매니저)
    - LLM 호출은 _call_llm() 한 곳에서만 — Langfuse trace 포함
    """

    #: 서브클래스에서 오버라이드 가능
    model_name: str = "claude-sonnet-4-6"

    #: LLM 호출 없는 에이전트는 False
    uses_llm: bool = True

    def __init__(self, session: Optional[AsyncSession] = None) -> None:
        self.session = session
        self.logger = get_logger(self.__class__.__name__)
        self.persona = get_persona(self.__class__.__name__)
        self._last_input_tokens: int = 0
        self._last_output_tokens: int = 0
        self._anthropic: Any = None  # lazy

    # ------------------------------------------------------------------
    # 추상 메서드
    # ------------------------------------------------------------------
    @abc.abstractmethod
    async def __call__(self, state: PipelineState) -> PipelineState:
        """그래프에서 호출되는 진입점. 상태 in → 상태 out."""

    # ------------------------------------------------------------------
    # 공통 헬퍼
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def log_agent_run(self, state: PipelineState) -> AsyncIterator[None]:
        """agent_runs 테이블에 running → completed/failed 기록."""
        from ada.db.models import AgentRun

        bind_context(job_id=state.job_id, agent_name=self.__class__.__name__)
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
            # Day 1 — Prometheus 메트릭 인스트루먼테이션 (단일 진입점)
            try:
                from ada.observability.metrics import record_agent_run

                err_type = None
                if status == "failed" and error:
                    err_type = error.split(":", 1)[0]
                record_agent_run(self.__class__.__name__, duration_ms / 1000.0, err_type)
            except Exception:
                pass
            if self.session is not None:
                row = await self.session.get(AgentRun, run_id)
                if row is not None:
                    row.status = status
                    row.duration_ms = duration_ms
                    row.input_tokens = self._last_input_tokens
                    row.output_tokens = self._last_output_tokens
                    row.error = error
                    await self.session.flush()

    # ------------------------------------------------------------------
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
        """LLM 호출 단일 진입점 (R-004).

        - 개발환경 (ANTHROPIC_API_KEY 미설정): Claude CLI 서브프로세스 호출 (무료)
        - 운영환경 (ANTHROPIC_API_KEY 설정됨): AsyncAnthropic API 호출 (과금)
        - 페르소나 prefix 자동 주입 (시스템 프롬프트 앞)
        - 회로차단기로 보호 (R-709)
        - input/output 토큰 카운트 self.* 에 누적
        - JSON 모드: 응답 텍스트의 마크다운 fence 자동 제거
        """
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
        """운영환경: AsyncAnthropic API (non-blocking await)."""
        import anthropic  # noqa: WPS433

        if self._anthropic is None:
            self._anthropic = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        breaker = get_breaker("anthropic", fail_max=3, reset_timeout=30)

        async def _do_call() -> Any:
            return await self._anthropic.messages.create(
                model=model_name or self.model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )

        try:
            resp = await breaker.call(_do_call) if asyncio.iscoroutinefunction(breaker.call) else await _do_call()
        except Exception as e:
            self.logger.error("llm_api_call_failed", error=str(e))
            raise

        # 토큰 사용량 누적
        usage = getattr(resp, "usage", None)
        self._last_input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        self._last_output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        try:
            from ada.observability.metrics import record_llm_tokens

            record_llm_tokens(
                model_name or self.model_name,
                self._last_input_tokens,
                self._last_output_tokens,
            )
        except Exception:
            pass

        text = ""
        for blk in resp.content:
            if getattr(blk, "type", None) == "text":
                text += blk.text  # type: ignore[attr-defined]
        return text

    async def _call_llm_cli(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        """개발환경: Claude CLI 서브프로세스 호출 (API 키 불필요, 무료).

        `claude -p "..." --output-format json` 을 asyncio.to_thread 로 실행.
        CLI 미설치 시 RuntimeError 발생.
        """
        import asyncio
        import json as _json
        import shutil
        import subprocess

        if shutil.which("claude") is None:
            raise RuntimeError(
                "Claude CLI 미설치 (개발환경). `npm install -g @anthropic-ai/claude-code` 또는 ANTHROPIC_API_KEY 설정."
            )

        prompt = f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"

        def _run() -> str:
            proc = subprocess.run(
                ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "1"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            return proc.stdout

        breaker = get_breaker("claude_cli", fail_max=3, reset_timeout=60)

        try:
            raw = await asyncio.to_thread(breaker.call, _run)
        except Exception as e:
            self.logger.error("llm_cli_call_failed", error=str(e))
            raise

        # Claude CLI JSON 출력에서 텍스트 추출
        try:
            data = _json.loads(raw)
            # {"result": "...", "type": "result"} 포맷
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

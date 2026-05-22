"""ada.error_handler.claude_cli_bridge — Claude CLI 사이드카 브리지 (Day16 R-601).

SDK 비동기 호출 우선. 사이드카 컨테이너 내부에서만 --allowed-tools 강제 (R-602).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from typing import Any

from ada.core.breaker import get_breaker
from ada.core.logger import get_logger

log = get_logger("claude_cli")


ALLOWED_TOOLS = "Read,Grep,Glob"


class ClaudeCLIBridge:
    """동기/비동기 양쪽 진입점 제공. 운영은 비동기 우선."""

    def _cmd(self, prompt: str) -> list[str]:
        # 사이드카 컨테이너 안에서 `claude` 가 PATH 에 있음.
        # R-602 — --allowed-tools 강제.
        return [
            "claude",
            "-p",
            prompt,
            "--allowed-tools",
            ALLOWED_TOOLS,
            "--output-format",
            "json",
            "--max-turns",
            "3",
        ]

    async def request_patch(self, *, error_signature: str, stack: str) -> dict[str, Any]:
        prompt = (
            "다음 오류를 분석해 최소 변경 unified diff 와 test_plan 을 JSON 으로 반환:\n"
            f"## error\n{error_signature}\n\n## stack\n{stack[:2000]}\n\n"
            "JSON 키: diff, test_plan, confidence(0~1)"
        )
        breaker = get_breaker("claude_cli", fail_max=3, reset_timeout=120)
        if shutil.which("claude") is None:
            # 사이드카 미설치 환경 — 빈 패치 반환
            return {"diff": "", "test_plan": "(no claude-cli)", "confidence": 0.0}

        def _run() -> str:
            proc = subprocess.run(
                self._cmd(prompt),
                capture_output=True,
                text=True,
                timeout=60,
            )
            return proc.stdout

        try:
            out = await asyncio.to_thread(breaker.call, _run)
            try:
                data = json.loads(out)
            except Exception:
                data = {"diff": out[:2000], "test_plan": "", "confidence": 0.3}
            return data
        except Exception as e:
            log.warning("claude_cli_failed", error=str(e))
            return {"diff": "", "test_plan": "", "confidence": 0.0}

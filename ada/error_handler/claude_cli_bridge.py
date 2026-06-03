"""ada.error_handler.claude_cli_bridge — Claude CLI 브리지 (Day16 + Full-Access 모드).

두 가지 모드:

[기존] request_patch() — 제한 모드
    --allowed-tools Read,Grep,Glob  (읽기 전용)
    --max-turns 3
    오류 + 스택만 주고 JSON diff 반환 요청
    → 단순·명확한 오류에 적합

[신규] request_fix_direct() — Claude Code 전체 도구 모드
    --allowed-tools Read,Write,Edit,Bash,Grep,Glob  (전체 도구)
    --max-turns 20
    격리된 git worktree 안에서 실행
    Claude 가 직접 파일을 읽고·수정·검증
    완료 후 git diff 로 변경사항 자동 추출
    → 복잡한 오류, 여러 파일에 걸친 버그에 적합

auto_handler Tier 3 는 request_fix_direct() 를 먼저 시도하고
실패 시 request_patch() 로 폴백한다.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import uuid as _uuid
from pathlib import Path
from typing import Any

from ada.core.breaker import get_breaker
from ada.core.logger import get_logger

log = get_logger("claude_cli")

# 기존 제한 모드
_RESTRICTED_TOOLS = "Read,Grep,Glob"

# Claude Code 전체 도구 모드 (worktree 격리 안에서만)
_FULL_TOOLS = "Read,Write,Edit,Bash,Grep,Glob"

# 프로젝트 루트 (worktree 생성 기준)
_REPO_ROOT = Path(os.environ.get("ADA_REPO_ROOT", "/app")).resolve()


class ClaudeCLIBridge:
    """동기/비동기 양쪽 진입점 제공. 운영은 비동기 우선."""

    # ─────────────────────────────────────────────────────────────────
    # [기존] 제한 모드 — JSON diff 반환
    # ─────────────────────────────────────────────────────────────────

    def _cmd_restricted(self, prompt: str) -> list[str]:
        return [
            "claude",
            "-p",
            prompt,
            "--allowed-tools",
            _RESTRICTED_TOOLS,
            "--output-format",
            "json",
            "--max-turns",
            "3",
        ]

    async def request_patch(self, *, error_signature: str, stack: str) -> dict[str, Any]:
        """읽기 전용 3턴으로 JSON diff 생성."""
        prompt = (
            "다음 오류를 분석해 최소 변경 unified diff 와 test_plan 을 JSON 으로 반환:\n"
            f"## error\n{error_signature}\n\n## stack\n{stack[:2000]}\n\n"
            "JSON 키: diff, test_plan, confidence(0~1)"
        )
        breaker = get_breaker("claude_cli", fail_max=3, reset_timeout=120)
        if shutil.which("claude") is None:
            return {"diff": "", "test_plan": "(no claude-cli)", "confidence": 0.0}

        def _run() -> str:
            proc = subprocess.run(
                self._cmd_restricted(prompt),
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

    # ─────────────────────────────────────────────────────────────────
    # [신규] Claude Code 전체 도구 모드 — worktree 격리 직접 수정
    # ─────────────────────────────────────────────────────────────────

    async def request_fix_direct(
        self,
        *,
        error_signature: str,
        stack: str,
        repo_root: str | None = None,
    ) -> dict[str, Any]:
        """Claude Code 전체 도구(Read/Write/Edit/Bash/Grep/Glob)로 직접 수정.

        흐름:
            1. git worktree 생성 (격리 환경)
            2. CLAUDE.md 컨텍스트 포함 프롬프트 전달
            3. Claude 가 파일을 직접 읽고 수정 (최대 20턴)
            4. git diff HEAD 로 변경사항 자동 추출
            5. diff 반환 → apply_patch() 로 실제 적용

        claude CLI 없으면 빈 dict 반환 (request_patch 로 폴백).
        worktree 는 성공·실패 무관 항상 정리.
        """
        if shutil.which("claude") is None:
            return {"diff": "", "test_plan": "(no claude-cli)", "confidence": 0.0}

        root = Path(repo_root or str(_REPO_ROOT)).resolve()
        branch = f"autofix/claude-full-{_uuid.uuid4().hex[:8]}"
        worktree_dir: Path | None = None

        try:
            # 1. worktree 생성
            tmp = tempfile.mkdtemp(prefix="ada-claude-")
            worktree_dir = Path(tmp) / "wt"

            r = await asyncio.to_thread(
                subprocess.run,
                ["git", "worktree", "add", "-b", branch, str(worktree_dir), "HEAD"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if r.returncode != 0:
                log.warning("claude_full_worktree_failed", stderr=r.stderr[:300])
                return {"diff": "", "confidence": 0.0}

            # 2. CLAUDE.md 읽기 (프롬프트에 포함)
            claude_md = ""
            try:
                claude_md_path = root / "CLAUDE.md"
                if claude_md_path.exists():
                    claude_md = claude_md_path.read_text(encoding="utf-8")[:3000]
            except Exception:
                pass

            prompt = (
                "다음 Python 오류를 직접 수정하세요.\n\n"
                f"## 오류 시그니처\n{error_signature}\n\n"
                f"## 스택트레이스\n{stack[:3000]}\n\n"
                "## 지시사항\n"
                "1. Read/Grep/Glob 으로 오류 원인 파일을 찾고 분석하세요.\n"
                "2. Edit/Write 로 최소한의 변경만 직접 수정하세요.\n"
                "3. Bash 로 수정 후 관련 테스트를 실행해 검증하세요.\n"
                "4. 수정이 완료되면 '수정 완료' 라고 출력하세요.\n\n"
                + (f"## 프로젝트 규칙 (CLAUDE.md 요약)\n{claude_md}\n" if claude_md else "")
            )

            # 3. Claude 전체 도구로 실행 (worktree cwd)
            def _run_full() -> subprocess.CompletedProcess:
                return subprocess.run(
                    [
                        "claude",
                        "-p",
                        prompt,
                        "--allowed-tools",
                        _FULL_TOOLS,
                        "--max-turns",
                        "20",
                        "--output-format",
                        "text",
                    ],
                    cwd=str(worktree_dir),
                    capture_output=True,
                    text=True,
                    timeout=300,
                )

            proc = await asyncio.to_thread(_run_full)
            log.info(
                "claude_full_finished",
                returncode=proc.returncode,
                output_len=len(proc.stdout),
            )

            # 4. git diff HEAD 로 변경사항 추출
            def _extract_diff() -> str:
                r2 = subprocess.run(
                    ["git", "diff", "HEAD"],
                    cwd=str(worktree_dir),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return r2.stdout

            diff = await asyncio.to_thread(_extract_diff)

            if not diff:
                log.info("claude_full_no_changes")
                return {"diff": "", "confidence": 0.0, "test_plan": "변경사항 없음"}

            log.info("claude_full_diff_extracted", chars=len(diff))
            return {
                "diff": diff,
                "test_plan": "[claude_code_full] 직접 수정 완료",
                "confidence": 0.90,  # 전체 도구 + 20턴 = 높은 신뢰도
            }

        except Exception as e:  # noqa: BLE001
            log.warning("claude_full_access_failed", error=str(e))
            return {"diff": "", "confidence": 0.0}

        finally:
            # worktree + branch 항상 정리
            if worktree_dir is not None:
                try:
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(worktree_dir)],
                        cwd=str(root),
                        timeout=30,
                        capture_output=True,
                    )
                except Exception:
                    pass
                try:
                    subprocess.run(
                        ["git", "branch", "-D", branch],
                        cwd=str(root),
                        timeout=10,
                        capture_output=True,
                    )
                except Exception:
                    pass
                try:
                    shutil.rmtree(str(worktree_dir.parent), ignore_errors=True)
                except Exception:
                    pass

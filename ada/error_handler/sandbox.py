"""ada.error_handler.sandbox — 패치 검증 격리 환경 (ADR-006 Phase 2-E).

🛡️ 자동 코드 수정 시스템의 가장 중요한 안전망.

LLM 이 생성한 diff 를 본 시스템에 직접 적용하는 건 자살 행위.
다음 4단계 검증을 격리된 git worktree 안에서 모두 통과해야만 적용 후보로 인정:

    1. 영역 검증 (R-403)  — diff 가 건드리는 파일이 HJ 영역인지
    2. 금지 파일 차단      — .env, migrations/, requirements/ 등 절대 금지
    3. diff syntax + ruff  — 적용 가능성 + 정적 분석
    4. pytest               — 실제 동작 (전체 또는 영역 한정)

격리 메커니즘:
    git worktree add → 별도 디렉토리 + 별도 브랜치
    → 패치 적용 → 테스트 → 결과 수집 → worktree 제거

운영 환경 (VPS) 안전 추가 고려:
    - sandbox 컨테이너 안에서 실행 (별도 Docker 네트워크, --cpus, --memory)
    - sandbox 내부 sqlite 사용 (운영 Postgres 접근 금지)
    - DRY_RUN 환경 변수 지원 (실제 적용 안 함, 검증 결과만)

본 모듈은 외부 의존성 0 — git / ruff / pytest 모두 subprocess 로 호출.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ada.core.logger import get_logger

log = get_logger("sandbox")


# =============================================================================
# 영역 매트릭스 (CLAUDE.md §1 와 동기 — HJ 영역만)
# =============================================================================

# HJ 가 수정 가능한 prefix (R-403 + CODEOWNERS 와 일치)
HJ_ALLOWED_PREFIXES: tuple[str, ...] = (
    "ada/",
    "orchestrator/",
    "api/",
    "frontend/app.py",
    "outputs/",
    "scripts/",
    "docker/",
    "docs/",
    # tests — HJ 만 수정 가능한 것들
    "tests/conftest.py",
    "tests/integration/",
    "tests/test_state.py",
    "tests/test_personas.py",
    "tests/test_graph_build.py",
    "tests/test_agents_count.py",
    "tests/test_autofix_",  # ADR-006 phase 1/2 테스트 (HJ 작성)
    "tests/test_day",  # tests/test_day{N}_*.py
    # agents — HJ 전용
    "agents/base.py",
    "agents/personas.py",
    "agents/stubs.py",
    "agents/supervisor.py",
    "agents/self_learning.py",
    "agents/auto_error_handler.py",
    "agents/security_guard.py",
    "agents/error_recovery.py",
    "agents/gates/",
    # 8 dispatcher
    "agents/data_profiler.py",
    "agents/preprocessing_strategist.py",
    "agents/feature_engineer.py",
    "agents/eda_agent.py",
    "agents/model_selection.py",
    "agents/eval_agent.py",
    "agents/insight.py",
    "agents/report_composer.py",
    # 기타 HJ agent
    "agents/hyperparameter_tuner.py",
    "agents/training_executor.py",
    "agents/training_monitor.py",
    "agents/metrics_aggregator.py",
    "agents/fine_tune_executor.py",
    "agents/intent_elicitor.py",
    "agents/schema_validator.py",
    "agents/explainability.py",
    "agents/handlers/__init__.py",
    "agents/handlers/_base.py",
    "agents/handlers/common/",
    # pipelines 공통
    "pipelines/base.py",
    "pipelines/factory.py",
    "pipelines/__init__.py",
    # 메타 / 인프라
    "Makefile",
    "AGENTS.md",
    "CLAUDE.md",
)

# 절대 자동 수정 금지 파일 (HJ 영역이라도 금지)
# 시크릿·인프라·의존성·마이그레이션 = 사람이 직접 다뤄야 함.
FORBIDDEN_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^\.env"),  # .env, .env.example, .env.local 등
    re.compile(r"^migrations/versions/"),  # alembic 마이그레이션
    re.compile(r"^requirements/"),  # 의존성 lock
    re.compile(r"^pyproject\.toml$"),
    re.compile(r"^alembic\.ini$"),
    re.compile(r"^\.github/workflows/"),  # CI/CD
    re.compile(r"^\.pre-commit-config\.yaml$"),
    re.compile(r"^\.gitattributes$"),
    re.compile(r"^docker/.*\.(yml|yaml)$"),  # docker-compose
    re.compile(r"\.secret$|\.key$|\.pem$|\.crt$"),  # 시크릿 파일
    re.compile(r"venv/|\.venv/|node_modules/"),  # 의존성 디렉토리
)


# =============================================================================
# 결과 데이터 클래스
# =============================================================================


@dataclass
class ValidationResult:
    """sandbox.validate() 의 결과."""

    passed: bool
    reason: str = ""
    # 영역 검증
    scope_violations: list[str] = field(default_factory=list)
    forbidden_violations: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    # 정적 분석
    ruff_passed: bool = False
    ruff_stderr: str = ""
    # 테스트
    tests_run: int = 0
    tests_failed: int = 0
    tests_passed: int = 0
    test_stdout_tail: str = ""
    test_stderr_tail: str = ""
    # 메타
    duration_ms: int = 0
    worktree_branch: str = ""

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "scope_violations": self.scope_violations,
            "forbidden_violations": self.forbidden_violations,
            "files_modified": self.files_modified,
            "ruff_passed": self.ruff_passed,
            "tests_run": self.tests_run,
            "tests_failed": self.tests_failed,
            "tests_passed": self.tests_passed,
            "duration_ms": self.duration_ms,
            "worktree_branch": self.worktree_branch,
        }


# =============================================================================
# 순수 함수 (단위 테스트 친화적)
# =============================================================================


def extract_modified_files(diff: str) -> list[str]:
    """unified diff 에서 수정되는 파일 경로 추출.

    Args:
        diff: ``--- a/path\\n+++ b/path`` 헤더 포함된 unified diff

    Returns:
        수정/추가/삭제 대상 파일 경로 list (중복 제거)
    """
    if not diff:
        return []
    paths: set[str] = set()
    # +++ b/path 형식 (new file 또는 modified)
    for m in re.finditer(r"^\+\+\+ b/(.+)$", diff, re.MULTILINE):
        path = m.group(1).strip()
        if path != "/dev/null":
            paths.add(path)
    # --- a/path 형식 (deleted 의 경우 +++ /dev/null 이라 위 caught 안 됨)
    for m in re.finditer(r"^--- a/(.+)$", diff, re.MULTILINE):
        path = m.group(1).strip()
        if path != "/dev/null":
            paths.add(path)
    return sorted(paths)


def check_scope_violations(files: list[str]) -> list[str]:
    """HJ 허용 영역 외 파일 검출.

    Args:
        files: extract_modified_files() 결과

    Returns:
        영역 위반 파일 list (HJ 영역이 아닌 것들)
    """
    violations = []
    for f in files:
        if not any(f.startswith(p) for p in HJ_ALLOWED_PREFIXES):
            violations.append(f)
    return violations


def check_forbidden_files(files: list[str]) -> list[str]:
    """절대 자동 수정 금지 파일 검출.

    Args:
        files: extract_modified_files() 결과

    Returns:
        금지 파일 list
    """
    violations = []
    for f in files:
        if any(pat.search(f) for pat in FORBIDDEN_PATTERNS):
            violations.append(f)
    return violations


# =============================================================================
# PatchValidator (git worktree + ruff + pytest)
# =============================================================================


class PatchValidator:
    """diff 를 격리된 worktree 에서 검증.

    Args:
        repo_root: git repository 루트. None 이면 cwd 사용.
        python_exe: python 인터프리터 (venv 의 python 사용 권장)
        ruff_cmd: ruff 명령. None 이면 ``python -m ruff``.
        pytest_cmd: pytest 명령. None 이면 ``python -m pytest tests/ -q --timeout=60``.
        skip_tests: True 면 pytest 단계 skip (개발/디버깅용)
        skip_ruff: True 면 ruff 단계 skip
    """

    def __init__(
        self,
        repo_root: Optional[str] = None,
        *,
        python_exe: Optional[str] = None,
        ruff_cmd: Optional[list[str]] = None,
        pytest_cmd: Optional[list[str]] = None,
        skip_tests: bool = False,
        skip_ruff: bool = False,
    ) -> None:
        self.repo_root = Path(repo_root or os.getcwd()).resolve()
        self.python_exe = python_exe or "python"
        self.ruff_cmd = ruff_cmd or [self.python_exe, "-m", "ruff", "check"]
        self.pytest_cmd = pytest_cmd or [self.python_exe, "-m", "pytest", "tests/", "-q", "--timeout=60", "-x"]
        self.skip_tests = skip_tests
        self.skip_ruff = skip_ruff

    # ------------------------------------------------------------------
    # 정적 검증 (worktree 없이)
    # ------------------------------------------------------------------

    def static_check(self, diff: str) -> ValidationResult:
        """worktree 만들기 전 빠른 검증 (금지 파일 → 영역).

        실제 패치 적용 / 테스트는 안 함. 이 단계 통과 못 하면 validate() 도 fail.

        검증 순서 (심각도 순):
            1. diff 가 파일을 가리키는가
            2. 금지 파일 (.env, migrations, requirements 등) — 가장 심각
            3. HJ 영역 외 파일 (R-403 거버넌스)

        forbidden 을 scope 보다 먼저 검사 — 같은 파일이 둘 다에 해당해도
        forbidden_file 사유로 보고 (시크릿/마이그레이션이 더 critical).
        """
        result = ValidationResult(passed=False)
        files = extract_modified_files(diff)
        result.files_modified = files

        if not files:
            result.reason = "diff_no_files"
            return result

        scope_v = check_scope_violations(files)
        forbidden_v = check_forbidden_files(files)
        result.scope_violations = scope_v
        result.forbidden_violations = forbidden_v

        # 1순위: 금지 파일 (시크릿/마이그레이션 — 가장 심각)
        if forbidden_v:
            result.reason = f"forbidden_file: 자동 수정 금지 파일 — {', '.join(forbidden_v[:3])}" + (
                f" (+{len(forbidden_v) - 3}개)" if len(forbidden_v) > 3 else ""
            )
            return result

        # 2순위: 영역 위반 (R-403)
        if scope_v:
            result.reason = f"scope_violation: HJ 영역 외 파일 수정 시도 — {', '.join(scope_v[:3])}" + (
                f" (+{len(scope_v) - 3}개)" if len(scope_v) > 3 else ""
            )
            return result

        result.passed = True
        result.reason = "static_check_ok"
        return result

    # ------------------------------------------------------------------
    # 전체 검증 (worktree + 패치 적용 + ruff + pytest)
    # ------------------------------------------------------------------

    async def validate(
        self,
        diff: str,
        *,
        timeout_sec: int = 600,
    ) -> ValidationResult:
        """diff 를 격리 worktree 에서 검증.

        흐름:
            1. static_check (영역 + 금지)
            2. git worktree add
            3. git apply --check (패치 가능?)
            4. git apply
            5. ruff check (skip_ruff=False 시)
            6. pytest (skip_tests=False 시)
            7. worktree remove
        """
        import time

        start = time.perf_counter()

        # 1) 정적 검증
        result = self.static_check(diff)
        if not result.passed:
            result.duration_ms = int((time.perf_counter() - start) * 1000)
            return result

        # 검증 실패 시 worktree 정리하므로 try/finally
        worktree_dir: Optional[Path] = None
        branch = f"autofix/sandbox-{uuid.uuid4().hex[:8]}"
        try:
            # 2) worktree 생성
            tmp = tempfile.mkdtemp(prefix="ada-sandbox-")
            worktree_dir = Path(tmp) / "wt"
            result.worktree_branch = branch
            r = await self._run(
                ["git", "worktree", "add", "-b", branch, str(worktree_dir), "HEAD"],
                cwd=self.repo_root,
                timeout=60,
            )
            if r.returncode != 0:
                result.passed = False
                result.reason = f"worktree_create_failed: {r.stderr[:500]}"
                return result

            # 3) diff syntax 검증 (apply --check)
            r = await self._run(
                ["git", "apply", "--check", "-"],
                cwd=worktree_dir,
                stdin=diff,
                timeout=30,
            )
            if r.returncode != 0:
                result.passed = False
                result.reason = "diff_invalid"
                result.test_stderr_tail = r.stderr[-1000:]
                return result

            # 4) diff 실제 적용
            r = await self._run(
                ["git", "apply", "-"],
                cwd=worktree_dir,
                stdin=diff,
                timeout=30,
            )
            if r.returncode != 0:
                result.passed = False
                result.reason = "diff_apply_failed"
                result.test_stderr_tail = r.stderr[-1000:]
                return result

            # 5) ruff
            if not self.skip_ruff:
                r = await self._run(
                    self.ruff_cmd + ["."],
                    cwd=worktree_dir,
                    timeout=120,
                )
                result.ruff_passed = r.returncode == 0
                if not result.ruff_passed:
                    result.passed = False
                    result.reason = "ruff_failed"
                    result.ruff_stderr = r.stdout[-2000:]
                    return result
            else:
                result.ruff_passed = True  # skip 시 통과로 간주

            # 6) pytest
            if not self.skip_tests:
                r = await self._run(
                    self.pytest_cmd,
                    cwd=worktree_dir,
                    timeout=timeout_sec,
                )
                stdout = r.stdout or ""
                m_pass = re.search(r"(\d+) passed", stdout)
                m_fail = re.search(r"(\d+) failed", stdout)
                result.tests_passed = int(m_pass.group(1)) if m_pass else 0
                result.tests_failed = int(m_fail.group(1)) if m_fail else 0
                result.tests_run = result.tests_passed + result.tests_failed
                result.test_stdout_tail = stdout[-2000:]
                result.test_stderr_tail = (r.stderr or "")[-1000:]

                if r.returncode != 0 or result.tests_failed > 0:
                    result.passed = False
                    result.reason = f"tests_failed: {result.tests_failed} failed / {result.tests_run} run"
                    return result

            # ✅ 모든 단계 통과
            result.passed = True
            result.reason = "all_checks_passed"
            return result

        except Exception as e:
            result.passed = False
            result.reason = f"sandbox_error: {type(e).__name__}: {e}"
            log.warning("sandbox_unexpected_error", error=str(e), branch=branch)
            return result

        finally:
            result.duration_ms = int((time.perf_counter() - start) * 1000)
            # worktree + branch 정리
            await self._cleanup_worktree(worktree_dir, branch)

    async def _cleanup_worktree(self, worktree_dir: Optional[Path], branch: str) -> None:
        try:
            if worktree_dir and worktree_dir.exists():
                await self._run(
                    ["git", "worktree", "remove", "--force", str(worktree_dir)],
                    cwd=self.repo_root,
                    timeout=30,
                )
        except Exception as e:
            log.warning("worktree_remove_failed", error=str(e))
        try:
            await self._run(
                ["git", "branch", "-D", branch],
                cwd=self.repo_root,
                timeout=10,
            )
        except Exception:
            pass
        # tmpdir 정리
        try:
            if worktree_dir and worktree_dir.parent.exists():
                shutil.rmtree(worktree_dir.parent, ignore_errors=True)
        except Exception:
            pass

    async def _run(
        self,
        cmd: list[str],
        *,
        cwd: Path,
        stdin: Optional[str] = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess:
        """subprocess 비동기 wrapper (to_thread)."""

        def _go() -> subprocess.CompletedProcess:
            return subprocess.run(
                cmd,
                cwd=str(cwd),
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

        return await asyncio.to_thread(_go)


__all__ = [
    "PatchValidator",
    "ValidationResult",
    "extract_modified_files",
    "check_scope_violations",
    "check_forbidden_files",
    "HJ_ALLOWED_PREFIXES",
    "FORBIDDEN_PATTERNS",
]

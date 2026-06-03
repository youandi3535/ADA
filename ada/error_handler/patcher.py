"""ada.error_handler.patcher — 검증 통과된 diff 를 실제 코드베이스에 자동 적용.

sandbox.PatchValidator.validate() 통과 후에만 호출.
git apply → git commit (감사 로그) → importlib.reload (hot-reload) 순서.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
from pathlib import Path
from typing import Any

from ada.core.logger import get_logger
from ada.error_handler.sandbox import extract_modified_files

log = get_logger("patcher")


async def apply_patch(
    diff: str,
    *,
    repo_root: str | None = None,
    commit_msg: str | None = None,
    reload_modules: bool = True,
) -> dict[str, Any]:
    """검증된 unified diff 를 실제 레포지토리에 적용한다.

    Args:
        diff:          unified diff 문자열 (sandbox 통과 완료본)
        repo_root:     git 레포 루트. None 이면 cwd 사용.
        commit_msg:    git commit 메시지. None 이면 자동 생성.
        reload_modules: True 면 영향받는 Python 모듈 hot-reload 시도.

    Returns::

        {
            "applied": bool,
            "files_changed": list[str],
            "git_commit": str | None,   # 커밋 hash (실패 시 None)
            "modules_reloaded": list[str],
            "reason": str,
        }
    """
    root = Path(repo_root or os.getcwd()).resolve()
    files_changed = extract_modified_files(diff)

    result: dict[str, Any] = {
        "applied": False,
        "files_changed": files_changed,
        "git_commit": None,
        "modules_reloaded": [],
        "reason": "",
    }

    if not diff or not files_changed:
        result["reason"] = "empty_diff"
        return result

    # ── 1. git apply ──────────────────────────────────────────────────────────
    def _apply() -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "apply", "-"],
            cwd=str(root),
            input=diff,
            capture_output=True,
            text=True,
            timeout=30,
        )

    try:
        r = await asyncio.to_thread(_apply)
    except Exception as e:  # noqa: BLE001
        result["reason"] = f"apply_exception: {e}"
        log.error("patch_apply_exception", error=str(e))
        return result

    if r.returncode != 0:
        result["reason"] = f"git_apply_failed: {r.stderr[:500]}"
        log.warning("patch_apply_failed", reason=result["reason"])
        return result

    result["applied"] = True
    log.info("patch_applied", files=files_changed)

    # ── 2. git commit (감사 로그) ─────────────────────────────────────────────
    msg = commit_msg or f"auto-fix: {', '.join(files_changed[:2])}"
    try:

        def _commit() -> subprocess.CompletedProcess:
            subprocess.run(
                ["git", "add", "--"] + files_changed,
                cwd=str(root),
                timeout=15,
                capture_output=True,
            )
            return subprocess.run(
                ["git", "commit", "-m", msg, "--no-verify"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=30,
            )

        cr = await asyncio.to_thread(_commit)
        if cr.returncode == 0:
            import re as _re

            m = _re.search(r"\[[\w/\-]+ ([a-f0-9]+)\]", cr.stdout or "")
            result["git_commit"] = m.group(1) if m else "committed"
            log.info("patch_committed", commit=result["git_commit"], msg=msg)
        else:
            log.warning("patch_commit_failed", stderr=cr.stderr[:300])
    except Exception as e:  # noqa: BLE001
        log.warning("patch_commit_exception", error=str(e))

    # ── 3. Python 모듈 hot-reload ─────────────────────────────────────────────
    if reload_modules:
        result["modules_reloaded"] = _reload_modules(files_changed, root)

    result["reason"] = "applied"
    return result


def _reload_modules(files_changed: list[str], repo_root: Path) -> list[str]:
    """수정된 .py 파일에 대응하는 sys.modules 항목을 importlib.reload.

    실패하는 모듈은 조용히 건너뜀 — 안전이 최우선.
    """
    import sys

    reloaded: list[str] = []
    for rel_path in files_changed:
        if not rel_path.endswith(".py"):
            continue
        abs_path = os.path.normcase(os.path.abspath(str(repo_root / rel_path)))
        for mod_name, mod in list(sys.modules.items()):
            try:
                origin = getattr(getattr(mod, "__spec__", None), "origin", None) or getattr(mod, "__file__", None)
                if origin and os.path.normcase(os.path.abspath(origin)) == abs_path:
                    importlib.reload(mod)
                    reloaded.append(mod_name)
                    log.info("module_reloaded", module=mod_name, file=rel_path)
                    break
            except Exception as e:  # noqa: BLE001
                log.warning("module_reload_failed", module=mod_name, error=str(e))
    return reloaded

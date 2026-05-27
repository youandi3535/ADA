"""Day 2 — AutoErrorHandler 데몬 + Vault 마이그 스크립트 검증.

DoD:
    - scan_new_failures_async 가 새 FailureLog 를 모아 AutoErrorHandler.handle 호출
    - 결과 dict 에 scanned/auto_kb_matched/patches_queued 포함
    - register_error_handler_beat 가 30초 스케줄을 반환
    - vault_migrate_dev_to_raft.sh 가 dry-run 으로 안전하게 시작 가능
"""

from __future__ import annotations

import asyncio
import os
import platform
import re
import subprocess
from typing import Any


def _bash_path(p: str) -> str:
    """Windows 경로를 MSYS2/Git Bash 경로로 변환 (다른 OS 는 그대로 반환)."""
    if platform.system() != "Windows":
        return p
    p = p.replace("\\", "/")
    p = re.sub(r"^([A-Za-z]):/", lambda m: f"/{m.group(1).lower()}/", p)
    return p


# ----- 1) scan_new_failures_async — handler 호출 흐름 -----------------------------
def test_daemon_scan_calls_handler(monkeypatch):
    """FakeSession 의 결과 row 가 AutoErrorHandler.handle 로 전달되는지."""
    from ada.error_handler import daemon as daemon_mod

    class FakeRow:
        def __init__(self, id_: str, msg: str):
            self.id = id_
            self.error_message = msg
            self.stack_trace = ""
            self.auto_handled_by_kb = False
            self.error_kb_id = None

    class FakeScalarResult:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeSession:
        async def scalars(self, *a, **k):
            return FakeScalarResult([FakeRow("1", "err A"), FakeRow("2", "err B")])

        async def commit(self):
            return None

        async def rollback(self):
            return None

    calls = []

    class FakeAutoHandler:
        def __init__(self, session):
            self.session = session

        async def handle(self, row):
            calls.append(row.id)
            return {"action": "auto_kb_match" if row.id == "1" else "patch_queued"}

    monkeypatch.setattr("ada.error_handler.auto_handler.AutoErrorHandler", FakeAutoHandler)

    result = asyncio.run(daemon_mod.scan_new_failures_async(FakeSession()))
    assert result["scanned"] == 2
    assert result["auto_kb_matched"] == 1
    assert result["patches_queued"] == 1
    assert sorted(calls) == ["1", "2"]


# ----- 2) handler 가 예외 던지면 errors 목록에 기록 -----------------------------
def test_daemon_collects_errors(monkeypatch):
    from ada.error_handler import daemon as daemon_mod

    class FakeRow:
        def __init__(self, id_):
            self.id = id_
            self.error_message = ""
            self.stack_trace = ""
            self.auto_handled_by_kb = False
            self.error_kb_id = None

    class FakeScalarResult:
        def all(self):
            return [FakeRow("X")]

    class FakeSession:
        async def scalars(self, *a, **k):
            return FakeScalarResult()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    class CrashHandler:
        def __init__(self, session):
            pass

        async def handle(self, row):
            raise RuntimeError("kaboom")

    monkeypatch.setattr("ada.error_handler.auto_handler.AutoErrorHandler", CrashHandler)

    result = asyncio.run(daemon_mod.scan_new_failures_async(FakeSession()))
    assert result["scanned"] == 1
    assert len(result["errors"]) == 1
    assert "kaboom" in result["errors"][0]["error"]


# ----- 3) beat schedule 등록 -----------------------------------------------------
def test_beat_schedule_30s():
    from orchestrator.harness_tasks import register_error_handler_beat

    sched = register_error_handler_beat()
    assert "ada-error-handler-scan" in sched
    entry = sched["ada-error-handler-scan"]
    assert entry["task"] == "ada.error_handler.scan"
    assert entry["schedule"] == 30.0
    # 기존 스케줄 머지
    sched2 = register_error_handler_beat({"existing-task": {"task": "x", "schedule": 60}})
    assert "existing-task" in sched2
    assert "ada-error-handler-scan" in sched2


# ----- 4) vault_migrate 스크립트 — dry-run 진입 가능 ----------------------------
def test_vault_migrate_script_exists_and_dry_run():
    repo = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(repo, "scripts", "security", "vault_migrate_dev_to_raft.sh")
    assert os.path.isfile(path), f"missing: {path}"
    assert os.access(path, os.X_OK), f"not executable: {path}"
    # bash -n 으로 syntax 검증 (Windows: MSYS2 경로 변환 + shell=True)
    r = subprocess.run(
        f'bash -n "{_bash_path(path)}"',
        shell=True,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, f"syntax error: {r.stderr}"
    # 헤더에 dry-run 기본 표기
    with open(path, encoding="utf-8") as f:
        head = f.read(2000)
    assert "DRY_RUN" in head or "dry-run" in head
    assert "--apply" in head

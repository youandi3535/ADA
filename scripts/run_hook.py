#!/usr/bin/env python3
"""scripts/run_hook.py — Cross-platform venv-aware hook launcher.

Usage (settings.json hook command):
  Windows : python  -X utf8 scripts/run_hook.py <target_script.py>
  Linux   : python3 -X utf8 scripts/run_hook.py <target_script.py>

동작
----
1. .venv Python 경로를 OS 별로 자동 감지
2. venv 없으면 sys.executable(현재 Python) 로 폴백
3. target_script 를 venv Python 으로 실행, stdin/stdout 그대로 전달

팀원 설정
---------
  Windows  : 설정 불필요 (settings.json 기본값 = python)
  Linux/Mac: scripts/dev/setup_hooks_unix.sh 1회 실행
"""

from __future__ import annotations

import os
import subprocess
import sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if sys.platform == "win32":
    _candidates = [
        os.path.join(_root, ".venv", "Scripts", "python.exe"),
        os.path.join(_root, ".venv", "Scripts", "python"),
    ]
else:
    _candidates = [
        os.path.join(_root, ".venv", "bin", "python3"),
        os.path.join(_root, ".venv", "bin", "python"),
    ]

_py = next((p for p in _candidates if os.path.isfile(p)), sys.executable)
_target = os.path.join(_root, "scripts", sys.argv[1])

proc = subprocess.run(
    [_py, "-X", "utf8", _target],
    stdin=sys.stdin.buffer,
    stdout=sys.stdout.buffer,
)
sys.exit(proc.returncode)

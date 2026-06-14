#!/usr/bin/env python3
"""scripts/collect_tool_use.py — Claude Code PostToolUse 훅 (코드 변경 이력 자동 수집)

목적
----
collect_qa.py 가 '마지막 Q&A 텍스트'만 저장하는 것과 달리, 이 훅은 매 도구 호출
직후 발동해 **실제 코드 변경(Edit/Write/...)** 을 서버에 적재한다.
→ "어떤 파일을 어떻게 고쳤는지" 가 팀 KB(conversation_logs)에 남는다.

수집 대상 (쓰기성 도구만)
------------------------
    Edit · MultiEdit · Write · NotebookEdit
    읽기/탐색 도구(Read·Grep·Glob·Bash 조회)는 노이즈·부하 방지 위해 제외.
    (settings.json 의 matcher 가 1차로 거르고, 본 스크립트가 2차 방어한다.)

민감정보 보호 (feedback_env_security)
------------------------------------
    .env / secret / credential / *.pem / *.key / id_rsa / password 가 경로에 포함되면
    내용을 보내지 않고 경로만 기록한다. 본문은 길이 절단.

전송
----
    기존 POST /kb/conversation 엔드포인트 재사용 (서버 무변경).
    source="claude_code_tool" 로 Q&A 와 구분 → stats 에서 필터 가능.
    품질 게이트(_quality_score)에 의해 self_learning_kb(qa_pair) 인덱싱은 대부분
    건너뛰므로 Q&A 시맨틱 검색을 오염시키지 않는다 (감사 저장 전용).

실패해도 조용히 종료 → Claude Code 응답 블로킹 없음.

환경변수 (collect_qa.py 와 동일)
-------------------------------
    KB_SERVER_URL       웹서버 주소        (기본: http://115.68.216.191/api)
    KB_COLLECT_SECRET   X-KB-Secret 헤더  (미설정 시 빈 문자열 → 개발모드 허용)
    TEAM_MEMBER         팀원 이름          (미설정 시 git config user.name 사용)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

_WRITE_TOOLS = {"Edit", "MultiEdit", "Write", "NotebookEdit"}
# 경로에 이 토큰이 들어가면 내용 미전송 (경로만 기록)
_SENSITIVE_TOKENS = (".env", "secret", "credential", ".pem", ".key", "id_rsa", "password")
_MAX_PART = 6_000  # before/after 각 절단 길이
_MAX_Q = 10_000
_MAX_A = 50_000
_MIN_LEN = 2  # 서버 ConversationIn 의 min_length 와 동일
_LOG_FILE = Path.home() / ".ada_hooks.log"


def _log(msg: str) -> None:
    """ADA_HOOK_DEBUG=1 일 때만 홈 디렉토리 로그 파일에 기록 (화면 출력 없음)."""
    if not os.environ.get("ADA_HOOK_DEBUG"):
        return
    try:
        from datetime import datetime

        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] collect_tool_use: {msg}\n")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# .env 파서 (collect_qa.py 와 동일 — 훅 독립성 위해 의존성 두지 않음)
# ---------------------------------------------------------------------------


def _load_env_file(cwd: str) -> dict[str, str]:
    env_file = Path(cwd) / ".env"
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            result[key] = val
    return result


def _get_team_member(cwd: str) -> str:
    """환경변수 TEAM_MEMBER → git config user.name → 'unknown' 순으로 시도."""
    env_name = os.environ.get("TEAM_MEMBER", "").strip()
    if env_name:
        return env_name
    try:
        extra: dict = {}
        if os.name == "nt":
            extra["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
            **extra,
        )
        name = proc.stdout.strip()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# 요약 생성
# ---------------------------------------------------------------------------


def _is_sensitive(path: str) -> bool:
    p = (path or "").lower()
    return any(tok in p for tok in _SENSITIVE_TOKENS)


def summarize(tool_name: str, tool_input: object) -> tuple[str, str]:
    """(question, answer) 생성. 민감 파일은 경로만 기록.

    question = "[TOOL:{tool_name}] {file_path}"
    answer   = 변경 요약 (before/after diff · content · edits · new_source)
    """
    fp = ""
    ti: dict = tool_input if isinstance(tool_input, dict) else {}
    fp = str(ti.get("file_path") or ti.get("notebook_path") or "").strip()

    question = f"[TOOL:{tool_name}] {fp}".strip()

    if _is_sensitive(fp):
        return question, f"(민감 파일 — 내용 생략) {tool_name} on {fp}"

    parts: list[str] = []
    if "old_string" in ti and "new_string" in ti:  # Edit
        parts.append("--- before\n" + str(ti.get("old_string", ""))[:_MAX_PART])
        parts.append("+++ after\n" + str(ti.get("new_string", ""))[:_MAX_PART])
    elif "edits" in ti:  # MultiEdit
        parts.append("edits:\n" + json.dumps(ti.get("edits"), ensure_ascii=False)[:_MAX_PART])
    elif "content" in ti:  # Write
        parts.append("content:\n" + str(ti.get("content", ""))[:_MAX_PART])
    elif "new_source" in ti:  # NotebookEdit
        parts.append("new_source:\n" + str(ti.get("new_source", ""))[:_MAX_PART])
    else:
        parts.append(json.dumps(ti, ensure_ascii=False)[:_MAX_PART])

    return question, "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> None:
    # ── 1. stdin 페이로드 수신 ──────────────────────────────────────────
    try:
        raw = sys.stdin.read()
        payload: dict = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        sys.exit(0)

    tool_name: str = str(payload.get("tool_name", "")).strip()
    if tool_name not in _WRITE_TOOLS:  # 쓰기성 도구만 (2차 방어)
        sys.exit(0)

    tool_input = payload.get("tool_input", {})
    session_id: str = payload.get("session_id", "")
    cwd: str = payload.get("cwd", "") or os.getcwd()
    project = Path(cwd).name if cwd else ""

    question, answer = summarize(tool_name, tool_input)
    if len(question) < _MIN_LEN or len(answer) < _MIN_LEN:
        sys.exit(0)

    question = question[:_MAX_Q]
    answer = answer[:_MAX_A]

    # ── 2. .env 로드 (환경변수 없을 때 대비) ─────────────────────────────
    env_vals = _load_env_file(cwd)

    def _env(key: str, default: str = "") -> str:
        return os.environ.get(key, "").strip() or env_vals.get(key, default)

    server_url = _env("KB_SERVER_URL", "http://115.68.216.191/api").rstrip("/")
    kb_secret = _env("KB_COLLECT_SECRET", "")
    team_member = _get_team_member(cwd)

    # ── 3. 웹서버에 POST (기존 /kb/conversation 재사용) ──────────────────
    body = json.dumps(
        {
            "question": question,
            "answer": answer,
            "team_member": team_member,
            "session_id": session_id,
            "project": project,
            "source": "claude_code_tool",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{server_url}/kb/conversation",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-KB-Secret": kb_secret,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            record_id = result.get("id", "?")
            _log(f"✅ 저장 완료 id={str(record_id)[:8]}… ({team_member} / {tool_name} / {project})")
    except urllib.error.HTTPError as e:
        _log(f"⚠️  HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        _log(f"⚠️  서버 연결 실패: {e.reason}")
    except Exception as e:  # noqa: BLE001
        _log(f"⚠️  예외: {e}")

    sys.exit(0)


if __name__ == "__main__":
    main()

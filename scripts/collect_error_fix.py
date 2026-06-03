#!/usr/bin/env python3
"""scripts/collect_error_fix.py — Claude Code Stop 훅 (자동수정 사례 누적)

Day24 추가 훅. collect_qa.py 와 병렬 실행되어 다음을 자동 수집:
    "Claude Code / Cowork 세션 안에서 에러가 발생하고 해당 에러를 고친 패치
     (Edit/Write 툴 사용 또는 unified diff) 가 같이 등장한 경우"
→ POST /kb/conversation/error_fix 로 전송 → SelfLearningKB.failure_lesson 적재
→ 이후 동일/유사 에러는 auto_handler Tier 1.5 가 자동 재사용 (LLM 비용 0)

동작 흐름
---------
1. Stop 훅 발동 → stdin 으로 JSON 페이로드 수신
2. transcript_path 에서 대화 JSONL 읽기 (모든 메시지)
3. "최근 에러 컨텍스트 + 직후 fix" 패턴 1쌍 추출
4. 웹서버 POST /kb/conversation/error_fix 로 전송
5. 실패해도 조용히 종료 → Claude Code 응답 블로킹 없음

검출 휴리스틱
-------------
- 에러 시그니처: tool_result 또는 user 메시지 안에서 "Traceback (most recent call last)"
  / "Error:" / "Exception:" / "ModuleNotFoundError" 등 패턴 + 직후 줄
- 수정 diff: assistant 메시지의 tool_use (Edit/Write) 또는 ```diff … ``` 코드블록
- 같은 turn 또는 직전 turn 안에서 두 가지가 모두 보여야 제출.
- 너무 흔한 키워드 (예: stub Error 안내) 회피 위해 stack trace 가 함께 보일 때만.

환경변수
--------
    KB_SERVER_URL       기본 http://115.68.216.191/api  (collect_qa.py 와 동일)
    KB_COLLECT_SECRET   X-KB-Secret 헤더
    TEAM_MEMBER         미설정 시 git config user.name
    ADA_ERROR_FIX_DISABLE=1  완전히 비활성화 (디버깅용)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# .env / 팀원 이름 — collect_qa.py 와 동일한 헬퍼
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
# 패턴 — 에러 시그니처 & diff 검출
# ---------------------------------------------------------------------------

# 에러 패턴: stack trace 한 줄 + 다음 줄(보통 메시지)
_TRACEBACK_RE = re.compile(r"Traceback \(most recent call last\):")
_ERROR_LINE_RE = re.compile(
    r"^(?:[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Warning)|"
    r"ModuleNotFoundError|ImportError|SyntaxError|NameError|TypeError|ValueError|"
    r"AttributeError|KeyError|IndexError|FileNotFoundError|PermissionError|"
    r"RuntimeError|AssertionError|OSError|ZeroDivisionError|StopIteration|"
    r"NotImplementedError|UnboundLocalError|RecursionError|MemoryError|"
    r"ConnectionError|TimeoutError)\b.*",
    re.M,
)

# unified diff 헤더 (--- a/x +++ b/x @@) — 한 messages 안에 모두 있어야 강한 신호
_DIFF_HEADER_RE = re.compile(r"^@@ .*? @@", re.M)
_DIFF_FILE_RE = re.compile(r"^(?:--- |\+\+\+ )", re.M)

# Edit/Write tool 사용 흔적 (Claude Code 의 assistant 가 사용)
_EDIT_TOOL_RE = re.compile(r'"(?:name|tool_name)"\s*:\s*"(Edit|MultiEdit|Write|NotebookEdit)"')

# ---------------------------------------------------------------------------
# 대화 JSONL 파서
# ---------------------------------------------------------------------------


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", "") or "")
            elif btype == "tool_use":
                # diff/path 추출 — Edit 인 경우 old_string / new_string 결합
                ti = block.get("input") or {}
                if isinstance(ti, dict):
                    old = ti.get("old_string") or ""
                    new = ti.get("new_string") or ""
                    fp = ti.get("file_path") or ""
                    if fp and (old or new):
                        # pseudo unified diff (헬퍼 — 정확한 diff 는 아님)
                        parts.append(
                            f"--- a/{fp}\n+++ b/{fp}\n@@ edit @@\n"
                            + "\n".join(f"-{ln}" for ln in (old or "").splitlines()[:30])
                            + "\n"
                            + "\n".join(f"+{ln}" for ln in (new or "").splitlines()[:30])
                        )
            elif btype == "tool_result":
                tc = block.get("content")
                if isinstance(tc, list):
                    for sub in tc:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            parts.append(sub.get("text", "") or "")
                elif isinstance(tc, str):
                    parts.append(tc)
        return "\n".join(p for p in parts if p)
    return ""


def _parse_entry(raw_line: str) -> Optional[tuple[str, str]]:
    """JSONL 한 줄 → (role, text). collect_qa._parse_entry 와 동일 포맷 지원."""
    try:
        obj = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    otype = obj.get("type", "")
    if otype in ("human", "user", "assistant", "tool_use", "tool_result"):
        msg = obj.get("message", {})
        if isinstance(msg, dict) and msg:
            role = "user" if otype in ("human", "user", "tool_result") else "assistant"
            text = _extract_text(msg.get("content", ""))
            return (role, text) if text else None

    role = obj.get("role", "")
    if role in ("user", "assistant"):
        text = _extract_text(obj.get("content", ""))
        return (role, text) if text else None
    return None


# ---------------------------------------------------------------------------
# 에러 + 수정 페어 추출
# ---------------------------------------------------------------------------


def _extract_error_signature(text: str) -> Optional[tuple[str, str]]:
    """user/tool_result 텍스트에서 (signature, stack_top) 추출.

    Returns:
        (signature, stack_top) 또는 None.
    """
    if not text:
        return None

    # 우선 Traceback 블록 우선
    if _TRACEBACK_RE.search(text):
        lines = text.splitlines()
        # 마지막 traceback 블록 찾기
        start = -1
        for i, ln in enumerate(lines):
            if _TRACEBACK_RE.search(ln):
                start = i
        if start >= 0:
            block = "\n".join(lines[start : start + 25])
            # 시그니처 = 마지막 ErrorName: 줄
            sig_match = None
            for ln in lines[start:]:
                m = _ERROR_LINE_RE.match(ln.strip())
                if m:
                    sig_match = ln.strip()
            if sig_match:
                return sig_match[:500], block[:1000]
            # 시그니처 못 찾으면 traceback 헤더 다음 줄
            return lines[start][:500], block[:1000]

    # Traceback 없으면 단순 ErrorName 라인
    for ln in text.splitlines():
        if _ERROR_LINE_RE.match(ln.strip()):
            return ln.strip()[:500], ""
    return None


def _extract_fix_diff(text: str) -> str:
    """assistant 텍스트에서 unified diff 헤더가 있는 코드블록만 추출.

    완전한 diff 가 아니어도 hunk 헤더가 있으면 OK (서버 측 검증에서 걸러짐).
    """
    if not text:
        return ""

    # ```diff ... ``` 코드블록 우선
    diff_blocks = re.findall(r"```(?:diff|patch)?\s*\n(.*?)```", text, re.S)
    for block in diff_blocks:
        if _DIFF_HEADER_RE.search(block) or _DIFF_FILE_RE.search(block):
            return block[:20000]

    # tool_use Edit 가 만들어준 pseudo-diff (extract 단계에서 합성됨)
    if _DIFF_HEADER_RE.search(text) and _DIFF_FILE_RE.search(text):
        # 헤더부터 끝까지의 영역만
        idx = text.find("--- ")
        if idx >= 0:
            return text[idx : idx + 20000]

    return ""


def extract_error_fix_pair(transcript_path: str) -> Optional[dict]:
    """transcript 마지막 부분에서 (에러, 수정 diff) 1쌍 추출.

    조건:
        - 에러 시그니처가 직전 user / tool_result 에 등장
        - 같은 turn 또는 그 다음 assistant 응답에 diff 등장
        - 둘 다 잡혀야 반환. 못 찾으면 None.

    Returns:
        {"error_signature", "stack_top", "fix_diff"} 또는 None.
    """
    p = Path(transcript_path)
    if not p.exists():
        return None

    entries: list[tuple[str, str]] = []
    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parsed = _parse_entry(raw)
        if parsed:
            entries.append(parsed)

    if not entries:
        return None

    # 끝에서부터 역추적 — 마지막 assistant 응답에서 diff 찾고, 그 직전 user 에서 error 찾기
    # IMPORTANT-1 수정: 무관 페어링 방지 위해 lookback=2 (immediate predecessor 만).
    # 너무 오래 전 에러는 후속 diff 와 의미적으로 무관 → false positive 폭증 위험.
    last_error: Optional[tuple[str, str]] = None
    last_diff: str = ""

    # 1) 가장 최근 assistant 메시지의 diff
    for i in range(len(entries) - 1, -1, -1):
        role, text = entries[i]
        if role == "assistant":
            d = _extract_fix_diff(text)
            if d:
                last_diff = d
                # 이 assistant 메시지 이전 최대 2 메시지 안에서만 user error 찾기.
                # (예: [user error → assistant fix] 또는 [user error → tool_result → assistant fix])
                lookback = max(0, i - 2)
                for j in range(i - 1, lookback - 1, -1):
                    r2, t2 = entries[j]
                    if r2 == "user":
                        sig = _extract_error_signature(t2)
                        if sig:
                            last_error = sig
                            break
                break  # 가장 최근 assistant + 그 직전 error 한 쌍이면 충분

    if not last_diff or not last_error:
        return None

    signature, stack_top = last_error
    return {
        "error_signature": signature,
        "stack_top": stack_top,
        "fix_diff": last_diff,
    }


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

_LOG_FILE = Path.home() / ".ada_hooks.log"


def _log(msg: str) -> None:
    if not os.environ.get("ADA_HOOK_DEBUG"):
        return
    try:
        from datetime import datetime

        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] collect_error_fix: {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def main() -> None:  # noqa: C901
    if os.environ.get("ADA_ERROR_FIX_DISABLE"):
        sys.exit(0)

    # ── 1. stdin 페이로드 ────────────────────────────────────────────────
    try:
        raw = sys.stdin.read()
        payload: dict = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        sys.exit(0)

    transcript_path: str = payload.get("transcript_path", "")
    session_id: str = payload.get("session_id", "")
    cwd: str = payload.get("cwd", "") or os.getcwd()

    if not transcript_path:
        sys.exit(0)

    project = Path(cwd).name if cwd else ""

    # ── 2. .env ─────────────────────────────────────────────────────────
    env_vals = _load_env_file(cwd)

    def _env(key: str, default: str = "") -> str:
        return os.environ.get(key, "").strip() or env_vals.get(key, default)

    server_url = _env("KB_SERVER_URL", "http://115.68.216.191/api").rstrip("/")
    kb_secret = _env("KB_COLLECT_SECRET", "")

    # ── 3. 에러+수정 pair 추출 ────────────────────────────────────────────
    try:
        pair = extract_error_fix_pair(transcript_path)
    except Exception as e:  # noqa: BLE001
        _log(f"extract failed: {e}")
        sys.exit(0)

    if not pair:
        # 에러+수정 페어가 없으면 그냥 종료 (정상 — 매 턴 호출되므로)
        sys.exit(0)

    team_member = _get_team_member(cwd)

    # ── 4. PII 마스킹 (BLOCKER 수정) — VPS 전송 전 클라이언트측 redact ────
    # 스택트레이스에 윈도우 username / JWT / DB 비밀번호가 들어갈 수 있어
    # ada.error_handler.redactor 를 import 해서 클라이언트측에서도 마스킹.
    # 실패해도 (예: PYTHONPATH 문제) 원본 그대로 보내지 않고 그냥 종료.
    sig = pair["error_signature"]
    stack = pair.get("stack_top", "")
    diff = pair["fix_diff"]
    try:
        # 프로젝트 루트를 sys.path 에 임시 추가 (스크립트 단독 실행 안전)
        if cwd and cwd not in sys.path:
            sys.path.insert(0, cwd)
        from ada.error_handler.redactor import redact  # noqa: PLC0415

        sig, _ = redact(sig)
        stack, _ = redact(stack)
        diff, _ = redact(diff)
    except Exception as e:  # noqa: BLE001
        # redactor import 실패 = ada 모듈 없는 경로에서 hook 호출됨.
        # 누출 위험이 있으므로 그냥 종료 (보수적 fail-closed).
        _log(f"redactor unavailable, abort: {e}")
        sys.exit(0)

    # 5) POST to VPS
    body = json.dumps(
        {
            "error_signature": sig,
            "stack_top": stack,
            "fix_diff": diff,
            "explanation": "",
            "confidence": 0.75,
            "team_member": team_member,
            "session_id": session_id,
            "project": project,
            "source": "team_manual",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{server_url}/kb/conversation/error_fix",
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
            kb_id = result.get("kb_id") or "?"
            status = result.get("status") or "?"
            _log(f"OK status={status} kb_id={str(kb_id)[:8]} ({team_member} / {project})")
    except urllib.error.HTTPError as e:
        _log(f"HTTP {e.code}: {e.reason}")
    except urllib.error.URLError as e:
        _log(f"connect failed: {e.reason}")
    except Exception as e:  # noqa: BLE001
        _log(f"unexpected: {e}")

    sys.exit(0)


if __name__ == "__main__":
    main()

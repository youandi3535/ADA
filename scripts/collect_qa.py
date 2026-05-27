#!/usr/bin/env python3
"""scripts/collect_qa.py — Claude Code Stop 훅 (팀 Q&A 자동 수집)

동작 흐름
---------
1. Stop 훅 발동 → stdin 으로 JSON 페이로드 수신
2. transcript_path 에서 대화 JSONL 읽기
3. 마지막 Q&A 쌍 추출 (Stop 훅은 매 응답마다 실행됨)
4. 웹서버 POST /kb/conversation 로 전송
5. 실패해도 조용히 종료 → Claude Code 응답 블로킹 없음

환경변수 (팀원 로컬 .env 또는 시스템 환경변수)
---------------------------------------------
    KB_SERVER_URL       웹서버 주소        (기본: http://221.150.237.129/api  ← 팀 VPS)
    KB_COLLECT_SECRET   X-KB-Secret 헤더  (미설정 시 빈 문자열 → 개발모드 허용)
    TEAM_MEMBER         팀원 이름          (미설정 시 git config user.name 사용)

Linux 사용자 참고
----------------
    python → python3 으로 교체하거나, .claude/settings.json 의 command 를
    "python3 scripts/collect_qa.py" 로 변경하세요.
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
# .env 파일 파서 — python-dotenv 없이 표준 라이브러리만 사용
# ---------------------------------------------------------------------------


def _load_env_file(cwd: str) -> dict[str, str]:
    """프로젝트 루트 .env 를 파싱해 dict 반환.

    이미 설정된 환경변수(시스템/터미널)는 덮어쓰지 않음.
    """
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


# ---------------------------------------------------------------------------
# 팀원 이름 결정
# ---------------------------------------------------------------------------


def _get_team_member(cwd: str) -> str:
    """환경변수 TEAM_MEMBER → git config user.name → 'unknown' 순으로 시도."""
    env_name = os.environ.get("TEAM_MEMBER", "").strip()
    if env_name:
        return env_name
    try:
        proc = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=cwd,
        )
        name = proc.stdout.strip()
        if name:
            return name
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# 대화 JSONL 파서
# ---------------------------------------------------------------------------


def _extract_text(content: object) -> str:
    """content 필드(str 또는 list[dict])에서 순수 텍스트만 추출."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts).strip()
    return ""


def _parse_entry(raw_line: str) -> tuple[str, str] | None:
    """JSONL 한 줄 파싱 → (role, text) 또는 None.

    지원 포맷
    ---------
    A) Claude Code 기본 포맷:
       {"type": "human"|"assistant", "message": {"role":…, "content": […]}, …}
    B) 단순 포맷:
       {"role": "user"|"assistant", "content": …}
    """
    try:
        obj = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    # 포맷 A — "type" 키로 판별
    # Claude Code 구버전: "human" / 신버전(2025+): "user"  # noqa: ERA001
    otype = obj.get("type", "")
    if otype in ("human", "user", "assistant"):
        msg = obj.get("message", {})
        role = "user" if otype in ("human", "user") else "assistant"
        text = _extract_text(msg.get("content", ""))
        if text:
            return role, text
        return None

    # 포맷 B — "role" 키로 판별 (단순 포맷)
    role = obj.get("role", "")
    if role in ("user", "assistant"):
        text = _extract_text(obj.get("content", ""))
        if text:
            return role, text

    return None


def extract_last_qa(transcript_path: str) -> tuple[str, str] | None:
    """JSONL 전체를 순회해 가장 마지막 Q&A 쌍 반환.

    Stop 훅은 매 응답마다 호출되므로 매번 '가장 최근' 교환을 추출.

    예시 (3회 교환된 세션의 3번째 호출):
        [Q1, A1, Q2, A2, Q3, A3]  →  (Q3, A3)
    """
    p = Path(transcript_path)
    if not p.exists():
        return None

    last_question = ""
    last_answer = ""
    pending_q = ""  # 답변 대기 중인 질문

    for raw in p.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parsed = _parse_entry(raw)
        if parsed is None:
            continue
        role, text = parsed

        if role == "user":
            pending_q = text
        elif role == "assistant" and pending_q:
            last_question = pending_q
            last_answer = text
            pending_q = ""  # 쌍 완성 → 초기화

    if last_question and last_answer:
        return last_question, last_answer
    return None


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

_MIN_LEN = 5  # 너무 짧은 Q/A 는 무시 (실수 클릭 등)
_MAX_Q = 8_000
_MAX_A = 40_000


def main() -> None:  # noqa: C901
    # ── 1. stdin 페이로드 수신 ──────────────────────────────────────────
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

    # ── 2. .env 로드 (환경변수 없을 때 대비) ─────────────────────────────
    env_vals = _load_env_file(cwd)

    def _env(key: str, default: str = "") -> str:
        return os.environ.get(key, "").strip() or env_vals.get(key, default)

    server_url = _env("KB_SERVER_URL", "http://221.150.237.129/api").rstrip("/")
    kb_secret = _env("KB_COLLECT_SECRET", "")

    # ── 3. 마지막 Q&A 추출 ───────────────────────────────────────────────
    qa = extract_last_qa(transcript_path)
    if not qa:
        sys.exit(0)

    question, answer = qa

    if len(question) < _MIN_LEN or len(answer) < _MIN_LEN:
        sys.exit(0)

    # 최대 길이 절단 (웹서버 Pydantic 검증 통과)
    question = question[:_MAX_Q]
    answer = answer[:_MAX_A]

    team_member = _get_team_member(cwd)

    # ── 4. 웹서버에 POST ─────────────────────────────────────────────────
    body = json.dumps(
        {
            "question": question,
            "answer": answer,
            "team_member": team_member,
            "session_id": session_id,
            "project": project,
            "source": "claude_code",
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
            print(
                f"[collect_qa] ✅ 저장 완료 id={record_id[:8]}… ({team_member} / {project})",
                file=sys.stderr,
            )
    except urllib.error.HTTPError as e:
        print(f"[collect_qa] ⚠️  HTTP {e.code}: {e.reason}", file=sys.stderr)
    except urllib.error.URLError as e:
        # 서버 미기동 시 — 조용히 무시 (오프라인 작업 방해 금지)
        print(f"[collect_qa] ⚠️  서버 연결 실패: {e.reason}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[collect_qa] ⚠️  예외: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()

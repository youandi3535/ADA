#!/usr/bin/env python3
"""scripts/ingest_history.py — Claude Code + Cowork 과거 대화 전체 일괄 수집

현재 세션만 수집하는 Stop 훅(collect_qa.py)과 달리,
모든 IDE/앱의 대화 이력을 스캔해 KB에 편입.

지원 소스
---------
  VS Code Claude Code  ~/.claude/projects/**/*.jsonl
  Cowork (Windows)     %APPDATA%\\Claude\\local-agent-mode-sessions\\**\\*.{txt,json,md}
  Cowork (Mac)         ~/Library/Application Support/Claude/local-agent-mode-sessions/**

수집 방식 차이
--------------
  VS Code Claude Code:
    - Stop 훅(collect_qa.py)이 매 응답마다 최신 Q&A를 실시간 전송
    - ingest_history.py는 "과거 이력"을 일괄 백필(backfill)하는 용도

  Cowork (Claude Desktop App):
    - 훅 메커니즘이 없음 → Stop 훅 불가
    - ingest_history.py만이 유일한 수집 경로
    - 5분 cron으로 주기적 실행 권장

동작 흐름
---------
1. ~/.ada_ingest_state.json 에서 처리 이력(파일별 mtime) 로드
2. 전체 소스 디렉토리 스캔 (mtime 변경 파일만 처리)
3. 파일 형식별 파서로 모든 Q&A 쌍 추출
4. POST /kb/conversation 전송 (source 필드로 출처 구분)
5. 처리 이력 업데이트

실행 방법
---------
  python scripts/ingest_history.py              # 기본 실행
  python scripts/ingest_history.py --dry-run    # 전송 없이 파싱 결과만 출력
  python scripts/ingest_history.py --force      # 이력 무시, 전체 재처리
  python scripts/ingest_history.py --limit 200  # Q&A 최대 200건만 전송

5분 cron 설정 (리눅스/Mac) — Cowork 실시간 학습
-------------------------------------------------
  */5 * * * * cd /path/to/ADA && python3 scripts/ingest_history.py >> /var/log/ada_ingest.log 2>&1

Windows 작업 스케줄러 (PowerShell)
-----------------------------------
  # 5분마다 실행 등록 (관리자 권한 불필요)
  $action = New-ScheduledTaskAction -Execute "python" -Argument "scripts/ingest_history.py" -WorkingDirectory "C:\\IT\\workspace_python\\ADA"
  $trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)
  Register-ScheduledTask -TaskName "ADA-IngestHistory" -Action $action -Trigger $trigger

환경변수
--------
  KB_SERVER_URL       웹서버 주소 (기본: http://115.68.216.191/api  ← 팀 VPS)
  KB_COLLECT_SECRET   X-KB-Secret 헤더
  TEAM_MEMBER         팀원 이름 (미설정 시 git config user.name)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ingest_history")

# ---------------------------------------------------------------------------
# 경로 상수 — VS Code Claude Code + Cowork 양쪽 지원
# ---------------------------------------------------------------------------

_HOME = Path.home()
_STATE_FILE = _HOME / ".ada_ingest_state.json"
_PROJECT_ROOT = Path(__file__).parent.parent

# 처리 제외 디렉토리
_SKIP_DIRS = {"outputs", "uploads", ".auto-memory", "node_modules", "__pycache__"}
_MIN_FILE_BYTES = 100


def _get_transcript_sources() -> list[tuple[Path, str]]:
    """스캔할 (디렉토리, source_label) 목록 반환.

    source_label 은 KB 에 저장될 conversation_logs.source 값.
    존재하지 않는 디렉토리는 자동 제외.
    """
    sources: list[tuple[Path, str]] = []

    # ── VS Code Claude Code ──────────────────────────────────────────────
    claude_code_dir = _HOME / ".claude" / "projects"
    if claude_code_dir.exists():
        sources.append((claude_code_dir, "claude_code_history"))

    # ── Cowork (Claude Desktop App) — Windows ────────────────────────────
    # %APPDATA% = C:\Users\{user}\AppData\Roaming
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cowork_win = Path(appdata) / "Claude" / "local-agent-mode-sessions"
        if cowork_win.exists():
            sources.append((cowork_win, "cowork"))

    # %LOCALAPPDATA% 도 시도 (앱 버전에 따라 위치 다를 수 있음)
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        cowork_win_local = Path(localappdata) / "Claude" / "local-agent-mode-sessions"
        if cowork_win_local.exists():
            sources.append((cowork_win_local, "cowork"))

    # ── Cowork (Claude Desktop App) — Mac ────────────────────────────────
    cowork_mac = _HOME / "Library" / "Application Support" / "Claude" / "local-agent-mode-sessions"
    if cowork_mac.exists():
        sources.append((cowork_mac, "cowork"))

    # ── 사용자 정의 경로 (환경변수) ─────────────────────────────────────
    extra = os.environ.get("ADA_TRANSCRIPT_DIR", "").strip()
    if extra:
        extra_path = Path(extra)
        if extra_path.exists():
            sources.append((extra_path, "custom"))

    return sources


# ---------------------------------------------------------------------------
# 설정 로드
# ---------------------------------------------------------------------------


def _load_env_file() -> dict[str, str]:
    env_file = _PROJECT_ROOT / ".env"
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key:
            result[key] = val
    return result


_env_vals = _load_env_file()


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, "").strip() or _env_vals.get(key, default)


def _get_team_member() -> str:
    tm = _cfg("TEAM_MEMBER")
    if tm:
        return tm
    try:
        p = subprocess.run(["git", "config", "user.name"], capture_output=True, text=True, timeout=3)
        if p.stdout.strip():
            return p.stdout.strip()
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


# ---------------------------------------------------------------------------
# 이력 파일 (mtime 기반 증분 처리)
# ---------------------------------------------------------------------------


def _load_state() -> dict[str, float]:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _save_state(state: dict[str, float]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("state_save_failed: %s", e)


# ---------------------------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------------------------


def _extract_content(content: object) -> str:
    """content 필드(str / list[dict]) → 순수 텍스트."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if t:
                    parts.append(t)
        return "\n".join(parts).strip()
    return ""


# ---------------------------------------------------------------------------
# 파서 A: Claude Code JSONL  (.jsonl)
# {"type":"human"|"assistant", "message": {"content": ...}}
# ---------------------------------------------------------------------------


def _parse_jsonl_entry(raw_line: str) -> tuple[str, str] | None:
    try:
        obj = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    otype = obj.get("type", "")
    # Claude Code 구버전: "human" / 신버전(2025+): "user"
    if otype in ("human", "user", "assistant"):
        msg = obj.get("message", {})
        role = "user" if otype in ("human", "user") else "assistant"
        text = _extract_content(msg.get("content", ""))
        if text and "(called " not in text[:60]:
            return role, text
        return None

    role = obj.get("role", "")
    if role in ("user", "assistant"):
        text = _extract_content(obj.get("content", ""))
        if text and "(called " not in text[:60]:
            return role, text

    return None


def _extract_all_qa_jsonl(path: Path) -> list[tuple[str, str]]:
    """JSONL 파일 → 모든 Q&A 쌍."""
    pairs: list[tuple[str, str]] = []
    pending_q = ""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return pairs
    for raw in content.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        parsed = _parse_jsonl_entry(raw)
        if not parsed:
            continue
        role, text = parsed
        if role == "user":
            pending_q = text
        elif role == "assistant" and pending_q:
            pairs.append((pending_q, text))
            pending_q = ""
    return pairs


# ---------------------------------------------------------------------------
# 파서 B: Cowork 텍스트 형식  (.txt / .md)
# [user]\n질문\n\n[assistant]\n답변\n\n[user]\n...
# ---------------------------------------------------------------------------


def _extract_all_qa_txt(path: Path) -> list[tuple[str, str]]:
    """Cowork .txt/.md 형식 파서: [user] / [assistant] 마커로 Q&A 추출."""
    pairs: list[tuple[str, str]] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return pairs

    # [user], [assistant], [human] 마커로 섹션 분리
    sections = re.split(r"\[(user|assistant|human)\]", content, flags=re.IGNORECASE)

    current_role: str | None = None
    pending_q = ""

    for section in sections:
        s = section.strip().lower()
        if s in ("user", "human"):
            current_role = "user"
        elif s == "assistant":
            current_role = "assistant"
        else:
            text = section.strip()
            if not text:
                continue
            if current_role == "user":
                pending_q = text
            elif current_role == "assistant" and pending_q:
                pairs.append((pending_q, text))
                pending_q = ""

    return pairs


# ---------------------------------------------------------------------------
# 파서 C: 단일 JSON 객체 형식  (.json)
# {"messages": [{"role": "user", "content": "..."}, ...]}
# ---------------------------------------------------------------------------


def _extract_all_qa_json(path: Path) -> list[tuple[str, str]]:
    """단일 JSON 객체 형식 파서."""
    pairs: list[tuple[str, str]] = []
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return pairs

    messages = data.get("messages", [])
    if not isinstance(messages, list):
        return pairs

    pending_q = ""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        text = _extract_content(content) if not isinstance(content, str) else content.strip()
        if not text:
            continue
        if role in ("user", "human"):
            pending_q = text
        elif role == "assistant" and pending_q:
            pairs.append((pending_q, text))
            pending_q = ""

    return pairs


# ---------------------------------------------------------------------------
# 파일 형식 감지 & 파서 선택
# ---------------------------------------------------------------------------


def _extract_all_qa(path: Path) -> list[tuple[str, str]]:
    """파일 확장자에 따라 적절한 파서 선택."""
    ext = path.suffix.lower()
    if ext == ".jsonl":
        return _extract_all_qa_jsonl(path)
    if ext == ".json":
        # JSONL 형식일 수도 있으므로 양쪽 시도
        pairs = _extract_all_qa_json(path)
        if not pairs:
            pairs = _extract_all_qa_jsonl(path)
        return pairs
    if ext in (".txt", ".md"):
        return _extract_all_qa_txt(path)
    return []


# ---------------------------------------------------------------------------
# 파일 스캔
# ---------------------------------------------------------------------------

_SUPPORTED_EXTS = {".jsonl", ".json", ".txt", ".md"}


def _scan_files(base_dir: Path) -> Iterator[Path]:
    """디렉토리 하위의 지원 형식 파일 반환."""
    for fpath in base_dir.rglob("*"):
        if not fpath.is_file():
            continue
        if fpath.suffix.lower() not in _SUPPORTED_EXTS:
            continue
        if any(skip in fpath.parts for skip in _SKIP_DIRS):
            continue
        try:
            if fpath.stat().st_size < _MIN_FILE_BYTES:
                continue
        except OSError:
            continue
        yield fpath


# ---------------------------------------------------------------------------
# API 전송
# ---------------------------------------------------------------------------


def _post_qa(
    server_url: str,
    secret: str,
    question: str,
    answer: str,
    team_member: str,
    session_id: str,
    source: str,
) -> bool:
    body = json.dumps(
        {
            "question": question[:8_000],
            "answer": answer[:40_000],
            "team_member": team_member,
            "session_id": session_id,
            "source": source,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{server_url}/kb/conversation",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-KB-Secret": secret,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except urllib.error.URLError as e:
        log.error("서버 연결 실패: %s", e)
        return False
    except Exception as e:  # noqa: BLE001
        log.warning("전송 오류: %s", e)
        return False


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude Code + Cowork 과거 대화 일괄 수집")
    parser.add_argument("--dry-run", action="store_true", help="전송 없이 파싱 결과만 출력")
    parser.add_argument("--force", action="store_true", help="이력 무시, 전체 재처리")
    parser.add_argument("--limit", type=int, default=0, help="최대 전송 Q&A 수 (0=무제한)")
    args = parser.parse_args()

    server_url = _cfg("KB_SERVER_URL", "http://115.68.216.191/api").rstrip("/")
    kb_secret = _cfg("KB_COLLECT_SECRET", "")
    team_member = _get_team_member()

    sources = _get_transcript_sources()
    if not sources:
        log.error("수집 가능한 대화 디렉토리를 찾지 못했습니다.")
        log.error("Claude Code: ~/.claude/projects/  Cowork: %%APPDATA%%\\Claude\\local-agent-mode-sessions\\")
        sys.exit(1)

    log.info("수집 소스 %d개: %s", len(sources), [str(d) for d, _ in sources])

    state = {} if args.force else _load_state()
    new_state = dict(state)
    total_ok = total_skip = total_fail = 0

    for base_dir, source_label in sources:
        log.info("── 스캔 중: %s  [%s]", base_dir, source_label)

        for fpath in _scan_files(base_dir):
            fkey = str(fpath)
            try:
                mtime = fpath.stat().st_mtime
            except OSError:
                continue

            if not args.force and state.get(fkey) == mtime:
                continue

            pairs = _extract_all_qa(fpath)
            if not pairs:
                new_state[fkey] = mtime
                continue

            session_id = fpath.stem
            log.info("  %s (%d쌍) [%s]", fpath.name, len(pairs), source_label)

            for question, answer in pairs:
                if len(question) < 5 or len(answer) < 5:
                    total_skip += 1
                    continue

                if args.dry_run:
                    log.info("    [DRY-RUN][%s] Q: %s…", source_label, question[:60])
                    total_ok += 1
                else:
                    ok = _post_qa(server_url, kb_secret, question, answer, team_member, session_id, source_label)
                    if ok:
                        total_ok += 1
                    else:
                        total_fail += 1

                if args.limit > 0 and total_ok >= args.limit:
                    log.info("=== limit %d 도달, 중단 ===", args.limit)
                    if not args.dry_run:
                        _save_state(new_state)
                    log.info("완료: ok=%d  skip=%d  fail=%d", total_ok, total_skip, total_fail)
                    return

            new_state[fkey] = mtime

    if not args.dry_run:
        _save_state(new_state)

    log.info("=== 완료: ok=%d  skip=%d  fail=%d ===", total_ok, total_skip, total_fail)
    if args.dry_run:
        log.info("(dry-run 모드 — 실제 전송 없음)")


if __name__ == "__main__":
    main()

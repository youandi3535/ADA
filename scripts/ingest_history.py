#!/usr/bin/env python3
"""scripts/ingest_history.py — Claude Code 과거 대화 전체 일괄 수집

현재 세션만 수집하는 Stop 훅(collect_qa.py)과 달리,
~/.claude/projects/ 의 모든 JSONL 파일을 스캔해 과거 대화를 KB에 편입.

동작 흐름
---------
1. ~/.ada_ingest_state.json 에서 처리 이력(파일별 mtime) 로드
2. ~/.claude/projects/**/*.jsonl 스캔
3. mtime 변경 파일만 처리 (증분 처리)
4. 각 JSONL에서 모든 Q&A 쌍 추출 (Stop 훅은 마지막 1쌍만 수집)
5. POST /kb/conversation 으로 전송 (source="history_ingest")
6. 처리 이력 업데이트

실행 방법
---------
  python scripts/ingest_history.py              # 기본 실행
  python scripts/ingest_history.py --dry-run    # 전송 없이 파싱 결과만 출력
  python scripts/ingest_history.py --force      # 이력 무시, 전체 재처리
  python scripts/ingest_history.py --limit 200  # Q&A 최대 200건만 전송

환경변수
--------
  KB_SERVER_URL       웹서버 주소 (기본: http://localhost:8000)
  KB_COLLECT_SECRET   X-KB-Secret 헤더
  TEAM_MEMBER         팀원 이름 (미설정 시 git config user.name)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
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
# 경로 상수
# ---------------------------------------------------------------------------

_HOME = Path.home()
_CLAUDE_PROJECTS_DIR = _HOME / ".claude" / "projects"
_STATE_FILE = _HOME / ".ada_ingest_state.json"
_PROJECT_ROOT = Path(__file__).parent.parent

# 처리 제외 디렉토리/파일 패턴
_SKIP_DIRS = {"outputs", "uploads", ".auto-memory", "node_modules", "__pycache__"}
_MIN_FILE_BYTES = 100  # 100바이트 미만 파일 제외

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
# JSONL 파서 (collect_qa._parse_entry 와 동일 로직, 전체 Q&A 추출)
# ---------------------------------------------------------------------------


def _extract_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _parse_entry(raw_line: str) -> tuple[str, str] | None:
    """JSONL 한 줄 → (role, text) 또는 None."""
    try:
        obj = json.loads(raw_line)
    except json.JSONDecodeError:
        return None

    # 포맷 A: Claude Code 기본
    otype = obj.get("type", "")
    if otype in ("human", "assistant"):
        msg = obj.get("message", {})
        role = "user" if otype == "human" else "assistant"
        text = _extract_text(msg.get("content", ""))
        # 도구 호출만 있는 assistant 메시지 제외
        if text and "(called " not in text[:50]:
            return role, text
        return None

    # 포맷 B: 단순
    role = obj.get("role", "")
    if role in ("user", "assistant"):
        text = _extract_text(obj.get("content", ""))
        if text and "(called " not in text[:50]:
            return role, text

    return None


def _extract_all_qa(jsonl_path: Path) -> list[tuple[str, str]]:
    """JSONL 파일에서 모든 Q&A 쌍 추출."""
    pairs: list[tuple[str, str]] = []
    pending_q = ""

    try:
        content = jsonl_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return pairs

    for raw in content.splitlines():
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
            pairs.append((pending_q, text))
            pending_q = ""

    return pairs


# ---------------------------------------------------------------------------
# JSONL 파일 스캔
# ---------------------------------------------------------------------------


def _scan_jsonl_files() -> Iterator[Path]:
    """~/.claude/projects/ 하위 모든 JSONL 파일 반환."""
    if not _CLAUDE_PROJECTS_DIR.exists():
        return

    for fpath in _CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        # 제외 디렉토리 체크
        if any(skip in fpath.parts for skip in _SKIP_DIRS):
            continue
        # 너무 작은 파일 제외
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
) -> bool:
    """POST /kb/conversation. 성공 True, 실패 False."""
    body = json.dumps(
        {
            "question": question[:8_000],
            "answer": answer[:40_000],
            "team_member": team_member,
            "session_id": session_id,
            "source": "history_ingest",
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
    parser = argparse.ArgumentParser(description="Claude Code 과거 대화 일괄 수집")
    parser.add_argument("--dry-run", action="store_true", help="전송 없이 파싱 결과만 출력")
    parser.add_argument("--force", action="store_true", help="이력 무시, 전체 재처리")
    parser.add_argument("--limit", type=int, default=0, help="최대 전송 Q&A 수 (0 = 무제한)")
    args = parser.parse_args()

    server_url = _cfg("KB_SERVER_URL", "http://localhost:8000").rstrip("/")
    kb_secret = _cfg("KB_COLLECT_SECRET", "")
    team_member = _get_team_member()

    if not _CLAUDE_PROJECTS_DIR.exists():
        log.error("~/.claude/projects/ 디렉토리가 없습니다. Claude Code 설치 확인.")
        sys.exit(1)

    state = {} if args.force else _load_state()
    jsonl_files = list(_scan_jsonl_files())
    log.info("스캔된 JSONL 파일: %d개", len(jsonl_files))

    total_ok = total_skip = total_fail = 0
    new_state = dict(state)

    for fpath in jsonl_files:
        fkey = str(fpath)
        try:
            mtime = fpath.stat().st_mtime
        except OSError:
            continue

        # 이미 처리된 파일이고 mtime 미변경 → 건너뜀
        if not args.force and state.get(fkey) == mtime:
            continue

        pairs = _extract_all_qa(fpath)
        if not pairs:
            new_state[fkey] = mtime
            continue

        session_id = fpath.stem  # 파일명을 session_id 로 사용

        log.info("처리 중: %s (%d쌍)", fpath.name, len(pairs))

        for question, answer in pairs:
            # 너무 짧은 Q/A 제외
            if len(question) < 5 or len(answer) < 5:
                total_skip += 1
                continue

            if args.dry_run:
                log.info("  [DRY-RUN] Q: %s…", question[:60])
                log.info("  [DRY-RUN] A: %s…", answer[:60])
                total_ok += 1
            else:
                ok = _post_qa(server_url, kb_secret, question, answer, team_member, session_id)
                if ok:
                    total_ok += 1
                else:
                    total_fail += 1

            # limit 도달 시 종료
            if args.limit > 0 and total_ok >= args.limit:
                log.info("=== limit %d 도달, 중단 ===", args.limit)
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

#!/usr/bin/env python3
"""scripts/query_kb_hook.py — Claude Code UserPromptSubmit 훅

모든 질문을 1/2/3순위로 판단 후 배지와 함께 답변 출력.

동작 흐름
---------
1. Claude Code 가 질문을 전송하기 직전 → stdin 으로 페이로드 수신
2. 1순위: POST /kb/search → KB 히트 시 [1순위 🗄️ KB] 배지 + 답변 → exit 2
3. 2순위: Ollama /api/chat 직접 호출 (KB 서버와 독립) → exit 2
4. 3순위: claude -p 로 Claude LLM 직접 호출 → [3순위 ☁️ Claude] 배지 + 답변 → exit 2
   (claude CLI 실패 시 exit 0 폴백 — Claude Code 가 처리)

재귀 방지
---------
  hook 내 claude -p 호출 시 ADA_HOOK_SKIP=1 을 환경변수로 전달.
  hook 진입 시 이 변수가 있으면 즉시 exit 0.

환경변수
--------
  KB_SERVER_URL       웹서버 주소 (기본: http://localhost:8000)
  KB_COLLECT_SECRET   X-KB-Secret 헤더
  KB_HOOK_THRESHOLD   유사도 임계값 (기본: 0.85)
  KB_HOOK_MIN_HITS    최소 success_count (기본: 3)
  OLLAMA_BASE_URL     Ollama 서버 주소 (기본: http://localhost:11434)
  OLLAMA_MODEL        Ollama 모델명 (기본: qwen2.5:7b)

설치 (팀원 로컬 .claude/settings.json)
---------------------------------------
  hooks.UserPromptSubmit 에 "python scripts/query_kb_hook.py" 추가
  → 이미 프로젝트 .claude/settings.json 에 등록됨
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# .env 파서 (표준 라이브러리만 사용 — collect_qa.py 와 동일 방식)
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
        key, val = key.strip(), val.strip().strip('"').strip("'")
        # 중복 키는 첫 번째 값 우선 (Docker용 URL 이 host 전용 URL 을 덮어쓰는 문제 방지)
        if key and key not in result:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# 배지 제거 (sub-claude 출력 정리용)
# ---------------------------------------------------------------------------

_BADGE_LINE_RE = re.compile(r"^\[[1-9]순위")


def _strip_badge_lines(text: str) -> str:
    """[N순위 ...] 형태의 배지 줄을 모두 제거하고 앞뒤 공백 정리."""
    cleaned = [line for line in text.splitlines() if not _BADGE_LINE_RE.match(line)]
    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# 2순위: Ollama 직접 호출 (KB 서버와 완전 독립)
# ---------------------------------------------------------------------------


def _call_ollama(prompt: str, ollama_url: str, ollama_model: str) -> str | None:
    """Ollama /api/chat 직접 호출. 실패·오프라인 시 None 반환."""
    base = ollama_url.rstrip("/")

    # 헬스체크 (3초)
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception:  # noqa: BLE001
        return None  # Ollama 오프라인

    # 응답 생성 (최대 120초 — 로컬 7B 모델 기준 여유)
    payload = json.dumps(
        {
            "model": ollama_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "당신은 ADA 프로젝트(AutoAI 분석 플랫폼)의 전문 어시스턴트입니다. "
                        "팀원의 질문에 정확하고 간결하게 한국어로 답변하세요."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "num_predict": 512,
                "temperature": 0.3,
                "top_p": 0.9,
                "num_gpu": 0,
                "num_thread": 14,
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            f"{base}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        answer = data.get("message", {}).get("content", "").strip()
        return answer or None
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# 3순위: Claude CLI 직접 호출
# ---------------------------------------------------------------------------


def _call_claude(prompt: str, cwd: str) -> str | None:
    """claude -p 로 Claude LLM 직접 호출 (독립 질문). 실패 시 None 반환."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return None

    # Windows: .cmd 파일은 cmd /c 로 실행해야 subprocess 에서 인식됨
    if os.name == "nt":
        cmd = ["cmd", "/c", claude_bin, "-p", prompt]
        extra: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
    else:
        cmd = [claude_bin, "-p", prompt]
        extra = {}

    env = os.environ.copy()
    env["ADA_HOOK_SKIP"] = "1"  # 재귀 방지
    try:
        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,  # hook이 stdin 소진 후 EOF 상속 방지
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            cwd=cwd,
            env=env,
            **extra,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            # sub-claude 가 CLAUDE.md 규칙·KB MCP 로 붙인 배지를 모두 제거
            answer = _strip_badge_lines(proc.stdout)
            return answer or None
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------


def main() -> None:
    # ── 0. 재귀 호출 방지 ──────────────────────────────────────────────
    if os.environ.get("ADA_HOOK_SKIP"):
        sys.exit(0)

    # ── 1. stdin 페이로드 수신 ──────────────────────────────────────────
    try:
        raw = sys.stdin.read()
        payload: dict = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        sys.exit(0)

    prompt: str = payload.get("prompt", "").strip()
    cwd: str = payload.get("cwd", "") or os.getcwd()

    # 너무 짧은 질문 (2자 미만) → Claude 처리
    if len(prompt) < 2:
        sys.exit(0)

    # ── 2. 설정 로드 ────────────────────────────────────────────────────
    env_vals = _load_env_file(cwd)

    def _env(key: str, default: str = "") -> str:
        return os.environ.get(key, "").strip() or env_vals.get(key, default)

    server_url = _env("KB_SERVER_URL", "http://localhost:8000").rstrip("/")
    kb_secret = _env("KB_COLLECT_SECRET", "")
    threshold = float(_env("KB_HOOK_THRESHOLD", "0.85"))
    min_hits = int(_env("KB_HOOK_MIN_HITS", "3"))
    ollama_url = _env("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model = _env("OLLAMA_MODEL", "qwen2.5:7b")

    # ── 3-A. 1순위: KB 전용 빠른 체크 (타임아웃 5초) ────────────────────
    body_kb = json.dumps(
        {
            "question": prompt,
            "threshold": threshold,
            "min_hit_count": min_hits,
            "min_word_overlap": 0.5,
            "use_ollama_fallback": False,
            "use_claude_fallback": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req_kb = urllib.request.Request(
        f"{server_url}/kb/search",
        data=body_kb,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-KB-Secret": kb_secret,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req_kb, timeout=5) as resp:
            result = json.loads(resp.read())
        if result.get("answered_by") == "team_kb" and result.get("answer", "").strip():
            # ✅ 1순위 KB 히트 → exit 2  (answer 안에 이전 배지가 섞였을 수 있어 제거)
            kb_answer = _strip_badge_lines(result["answer"])
            if kb_answer:
                print(f"[1순위 🗄️ KB  |  💰 무료]\n{kb_answer}", flush=True)
                sys.exit(2)
    except Exception:  # noqa: BLE001
        pass  # 서버 미기동 or 타임아웃 → 2순위로

    # ── 3-B. 2순위: Ollama 직접 호출 (KB 서버와 독립) ────────────────────
    ollama_answer = _call_ollama(prompt, ollama_url, ollama_model)
    if ollama_answer:
        # ✅ 2순위 Ollama 히트 → exit 2
        print(f"[2순위 🦙 Ollama  |  💰 무료]\n{ollama_answer}", flush=True)
        sys.exit(2)

    # ── 4. 3순위: Claude CLI 직접 호출 → 배지 강제 삽입 후 exit 2 ───────
    claude_answer = _call_claude(prompt, cwd)
    if claude_answer:
        print(f"[3순위 ☁️ Claude  |  💸 유료]\n{claude_answer}", flush=True)
        sys.exit(2)

    # 모든 폴백 실패 시 → exit 0 (Claude Code 가 일반 처리)
    sys.exit(0)


if __name__ == "__main__":
    main()

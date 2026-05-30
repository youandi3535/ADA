#!/usr/bin/env python3
"""scripts/query_kb_hook.py — Claude Code UserPromptSubmit 훅

KB에 고신뢰도 답변이 있으면 Claude 호출을 차단하고 즉시 KB 답변 반환.

동작 흐름
---------
1. Claude Code 가 질문을 전송하기 직전 → stdin 으로 페이로드 수신
2. POST /kb/search (KB 전용, 타임아웃 5초)
3. 다중 게이트 모두 통과 시 → stdout 에 답변 출력 → exit 2 (Claude 차단, API 비용 0)
4. KB 미스 or 게이트 실패 → exit 0 (Claude 가 처리)

다중 게이트 (query_kb_hook 전용 엄격 기준):
  - 코사인 유사도 ≥ KB_HOOK_THRESHOLD (기본 0.85)
  - success_count ≥ KB_HOOK_MIN_HITS (기본 3)  ← 최소 3번 검증된 답변만 차단
  - 단어 겹침 비율 ≥ 0.5
  - 유사도 ≥ 0.98 (사실상 동일 문장) → hit_count/overlap 게이트 면제

환경변수
--------
  KB_SERVER_URL       웹서버 주소 (기본: http://localhost:8000)
  KB_COLLECT_SECRET   X-KB-Secret 헤더
  KB_HOOK_THRESHOLD   유사도 임계값 (기본: 0.85)
  KB_HOOK_MIN_HITS    최소 success_count (기본: 3)

설치 (팀원 로컬 .claude/settings.json)
---------------------------------------
  hooks.UserPromptSubmit 에 "python scripts/query_kb_hook.py" 추가
  → 이미 프로젝트 .claude/settings.json 에 등록됨
"""

from __future__ import annotations

import json
import os
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
        if key:
            result[key] = val
    return result


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

    prompt: str = payload.get("prompt", "").strip()
    cwd: str = payload.get("cwd", "") or os.getcwd()

    # 너무 짧은 질문 (5자 미만) → Claude 처리
    if len(prompt) < 5:
        sys.exit(0)

    # ── 2. 설정 로드 ────────────────────────────────────────────────────
    env_vals = _load_env_file(cwd)

    def _env(key: str, default: str = "") -> str:
        return os.environ.get(key, "").strip() or env_vals.get(key, default)

    server_url = _env("KB_SERVER_URL", "http://localhost:8000").rstrip("/")
    kb_secret = _env("KB_COLLECT_SECRET", "")
    threshold = float(_env("KB_HOOK_THRESHOLD", "0.85"))
    min_hits = int(_env("KB_HOOK_MIN_HITS", "3"))

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
            # ✅ 1순위 KB 히트 → exit 2
            print(f"[1순위 🗄️ KB  |  💰 무료]\n{result['answer'].strip()}", flush=True)
            sys.exit(2)
    except Exception:  # noqa: BLE001
        pass  # 서버 미기동 or 타임아웃 → Ollama 시도

    # ── 3-B. 2순위: Ollama 체크 (타임아웃 90초) ──────────────────────────
    body_ollama = json.dumps(
        {
            "question": prompt,
            "threshold": threshold,
            "min_hit_count": min_hits,
            "min_word_overlap": 0.5,
            "use_ollama_fallback": True,
            "use_claude_fallback": False,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req_ollama = urllib.request.Request(
        f"{server_url}/kb/search",
        data=body_ollama,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-KB-Secret": kb_secret,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req_ollama, timeout=90) as resp:
            result = json.loads(resp.read())
        if result.get("answered_by") == "ollama_local" and result.get("answer", "").strip():
            # ✅ 2순위 Ollama 히트 → exit 2
            print(f"[2순위 🦙 Ollama  |  💰 무료]\n{result['answer'].strip()}", flush=True)
            sys.exit(2)
    except Exception:  # noqa: BLE001
        pass  # Ollama 오프라인 or 타임아웃 → Claude 처리

    # ── 4. 3순위: Claude 처리 알림 후 exit 0 ────────────────────────────
    print("[3순위 ☁️ Claude  |  💸 유료]", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()

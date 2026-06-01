#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/query_kb_hook.py — Claude Code UserPromptSubmit 훅 (Day 11 최종판).

동작 흐름
---------
질문이 들어오면 1/2/3 순위로 처리:

  1순위 (KB 히트)    → JSON {decision:block, reason:[1순위]+답변, suppressOriginalPrompt:true}
                        + plain stdout 백업 (이중 안전망)
                        exit 0  → 사용자 화면에 답변 노출 + parent Claude 차단
  2순위 (Ollama 응답) → 동일 패턴 ([2순위] 배지)
  3순위 (폴백)        → JSON·stdout 미출력 + exit 0  → parent Claude 가 직접 답변
                        (CLAUDE.md §7-5 규칙으로 [3순위 ☁️ Claude] 배지 자동)

핵심 수정 (이전 버그)
---------------------
이전 코드:  print(answer) + sys.exit(2)
공식 사양:  exit 2 는 stdout 무시, stderr 만 사용자에게 노출 + 프롬프트 차단.
            결과 → 사용자 화면 비어있음 (질문 차단 + 답변 손실).

지금 :  exit 0 + JSON {"decision":"block","reason":"..."} 패턴 (표준 사양만 사용).
        - reason → 사용자에게 표시
        - hookSpecificOutput / suppressOriginalPrompt 제거 (비표준 → 답변 사라짐 버그)
        - Ollama timeout 25s (Claude Code hook 제한 60s 이하로 유지)

디버그 모드
-----------
  ADA_HOOK_DEBUG=1 환경변수 설정 시 모든 단계가
  ``<repo>/.ada_hook_debug.log`` 에 append 로 기록됨.
  훅이 동작하지 않을 때 이 파일부터 확인.

환경변수
--------
  KB_SERVER_URL       (기본: http://localhost:8000)
  KB_COLLECT_SECRET   X-KB-Secret 헤더
  KB_HOOK_THRESHOLD   유사도 임계값 (기본: 0.85)
  KB_HOOK_MIN_HITS    최소 success_count (기본: 3)
  OLLAMA_BASE_URL     (기본: http://localhost:11434)
  OLLAMA_MODEL        (기본: qwen2.5:7b)
  ADA_HOOK_SKIP=1     hook 즉시 통과 (재귀 방지용)
  ADA_HOOK_DEBUG=1    파일 로깅 활성

참조: https://docs.claude.com/en/docs/claude-code/hooks
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 디버그 로거 — 훅 동작 진단용
# ---------------------------------------------------------------------------


def _debug(msg: str, cwd: str = "") -> None:
    """ADA_HOOK_DEBUG=1 일 때만 파일에 기록. 실패는 조용히 무시."""
    if not os.environ.get("ADA_HOOK_DEBUG"):
        return
    try:
        log_path = Path(cwd or os.getcwd()) / ".ada_hook_debug.log"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# .env 파서 (표준 라이브러리만)
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
        if key and key not in result:
            result[key] = val
    return result


# ---------------------------------------------------------------------------
# 배지 정제 (KB 에 저장된 답변에 이전 배지가 섞여있을 수 있음)
# ---------------------------------------------------------------------------

_BADGE_LINE_RE = re.compile(r"^\[[1-9]순위")


def _strip_badge_lines(text: str) -> str:
    cleaned = [line for line in text.splitlines() if not _BADGE_LINE_RE.match(line)]
    return "\n".join(cleaned).strip()


# ---------------------------------------------------------------------------
# UserPromptSubmit 응답 헬퍼
# ---------------------------------------------------------------------------


def _emit_block_with_answer(badge: str, answer: str, cwd: str = "") -> None:
    """답변을 사용자에게 표시 + parent Claude 차단. exit 0.

    공식 사양 (UserPromptSubmit):
        - exit 0 + JSON {"decision":"block","reason":"..."} 만 사용.
        - reason 이 사용자 화면에 표시됨.
        - hookSpecificOutput / suppressOriginalPrompt 는 비표준 필드 → 사용 금지.
          (suppression 필드가 reason 표시까지 억제해 답변이 사라지는 버그 원인)
    """
    body = f"{badge}\n{answer}"

    payload = {
        "decision": "block",
        "reason": body,
    }
    out = json.dumps(payload, ensure_ascii=False)

    _debug(f"emit_block: badge={badge!r}, answer_len={len(answer)}", cwd)
    _debug(f"emit_block: stdout_json={out[:300]}", cwd)

    try:
        # buffer 레벨에서 UTF-8 직접 출력 — Windows 에서 sys.stdout 인코딩 오류 방지
        sys.stdout.buffer.write(out.encode("utf-8"))
        sys.stdout.buffer.flush()
    except Exception as e:  # noqa: BLE001
        _debug(f"stdout_write_failed: {e}", cwd)

    sys.exit(0)


def _emit_passthrough(cwd: str = "", reason: str = "") -> None:
    """JSON·stdout 미출력 + exit 0 → parent Claude 가 정상 처리."""
    _debug(f"passthrough: reason={reason}", cwd)
    sys.exit(0)


def _emit_error_fail_safe(msg: str, cwd: str = "") -> None:
    """예외 발생 시 안전 폴백 — 사용자가 잠긴 화면을 보지 않도록 exit 0 으로 통과.

    Claude Code 가 정상적으로 parent Claude 를 실행하므로 사용자는 답변을 받음.
    """
    _debug(f"FAILSAFE: {msg}", cwd)
    sys.exit(0)


# ---------------------------------------------------------------------------
# 2순위: Ollama 직접 호출
# ---------------------------------------------------------------------------


def _call_ollama(prompt: str, ollama_url: str, ollama_model: str, cwd: str) -> str | None:
    base = ollama_url.rstrip("/")

    # 헬스체크 (3초)
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3):
            pass
    except Exception as e:  # noqa: BLE001
        _debug(f"ollama_health_failed: {type(e).__name__}: {e}", cwd)
        return None

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
        # timeout=25: Claude Code hook 제한(60s) 안에 KB(5s)+헬스(3s)+Ollama(25s) 완료 가능
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
        answer = (data.get("message", {}).get("content", "") or "").strip()
        _debug(f"ollama_response_len={len(answer)}", cwd)
        return answer or None
    except Exception as e:  # noqa: BLE001
        _debug(f"ollama_call_failed: {type(e).__name__}: {e}", cwd)
        return None


# ---------------------------------------------------------------------------
# 1순위: KB 서버 호출
# ---------------------------------------------------------------------------


def _call_kb(server_url: str, secret: str, prompt: str, threshold: float, min_hits: int, cwd: str) -> str | None:
    body = json.dumps(
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

    req = urllib.request.Request(
        f"{server_url}/kb/search",
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-KB-Secret": secret,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        _debug(f"kb_call_failed: {type(e).__name__}: {e}", cwd)
        return None

    answered_by = result.get("answered_by")
    _debug(f"kb_answered_by={answered_by}", cwd)
    if answered_by != "team_kb":
        return None
    answer = (result.get("answer") or "").strip()
    if not answer:
        return None
    cleaned = _strip_badge_lines(answer)
    return cleaned or None


# ---------------------------------------------------------------------------
# 메인 — 어떤 예외든 발생 시 안전하게 exit 0 으로 통과 (Claude Code 잠금 방지)
# ---------------------------------------------------------------------------


def main() -> None:
    cwd_for_log = os.getcwd()  # stdin 파싱 실패 시 폴백
    try:
        # 0) 재귀 방지
        if os.environ.get("ADA_HOOK_SKIP"):
            _debug("ADA_HOOK_SKIP=1 → passthrough", cwd_for_log)
            _emit_passthrough(cwd_for_log, reason="ADA_HOOK_SKIP")

        # 1) stdin 페이로드 수신 (utf-8-sig: Windows PowerShell BOM 자동 제거)
        try:
            raw = sys.stdin.buffer.read().decode("utf-8-sig")
            payload: dict = json.loads(raw) if raw.strip() else {}
        except Exception as e:  # noqa: BLE001
            _emit_error_fail_safe(f"stdin_parse_failed: {e}", cwd_for_log)
            return

        prompt: str = (payload.get("prompt") or "").strip()
        cwd: str = payload.get("cwd") or os.getcwd()
        cwd_for_log = cwd
        _debug(f"=== HOOK START === prompt_len={len(prompt)}, cwd={cwd}", cwd)

        # 짧은 질문 통과
        if len(prompt) < 2:
            _emit_passthrough(cwd, reason="prompt_too_short")

        # 2) 설정 로드
        env_vals = _load_env_file(cwd)

        def _env(key: str, default: str = "") -> str:
            return os.environ.get(key, "").strip() or env_vals.get(key, default)

        server_url = _env("KB_SERVER_URL", "http://localhost:8000").rstrip("/")
        kb_secret = _env("KB_COLLECT_SECRET", "")
        threshold = float(_env("KB_HOOK_THRESHOLD", "0.85"))
        min_hits = int(_env("KB_HOOK_MIN_HITS", "3"))
        ollama_url = _env("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = _env("OLLAMA_MODEL", "qwen2.5:7b")
        _debug(f"config: kb={server_url}, ollama={ollama_url}/{ollama_model}", cwd)

        # 3-A) 1순위 KB
        kb_answer = _call_kb(server_url, kb_secret, prompt, threshold, min_hits, cwd)
        if kb_answer:
            _emit_block_with_answer("[1순위 🗄️ KB  |  💰 무료]", kb_answer, cwd)

        # 3-B) 2순위 Ollama
        ollama_answer = _call_ollama(prompt, ollama_url, ollama_model, cwd)
        if ollama_answer:
            _emit_block_with_answer("[2순위 🦙 Ollama  |  💰 무료]", ollama_answer, cwd)

        # 4) 3순위 — parent Claude 가 직접 처리 (CLAUDE.md §7-5 로 배지 자동)
        _emit_passthrough(cwd, reason="kb_and_ollama_miss")

    except SystemExit:
        # _emit_* 헬퍼가 호출한 정상 종료 — 그대로 전파
        raise
    except Exception as e:  # noqa: BLE001
        # 예상 못 한 예외 — 사용자에게 답변 보장 위해 exit 0 으로 통과
        _debug(f"UNHANDLED: {type(e).__name__}: {e}\n{traceback.format_exc()}", cwd_for_log)
        _emit_error_fail_safe(f"unhandled: {e}", cwd_for_log)


if __name__ == "__main__":
    main()

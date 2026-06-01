#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/query_kb_hook.py — Claude Code UserPromptSubmit 훅.

동작 흐름
---------
질문이 들어오면 1/2 순위로 처리:

  1순위 (KB 히트)  → JSON {"decision":"block","reason":"[1순위]+답변"} + exit 0
                      → 사용자 화면에 답변 노출 + parent Claude 차단
  2순위 (폴백)     → stdout 미출력 + exit 0
                      → parent Claude 가 직접 답변
                      (CLAUDE.md §7-5 규칙으로 [3순위 ☁️ Claude] 배지 자동)

  ※ Ollama 는 hook 에서 제거됨 (num_predict=512 @ 7.2t/s → 최대 71s 대기,
     타임아웃 25s 로도 화면 공백 28s 발생).
     Ollama 응답을 원할 경우 OLLAMA_HOOK_ENABLE=1 환경변수로 활성화 가능.

핵심 설계 원칙
--------------
  - KB 응답(최대 3s): 빠름 → 차단 방식 유지
  - KB 미스: 즉시 passthrough → Claude 가 바로 실행됨 (대기 없음)
  - Ollama 기본 비활성: hook 총 대기 = max 3s (KB timeout)

디버그 모드
-----------
  ADA_HOOK_DEBUG=1 환경변수 설정 시 모든 단계가
  ``<repo>/.ada_hook_debug.log`` 에 append 로 기록됨.

환경변수
--------
  KB_SERVER_URL        (기본: http://localhost:8000)
  KB_COLLECT_SECRET    X-KB-Secret 헤더
  KB_HOOK_THRESHOLD    유사도 임계값 (기본: 0.85)
  KB_HOOK_MIN_HITS     최소 success_count (기본: 3)
  OLLAMA_HOOK_ENABLE=1 Ollama 2순위 활성화 (기본: 비활성)
  OLLAMA_BASE_URL      (기본: http://localhost:11434)
  OLLAMA_MODEL         (기본: qwen2.5:7b)
  ADA_HOOK_SKIP=1      hook 즉시 통과 (재귀 방지용)
  ADA_HOOK_DEBUG=1     파일 로깅 활성

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


# 비답변(사과·되묻기·모름류) 패턴 — 이런 응답으로는 Claude 를 차단하지 않는다
_NON_ANSWER_PAT = re.compile(
    r"죄송|이해하기\s*어렵|질문을\s*명확|잘\s*모르겠|모르겠습니다|답변(?:할|하기)\s*(?:수\s*없|어렵)|확실하지\s*않"
)


def _is_low_quality_answer(answer: str) -> bool:
    """차단(block)해도 좋을 만큼 '진짜 답변'인지 판정.

    너무 짧거나(<8자) 사과/되묻기/모름류 비답변이면 True.
    → 이 경우 차단하지 않고 passthrough 하여 Claude 가 직접 답하게 한다
      (화면 공백·무의미 답변으로 답이 사라지는 것을 원천 차단).
    """
    a = (answer or "").strip()
    if len(a) < 8:
        return True
    return bool(_NON_ANSWER_PAT.search(a))


# ---------------------------------------------------------------------------
# UserPromptSubmit 응답 헬퍼
# ---------------------------------------------------------------------------


def _emit_block_with_answer(badge: str, answer: str, cwd: str = "") -> None:
    """KB/Ollama 답변을 additionalContext 로 주입 → Claude 가 채팅에 표시. exit 0.

    변경 이유
    ---------
    VS Code 익스텐션에서 {"decision":"block","reason":"..."} 방식은
    reason 이 채팅 화면에 렌더링되지 않아 사용자에게 답변이 보이지 않는 버그.
    → additionalContext 주입 방식으로 전환:
      Claude 가 차단되지 않고 KB 답변을 컨텍스트로 받아 채팅에 직접 출력.
    """
    ans = (answer or "").strip()
    # 안전장치: 빈/저품질 답변으로는 컨텍스트 주입하지 않는다.
    if _is_low_quality_answer(ans):
        _debug(f"low_quality_answer → passthrough (len={len(ans)})", cwd)
        _emit_passthrough(cwd, reason="low_quality_answer")
        return

    # Claude 에게 KB 답변을 컨텍스트로 전달 + 배지·출력 지시
    context = (
        f"[KB 답변 주입 — Claude 에 대한 지시]\n"
        f"아래는 ADA 팀 KB에서 검색된 답변입니다. 이 내용을 그대로 출력하되:\n"
        f"1) 반드시 첫 줄에 '{badge}' 배지를 그대로 출력하세요.\n"
        f"2) 3순위 Claude 배지([3순위 ☁️ Claude | 💸 유료])는 붙이지 마세요.\n"
        f"3) KB 답변 이외의 추가 설명은 최소화하세요.\n\n"
        f"KB 답변 내용:\n{ans}"
    )

    payload = {"additionalContext": context}
    out = json.dumps(payload, ensure_ascii=False)

    _debug(f"emit_context_inject: badge={badge!r}, answer_len={len(ans)}", cwd)
    _debug(f"emit_context_inject: stdout_json={out[:300]}", cwd)

    try:
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
    """Ollama streaming 호출. 최대 50s 내 수집한 내용 반환.

    stream=True 사용 이유
    --------------------
    stream=False + timeout=25s 방식은 Ollama가 모든 토큰을 생성한 뒤에야 HTTP 응답을 보냄.
    num_predict=512 @ 7.2t/s = 최대 71s → 25s timeout 에 걸려 항상 응답 손실.

    stream=True 방식:
    - 토큰 생성 즉시 수신 → 50s deadline 내 수집한 내용으로 답변 구성
    - 7.2t/s × 50s ≈ 360 토큰 수집 가능 (일반 답변 충분)
    - KB(3s) + health(1s) + streaming(50s) = 54s < Claude Code hook 60s 제한 ✓
    """
    import time

    base = ollama_url.rstrip("/")

    # 헬스체크 (1초)
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=1):
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
            "stream": True,
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

    # KB(3s) + health(1s) + streaming(50s) = 54s < Claude Code hook 60s 제한
    _STREAM_BUDGET = 50
    deadline = time.monotonic() + _STREAM_BUDGET
    collected: list[str] = []

    try:
        req = urllib.request.Request(
            f"{base}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_STREAM_BUDGET) as resp:
            while time.monotonic() < deadline:
                line = resp.readline()
                if not line:
                    break
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                token = chunk.get("message", {}).get("content", "")
                if token:
                    collected.append(token)
                if chunk.get("done"):
                    break
    except Exception as e:  # noqa: BLE001
        _debug(f"ollama_stream_failed: {type(e).__name__}: {e}", cwd)

    if not collected:
        return None

    answer = "".join(collected).strip()
    _debug(f"ollama_tokens={len(collected)}, chars={len(answer)}", cwd)
    return answer or None


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
        with urllib.request.urlopen(req, timeout=3) as resp:
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

        # 3-B) 2순위 Ollama (기본 비활성 — OLLAMA_HOOK_ENABLE=1 로 활성화)
        # 이유: num_predict=512 @ 7.2t/s → 최대 71s 대기, timeout=25s 로도 28s 화면 공백 발생
        if _env("OLLAMA_HOOK_ENABLE") == "1":
            ollama_answer = _call_ollama(prompt, ollama_url, ollama_model, cwd)
            if ollama_answer:
                _emit_block_with_answer("[2순위 🦙 Ollama  |  💰 무료]", ollama_answer, cwd)

        # 4) 3순위 — parent Claude 가 직접 처리 (CLAUDE.md §7-5 로 배지 자동)
        _emit_passthrough(cwd, reason="kb_miss_no_ollama")

    except SystemExit:
        # _emit_* 헬퍼가 호출한 정상 종료 — 그대로 전파
        raise
    except Exception as e:  # noqa: BLE001
        # 예상 못 한 예외 — 사용자에게 답변 보장 위해 exit 0 으로 통과
        _debug(f"UNHANDLED: {type(e).__name__}: {e}\n{traceback.format_exc()}", cwd_for_log)
        _emit_error_fail_safe(f"unhandled: {e}", cwd_for_log)


if __name__ == "__main__":
    main()

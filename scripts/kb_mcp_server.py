#!/usr/bin/env python3
"""scripts/kb_mcp_server.py — ADA 팀 KB MCP 서버

VS Code Claude Code 에서 /kb/search 엔드포인트를 MCP 도구로 노출.
팀원이 클로드 채팅창에서 @kb search "질문" 형태로 KB를 직접 검색 가능.

[MCP 프로토콜]
- stdio 기반 MCP 서버 (claude code 가 stdin/stdout 으로 통신)
- 도구 1개: search_team_kb(question, threshold?)

[설치 방법]
1. .claude/settings.json 에 MCP 서버 등록 (이미 업데이트됨)
2. 이 파일은 표준 라이브러리만 사용 (pip 설치 불필요)

[환경변수 / .env]
    KB_SERVER_URL       웹서버 주소 (기본: http://localhost:8000)
    KB_COLLECT_SECRET   X-KB-Secret 헤더
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# .env 파서
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent


def _load_env() -> dict[str, str]:
    env_file = _PROJECT_ROOT / ".env"
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


_ENV = _load_env()


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, "").strip() or _ENV.get(key, default)


# ---------------------------------------------------------------------------
# KB 검색 HTTP 호출
# ---------------------------------------------------------------------------


def _search_kb(question: str, threshold: float = 0.82, use_fallback: bool = True) -> dict:
    """POST /kb/search → dict 반환."""
    server_url = _cfg("KB_SERVER_URL", "http://localhost:8000").rstrip("/")
    secret = _cfg("KB_COLLECT_SECRET", "")

    body = json.dumps(
        {
            "question": question,
            "threshold": threshold,
            "use_claude_fallback": use_fallback,
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# MCP 프로토콜 핸들러 (JSON-RPC 2.0 over stdio)
# ---------------------------------------------------------------------------

# MCP 서버 메타데이터
SERVER_INFO = {
    "name": "ada-team-kb",
    "version": "1.0.0",
}

# 제공하는 도구 목록
TOOLS = [
    {
        "name": "search_team_kb",
        "description": (
            "ADA 팀 Q&A 지식 베이스에서 질문과 가장 유사한 답변을 검색합니다. "
            "팀원들이 Claude Code 사용 중 축적한 Q&A 가 저장되어 있습니다. "
            "KB 에 답이 없으면 Claude API 로 폴백합니다."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "검색할 질문 텍스트",
                },
                "threshold": {
                    "type": "number",
                    "description": "KB 유사도 임계값 (0.0~1.0, 기본 0.82)",
                    "default": 0.82,
                },
                "use_claude_fallback": {
                    "type": "boolean",
                    "description": "KB 미스 시 Claude API 폴백 여부 (기본 true)",
                    "default": True,
                },
            },
            "required": ["question"],
        },
    }
]


def _send(obj: dict) -> None:
    """JSON-RPC 응답을 stdout 으로 출력."""
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _handle_request(req: dict) -> None:
    """단일 JSON-RPC 요청 처리."""
    rid = req.get("id")
    method = req.get("method", "")
    params = req.get("params", {})

    # initialize
    if method == "initialize":
        _send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": SERVER_INFO,
                    "capabilities": {"tools": {}},
                },
            }
        )

    # tools/list
    elif method == "tools/list":
        _send(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"tools": TOOLS},
            }
        )

    # tools/call
    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "search_team_kb":
            question = arguments.get("question", "")
            threshold = float(arguments.get("threshold", 0.82))
            use_cb = bool(arguments.get("use_claude_fallback", True))

            if not question:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32602, "message": "question 필드가 비어 있습니다."},
                    }
                )
                return

            try:
                result = _search_kb(question, threshold, use_cb)
            except urllib.error.URLError as e:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32603, "message": f"KB 서버 연결 실패: {e}"},
                    }
                )
                return
            except Exception as e:  # noqa: BLE001
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": rid,
                        "error": {"code": -32603, "message": str(e)},
                    }
                )
                return

            # 결과 포맷
            answered_by = result.get("answered_by", "?")
            answer = result.get("answer", "")
            similarity = result.get("similarity")
            elapsed_ms = result.get("elapsed_ms", 0)
            hits = result.get("hits", [])

            if answered_by == "team_kb" and hits:
                best = hits[0]
                text = (
                    f"**[팀 KB 답변]** (유사도: {similarity:.2%} | {elapsed_ms}ms)\n\n"
                    f"{answer}\n\n"
                    f"---\n"
                    f"📌 출처: {best.get('team_member', 'unknown')} / {best.get('project', '?')}"
                )
            else:
                text = f"**[Claude 폴백]** (KB 미스 | {elapsed_ms}ms)\n\n{answer}"

            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "result": {
                        "content": [{"type": "text", "text": text}],
                        "isError": False,
                    },
                }
            )

        else:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
            )

    # notifications/initialized (응답 불필요)
    elif method == "notifications/initialized":
        pass

    # 미지원 메서드
    else:
        if rid is not None:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )


def main() -> None:
    """stdin 에서 JSON-RPC 메시지를 읽어 처리 (한 줄 = 한 메시지)."""
    # Windows 에서 UTF-8 I/O 강제 (cp949 혼용 방지)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")

    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            req = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        try:
            _handle_request(req)
        except Exception as e:  # noqa: BLE001
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": f"Internal error: {e}"},
                }
            )


if __name__ == "__main__":
    main()

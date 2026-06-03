"""Day24 — Stop 훅 (collect_error_fix.py) + linux_kb_sync.py failure_lessons 모드.

검증 항목:
    1. collect_error_fix.extract_error_signature — Traceback / 단순 ErrorName 양쪽
    2. collect_error_fix.extract_fix_diff       — diff 코드블록 추출
    3. collect_error_fix.extract_error_fix_pair — JSONL 끝에서 1쌍 추출
    4. collect_error_fix 의 ADA_ERROR_FIX_DISABLE — env flag 시 즉시 exit
    5. linux_kb_sync._summarize_for_embedding   — payload → 요약
    6. linux_kb_sync._upsert_failure_lesson     — payload 무효 시 skipped
    7. linux_kb_sync timestamp 파일 IO          — 저장/읽기

외부 의존성 (DB, sentence_transformers, network) 없이 모두 mock 으로 검증.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# scripts/ 디렉토리를 import path 에 추가 (테스트 한정)
_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# =============================================================================
# 1) extract_error_signature
# =============================================================================


def test_extract_error_signature_traceback():
    import collect_error_fix

    text = """
Some output here
Traceback (most recent call last):
  File "x.py", line 3, in foo
    raise ValueError("bad data")
ValueError: bad data
""".strip()
    sig = collect_error_fix._extract_error_signature(text)
    assert sig is not None
    signature, stack_top = sig
    assert "ValueError" in signature
    assert "Traceback" in stack_top


def test_extract_error_signature_plain_error_line():
    import collect_error_fix

    text = "Some preamble\nKeyError: 'missing_key'\nmore stuff"
    sig = collect_error_fix._extract_error_signature(text)
    assert sig is not None
    signature, _ = sig
    assert "KeyError" in signature


def test_extract_error_signature_no_error_returns_none():
    import collect_error_fix

    assert collect_error_fix._extract_error_signature("") is None
    assert collect_error_fix._extract_error_signature("just normal output") is None


# =============================================================================
# 2) extract_fix_diff
# =============================================================================


def test_extract_fix_diff_unified_diff_block():
    import collect_error_fix

    text = """여기 패치 드릴게요:
```diff
--- a/x.py
+++ b/x.py
@@ -1 +1 @@
-bad
+good
```
다 됐어요"""
    d = collect_error_fix._extract_fix_diff(text)
    assert "--- a/x.py" in d
    assert "@@" in d


def test_extract_fix_diff_no_diff_returns_empty():
    import collect_error_fix

    assert collect_error_fix._extract_fix_diff("just text") == ""
    assert collect_error_fix._extract_fix_diff("") == ""


def test_extract_fix_diff_inline_pseudo_diff():
    """tool_use Edit 가 합성한 pseudo-diff (헤더만) 도 검출되는지."""
    import collect_error_fix

    text = "--- a/foo.py\n+++ b/foo.py\n@@ edit @@\n-x\n+y"
    d = collect_error_fix._extract_fix_diff(text)
    assert "+++ b/foo.py" in d


# =============================================================================
# 3) extract_error_fix_pair
# =============================================================================


def test_extract_error_fix_pair_finds_recent_pair(tmp_path):
    import collect_error_fix

    transcript = tmp_path / "t.jsonl"
    lines = [
        {"role": "user", "content": "build it"},
        {"role": "assistant", "content": "ok let me try"},
        # 다음 user 메시지에 error
        {
            "role": "user",
            "content": 'Traceback (most recent call last):\n  File "x", line 2\nValueError: bad input',
        },
        # 다음 assistant 가 diff 응답
        {
            "role": "assistant",
            "content": "여기 수정:\n```diff\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-bad\n+good\n```",
        },
    ]
    transcript.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in lines), encoding="utf-8")

    pair = collect_error_fix.extract_error_fix_pair(str(transcript))
    assert pair is not None
    assert "ValueError" in pair["error_signature"]
    assert "--- a/x.py" in pair["fix_diff"]


def test_extract_error_fix_pair_no_error_returns_none(tmp_path):
    import collect_error_fix

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        '{"role":"user","content":"hi"}\n{"role":"assistant","content":"hello"}\n',
        encoding="utf-8",
    )
    assert collect_error_fix.extract_error_fix_pair(str(transcript)) is None


def test_extract_error_fix_pair_diff_without_error_returns_none(tmp_path):
    """diff 만 있고 error 시그니처 없으면 None — 무관 패치 잘못 학습 방지."""
    import collect_error_fix

    transcript = tmp_path / "t.jsonl"
    lines = [
        {"role": "user", "content": "refactor this"},
        {
            "role": "assistant",
            "content": "```diff\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n```",
        },
    ]
    transcript.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")
    assert collect_error_fix.extract_error_fix_pair(str(transcript)) is None


# =============================================================================
# 4) ADA_ERROR_FIX_DISABLE  — kill switch
# =============================================================================


def test_disable_env_flag_short_circuits(monkeypatch, capsys):
    import collect_error_fix

    monkeypatch.setenv("ADA_ERROR_FIX_DISABLE", "1")
    with pytest.raises(SystemExit) as e:
        collect_error_fix.main()
    assert e.value.code == 0


# =============================================================================
# 5) linux_kb_sync._summarize_for_embedding
# =============================================================================


def test_summarize_for_embedding_basic():
    import linux_kb_sync

    payload = {
        "error_signature": "ValueError: bad",
        "explanation": "strip whitespace before parse",
        "fix_diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-bad\n+good\n",
    }
    out = linux_kb_sync._summarize_for_embedding(payload)
    assert "ERROR: ValueError: bad" in out
    assert "FIX_EXPLANATION: strip" in out
    assert "DIFF_TARGETS:" in out
    assert "--- a/x.py" in out
    assert len(out) <= 1000


def test_summarize_for_embedding_empty_payload():
    import linux_kb_sync

    assert linux_kb_sync._summarize_for_embedding({}) == ""


# =============================================================================
# 6) linux_kb_sync._upsert_failure_lesson  — invalid payload → skipped
# =============================================================================


async def test_upsert_failure_lesson_skips_no_diff():
    import linux_kb_sync

    item = {"error_hash": "x" * 64, "payload": {"error_signature": "boom"}, "confidence": 0.5}
    status, kb_id = await linux_kb_sync._upsert_failure_lesson(
        db_url="postgresql://test/test",
        item=item,
        dry_run=True,
    )
    assert status == "skipped"
    assert kb_id == ""


async def test_upsert_failure_lesson_skips_no_hash():
    import linux_kb_sync

    item = {"error_hash": "", "payload": {"fix_diff": "--- a/x\n@@ @@\n-a\n+b"}}
    status, _ = await linux_kb_sync._upsert_failure_lesson(
        db_url="postgresql://test/test",
        item=item,
        dry_run=True,
    )
    assert status == "skipped"


async def test_upsert_failure_lesson_dry_run_returns_dryrun():
    import linux_kb_sync

    item = {
        "kb_id": "src-kb-1",
        "error_hash": "h" * 64,
        "payload": {
            "error_signature": "ValueError",
            "fix_diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-bad\n+good\n",
        },
        "confidence": 0.9,
    }
    status, kb_id = await linux_kb_sync._upsert_failure_lesson(
        db_url="postgresql://test/test",
        item=item,
        dry_run=True,
    )
    assert status == "dryrun"
    assert kb_id == "src-kb-1"


def test_upsert_failure_lesson_payload_as_string_parsed():
    """payload 가 JSON 문자열로 와도 정상 처리 (FastAPI 직렬화 변형 대응)."""
    import linux_kb_sync

    item = {
        "error_hash": "z" * 64,
        "payload": json.dumps(
            {
                "error_signature": "X",
                "fix_diff": "--- a/x\n@@ @@\n-a\n+b\n",
            }
        ),
        "confidence": 0.7,
    }
    import asyncio as _aio

    status, _ = _aio.run(
        linux_kb_sync._upsert_failure_lesson(
            db_url="postgresql://test/test",
            item=item,
            dry_run=True,
        )
    )
    assert status == "dryrun"


# =============================================================================
# 7) timestamp 파일 IO
# =============================================================================


def test_last_sync_ts_io(tmp_path, monkeypatch):
    import linux_kb_sync

    monkeypatch.setattr(linux_kb_sync, "_TS_FILE", tmp_path / "ts")
    # 처음엔 없음
    assert linux_kb_sync._read_last_sync_ts() is None
    # 쓰기
    linux_kb_sync._write_last_sync_ts("2026-06-03T05:00:00Z")
    # 다시 읽기
    assert linux_kb_sync._read_last_sync_ts() == "2026-06-03T05:00:00Z"


# =============================================================================
# 8) .claude/settings.json 에 collect_error_fix 훅 등록 확인
# =============================================================================


def test_settings_json_has_collect_error_fix_hook():
    """팀원이 pull 받으면 settings.json 안에 새 Stop 훅이 등록돼 있어야 함."""
    settings_path = Path(__file__).parent.parent / ".claude" / "settings.json"
    if not settings_path.exists():
        pytest.skip(".claude/settings.json not present")
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    stop_hooks = data.get("hooks", {}).get("Stop", [])
    cmds = []
    for entry in stop_hooks:
        for h in entry.get("hooks", []):
            cmds.append(h.get("command", ""))
    assert any("collect_error_fix" in c for c in cmds), cmds
    # 기존 collect_qa 도 그대로 살아있어야 함 (회귀방지)
    assert any("collect_qa" in c for c in cmds), cmds


# =============================================================================
# 9) BLOCKER 수정 검증 — PII 마스킹 / pairing lookback 2
# =============================================================================


def test_pairing_lookback_2_rejects_far_error(tmp_path):
    """3턴 이상 떨어진 error+diff 는 무관 페어로 간주, None 반환."""
    import collect_error_fix

    transcript = tmp_path / "t.jsonl"
    lines = [
        {"role": "user", "content": "ValueError: bad input"},  # 멀리 떨어진 error
        {"role": "assistant", "content": "fixed by..."},
        {"role": "user", "content": "now do something else"},  # 무관 요청
        {"role": "user", "content": "and one more thing"},  # 더 무관
        {
            "role": "assistant",
            "content": "```diff\n--- a/y.py\n+++ b/y.py\n@@ @@\n-x\n+y\n```",  # error 와 무관한 diff
        },
    ]
    transcript.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")
    # error 가 4메시지 떨어져 있어 lookback=2 윈도우 밖 → None
    assert collect_error_fix.extract_error_fix_pair(str(transcript)) is None


def test_pairing_lookback_2_accepts_adjacent(tmp_path):
    """직전 user 메시지에 error 있으면 정상 페어링."""
    import collect_error_fix

    transcript = tmp_path / "t.jsonl"
    lines = [
        {"role": "user", "content": "something"},
        {"role": "assistant", "content": "..."},
        {"role": "user", "content": "TypeError: cannot concatenate str and int"},
        {
            "role": "assistant",
            "content": "```diff\n--- a/x.py\n+++ b/x.py\n@@ @@\n-bad\n+good\n```",
        },
    ]
    transcript.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")
    pair = collect_error_fix.extract_error_fix_pair(str(transcript))
    assert pair is not None
    assert "TypeError" in pair["error_signature"]


# =============================================================================
# 10) linux_kb_sync — embed 실패 graceful skip
# =============================================================================


async def test_upsert_failure_lesson_dryrun_with_string_payload():
    """payload 가 JSON 문자열이어도 정상 dryrun."""
    import linux_kb_sync

    item = {
        "kb_id": "src-2",
        "error_hash": "k" * 64,
        "payload": json.dumps(
            {
                "error_signature": "Foo",
                "fix_diff": "--- a/a\n+++ b/a\n@@ @@\n-x\n+y\n",
            }
        ),
        "confidence": 0.5,
    }
    status, kb_id = await linux_kb_sync._upsert_failure_lesson(
        db_url="postgresql://test/test",
        item=item,
        dry_run=True,
    )
    assert status == "dryrun"
    assert kb_id == "src-2"


# =============================================================================
# 11) PII 마스킹 — main 흐름 검증 (mock 으로 redact 호출 확인)
# =============================================================================


def test_main_calls_redactor_before_post(tmp_path, monkeypatch):
    """sig/stack/diff 가 모두 redact 처리된 뒤에 POST 되어야 함."""
    import collect_error_fix

    # 가짜 transcript 작성
    transcript = tmp_path / "t.jsonl"
    lines = [
        {"role": "user", "content": "ValueError: bad at C:\\Users\\johnny\\secret"},
        {
            "role": "assistant",
            "content": "```diff\n--- a/x.py\n+++ b/x.py\n@@ @@\n-bad\n+good\n```",
        },
    ]
    transcript.write_text("\n".join(json.dumps(o) for o in lines), encoding="utf-8")

    # stdin 페이로드 mock
    stdin_payload = json.dumps(
        {
            "transcript_path": str(transcript),
            "session_id": "s1",
            "cwd": str(tmp_path),
        }
    )
    monkeypatch.setattr("sys.stdin", _StringStdin(stdin_payload))
    monkeypatch.delenv("ADA_ERROR_FIX_DISABLE", raising=False)

    captured: dict = {}

    def fake_redact(s):
        captured.setdefault("calls", []).append(s)
        return f"[REDACTED]{s[:20]}", []

    # ada 모듈 stub
    import types

    fake_mod = types.ModuleType("ada.error_handler.redactor")
    fake_mod.redact = fake_redact
    fake_ada = types.ModuleType("ada")
    fake_ada_eh = types.ModuleType("ada.error_handler")
    monkeypatch.setitem(sys.modules, "ada", fake_ada)
    monkeypatch.setitem(sys.modules, "ada.error_handler", fake_ada_eh)
    monkeypatch.setitem(sys.modules, "ada.error_handler.redactor", fake_mod)

    # urlopen mock
    posted = {}

    class _FakeResp:
        def read(self):
            return b'{"kb_id":"x","status":"recorded"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout=10):
        posted["body"] = req.data
        return _FakeResp()

    monkeypatch.setattr(collect_error_fix.urllib.request, "urlopen", fake_urlopen)

    # 실행
    with pytest.raises(SystemExit):
        collect_error_fix.main()

    # 3회 redact 호출됐는지 (sig + stack + diff)
    assert len(captured.get("calls", [])) >= 2
    # POST body 에 [REDACTED] 가 들어가있어야 함
    if posted.get("body"):
        body_str = posted["body"].decode("utf-8")
        assert "[REDACTED]" in body_str


class _StringStdin:
    """sys.stdin.read() 가 주어진 문자열 반환하도록 하는 헬퍼."""

    def __init__(self, s: str) -> None:
        self._s = s

    def read(self) -> str:
        return self._s

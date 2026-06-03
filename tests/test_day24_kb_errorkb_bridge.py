"""Day24 — SelfLearningKB ↔ ErrorKB 통합 단위 테스트.

검증 항목:
    1. record_error_fix         — payload 구성 + 입력 검증 + index_lesson 호출
    2. validate_and_record       — sandbox green → KB 적재, red → 적재 안 함
    3. _schedule_validate_and_record — 이벤트 루프 안/밖 둘 다 안전 호출
    4. auto_handler Tier 1.5     — search_lessons 히트 시 auto_self_learning_match 반환
    5. auto_error_handler agent  — RESOLVED_ACTIONS 에 auto_self_learning_match 포함
    6. ErrorFixIn 스키마          — fix_diff hunk 없을 시 rejected
    7. stable_hash_for_signature — 동일 입력 동일 hash, 다른 입력 다른 hash

외부 의존성 (postgres / sandbox / pytest-실행) 없이 모두 mock 으로 검증.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# =============================================================================
# 1) record_error_fix — payload + 입력 검증
# =============================================================================


@pytest.mark.asyncio
async def test_record_error_fix_inserts_and_indexes():
    from agents.self_learning import record_error_fix

    session = AsyncMock()
    # execute().fetchone() → row with id
    exec_result = MagicMock()
    exec_result.fetchone.return_value = ("00000000-0000-0000-0000-000000000abc",)
    session.execute.return_value = exec_result

    with patch("ada.harness.rag.KBRAG") as MockRAG:
        rag_inst = MagicMock()
        rag_inst.index_lesson = AsyncMock()
        MockRAG.return_value = rag_inst

        kb_id = await record_error_fix(
            session,
            error_hash="abcd1234" * 8,  # 64 chars
            error_signature="ValueError: bad data",
            fix_diff="--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-bad\n+good\n",
            source="ollama",
            confidence=0.85,
            explanation="strip whitespace",
        )

        assert kb_id == "00000000-0000-0000-0000-000000000abc"
        session.execute.assert_called_once()
        rag_inst.index_lesson.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_error_fix_empty_diff_rejected():
    from agents.self_learning import record_error_fix

    session = AsyncMock()
    kb_id = await record_error_fix(
        session,
        error_hash="x" * 64,
        error_signature="err",
        fix_diff="   ",  # 공백만
        source="ollama",
        confidence=0.5,
    )
    assert kb_id is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_record_error_fix_no_hash_rejected():
    from agents.self_learning import record_error_fix

    session = AsyncMock()
    kb_id = await record_error_fix(
        session,
        error_hash="",
        error_signature="err",
        fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
        source="ollama",
        confidence=0.5,
    )
    assert kb_id is None
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_record_error_fix_clamps_confidence():
    """confidence 범위 0.0~1.0 강제."""
    from agents.self_learning import record_error_fix

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.fetchone.return_value = ("00000000-0000-0000-0000-000000000abc",)
    session.execute.return_value = exec_result

    with patch("ada.harness.rag.KBRAG") as MockRAG:
        MockRAG.return_value = MagicMock(index_lesson=AsyncMock())
        # 음수 → 0 clamp
        await record_error_fix(
            session,
            error_hash="h" * 64,
            error_signature="sig",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="ollama",
            confidence=-2.0,
        )
        # 1 초과 → 1.0 clamp
        await record_error_fix(
            session,
            error_hash="g" * 64,
            error_signature="sig",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="ollama",
            confidence=2.5,
        )
    # 두 번 모두 호출됨 — clamp 가 raise 하지 않음을 확인
    assert session.execute.call_count == 2


# =============================================================================
# 2) validate_and_record — sandbox green/red 분기
# =============================================================================


@pytest.mark.asyncio
async def test_validate_and_record_green_path():
    from agents.self_learning import validate_and_record

    # PatchValidator.validate → ValidationResult(passed=True)
    sandbox_result = SimpleNamespace(
        passed=True,
        reason="all_checks_passed",
        tests_passed=5,
        tests_run=5,
    )
    fake_validator = MagicMock()
    fake_validator.validate = AsyncMock(return_value=sandbox_result)

    # session_factory mock
    fake_session = AsyncMock()
    fake_session.commit = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=fake_session)

    with (
        patch("ada.error_handler.sandbox.PatchValidator", return_value=fake_validator),
        patch("agents.self_learning.record_error_fix", new=AsyncMock(return_value="kb-uuid")),
    ):
        out = await validate_and_record(
            error_hash="x" * 64,
            error_signature="boom",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="ollama",
            confidence=0.7,
            session_factory=session_factory,
        )

    assert out["recorded"] is True
    assert out["kb_id"] == "kb-uuid"
    assert out["reason"] == "validated"


@pytest.mark.asyncio
async def test_validate_and_record_red_skips_record():
    from agents.self_learning import validate_and_record

    sandbox_result = SimpleNamespace(passed=False, reason="tests_failed: 3 failed / 5 run")
    fake_validator = MagicMock()
    fake_validator.validate = AsyncMock(return_value=sandbox_result)

    record_mock = AsyncMock(return_value="should-not-be-used")

    with (
        patch("ada.error_handler.sandbox.PatchValidator", return_value=fake_validator),
        patch("agents.self_learning.record_error_fix", new=record_mock),
    ):
        out = await validate_and_record(
            error_hash="y" * 64,
            error_signature="boom",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="claude_cli",
            confidence=0.5,
            session_factory=MagicMock(),
        )

    assert out["recorded"] is False
    assert out["kb_id"] is None
    assert "tests_failed" in (out["reason"] or "")
    record_mock.assert_not_called()


# =============================================================================
# 3) _schedule_validate_and_record — fire-and-forget 안전성
# =============================================================================


@pytest.mark.asyncio
async def test_schedule_inside_running_loop_uses_create_task():
    from ada.error_handler.auto_handler import _schedule_validate_and_record

    captured: dict = {}

    async def fake_var(**kwargs):
        captured.update(kwargs)
        return {"recorded": True, "kb_id": "kb-1", "reason": "validated"}

    with patch("agents.self_learning.validate_and_record", new=fake_var):
        _schedule_validate_and_record(
            error_hash="z" * 64,
            error_signature="boom",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="ollama",
            confidence=0.6,
        )
        # task 가 schedule 되었는지 확인 — 한 cycle yield
        await asyncio.sleep(0.05)

    assert captured.get("source") == "ollama"
    assert captured.get("skip_tests") is True  # hot path 는 ruff+static 만


def test_schedule_outside_loop_uses_thread():
    """동기 컨텍스트 (이벤트 루프 없음) → 별도 thread 로 실행, 호출자 안 막힘."""
    from ada.error_handler.auto_handler import _schedule_validate_and_record

    captured: dict = {}

    async def fake_var(**kwargs):
        captured.update(kwargs)
        return {"recorded": True, "kb_id": None, "reason": "validated"}

    with patch("agents.self_learning.validate_and_record", new=fake_var):
        _schedule_validate_and_record(
            error_hash="a" * 64,
            error_signature="boom",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="claude_cli",
            confidence=0.4,
        )
        # thread daemon → 약간 대기
        import time as _t

        for _ in range(40):
            if captured:
                break
            _t.sleep(0.025)

    assert captured.get("source") == "claude_cli"


# =============================================================================
# 4) auto_handler Tier 1.5 — search_lessons 매칭 시 auto_self_learning_match
# =============================================================================


@pytest.mark.asyncio
async def test_auto_handler_tier_1_5_self_learning_match():
    """ErrorKB 미스 시 SelfLearningKB 시맨틱 매칭이 작동하는지."""
    from ada.error_handler.auto_handler import AutoErrorHandler

    session = AsyncMock()
    # ErrorKB scalar → None (해시 미스)
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.add = MagicMock()

    log_row = SimpleNamespace(
        error_message="ValueError: bad",
        stack_trace="  File 'x.py', line 1, in f\n    raise ValueError",
        error_category=None,
        auto_handled_by_kb=False,
        error_kb_id=None,
    )

    # 시맨틱 검색 → 강한 매칭
    high_match = {
        "kb_id": "abc-123",
        "payload": {
            "fix_diff": "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-bad\n+good\n",
            "source": "ollama",
        },
        "confidence": 0.85,
        "similarity": 0.92,
        "success_count": 3,
    }

    with (
        patch("ada.error_handler.redactor.redact", return_value=("ValueError: bad", [])),
        patch("ada.error_handler.classifier.classify_with_reason") as mock_cls,
        patch("ada.error_handler.classifier.get_strategy") as mock_strat,
        patch("ada.error_handler.classifier.should_skip_llm", return_value=False),
        patch("ada.error_handler.static_fixers.try_static_fix", return_value=None),
        patch("ada.harness.rag.KBRAG") as MockRAG,
        patch("ada.error_handler.sandbox.PatchValidator") as MockValidator,
    ):
        # classifier mock
        cls_enum = SimpleNamespace(value="code_bug")
        mock_cls.return_value = (cls_enum, "matched code_bug")
        mock_strat.return_value = SimpleNamespace(value="retry_then_llm")

        # KBRAG.search_lessons → 강한 매칭 반환
        rag_inst = MagicMock()
        rag_inst.search_lessons = AsyncMock(return_value=[high_match])
        MockRAG.return_value = rag_inst

        # static_check pass
        MockValidator.return_value.static_check.return_value = SimpleNamespace(
            passed=True, reason="ok", scope_violations=[], forbidden_violations=[]
        )

        out = await AutoErrorHandler(session).handle(log_row)

    assert out["action"] == "auto_self_learning_match", out
    assert out["kb_id"] == "abc-123"
    assert out["similarity"] >= 0.85
    # PendingPatch 가 review_status=approved 로 add 됨
    assert session.add.called


@pytest.mark.asyncio
async def test_auto_handler_tier_1_5_low_similarity_falls_through():
    """similarity 낮으면 Tier 1.5 가 매칭 안 하고 다음 Tier 로 흘러야 함."""
    from ada.error_handler.auto_handler import AutoErrorHandler

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)  # ErrorKB miss
    session.flush = AsyncMock()
    session.add = MagicMock()

    log_row = SimpleNamespace(
        error_message="ValueError: bad",
        stack_trace="",
        error_category=None,
        auto_handled_by_kb=False,
        error_kb_id=None,
    )
    weak_match = {
        "kb_id": "weak-1",
        "payload": {"fix_diff": "--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n"},
        "confidence": 0.85,
        "similarity": 0.5,  # < 0.85
    }

    with (
        patch("ada.error_handler.redactor.redact", return_value=("ValueError: bad", [])),
        patch("ada.error_handler.classifier.classify_with_reason") as mock_cls,
        patch("ada.error_handler.classifier.get_strategy") as mock_strat,
        patch("ada.error_handler.classifier.should_skip_llm", return_value=False),
        patch("ada.error_handler.static_fixers.try_static_fix", return_value=None),
        patch("ada.harness.rag.KBRAG") as MockRAG,
        patch("ada.error_handler.auto_handler._ollama_coder_fix", new=AsyncMock(side_effect=Exception("ollama-down"))),
        patch("ada.error_handler.budget.get_budget_manager") as mock_budget,
        patch("ada.error_handler.circuit_breaker.get_breaker") as mock_breaker,
        patch("ada.error_handler.claude_cli_bridge.ClaudeCLIBridge") as MockBridge,
    ):
        mock_cls.return_value = (SimpleNamespace(value="code_bug"), "ok")
        mock_strat.return_value = SimpleNamespace(value="llm")

        rag_inst = MagicMock()
        rag_inst.search_lessons = AsyncMock(return_value=[weak_match])
        MockRAG.return_value = rag_inst

        # Ollama 회로 차단기 — 호출 시 ollama-down 으로 진행
        cb = MagicMock()
        cb.call = AsyncMock(side_effect=Exception("ollama-down"))
        mock_breaker.return_value = cb

        # 예산 OK
        budget = MagicMock()
        budget.is_exceeded = AsyncMock(return_value=False)
        budget.get_today_spend = AsyncMock(return_value=0.0)
        budget.remaining_budget = AsyncMock(return_value=5.0)
        budget.track_call = AsyncMock()
        mock_budget.return_value = budget

        # Claude bridge 도 실패시켜서 noop 액션 받기
        bridge_inst = MagicMock()
        bridge_inst.request_patch = AsyncMock(side_effect=Exception("claude-down"))
        MockBridge.return_value = bridge_inst

        out = await AutoErrorHandler(session).handle(log_row)

    # Tier 1.5 매칭 안 함 (weak) → 흐름이 다음 Tier 로
    assert out["action"] != "auto_self_learning_match"


# =============================================================================
# 5) RESOLVED_ACTIONS 갱신
# =============================================================================


def test_resolved_actions_includes_self_learning_match():
    from agents.auto_error_handler import RESOLVED_ACTIONS

    assert "auto_self_learning_match" in RESOLVED_ACTIONS
    # 기존 action 도 그대로 살아있어야 함
    assert "auto_kb_match" in RESOLVED_ACTIONS
    assert "patch_reused_approved" in RESOLVED_ACTIONS


# =============================================================================
# 6) ErrorFixIn 스키마 & hash helper
# =============================================================================


def test_stable_hash_for_signature_deterministic():
    from agents.self_learning import stable_hash_for_signature

    h1 = stable_hash_for_signature("ValueError: bad", "File 'x', line 1")
    h2 = stable_hash_for_signature("ValueError: bad", "File 'x', line 1")
    h3 = stable_hash_for_signature("ValueError: different", "File 'x', line 1")

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA256 hex


def test_error_fix_in_schema_validates():
    from api.routes.conversation_kb import ErrorFixIn

    valid = ErrorFixIn(
        error_signature="ValueError: bad",
        fix_diff="--- a/x\n+++ b/x\n@@ -1 +1 @@\n-bad\n+good\n",
        confidence=0.8,
    )
    assert valid.confidence == 0.8
    assert valid.source == "team_manual"

    # confidence 범위 검증
    with pytest.raises(Exception):
        ErrorFixIn(error_signature="x" * 10, fix_diff="x" * 50, confidence=1.5)


# =============================================================================
# 7) BLOCKER-1 수정 검증 — source-aware 자동승인
# =============================================================================


@pytest.mark.asyncio
async def test_tier_1_5_trusted_source_auto_approved():
    """source=ollama (sandbox-검증) → review_status=approved."""
    from ada.error_handler.auto_handler import AutoErrorHandler

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    captured_patch = {}

    def _add(obj):
        captured_patch["review_status"] = getattr(obj, "review_status", None)
        captured_patch["confidence"] = getattr(obj, "confidence", None)

    session.add = MagicMock(side_effect=_add)

    log_row = SimpleNamespace(
        error_message="ValueError: bad",
        stack_trace="",
        error_category=None,
        auto_handled_by_kb=False,
        error_kb_id=None,
    )

    match = {
        "kb_id": "k1",
        "payload": {"fix_diff": "--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n", "source": "ollama"},
        "confidence": 0.9,
        "similarity": 0.95,
    }

    with (
        patch("ada.error_handler.redactor.redact", return_value=("ValueError: bad", [])),
        patch(
            "ada.error_handler.classifier.classify_with_reason", return_value=(SimpleNamespace(value="code_bug"), "ok")
        ),
        patch("ada.error_handler.classifier.get_strategy", return_value=SimpleNamespace(value="llm")),
        patch("ada.error_handler.classifier.should_skip_llm", return_value=False),
        patch("ada.error_handler.static_fixers.try_static_fix", return_value=None),
        patch("ada.harness.rag.KBRAG") as MockRAG,
        patch("ada.error_handler.sandbox.PatchValidator") as MockValidator,
    ):
        rag_inst = MagicMock()
        rag_inst.search_lessons = AsyncMock(return_value=[match])
        MockRAG.return_value = rag_inst
        MockValidator.return_value.static_check.return_value = SimpleNamespace(
            passed=True, reason="ok", scope_violations=[], forbidden_violations=[]
        )

        out = await AutoErrorHandler(session).handle(log_row)

    assert out["action"] == "auto_self_learning_match"
    assert out["trusted_source"] is True
    assert out["review_status"] == "approved"
    assert captured_patch["review_status"] == "approved"


@pytest.mark.asyncio
async def test_tier_1_5_untrusted_source_pending_only():
    """source=team_manual (sandbox 미검증) → review_status=pending. 자동승인 금지."""
    from ada.error_handler.auto_handler import AutoErrorHandler

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    captured_patch = {}

    def _add(obj):
        captured_patch["review_status"] = getattr(obj, "review_status", None)

    session.add = MagicMock(side_effect=_add)

    log_row = SimpleNamespace(
        error_message="ValueError: bad",
        stack_trace="",
        error_category=None,
        auto_handled_by_kb=False,
        error_kb_id=None,
    )

    match = {
        "kb_id": "k2",
        # 팀원이 수동 제출한 사례 (sandbox 미검증)
        "payload": {"fix_diff": "--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n", "source": "team_manual"},
        "confidence": 0.85,
        "similarity": 0.91,
    }

    with (
        patch("ada.error_handler.redactor.redact", return_value=("ValueError: bad", [])),
        patch(
            "ada.error_handler.classifier.classify_with_reason", return_value=(SimpleNamespace(value="code_bug"), "ok")
        ),
        patch("ada.error_handler.classifier.get_strategy", return_value=SimpleNamespace(value="llm")),
        patch("ada.error_handler.classifier.should_skip_llm", return_value=False),
        patch("ada.error_handler.static_fixers.try_static_fix", return_value=None),
        patch("ada.harness.rag.KBRAG") as MockRAG,
        patch("ada.error_handler.sandbox.PatchValidator") as MockValidator,
    ):
        rag_inst = MagicMock()
        rag_inst.search_lessons = AsyncMock(return_value=[match])
        MockRAG.return_value = rag_inst
        MockValidator.return_value.static_check.return_value = SimpleNamespace(
            passed=True, reason="ok", scope_violations=[], forbidden_violations=[]
        )

        out = await AutoErrorHandler(session).handle(log_row)

    assert out["action"] == "auto_self_learning_match"
    assert out["trusted_source"] is False
    assert out["review_status"] == "pending"
    assert captured_patch["review_status"] == "pending"


# =============================================================================
# 8) BLOCKER-2 수정 검증 — KB 적재 실패 audit
# =============================================================================


@pytest.mark.asyncio
async def test_validate_passes_record_fails_audit_failurelog():
    """검증 통과 → 적재 실패 → FailureLog audit row 생성."""
    from agents.self_learning import validate_and_record

    sandbox_result = SimpleNamespace(passed=True, reason="ok", tests_passed=1, tests_run=1)
    fake_validator = MagicMock()
    fake_validator.validate = AsyncMock(return_value=sandbox_result)

    # 두 개의 세션이 필요 — 하나는 적재용(실패), 하나는 audit 용(성공)
    record_session = AsyncMock()
    record_session.commit = AsyncMock()
    record_session.__aenter__ = AsyncMock(return_value=record_session)
    record_session.__aexit__ = AsyncMock(return_value=None)

    audit_session = AsyncMock()
    audit_session.commit = AsyncMock()
    audit_session.add = MagicMock()
    audit_session.__aenter__ = AsyncMock(return_value=audit_session)
    audit_session.__aexit__ = AsyncMock(return_value=None)

    call_count = {"n": 0}

    def session_factory():
        call_count["n"] += 1
        return record_session if call_count["n"] == 1 else audit_session

    with (
        patch("ada.error_handler.sandbox.PatchValidator", return_value=fake_validator),
        patch("agents.self_learning.record_error_fix", new=AsyncMock(return_value=None)),
    ):
        # record_error_fix 가 None 반환 = 적재 실패
        out = await validate_and_record(
            error_hash="z" * 64,
            error_signature="boom",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="ollama",
            confidence=0.7,
            session_factory=session_factory,
        )

    assert out["recorded"] is False
    assert out["reason"] == "record_failed_after_validation"
    # FailureLog row 가 audit session 에 add 됨
    audit_session.add.assert_called_once()
    audit_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_validate_db_exception_audit_failurelog():
    """검증 통과 → DB 예외 → FailureLog audit row 생성."""
    from agents.self_learning import validate_and_record

    sandbox_result = SimpleNamespace(passed=True, reason="ok", tests_passed=1, tests_run=1)
    fake_validator = MagicMock()
    fake_validator.validate = AsyncMock(return_value=sandbox_result)

    # record 세션 — record_error_fix 자체에서 예외 발생
    record_session = AsyncMock()
    record_session.commit = AsyncMock()
    record_session.__aenter__ = AsyncMock(return_value=record_session)
    record_session.__aexit__ = AsyncMock(return_value=None)

    audit_session = AsyncMock()
    audit_session.commit = AsyncMock()
    audit_session.add = MagicMock()
    audit_session.__aenter__ = AsyncMock(return_value=audit_session)
    audit_session.__aexit__ = AsyncMock(return_value=None)

    call_count = {"n": 0}

    def session_factory():
        call_count["n"] += 1
        return record_session if call_count["n"] == 1 else audit_session

    with (
        patch("ada.error_handler.sandbox.PatchValidator", return_value=fake_validator),
        patch("agents.self_learning.record_error_fix", new=AsyncMock(side_effect=RuntimeError("db connection lost"))),
    ):
        out = await validate_and_record(
            error_hash="w" * 64,
            error_signature="boom",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="claude_cli",
            confidence=0.6,
            session_factory=session_factory,
        )

    assert out["recorded"] is False
    assert "db_error" in (out["reason"] or "")
    audit_session.add.assert_called_once()
    audit_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_validate_failed_no_audit():
    """sandbox 검증 자체 실패 = 정상 거절. audit 불필요."""
    from agents.self_learning import validate_and_record

    sandbox_result = SimpleNamespace(passed=False, reason="tests_failed: 2 failed / 5 run")
    fake_validator = MagicMock()
    fake_validator.validate = AsyncMock(return_value=sandbox_result)

    audit_called = {"n": 0}

    def session_factory():
        audit_called["n"] += 1
        s = AsyncMock()
        s.add = MagicMock()
        s.commit = AsyncMock()
        s.__aenter__ = AsyncMock(return_value=s)
        s.__aexit__ = AsyncMock(return_value=None)
        return s

    with patch("ada.error_handler.sandbox.PatchValidator", return_value=fake_validator):
        out = await validate_and_record(
            error_hash="v" * 64,
            error_signature="boom",
            fix_diff="--- a/x\n+++ b/x\n@@ @@\n-a\n+b\n",
            source="ollama",
            confidence=0.5,
            session_factory=session_factory,
        )

    assert out["recorded"] is False
    # session_factory 한 번도 호출 안 됨 (검증 실패 = 즉시 return)
    assert audit_called["n"] == 0


# =============================================================================
# 9) IMPORTANT-1 수정 검증 — JSONB 파싱 실패 명시 경고
# =============================================================================


@pytest.mark.asyncio
async def test_tier_1_5_malformed_jsonb_logs_warning(caplog):
    """JSONB payload 가 깨진 문자열로 와도 silently drop 하지 않고 경고."""
    import logging

    from ada.error_handler.auto_handler import AutoErrorHandler

    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    session.add = MagicMock()

    log_row = SimpleNamespace(
        error_message="ValueError: bad",
        stack_trace="",
        error_category=None,
        auto_handled_by_kb=False,
        error_kb_id=None,
    )

    bad_match = {
        "kb_id": "broken-1",
        "payload": "{not valid json",  # 깨진 JSON
        "confidence": 0.85,
        "similarity": 0.91,
    }

    with (
        caplog.at_level(logging.WARNING),
        patch("ada.error_handler.redactor.redact", return_value=("ValueError: bad", [])),
        patch(
            "ada.error_handler.classifier.classify_with_reason", return_value=(SimpleNamespace(value="code_bug"), "ok")
        ),
        patch("ada.error_handler.classifier.get_strategy", return_value=SimpleNamespace(value="llm")),
        patch("ada.error_handler.classifier.should_skip_llm", return_value=False),
        patch("ada.error_handler.static_fixers.try_static_fix", return_value=None),
        patch("ada.harness.rag.KBRAG") as MockRAG,
        patch("ada.error_handler.auto_handler._ollama_coder_fix", new=AsyncMock(side_effect=Exception("ollama-stop"))),
        patch("ada.error_handler.budget.get_budget_manager") as mock_budget,
        patch("ada.error_handler.circuit_breaker.get_breaker") as mock_breaker,
        patch("ada.error_handler.claude_cli_bridge.ClaudeCLIBridge") as MockBridge,
    ):
        rag_inst = MagicMock()
        rag_inst.search_lessons = AsyncMock(return_value=[bad_match])
        MockRAG.return_value = rag_inst

        cb = MagicMock()
        cb.call = AsyncMock(side_effect=Exception("ollama-stop"))
        mock_breaker.return_value = cb

        budget = MagicMock()
        budget.is_exceeded = AsyncMock(return_value=False)
        mock_budget.return_value = budget

        bridge_inst = MagicMock()
        bridge_inst.request_patch = AsyncMock(side_effect=Exception("claude-stop"))
        MockBridge.return_value = bridge_inst

        await AutoErrorHandler(session).handle(log_row)

    # tier_1_5_payload_parse_failed 가 명시적으로 로깅됐는지
    assert any(
        "tier_1_5_payload_parse_failed" in rec.getMessage() or "tier_1_5_payload_parse_failed" in str(rec.args)
        for rec in caplog.records
    ), [r.getMessage() for r in caplog.records]

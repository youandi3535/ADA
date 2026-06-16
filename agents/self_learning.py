"""agents.self_learning — SelfLearningAgent (Day09 + Day 1 자동 KB 인덱싱).

job 종료 시:
    1) SelfLearningHarness.distill_from_job(job_id) — 사후 학습 (KB row 생성)
    2) Day 1 추가: distill 결과의 lesson_summary 가 있으면
       KBRAG.index_lesson 을 자동 호출해 pgvector 임베딩 색인.

추가 (Day24 — KB↔ErrorKB 통합):
    3) record_error_fix()  — Tier 2/3 패치 성공 시 SelfLearningKB.failure_lesson
       으로 적재 + 자동 임베딩 색인.
    4) validate_and_record() — 패치 diff 를 sandbox 로 검증(test_plan 실행) 후
       green 이면 record_error_fix() 호출. auto_handler 에서 fire-and-forget
       으로 호출되는 안전 래퍼.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ada.core.logger import get_logger
from ada.core.state import PipelineState
from agents.base import BaseAgent

_log = get_logger("self_learning")


class SelfLearningAgent(BaseAgent):
    uses_llm = False
    uses_db_session = (
        True  # HJ 2026-06-16 — distillation·KB 성장 활성(end-of-pipeline, distill/index 모두 try/except 보호).
    )

    async def __call__(self, state: PipelineState) -> PipelineState:
        async with self.log_agent_run(state):
            if self.session is None:
                return state.with_update(next_agent="END")

            distill_result: dict | None = None
            try:
                from ada.harness.distiller import SelfLearningHarness

                h = SelfLearningHarness(self.session)
                distill_result = await h.distill_from_job(state.job_id)
            except Exception as e:
                self.logger.warning("distill_failed", error=str(e))

            # Day 1 — distill 결과를 RAG 에 자동 색인 (새 KB row 가 있을 때만)
            if distill_result and distill_result.get("created_kb_ids"):
                await self._auto_index_lessons(distill_result)

            return state.with_update(next_agent="END")

    # ------------------------------------------------------------------
    async def _auto_index_lessons(self, distill_result: dict) -> None:
        """distill 결과의 created_kb_ids 를 KBRAG 로 pgvector 색인.

        distill_result 예상 키 (best-effort):
            - "created_kb_ids": list[uuid]   — 새로 만든 KB row id 목록
            - "summaries": dict[uuid, str]    — KB id → 요약 텍스트 (없으면 KB 조회)
        """
        try:
            from sqlalchemy import select

            from ada.db.models import SelfLearningKB
            from ada.harness.rag import KBRAG

            kb_ids: list = list(distill_result.get("created_kb_ids") or [])
            if not kb_ids:
                return
            summaries: dict = dict(distill_result.get("summaries") or {})

            rag = KBRAG(self.session)
            for kb_id in kb_ids:
                summary = summaries.get(kb_id) or summaries.get(str(kb_id))
                if not summary:
                    try:
                        row = await self.session.scalar(  # type: ignore[attr-defined]
                            select(SelfLearningKB).where(SelfLearningKB.id == kb_id)
                        )
                        if row is not None and isinstance(row.payload, dict):
                            summary = (
                                row.payload.get("lesson_summary")
                                or row.payload.get("summary")
                                or row.payload.get("description")
                                or ""
                            )
                    except Exception:
                        summary = ""
                if not summary:
                    continue
                try:
                    await rag.index_lesson(kb_id, summary)
                except Exception as e:
                    self.logger.warning("kb_index_failed", kb_id=str(kb_id), error=str(e))
        except Exception as e:
            self.logger.warning("auto_index_lessons_failed", error=str(e))


# =============================================================================
# Day24 — Error 자동수정 ↔ SelfLearningKB 통합
# =============================================================================

# 자동수정 성공 사례를 SelfLearningKB.failure_lesson 으로 적재할 때 사용하는
# 표준 source 라벨. auto_handler / 팀원 수동 제출 / 정적 fixer 모두 동일 라벨.
_VALID_SOURCES = frozenset(
    {
        "ollama",  # Tier 2 로컬 LLM 성공
        "claude_cli",  # Tier 3 외부 Claude 성공
        "static",  # Tier 0 정적 Fixer 성공
        "team_manual",  # 팀원이 VPS /kb/conversation/error_fix 로 제출
        "approved_patch",  # 사람이 PendingPatch 를 승인한 사례
    }
)


def _summarize_fix(error_signature: str, fix_diff: str, explanation: str = "") -> str:
    """RAG 임베딩용 요약 텍스트 (≤1000자).

    error_signature + (있으면) explanation + diff 의 hunk 헤더만.
    diff 본문은 너무 길고 노이즈 많아서 헤더만 추출.
    """
    parts = [f"ERROR: {error_signature[:300]}"]
    if explanation:
        parts.append(f"FIX_EXPLANATION: {explanation[:300]}")
    # diff hunk 헤더만 추출
    hunk_headers = [ln for ln in (fix_diff or "").splitlines() if ln.startswith(("--- ", "+++ ", "@@"))][:10]
    if hunk_headers:
        parts.append("DIFF_TARGETS: " + " | ".join(hunk_headers))
    return "\n".join(parts)[:1000]


async def record_error_fix(
    session: AsyncSession,
    *,
    error_hash: str,
    error_signature: str,
    fix_diff: str,
    source: str,
    confidence: float,
    explanation: str = "",
    team_member: Optional[str] = None,
    project: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """SelfLearningKB.failure_lesson 에 수정 사례 적재 + RAG 색인.

    동작:
        1) hash=error_hash 로 ON CONFLICT DO UPDATE — 동일 에러 패턴 누적
           - success_count += 1
           - confidence = 가중평균 (기존 confidence * old_count + new) / (old_count+1)
           - payload.fix_diff / source / 메타데이터 갱신 (마지막 성공 케이스 우선)
        2) KBRAG.index_lesson 으로 lesson_embeddings 색인 (시맨틱 검색 가능)

    Returns:
        새로 만든 / 갱신된 SelfLearningKB.id (str). 실패 시 None.

    Notes:
        - source 는 _VALID_SOURCES 중 하나여야 함. 다른 값은 warning 후 진행.
        - 같은 error_hash 가 이미 다른 kb_type 으로 존재해도 hash 가 unique 라
          conflict 발생 → DO UPDATE 가 payload 와 confidence 만 갱신.
        - hash UNIQUE 제약은 self_learning_kb 스키마에 이미 존재 (models.py:300).
    """
    if source not in _VALID_SOURCES:
        _log.warning("record_error_fix_unknown_source", source=source)

    fix_diff = (fix_diff or "").strip()
    if not fix_diff:
        _log.warning("record_error_fix_empty_diff", error_hash=error_hash[:16])
        return None
    if not error_hash:
        _log.warning("record_error_fix_no_hash")
        return None

    payload = {
        "error_signature": (error_signature or "")[:2000],
        "fix_diff": fix_diff[:20000],  # 패치 크기 상한 (저장 보호)
        "source": source,
        "explanation": (explanation or "")[:1000],
        "team_member": team_member,
        "project": project,
    }
    if extra:
        # extra 는 호출자가 임의 메타데이터 (예: ollama_model, claude_model) 넣는 용도
        payload["extra"] = extra

    new_id = str(uuid.uuid4())
    summary = _summarize_fix(error_signature or "", fix_diff, explanation)

    try:
        # ON CONFLICT (hash) DO UPDATE — 누적 학습
        row = await session.execute(
            text(
                """
                INSERT INTO self_learning_kb
                    (id, kb_type, hash, payload, confidence, success_count,
                     created_at, updated_at)
                VALUES (
                    CAST(:id AS uuid),
                    'failure_lesson',
                    :hash,
                    CAST(:payload AS jsonb),
                    :confidence,
                    1,
                    NOW(),
                    NOW()
                )
                ON CONFLICT (hash) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    confidence = (
                        (self_learning_kb.confidence * self_learning_kb.success_count
                         + EXCLUDED.confidence) / (self_learning_kb.success_count + 1)
                    ),
                    success_count = self_learning_kb.success_count + 1,
                    updated_at = NOW()
                RETURNING id
                """
            ).bindparams(
                id=new_id,
                hash=error_hash,
                payload=json.dumps(payload, ensure_ascii=False),
                confidence=float(max(0.0, min(1.0, confidence))),
            )
        )
        fetched = row.fetchone()
        kb_id = str(fetched[0]) if fetched else None

        if not kb_id:
            _log.warning("record_error_fix_no_id", error_hash=error_hash[:16])
            return None

        # 임베딩 색인 (실패해도 KB row 는 살아있음)
        try:
            from ada.harness.rag import KBRAG

            rag = KBRAG(session)
            await rag.index_lesson(kb_id, summary)
        except Exception as e:  # noqa: BLE001
            _log.warning(
                "record_error_fix_index_failed",
                kb_id=kb_id,
                error=str(e),
            )

        _log.info(
            "error_fix_recorded",
            kb_id=kb_id,
            error_hash=error_hash[:16],
            source=source,
            confidence=confidence,
        )
        return kb_id

    except Exception as e:  # noqa: BLE001
        _log.warning(
            "record_error_fix_failed",
            error_hash=error_hash[:16],
            source=source,
            error=str(e),
        )
        return None


async def _audit_record_failure(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    error_hash: str,
    error_signature: str,
    source: str,
    reason: str,
) -> None:
    """검증 통과했지만 KB 적재 실패 시 FailureLog 로 audit 흔적 남김.

    BLOCKER-2 수정: fire-and-forget 경로에서 누수가 안 보이는 문제 해결.
    KB 적재 실패 = 다음 동일 에러가 Tier 1.5 에서 못 잡힘 = 비용 누수.
    FailureLog 에 기록해 admin/모니터가 retry 할 수 있게 함.

    실패해도 caller 에 예외 누설 금지 (이미 실패 상황이라 cascade 회피).
    """
    try:
        from ada.db.models import FailureLog

        async with session_factory() as session:
            fl = FailureLog(
                error_hash=error_hash,
                error_message=(error_signature or "")[:2000],
                stack_trace=f"[record_kb_failed source={source}] {reason}"[:5000],
                error_category="kb_record_failed",  # admin 대시보드 필터용
            )
            session.add(fl)
            await session.commit()
    except Exception as e:  # noqa: BLE001
        # audit 자체도 실패 → 마지막 보루: ERROR 로그 (모니터링 alarm 트리거)
        _log.error(
            "audit_record_failure_lost",
            error=str(e),
            kb_error_hash=error_hash[:16],
            kb_source=source,
            kb_reason=reason,
        )


async def validate_and_record(
    *,
    error_hash: str,
    error_signature: str,
    fix_diff: str,
    source: str,
    confidence: float,
    explanation: str = "",
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    skip_tests: bool = False,
) -> dict[str, Any]:
    """패치 diff 를 sandbox 검증(test_plan) → green 이면 record_error_fix.

    auto_handler 가 fire-and-forget (asyncio.create_task) 으로 호출하는 안전 래퍼.
    별도 DB 세션을 생성해서 호출자 트랜잭션과 격리.

    BLOCKER-2 누수 방지:
        - sandbox 통과 후 KB 적재 실패 = 다음 동일 에러가 Tier 1 SelfLearningKB
          시맨틱 매칭에서 누락 (Day25 — 이전 다이어그램의 Tier 1.5 와 동일 단계)
        - 따라서 적재 실패 시 FailureLog 에 audit 흔적 (error_category='kb_record_failed')
        - admin 대시보드에서 retry 가능

    Args:
        skip_tests: True 면 pytest 단계 스킵 (ruff 만). 디폴트는 False (test_plan 통과 게이트).

    Returns:
        {"recorded": bool, "kb_id": str|None, "reason": str}
    """
    from ada.error_handler.sandbox import PatchValidator

    sf = session_factory
    if sf is None:
        from ada.db.session import AsyncSessionLocal

        sf = AsyncSessionLocal

    # 1) sandbox 검증 (worktree + ruff + pytest)
    validator = PatchValidator(skip_tests=skip_tests)
    try:
        result = await validator.validate(fix_diff, timeout_sec=300)
    except Exception as e:  # noqa: BLE001
        _log.warning("validate_and_record_sandbox_failed", error=str(e), source=source)
        # sandbox 자체 실패는 적재 누수 아님 (패치가 검증 안 됐을 뿐)
        return {"recorded": False, "kb_id": None, "reason": f"sandbox_error: {e}"}

    if not result.passed:
        _log.info(
            "validate_and_record_failed",
            reason=result.reason,
            source=source,
            error_hash=error_hash[:16],
        )
        # 검증 실패는 정상 결과 (나쁜 패치 거절) — audit 불필요
        return {"recorded": False, "kb_id": None, "reason": result.reason or "unknown"}

    # 2) 검증 통과 → 새 세션으로 KB 적재
    try:
        async with sf() as session:
            kb_id = await record_error_fix(
                session,
                error_hash=error_hash,
                error_signature=error_signature,
                fix_diff=fix_diff,
                source=source,
                confidence=confidence,
                explanation=explanation,
                extra={
                    "tests_passed": getattr(result, "tests_passed", 0),
                    "tests_run": getattr(result, "tests_run", 0),
                },
            )
            await session.commit()

            if kb_id is None:
                # 검증은 통과했는데 적재 실패 = 진짜 누수. audit 필수.
                _log.error(
                    "validate_passed_but_record_failed",
                    source=source,
                    error_hash=error_hash[:16],
                )
                await _audit_record_failure(
                    sf,
                    error_hash=error_hash,
                    error_signature=error_signature,
                    source=source,
                    reason="record_returned_none_after_validation_pass",
                )
                return {"recorded": False, "kb_id": None, "reason": "record_failed_after_validation"}

            return {
                "recorded": True,
                "kb_id": kb_id,
                "reason": "validated",
            }
    except Exception as e:  # noqa: BLE001
        _log.error(
            "validate_and_record_db_failed",
            error=str(e),
            source=source,
            error_hash=error_hash[:16],
        )
        # 검증 통과 후 DB 예외 → audit
        await _audit_record_failure(
            sf,
            error_hash=error_hash,
            error_signature=error_signature,
            source=source,
            reason=f"db_exception: {type(e).__name__}: {str(e)[:300]}",
        )
        return {"recorded": False, "kb_id": None, "reason": f"db_error: {e}"}


# hash 헬퍼 — auto_handler.fingerprint() 와 동일 알고리즘이 필요한 외부 호출자용
def stable_hash_for_signature(signature: str, stack_top: str = "") -> str:
    """error_signature + stack_top 으로 SHA256 hash 생성.

    자동수정 fingerprint() 와 정확히 동일한 입력 포맷 (clean\n---\nstack_top)
    을 사용해, 호출자가 동일 에러로 처리될 hash 를 손쉽게 만들 수 있게 함.
    팀원이 수동 제출하는 error_fix 가 자동수정 KB 와 매칭되려면 같은 hash 가
    필요하기 때문에 helper 로 노출.
    """
    composite = f"{(signature or '')[:2000]}\n---\n{(stack_top or '')[:1000]}"
    return hashlib.sha256(composite.encode("utf-8")).hexdigest()

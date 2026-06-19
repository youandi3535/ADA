"""ada.error_handler.auto_handler — AutoErrorHandler 데몬 (Day16 + Day24).

3단계 폴백 체계 (Day24 — SelfLearningKB 통합):
  1순위  ErrorKB 해시 완전일치 매칭 (fingerprint SHA256, confidence ≥ 0.7)
  1.5순위  SelfLearningKB.failure_lesson 시맨틱 검색 (similarity ≥ 0.85
          + confidence ≥ 0.7). 팀원이 누적시킨 수정 사례 재사용 — LLM 비용 0.
  2순위  Ollama qwen2.5-coder (로컬 LLM, diff 생성 특화)
          → 성공 시 sandbox 검증 후 SelfLearningKB 적재 (fire-and-forget)
  3순위  Claude CLI Bridge (클라우드, 최후 수단)
          → 성공 시 sandbox 검증 후 SelfLearningKB 적재 (fire-and-forget)

흐름:
  1. failure_logs INSERT (또는 PubSub 이벤트) 감지
  2. error_kb 에서 동일 fingerprint 매칭 (Tier 1)
  3. 매칭 없으면 SelfLearningKB.failure_lesson 시맨틱 폴백 (Tier 1.5)
  4. 그래도 없으면 Ollama qwen2.5-coder 로 패치 생성 시도 (Tier 2)
  5. Ollama 실패 시 Claude CLI 사이드카에 패치 요청 (Tier 3)
  6. Tier 2/3 성공한 패치는 pending_patches 큐 적재 + 백그라운드 sandbox 검증
     → green 이면 SelfLearningKB 에 자동 누적 학습 (다음 동일 에러는 Tier 1.5 에서 처리)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.db.models import FailureLog, PendingPatch

log = get_logger("auto_handler")

# AutoErrorHandler 가 반환하는 "완전 해결" action 집합.
# agents/auto_error_handler.py 의 RESOLVED_ACTIONS 와 동기화 유지.
# Day25: 레거시 호환 별칭(auto_kb_match, patch_reused_approved) 도 포함하여
#        agents/auto_error_handler.py 의 RESOLVED_ACTIONS 와 정확히 동일.
RESOLVED_ACTIONS: frozenset[str] = frozenset(
    {
        # ── 자동 적용 완료 (코드 수정까지 완료) ──────────────────────────────
        "auto_kb_applied",  # Tier 0  static fixer diff 자동 적용
        "auto_kb_match",  # 레거시 호환 alias (예전 ErrorKB hash 매칭)
        "auto_self_learning_match",  # Tier 1  SelfLearningKB 시맨틱 매칭 + 패치 큐
        "patch_reused_approved",  # 재사용 패치 승인 (apply-worker, 레거시 호환)
        "auto_ollama_applied",  # Tier 2  Ollama diff 자동 적용
        "auto_claude_applied",  # Tier 3  Claude diff 자동 적용
    }
)


def fingerprint(error_message: str, stack: str = "") -> dict[str, str]:
    """오류 시그니처 생성. 동일 패턴은 동일 hash.

    ADR-006 Phase 1.5 — 정규화 정밀화:
      - 메모리 주소 (0x...) → <ADDR>
      - UUID → <UUID>
      - ISO 타임스탬프 → <TS>
      - traceback line 번호 ("line 42") → "line <N>"  (코드 위치만)
      - venv 경로 (site-packages) → <sp>
      - ❌ 기존 `\\d+` 전체 치환 제거 — Python 3.10 vs 3.11, HTTP 200 vs 500
        같이 의미 있는 숫자까지 동일화되던 버그.

    Stack 의 상위 6 줄 (= 3 traceback 프레임, 프레임당 2 줄) 만 hash 에 반영해
    deep stack 변동을 무시한다.
    """
    # --- error_message 정규화 ---
    # 순서가 중요: UUID 먼저 (8-4-4-4-12 형태) → 메모리주소 → 타임스탬프 → IP → 포트 → line 번호
    clean = error_message
    clean = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "<UUID>",
        clean,
    )
    clean = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", clean)
    clean = re.sub(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?",
        "<TS>",
        clean,
    )
    # IPv4 주소 (의미있는 숫자 - 호스트 식별자라 정규화)
    clean = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP>", clean)
    # ADR-006 Phase 2-A: redactor 가 partial mask (`192.x.x.x`) 로 남긴 형태도 통합
    clean = re.sub(r"\b\d{1,3}\.x\.x\.x\b", "<IP>", clean)
    # 포트 번호 (콜론 뒤 숫자)
    clean = re.sub(r":(?:\d{2,5})\b", ":<PORT>", clean)
    # Python traceback line 번호
    clean = re.sub(r"line \d+", "line <N>", clean)

    # --- stack 정규화 ---
    norm_stack = stack
    norm_stack = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "<UUID>",
        norm_stack,
    )
    norm_stack = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", norm_stack)
    norm_stack = re.sub(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "<IP>", norm_stack)
    norm_stack = re.sub(r"\b\d{1,3}\.x\.x\.x\b", "<IP>", norm_stack)
    norm_stack = re.sub(r"line \d+", "line <N>", norm_stack)
    norm_stack = re.sub(r"/[^/]+/site-packages/", "/<sp>/", norm_stack)
    # Windows 경로의 사용자명
    norm_stack = re.sub(r"[CD]:\\\\Users\\\\[^\\\\]+\\\\", r"C:\\\\Users\\\\<USER>\\\\", norm_stack)

    # stack 상위 6줄 = 3 traceback 프레임 (Python 1 frame = "File ..." + 코드 라인 2줄)
    stack_top = "\n".join(norm_stack.split("\n")[:6])
    composite = f"{clean}\n---\n{stack_top}"

    h = hashlib.sha256(composite.encode("utf-8")).hexdigest()
    return {
        "hash": h,
        "signature": clean[:500],
        "stack_top": stack_top[:1000],
    }


# =============================================================================
# Ollama qwen2.5-coder 패치 생성 (2순위)
# =============================================================================

_CODER_SYSTEM_PROMPT = (
    "You are a Python debugging expert. "
    "Analyze the given error and stack trace, then return a minimal fix as valid JSON.\n"
    "Required JSON keys:\n"
    '  "diff"       : unified diff string (--- a/file ... +++ b/file ... format)\n'
    '  "test_plan"  : one-line test verification string\n'
    '  "confidence" : float 0.0~1.0 (how certain you are the fix is correct)\n'
    "Return ONLY the JSON object, no other text."
)


def _ollama_coder_fix_sync(error_signature: str, stack: str) -> dict[str, Any]:
    """Ollama qwen2.5-coder 동기 호출 → {diff, test_plan, confidence}.

    Day25 정비 — 네트워크 에러 정밀 분리:
        - URLError (connection refused / DNS) = 환경 미설정.
          ``_offline=True`` graceful 반환 → 외부 CircuitBreaker 카운트 X.
        - HTTPError (4xx/5xx) = 서버 응답 + 진짜 장애. re-raise 해서
          외부 브레이커가 카운트하도록 함.
        - TimeoutError / socket.timeout = URLError 자식 아님 → 처리 안 함
          → 외부로 전파 → 브레이커 카운트 (의도된 동작).
    """
    base_url = getattr(settings, "ollama_base_url", "http://localhost:11434").rstrip("/")
    model = getattr(settings, "ollama_coder_model", "qwen2.5-coder:7b")

    user_prompt = (
        "다음 Python 오류를 분석해 최소 변경 unified diff 와 test_plan 을 JSON 으로 반환하세요.\n\n"
        f"## error\n{error_signature}\n\n"
        f"## stack\n{stack[:2000]}"
    )

    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _CODER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",  # Ollama JSON 모드 강제
            "options": {
                "num_predict": 512,  # 512 / 7t/s = ~73s, timeout 120s 이내
                "temperature": 0.1,  # 코드 수정은 낮은 temperature (사실적)
                "top_p": 0.9,
                "num_gpu": 0,  # GTX 1060 3GB < 모델 4.7GB → PCIe 병목 회피
                "num_thread": 14,  # Ryzen 7 3800XT 16T − 2 (OS/Docker 여유)
            },
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{base_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError:
        # HTTP 4xx/5xx — 서버 응답 받았는데 에러 = 진짜 서버 장애.
        # 외부 브레이커가 카운트하도록 re-raise.
        # HTTPError 는 URLError 의 자식이라 반드시 URLError 보다 위에 위치.
        raise
    except urllib.error.URLError as e:
        # 연결 자체 실패 (DNS / connection refused / 서버 다운) = 환경 미설정.
        # 브레이커 카운트 X, Tier 3 폴백 신호만.
        return {
            "diff": "",
            "test_plan": "(ollama_offline)",
            "confidence": 0.0,
            "_offline": True,
            "_reason": str(e),
        }

    content = data.get("message", {}).get("content", "") or ""

    # JSON 파싱 시도
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # JSON 파싱 실패 → diff 텍스트로 처리, confidence 낮게
        result = {"diff": content[:2000], "test_plan": "", "confidence": 0.25}

    return result


async def _ollama_coder_fix(error_signature: str, stack: str) -> dict[str, Any]:
    """Ollama coder 비동기 래퍼."""
    return await asyncio.to_thread(_ollama_coder_fix_sync, error_signature, stack)


# =============================================================================
# Day24 — sandbox 검증 + SelfLearningKB 적재 fire-and-forget 헬퍼
# =============================================================================


def _schedule_validate_and_record(
    *,
    error_hash: str,
    error_signature: str,
    fix_diff: str,
    source: str,
    confidence: float,
    explanation: str = "",
) -> None:
    """Tier 2/3 패치 success 직후 호출. 백그라운드 task 등록 (블로킹 X).

    sandbox 검증 → green 이면 SelfLearningKB.failure_lesson 누적.
    이벤트 루프 미가용 / 검증 실패 / DB 오류 등 어떤 경우도 호출자에
    예외 누설 금지.

    BLOCKER-2 누수 가시화:
        - validate_and_record 내부에서 검증 통과 후 적재 실패는 FailureLog 로 audit.
        - 본 래퍼 자체의 task 실패 (이벤트루프 / 스레드) 는 ERROR 로그.
          INFO/WARNING 이 아닌 ERROR 라 모니터링 알람이 켜진다.

    구현 메모:
        - asyncio.get_running_loop() 가 RuntimeError 면 (동기 컨텍스트 호출)
          별도 thread + new loop 로 실행. 데몬·테스트 양쪽 안전.
    """
    try:
        from agents.self_learning import validate_and_record
    except Exception as e:  # noqa: BLE001
        # import 실패 = 코드 망가짐 = ERROR + FailureLog audit
        # 본 함수는 KB 적재(post-patch) 스케줄러이지 Tier 1/1.5 lookup 이 아니므로,
        # 여기서 return 해도 호출자의 패치 적용 흐름은 영향 받지 않는다.
        # 다만 적재 누수는 admin 이 추후 재시도해야 하므로 FailureLog 에 기록.
        log.error(
            "schedule_record_import_failed",
            error=str(e),
            error_hash=error_hash[:16],
            source=source,
        )
        try:
            import asyncio as _aio

            from ada.db.models import FailureLog  # noqa: WPS433
            from ada.db.session import AsyncSessionLocal  # noqa: WPS433

            # Python 은 except 절 종료 시 e 를 삭제하므로 클로저 캡처 전에 보존.
            _err_msg = f"validate_and_record import failed: {e}"[:2000]

            async def _audit() -> None:
                try:
                    async with AsyncSessionLocal() as sess:
                        sess.add(
                            FailureLog(
                                error_hash=error_hash,
                                error_message=_err_msg,
                                stack_trace=f"source={source}; cannot schedule KB record"[:5000],
                                error_category="kb_record_failed",
                            )
                        )
                        await sess.commit()
                except Exception:  # noqa: BLE001
                    pass

            try:
                _aio.get_running_loop().create_task(_audit())
            except RuntimeError:
                _aio.run(_audit())
        except Exception:  # noqa: BLE001
            pass
        return

    async def _wrapped() -> None:
        # task 안에서 어떤 예외든 잡아서 ERROR 로 보고 (Tier 2/3 누수 가시화)
        try:
            res = await validate_and_record(
                error_hash=error_hash,
                error_signature=error_signature,
                fix_diff=fix_diff,
                source=source,
                confidence=confidence,
                explanation=explanation,
                # sandbox pytest 는 무거우므로 hot path 는 skip_tests=True (ruff + static_check).
                # 완전 pytest 검증은 별도 야간 잡에서 처리 (TODO Day25 이후).
                skip_tests=True,
            )
            if not res.get("recorded"):
                # 검증 실패 (정상)는 INFO, 검증 통과 후 적재 실패는 audit 가 처리.
                # 여기서는 결과만 한번 INFO 로 기록 (모니터 가시성).
                log.info(
                    "schedule_record_outcome",
                    recorded=False,
                    source=source,
                    error_hash=error_hash[:16],
                    reason=res.get("reason"),
                )
        except Exception as e:  # noqa: BLE001
            log.error(
                "schedule_record_task_crashed",
                error=str(e),
                error_type=type(e).__name__,
                error_hash=error_hash[:16],
                source=source,
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_wrapped())
    except RuntimeError:
        # 동기 호출 컨텍스트 → 별도 스레드에서 새 루프 돌림
        import threading

        def _runner() -> None:
            try:
                asyncio.run(_wrapped())
            except Exception as e:  # noqa: BLE001
                log.error(
                    "schedule_record_thread_crashed",
                    error=str(e),
                    error_hash=error_hash[:16],
                    source=source,
                )

        threading.Thread(target=_runner, daemon=True, name="ada-kb-recorder").start()


# =============================================================================
# AutoErrorHandler
# =============================================================================


class AutoErrorHandler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def handle(self, log_row: FailureLog) -> dict[str, Any]:
        # ── ADR-006 Phase 2-A: PII / secret 마스킹 ──────────────────────────
        from ada.error_handler.redactor import redact

        raw_msg = log_row.error_message or ""
        raw_stack = log_row.stack_trace or ""
        clean_msg, msg_pii = redact(raw_msg)
        clean_stack, stack_pii = redact(raw_stack)
        if msg_pii or stack_pii:
            log.info(
                "pii_redacted_before_handler",
                msg_types=msg_pii,
                stack_types=stack_pii,
            )
            log_row.error_message = clean_msg[:2000]
            log_row.stack_trace = clean_stack[:5000]

        fp = fingerprint(clean_msg, clean_stack)

        # ── ADR-006 Phase 2-B: 5종 분류 + 단축경로 ─────────────────────────
        # TRANSIENT / CONFIG / DATA / USER_INPUT 은 LLM 호출 skip.
        # CODE_BUG / UNKNOWN 만 Tier 0~3 폴백 진행.
        from ada.error_handler.classifier import classify_with_reason, get_strategy, should_skip_llm

        cls, reason = classify_with_reason(clean_msg, clean_stack)
        strategy = get_strategy(cls)
        log.info(
            "error_classified",
            classification=cls.value,
            strategy=strategy.value,
            reason=reason,
            fingerprint=fp["hash"][:16],
        )
        # ★ 무한 재처리 방지(HJ 2026-06-19): 분류 즉시 classified_as 를 세운다.
        #   데몬 쿼리가 classified_as IS NULL 인 row 만 잡으므로, 한 번 시도(Tier 0~3)한 오류는
        #   다음 폴에서 다시 안 잡힌다. (기존엔 마킹이 없어 같은 오류를 5초마다 영원히 재시도했다.)
        log_row.classified_as = cls.value

        if should_skip_llm(cls):
            # LLM 호출 없이 즉시 분류 결과 반환.
            # 그래프 / Agent 가 이 action 보고 적절히 처리:
            #   transient → retry_with_backoff (supervisor 가 재시도)
            #   config    → human_only         (error_recovery 가 사용자 안내)
            #   data      → user_message       (error_recovery 가 데이터 수정 요청)
            #   user_input→ user_message
            log_row.error_category = cls.value
            await self.session.flush()
            return {
                "action": f"classified_{cls.value}",  # 예: classified_transient
                "classification": cls.value,
                "strategy": strategy.value,
                "reason": reason,
                "llm_skipped": True,
            }

        # ── Tier 0: 정적 결정론적 Fixer (LLM 비용 0, < 100ms) ──────────────
        try:
            from ada.error_handler.static_fixers import try_static_fix

            static = try_static_fix(
                log_row.error_message or "",
                log_row.stack_trace or "",
            )
            if static and static.get("diff"):
                from ada.error_handler.patcher import apply_patch
                from ada.error_handler.sandbox import PatchValidator

                _sv = PatchValidator(skip_tests=True)
                _sr = await _sv.validate(static["diff"])
                if _sr.passed:
                    _ar = await apply_patch(
                        static["diff"],
                        commit_msg=f"auto-fix/tier-0(static/{static['fixer']})",
                    )
                    self.session.add(
                        PendingPatch(
                            error_kb_id=None,
                            patch_diff=static["diff"],
                            test_plan=f"[static:{static['fixer']}] {static['test_plan']} applied={_ar['applied']}",
                            confidence=static["confidence"],
                            review_status="auto_applied" if _ar["applied"] else "apply_failed",
                        )
                    )
                    await self.session.flush()
                    if _ar["applied"]:
                        log.info("auto_static_applied", fixer=static["fixer"], git_commit=_ar.get("git_commit"))
                        return {
                            "action": "auto_kb_applied",
                            "fixer": static["fixer"],
                            "patch_chars": len(static["diff"]),
                            "git_commit": _ar.get("git_commit"),
                            "source": "static",
                        }
                # 검증 실패 또는 적용 실패 → Tier 1 으로 계속
                log.info("static_fixer_fallthrough", fixer=static["fixer"])
        except Exception as e:  # noqa: BLE001
            log.warning("static_fixer_failed", error=str(e))

        # ── Tier 1: SelfLearningKB 시맨틱 검색 + 패치 큐 ────────────────────
        # 팀원·Ollama·Claude 가 누적한 수정 사례를 pgvector 코사인 유사도로 검색.
        # similarity ≥ 0.85 + confidence ≥ 0.7 + 저장된 diff 존재 시:
        #   static_check(scope·format 검증) → 통과하면 PendingPatch 큐 적재.
        # apply_patch 는 백그라운드 apply-worker 가 처리. LLM 호출 없음, 비용 0.
        # source 신뢰도에 따라 review_status 결정:
        #   ollama/claude_cli/claude_code/static/auto → "approved"
        #     (모두 sandbox 검증 통과한 자동 패치 — 바로 적용 가능)
        #   team_manual / 미지 / 사용자 입력 → "pending"
        # Day25: Tier 3 가 source="claude_cli" 로 적재하는데 기존 집합엔 없어
        #        다른 인스턴스에서 재사용시 trusted 인식 안 되던 문제 해결.
        _TRUSTED_SOURCES = frozenset(
            {
                "ollama",
                "claude_cli",  # Tier 3 source 값과 일치
                "claude_code",  # Tier 3 full-access 별칭 (호환)
                "claude",  # legacy 별칭 (호환)
                "static",  # Tier 0 별칭 (호환)
                "auto",  # 일반 별칭 (호환)
            }
        )
        try:
            from ada.harness.rag import KBRAG

            rag = KBRAG(self.session)
            lessons = await rag.search_lessons(fp["signature"], top_k=3)
            if lessons:
                top = lessons[0]
                similarity = float(top.get("similarity") or 0.0)
                kb_confidence = float(top.get("confidence") or 0.0)
                payload = top.get("payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception as _parse_e:  # noqa: BLE001
                        log.warning(
                            "tier_1_5_payload_parse_failed",
                            kb_id=str(top.get("kb_id")),
                            error=str(_parse_e),
                            payload_preview=str(top.get("payload"))[:200],
                        )
                        payload = {}
                stored_diff = (payload.get("fix_diff") or "").strip() if isinstance(payload, dict) else ""
                src = payload.get("source") if isinstance(payload, dict) else None

                if similarity >= 0.85 and kb_confidence >= 0.7 and stored_diff:
                    from ada.error_handler.sandbox import PatchValidator

                    _validator = PatchValidator(skip_tests=True)
                    val_result = _validator.static_check(stored_diff)
                    if val_result.passed:
                        is_trusted = src in _TRUSTED_SOURCES
                        review_status = "approved" if is_trusted else "pending"
                        self.session.add(
                            PendingPatch(
                                error_kb_id=None,
                                patch_diff=stored_diff,
                                test_plan=(
                                    f"[tier-1/self_learning_kb:{src or 'unknown'}] "
                                    f"kb_id={top.get('kb_id')} sim={similarity:.3f}"
                                ),
                                confidence=min(0.95, kb_confidence),
                                review_status=review_status,
                            )
                        )
                        await self.session.flush()

                        log.info(
                            "auto_self_learning_match",
                            kb_id=str(top.get("kb_id")),
                            similarity=similarity,
                            source=src,
                            trusted=is_trusted,
                            review_status=review_status,
                        )
                        return {
                            "action": "auto_self_learning_match",
                            "kb_id": str(top.get("kb_id")),
                            "similarity": similarity,
                            "patch_chars": len(stored_diff),
                            "trusted_source": is_trusted,
                            "review_status": review_status,
                        }
                    else:
                        log.info(
                            "tier1_rejected_scope",
                            kb_id=str(top.get("kb_id")),
                            reason=val_result.reason,
                        )
        except Exception as e:  # noqa: BLE001
            log.warning("tier1_lookup_failed", error=str(e))

        # ── Tier 2: Ollama qwen2.5-coder ───────────────────────────────────
        # ADR-006 Phase 2-A: fp["signature"] 와 clean_stack 은 이미 redacted.
        # ADR-006 Phase 2-C: circuit breaker 로 보호. 5분 OPEN 후 자동 HALF_OPEN.
        from ada.error_handler.circuit_breaker import (
            CircuitBreakerOpenError,
            get_breaker,
        )

        _ollama_cb = get_breaker("ollama", failure_threshold=3, recovery_timeout=300)
        try:
            patch = await _ollama_cb.call(_ollama_coder_fix, fp["signature"], clean_stack)

            # _offline (URLError) — 환경 미설정, 브레이커 카운트 X, Tier 3 폴백
            if patch.get("_offline"):
                log.warning("ollama_coder_offline", reason=patch.get("_reason"))
                diff = ""
                confidence = 0.0
            else:
                diff = (patch.get("diff") or "").strip()
                confidence = float(patch.get("confidence", 0.0))

            if diff and confidence >= 0.4:
                # sandbox 전체 검증 (worktree + ruff, skip_tests=True で fast path)
                from ada.error_handler.sandbox import PatchValidator

                _validator = PatchValidator(skip_tests=True)
                val_result = await _validator.validate(diff)
                if not val_result.passed:
                    log.warning(
                        "ollama_patch_rejected",
                        reason=val_result.reason,
                        scope_violations=val_result.scope_violations,
                        forbidden=val_result.forbidden_violations,
                    )
                    # 검증 실패 → Claude 폴백
                else:
                    # ── 자동 적용 ──────────────────────────────────────────
                    from ada.error_handler.patcher import apply_patch

                    model_name = getattr(settings, "ollama_coder_model", "qwen2.5-coder:7b")
                    apply_result = await apply_patch(
                        diff,
                        commit_msg=f"auto-fix/tier-2(ollama/{model_name}): confidence={confidence:.2f}",
                    )
                    self.session.add(
                        PendingPatch(
                            error_kb_id=None,
                            patch_diff=diff,
                            test_plan=f"[ollama:{model_name}] {patch.get('test_plan') or ''} "
                            f"applied={apply_result['applied']}",
                            confidence=confidence,
                            review_status="auto_applied" if apply_result["applied"] else "apply_failed",
                        )
                    )
                    await self.session.flush()

                    if apply_result["applied"]:
                        log.info(
                            "auto_ollama_applied",
                            chars=len(diff),
                            confidence=confidence,
                            git_commit=apply_result.get("git_commit"),
                            modules_reloaded=apply_result.get("modules_reloaded"),
                        )
                        # KB 누적 학습 (fire-and-forget)
                        _schedule_validate_and_record(
                            error_hash=fp["hash"],
                            error_signature=fp["signature"],
                            fix_diff=diff,
                            source="ollama",
                            confidence=confidence,
                            explanation=patch.get("test_plan") or "",
                        )
                        return {
                            "action": "auto_ollama_applied",
                            "patch_chars": len(diff),
                            "git_commit": apply_result.get("git_commit"),
                            "modules_reloaded": apply_result.get("modules_reloaded"),
                        }
                    # 적용 실패 → Claude 폴백
                    log.warning("ollama_apply_failed", reason=apply_result.get("reason"))

            # diff 없거나 신뢰도 낮음 → Claude CLI 로 계속
            log.warning("ollama_low_confidence", confidence=confidence, has_diff=bool(diff))

        except CircuitBreakerOpenError as e:
            log.warning("ollama_circuit_open", retry_after_sec=e.retry_after_sec)
            # 회로 OPEN → Claude CLI 로 폴백 (아래 Tier 3 진행)
        except urllib.error.URLError as e:
            log.warning("ollama_coder_offline", error=str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("ollama_coder_failed", error=str(e))

        # ── Tier 3: Claude CLI Bridge ───────────────────────────────────────
        # ADR-006 Phase 2-D: Claude CLI 호출 전 일일 예산 체크
        # (Ollama 는 무료라 체크 skip)
        from ada.error_handler.budget import get_budget_manager

        budget = get_budget_manager()
        if await budget.is_exceeded():
            spend = await budget.get_today_spend()
            log.warning("claude_budget_exceeded", today_spend_usd=round(spend, 4))
            return {
                "action": "budget_exceeded",
                "today_spend_usd": round(spend, 4),
                "remaining_usd": round(await budget.remaining_budget(), 4),
            }

        # ── Tier 3: Claude CLI ───────────────────────────────────────────────
        # Full-Access 모드 우선 (worktree 격리 + 전체 도구 + 20턴)
        # 실패 시 기존 제한 모드(Read/Grep/Glob 3턴) 로 폴백
        _claude_cb = get_breaker("claude_cli", failure_threshold=3, recovery_timeout=180)
        try:
            from ada.error_handler.claude_cli_bridge import ClaudeCLIBridge

            bridge = ClaudeCLIBridge()

            # ── 3-A: Claude Code 전체 도구 모드 (우선 시도) ─────────────────
            # worktree 격리 환경에서 Read/Write/Edit/Bash/Grep/Glob 전부 허용.
            # Claude 가 직접 파일을 탐색·수정·검증 (최대 20턴).
            patch = await _claude_cb.call(
                bridge.request_fix_direct,
                error_signature=fp["signature"],
                stack=clean_stack,
            )

            # full-access 가 diff 를 못 만들었으면 제한 모드로 폴백
            if not (patch.get("diff") or "").strip():
                log.info("claude_full_no_diff_fallback_restricted")
                patch = await _claude_cb.call(
                    bridge.request_patch,
                    error_signature=fp["signature"],
                    stack=clean_stack,
                )

            # 토큰 비용 누적 — Day25 부터 두 모드 모두 토큰 반환
            # (claude_cli_bridge 가 --output-format json 의 usage 에서 추출).
            input_tokens = int(patch.get("input_tokens", 0) or 0)
            output_tokens = int(patch.get("output_tokens", 0) or 0)
            if input_tokens or output_tokens:
                # patch["model"] 이 빈 문자열일 수 있으므로 truthy 폴백.
                model_name = patch.get("model") or "claude-sonnet-4-6"
                await budget.track_call(
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

            # sandbox 전체 검증 (worktree + ruff, skip_tests=True で fast path)
            from ada.error_handler.sandbox import PatchValidator

            diff_str = patch.get("diff") or ""
            _validator = PatchValidator(skip_tests=True)
            val_result = await _validator.validate(diff_str)
            if not val_result.passed:
                log.warning(
                    "claude_patch_rejected",
                    reason=val_result.reason,
                    scope_violations=val_result.scope_violations,
                    forbidden=val_result.forbidden_violations,
                )
                return {
                    "action": "patch_rejected_scope",
                    "reason": val_result.reason,
                    "violations": val_result.scope_violations + val_result.forbidden_violations,
                }

            # ── 자동 적용 ──────────────────────────────────────────────────
            from ada.error_handler.patcher import apply_patch

            claude_confidence = float(patch.get("confidence", 0.4) or 0.4)
            apply_result = await apply_patch(
                diff_str,
                commit_msg=f"auto-fix/tier-3(claude): confidence={claude_confidence:.2f}",
            )
            self.session.add(
                PendingPatch(
                    error_kb_id=None,
                    patch_diff=diff_str,
                    test_plan=f"[claude_cli] {patch.get('test_plan') or ''} applied={apply_result['applied']}",
                    confidence=claude_confidence,
                    review_status="auto_applied" if apply_result["applied"] else "apply_failed",
                )
            )
            await self.session.flush()

            if apply_result["applied"]:
                log.info(
                    "auto_claude_applied",
                    chars=len(diff_str),
                    git_commit=apply_result.get("git_commit"),
                    modules_reloaded=apply_result.get("modules_reloaded"),
                )
                # KB 누적 학습 (fire-and-forget)
                _schedule_validate_and_record(
                    error_hash=fp["hash"],
                    error_signature=fp["signature"],
                    fix_diff=diff_str,
                    source="claude_cli",
                    confidence=claude_confidence,
                    explanation=patch.get("test_plan") or "",
                )
                return {
                    "action": "auto_claude_applied",
                    "patch_chars": len(diff_str),
                    "git_commit": apply_result.get("git_commit"),
                    "modules_reloaded": apply_result.get("modules_reloaded"),
                }

            log.warning("claude_apply_failed", reason=apply_result.get("reason"))
            return {"action": "noop", "error": f"apply_failed: {apply_result.get('reason')}"}
        except CircuitBreakerOpenError as e:
            log.warning("claude_circuit_open", retry_after_sec=e.retry_after_sec)
            return {"action": "circuit_open", "breaker": "claude_cli", "retry_after_sec": e.retry_after_sec}
        except Exception as e:
            log.warning("auto_handler_failed", error=str(e))
            return {"action": "noop", "error": str(e)}


# =============================================================================
# 그래프 외부 컨텍스트용 독립 진입점
# =============================================================================


async def capture_and_handle(
    error_message: str,
    stack_trace: str = "",
    job_id: str | None = None,
    source: str = "runner",
) -> dict[str, Any]:
    """LangGraph 그래프 밖(runner, API 미들웨어, 업로드 레이어)에서 발생한
    예외를 잡아 AutoErrorHandler Tier 0~3 폴백으로 처리한다.

    - 자체 AsyncSession 을 생성하므로 호출자 트랜잭션과 완전히 독립.
    - 내부 오류는 절대 호출자에 누설하지 않는다 (항상 dict 반환).
    - source 는 FailureLog.error_category 에 기록된다:
        "runner"  — Celery 워커 레벨 크래시
        "resume"  — 게이트 재개 레벨 크래시
        "api"     — FastAPI 미처리 예외
    """
    import uuid as _uuid

    from ada.db.models import FailureLog
    from ada.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as session:
            from ada.error_handler.redactor import redact

            clean_msg, msg_pii = redact(error_message)
            clean_stack, stack_pii = redact(stack_trace)
            if msg_pii or stack_pii:
                log.info(
                    "pii_redacted_capture",
                    msg_types=msg_pii,
                    stack_types=stack_pii,
                    source=source,
                )

            fp = fingerprint(clean_msg, clean_stack)

            job_id_val: _uuid.UUID | None = None
            if job_id:
                try:
                    job_id_val = _uuid.UUID(job_id)
                except (ValueError, TypeError):
                    pass

            # R-103: 원본(미마스킹) 에러는 raw_error_encrypted 에 암호화 저장.
            # 평문 컬럼은 redactor 통과한 clean_msg/clean_stack 만 들어간다.
            from ada.security.raw_error_crypto import encrypt_raw_error  # noqa: WPS433

            raw_blob = encrypt_raw_error(f"{error_message}\n---STACK---\n{stack_trace or ''}")

            fl = FailureLog(
                job_id=job_id_val,
                error_hash=fp["hash"],
                error_message=clean_msg[:2000],
                stack_trace=clean_stack[:5000],
                error_category=source,
                raw_error_encrypted=raw_blob,
            )
            session.add(fl)
            await session.flush()

            outcome = await AutoErrorHandler(session).handle(fl)
            await session.commit()

            log.info(
                "capture_and_handle_outcome",
                action=outcome.get("action"),
                source=source,
                fingerprint=fp["hash"][:16],
            )
            return outcome

    except Exception as e:  # noqa: BLE001
        log.error("capture_and_handle_failed", error=str(e), source=source)
        return {"action": "noop", "error": str(e)}

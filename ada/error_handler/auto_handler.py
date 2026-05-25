"""ada.error_handler.auto_handler — AutoErrorHandler 데몬 (Day16).

3단계 폴백 체계:
  1순위  ErrorKB 자동 매칭 (fingerprint SHA256, confidence ≥ 0.7)
  2순위  Ollama qwen2.5-coder (로컬 LLM, diff 생성 특화)
  3순위  Claude CLI Bridge (클라우드, 최후 수단)

흐름:
  1. failure_logs INSERT (또는 PubSub 이벤트) 감지
  2. error_kb 에서 동일 fingerprint 매칭
  3. 매칭이 있으면 자동 처리 (auto_handled_by_kb=True)
  4. 없으면 Ollama qwen2.5-coder 로 패치 생성 시도
  5. Ollama 실패 시 Claude CLI 사이드카에 패치 요청 → pending_patches 큐 적재
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.db.models import ErrorKB, FailureLog, PendingPatch

log = get_logger("auto_handler")


def fingerprint(error_message: str, stack: str = "") -> dict[str, str]:
    """오류 시그니처 생성. 동일 패턴은 동일 hash."""
    # 시간/메모리주소/UUID 등은 제거
    clean = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", error_message)
    clean = re.sub(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        "<UUID>",
        clean,
    )
    clean = re.sub(r"\d+", "<N>", clean)
    h = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    return {"hash": h, "signature": clean[:500]}


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
    """Ollama qwen2.5-coder 동기 호출 → {diff, test_plan, confidence}."""
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

    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())

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
# AutoErrorHandler
# =============================================================================


class AutoErrorHandler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def handle(self, log_row: FailureLog) -> dict[str, Any]:
        fp = fingerprint(log_row.error_message or "", log_row.stack_trace or "")

        # ── Tier 0: 정적 결정론적 Fixer (LLM 비용 0, < 100ms) ──────────────
        try:
            from ada.error_handler.static_fixers import try_static_fix

            static = try_static_fix(
                log_row.error_message or "",
                log_row.stack_trace or "",
            )
            if static and static.get("diff"):
                self.session.add(
                    PendingPatch(
                        error_kb_id=None,
                        patch_diff=static["diff"],
                        test_plan=f"[static:{static['fixer']}] {static['test_plan']}",
                        confidence=static["confidence"],
                        review_status="pending",
                    )
                )
                await self.session.flush()
                log.info(
                    "static_patch_queued",
                    fixer=static["fixer"],
                    confidence=static["confidence"],
                    chars=len(static["diff"]),
                )
                return {
                    "action": "patch_queued_static",
                    "fixer": static["fixer"],
                    "patch_chars": len(static["diff"]),
                }
        except Exception as e:  # noqa: BLE001
            log.warning("static_fixer_failed", error=str(e))

        # ── Tier 1: ErrorKB 자동 매칭 ──────────────────────────────────────
        kb = await self.session.scalar(select(ErrorKB).where(ErrorKB.error_hash == fp["hash"]))
        if kb and (kb.confidence or 0.0) >= 0.7:
            log_row.auto_handled_by_kb = True
            log_row.error_kb_id = kb.id
            kb.success_count = (kb.success_count or 0) + 1
            await self.session.flush()
            log.info("auto_kb_match", kb_id=str(kb.id), confidence=kb.confidence)
            return {"action": "auto_kb_match", "kb_id": str(kb.id)}

        # ── Tier 1.5: 승인된 패치 재사용 (LLM 비용 0) ─────────────────────
        if kb:
            try:
                approved = await self.session.scalar(
                    select(PendingPatch)
                    .where(PendingPatch.error_kb_id == kb.id)
                    .where(PendingPatch.review_status == "approved")
                    .order_by(PendingPatch.created_at.desc())
                )
                if approved and (approved.confidence or 0.0) >= 0.65:
                    kb.success_count = (kb.success_count or 0) + 1
                    await self.session.flush()
                    log.info(
                        "approved_patch_reused",
                        kb_id=str(kb.id),
                        patch_id=str(approved.id),
                        confidence=approved.confidence,
                    )
                    return {
                        "action": "patch_reused_approved",
                        "patch_id": str(approved.id),
                        "patch_chars": len(approved.patch_diff or ""),
                    }
            except Exception as e:  # noqa: BLE001
                log.warning("approved_patch_lookup_failed", error=str(e))

        # ── Tier 2: Ollama qwen2.5-coder ───────────────────────────────────
        try:
            patch = await _ollama_coder_fix(fp["signature"], log_row.stack_trace or "")
            diff = (patch.get("diff") or "").strip()
            confidence = float(patch.get("confidence", 0.0))

            if diff and confidence >= 0.4:
                # test_plan 앞에 출처 표시 (DB 스키마 변경 없이 소스 기록)
                test_plan = f"[ollama:{getattr(settings, 'ollama_coder_model', 'qwen2.5-coder:7b')}] " + (
                    patch.get("test_plan") or ""
                )
                self.session.add(
                    PendingPatch(
                        error_kb_id=(kb.id if kb else None),
                        patch_diff=diff,
                        test_plan=test_plan,
                        confidence=confidence,
                        review_status="pending",
                    )
                )
                await self.session.flush()
                log.info("ollama_patch_queued", chars=len(diff), confidence=confidence)
                return {"action": "patch_queued_ollama", "patch_chars": len(diff)}

            # diff 없거나 신뢰도 낮음 → Claude CLI 로 계속
            log.warning("ollama_low_confidence", confidence=confidence, has_diff=bool(diff))

        except urllib.error.URLError as e:
            log.warning("ollama_coder_offline", error=str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("ollama_coder_failed", error=str(e))

        # ── Tier 3: Claude CLI Bridge ───────────────────────────────────────
        try:
            from ada.error_handler.claude_cli_bridge import ClaudeCLIBridge

            bridge = ClaudeCLIBridge()
            patch = await bridge.request_patch(
                error_signature=fp["signature"],
                stack=log_row.stack_trace or "",
            )
            self.session.add(
                PendingPatch(
                    error_kb_id=(kb.id if kb else None),
                    patch_diff=patch.get("diff"),
                    test_plan="[claude_cli] " + (patch.get("test_plan") or ""),
                    confidence=patch.get("confidence", 0.4),
                    review_status="pending",
                )
            )
            await self.session.flush()
            log.info("claude_patch_queued", chars=len(patch.get("diff") or ""))
            return {"action": "patch_queued", "patch_chars": len(patch.get("diff") or "")}
        except Exception as e:
            log.warning("auto_handler_failed", error=str(e))
            return {"action": "noop", "error": str(e)}

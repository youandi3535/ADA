"""ada.error_handler.fixer_promoter — 반복 오류 패턴 → Tier 0 자동 fixer 승격.

SelfLearningKB.failure_lesson 에 성공 사례가 PROMOTE_THRESHOLD 이상 쌓이면
generated_fixers.py 에 새 fixer 함수를 자동 생성·추가하거나
기존 fixer 에 elif 분기를 추가해 점진적으로 고도화한다.

흐름:
    1. SelfLearningKB 에서 success_count >= PROMOTE_THRESHOLD 인 failure_lesson 조회
    2. 오류 타입별 그룹핑 (AttributeError / ImportError / TypeError 등)
    3. generated_fixers.py 에 같은 타입 fixer 이미 존재?
       YES → Claude 로 elif 분기 추가 (update)
       NO  → Claude 로 새 fixer 함수 생성 (add)
    4. apply_patch() 로 generated_fixers.py 에 즉시 반영
    5. Python 모듈 hot-reload → 다음 오류부터 즉시 Tier 0 처리
"""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path
from typing import Any

from ada.core.logger import get_logger

log = get_logger("fixer_promoter")

PROMOTE_THRESHOLD = 3  # N 회 이상 성공 시 Tier 0 승격
MAX_PATTERNS_PER_FIXER = 10  # fixer 하나당 최대 변형 수
GENERATED_FILE = Path(__file__).parent / "generated_fixers.py"

# 마커 — generated_fixers.py 안에서 fixer 삽입 위치를 찾는 데 사용
_START_MARKER = "# GENERATED_FIXERS_START"
_END_MARKER = "# GENERATED_FIXERS_END"


# =============================================================================
# 오류 타입 추출
# =============================================================================


def _extract_error_type(signature: str) -> str | None:
    """정규화된 오류 시그니처에서 예외 클래스명 추출."""
    m = re.match(r"^(\w+(?:Error|Exception|Warning|Fault))", signature.strip())
    return m.group(1) if m else None


def _slug(error_type: str) -> str:
    """오류 타입 → fixer 함수명용 snake_case 슬러그."""
    # AttributeError → attribute_error
    slug = re.sub(r"(?<!^)(?=[A-Z])", "_", error_type).lower()
    return slug


# =============================================================================
# SelfLearningKB 조회
# =============================================================================


async def _fetch_promotion_candidates(session: Any) -> list[dict[str, Any]]:
    """success_count >= PROMOTE_THRESHOLD 인 failure_lesson 조회."""
    from sqlalchemy import text

    rows = (
        (
            await session.execute(
                text(
                    """
                SELECT
                    id::text AS kb_id,
                    hash,
                    payload,
                    confidence,
                    success_count
                FROM self_learning_kb
                WHERE kb_type = 'failure_lesson'
                  AND success_count >= :threshold
                ORDER BY success_count DESC
                LIMIT 200
                """
                ).bindparams(threshold=PROMOTE_THRESHOLD)
            )
        )
        .mappings()
        .all()
    )

    candidates = []
    for r in rows:
        payload = r["payload"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:  # noqa: BLE001
                continue
        if not isinstance(payload, dict):
            continue

        sig = payload.get("error_signature") or payload.get("error_signature", "")
        diff = (payload.get("fix_diff") or "").strip()
        if not sig or not diff:
            continue

        error_type = _extract_error_type(sig)
        if not error_type:
            continue

        candidates.append(
            {
                "kb_id": r["kb_id"],
                "error_type": error_type,
                "signature": sig[:500],
                "fix_diff": diff,
                "success_count": int(r["success_count"] or 0),
                "confidence": float(r["confidence"] or 0.0),
                "source": payload.get("source", "unknown"),
            }
        )

    return candidates


def _group_by_error_type(candidates: list[dict]) -> dict[str, list[dict]]:
    """오류 타입별 그룹핑."""
    groups: dict[str, list[dict]] = {}
    for c in candidates:
        groups.setdefault(c["error_type"], []).append(c)
    return groups


# =============================================================================
# generated_fixers.py 파싱
# =============================================================================


def _read_generated_file() -> str:
    """현재 generated_fixers.py 전체 내용 반환."""
    return GENERATED_FILE.read_text(encoding="utf-8")


def _existing_fixer_names() -> set[str]:
    """generated_fixers.py 에 이미 있는 _fix_gen_* 함수명 집합."""
    src = _read_generated_file()
    return set(re.findall(r"^def (_fix_gen_\w+)\(", src, re.MULTILINE))


def _existing_fixer_source(fixer_name: str) -> str | None:
    """기존 fixer 함수의 소스 코드 추출."""
    src = _read_generated_file()
    pattern = re.compile(
        rf"^(def {re.escape(fixer_name)}\(.*?)(?=^def |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(src)
    return m.group(1).rstrip() if m else None


# =============================================================================
# Claude CLI 로 fixer 코드 생성 / 업데이트
# =============================================================================

_FIXER_SYSTEM_PROMPT = """\
당신은 Python 오류 자동 수정 함수 생성기다.

인터페이스 규칙:
- 함수 시그니처: def _fix_gen_{slug}(error_message: str, stack_trace: str) -> dict[str, Any] | None:
- 내부에서 사용할 수 있는 함수: _parse_last_file_and_line(stack_trace), _read_source(path), _make_diff(orig, modified, path), _result(diff, test_plan, confidence, fixer)
- 각 변형(variation)은 독립적인 if/elif 블록으로 처리
- 처리 못하면 return None
- 반드시 유효한 Python 코드만 출력 (설명 없이, 함수 정의만)

예시 구조:
def _fix_gen_attribute_error(error_message: str, stack_trace: str) -> dict[str, Any] | None:
    \"\"\"[자동생성] AttributeError 패턴 모음\"\"\"
    import re

    # 변형 1: NoneType 속성 접근 (3회 관찰)
    if "NoneType" in error_message and "has no attribute" in error_message:
        fpath, lineno = _parse_last_file_and_line(stack_trace)
        if not fpath or lineno < 1:
            return None
        lines = _read_source(fpath)
        if not lines:
            return None
        # ... 수정 로직 ...
        return _result(diff=diff, test_plan="...", confidence=0.70, fixer="_fix_gen_attribute_error")

    # 변형 2: 다른 패턴 (2회 관찰)
    elif "object has no attribute" in error_message:
        # ...
        pass

    return None
"""


async def _call_claude_for_fixer(
    slug: str,
    error_type: str,
    patterns: list[dict],
    existing_code: str | None = None,
) -> str | None:
    """Claude CLI 로 fixer 함수 코드 생성 또는 업데이트."""
    try:
        from ada.error_handler.claude_cli_bridge import ClaudeCLIBridge

        cases_text = "\n\n".join(
            f"[사례 {i + 1}] success_count={p['success_count']}\n"
            f"오류: {p['signature']}\n"
            f"수정 diff:\n{p['fix_diff'][:800]}"
            for i, p in enumerate(patterns[:MAX_PATTERNS_PER_FIXER])
        )

        if existing_code:
            user_prompt = (
                f"다음은 기존 _fix_gen_{slug} 함수다:\n\n"
                f"```python\n{existing_code}\n```\n\n"
                f"새로 관찰된 {error_type} 변형들:\n\n{cases_text}\n\n"
                f"기존 함수에 새 변형을 elif 블록으로 추가해 업데이트된 함수 전체를 반환하라. "
                f"기존 분기는 그대로 유지하고 새 분기만 추가할 것."
            )
        else:
            user_prompt = (
                f"다음 {len(patterns)}건의 {error_type} 성공 수정 사례를 분석해 "
                f"_fix_gen_{slug} fixer 함수를 생성하라.\n\n"
                f"{cases_text}\n\n"
                f"각 변형을 if/elif 블록으로 처리하라. 유사한 패턴은 하나의 블록으로 묶어도 된다."
            )

        bridge = ClaudeCLIBridge()
        result = await bridge.request_patch(
            error_signature=user_prompt,
            stack="",
            system_override=_FIXER_SYSTEM_PROMPT,
        )

        # ClaudeCLIBridge 는 diff 를 반환하지만, 여기서는 코드 자체가 필요
        # diff 필드가 없으면 raw content 를 시도
        code = result.get("code") or result.get("diff") or result.get("content") or ""
        if not code:
            return None

        # Python 코드 블록 추출
        m = re.search(r"```python\n(.*?)```", code, re.DOTALL)
        if m:
            code = m.group(1)

        # 함수 정의 추출
        m2 = re.search(
            rf"(def _fix_gen_{re.escape(slug)}\(.*?)(?=\ndef |\Z)",
            code,
            re.DOTALL,
        )
        if m2:
            return m2.group(1).rstrip()

        # 그대로 반환
        if f"def _fix_gen_{slug}" in code:
            return code.strip()

        return None

    except Exception as e:  # noqa: BLE001
        log.warning("claude_fixer_gen_failed", slug=slug, error=str(e))
        return None


# =============================================================================
# generated_fixers.py 업데이트
# =============================================================================


def _build_diff(old_content: str, new_content: str) -> str:
    """두 버전 사이의 unified diff 생성."""
    rel = str(GENERATED_FILE).replace("\\", "/")
    # repo root 기준 상대 경로 추출
    for sep in ["/ada/error_handler/", "\\ada\\error_handler\\"]:
        if sep in rel:
            rel = "ada/error_handler/generated_fixers.py"
            break

    lines_old = old_content.splitlines(keepends=True)
    lines_new = new_content.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            lines_old,
            lines_new,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


def _insert_fixer_code(file_content: str, fixer_code: str) -> str:
    """_START_MARKER ~ _END_MARKER 사이에 fixer 코드 삽입/교체."""
    start_idx = file_content.find(_START_MARKER)
    end_idx = file_content.find(_END_MARKER)
    if start_idx == -1 or end_idx == -1:
        log.warning("fixer_markers_not_found")
        return file_content

    before = file_content[: start_idx + len(_START_MARKER)]
    after = file_content[end_idx:]

    # 기존 섹션에서 같은 이름 함수 제거 후 새 버전 추가
    existing_section = file_content[start_idx + len(_START_MARKER) : end_idx]

    # 함수 이름 추출
    m = re.match(r"def (_fix_gen_\w+)\(", fixer_code.strip())
    if m:
        fname = m.group(1)
        # 기존 함수 제거
        existing_section = re.sub(
            rf"\n\n\ndef {re.escape(fname)}\(.*?(?=\n\n\ndef |\Z)",
            "",
            existing_section,
            flags=re.DOTALL,
        )

    new_section = existing_section.rstrip() + "\n\n\n" + fixer_code.strip() + "\n"
    return before + new_section + after


async def _apply_fixer_update(fixer_name: str, fixer_code: str) -> bool:
    """generated_fixers.py 에 fixer 추가/업데이트."""
    try:
        old_content = _read_generated_file()
        new_content = _insert_fixer_code(old_content, fixer_code)

        if old_content == new_content:
            log.info("fixer_no_change", fixer_name=fixer_name)
            return False

        diff = _build_diff(old_content, new_content)
        if not diff:
            return False

        from ada.error_handler.patcher import apply_patch

        result = await apply_patch(
            diff,
            commit_msg=f"auto-promote/tier-0: {fixer_name}",
        )
        if result["applied"]:
            log.info(
                "fixer_promoted",
                fixer_name=fixer_name,
                git_commit=result.get("git_commit"),
                modules_reloaded=result.get("modules_reloaded"),
            )
            return True

        log.warning("fixer_apply_failed", fixer_name=fixer_name, reason=result.get("reason"))
        return False

    except Exception as e:  # noqa: BLE001
        log.error("fixer_update_error", fixer_name=fixer_name, error=str(e))
        return False


# =============================================================================
# 메인 진입점
# =============================================================================


async def check_and_promote(session: Any) -> dict[str, Any]:
    """SelfLearningKB 에서 반복 패턴 감지 → Tier 0 fixer 자동 생성·업데이트.

    Returns::

        {
            "candidates": int,   # 승격 후보 수
            "promoted": int,     # 새로 생성된 fixer 수
            "updated": int,      # 기존 fixer 에 변형 추가된 수
            "skipped": int,      # 처리 건너뜀
        }
    """
    result: dict[str, Any] = {
        "candidates": 0,
        "promoted": 0,
        "updated": 0,
        "skipped": 0,
    }

    # 1. 승격 후보 조회
    candidates = await _fetch_promotion_candidates(session)
    result["candidates"] = len(candidates)
    if not candidates:
        return result

    # 2. 오류 타입별 그룹핑
    groups = _group_by_error_type(candidates)
    existing_names = _existing_fixer_names()

    for error_type, patterns in groups.items():
        slug = _slug(error_type)
        fixer_name = f"_fix_gen_{slug}"

        # 이미 MAX_PATTERNS_PER_FIXER 개 이상 처리 중이면 skip
        if len(patterns) > MAX_PATTERNS_PER_FIXER * 2:
            patterns = sorted(patterns, key=lambda x: x["success_count"], reverse=True)[:MAX_PATTERNS_PER_FIXER]

        if fixer_name in existing_names:
            # 기존 fixer 에 새 변형 추가
            existing_code = _existing_fixer_source(fixer_name)
            new_code = await _call_claude_for_fixer(
                slug=slug,
                error_type=error_type,
                patterns=patterns,
                existing_code=existing_code,
            )
            if new_code:
                applied = await _apply_fixer_update(fixer_name, new_code)
                if applied:
                    result["updated"] += 1
                    log.info(
                        "fixer_updated",
                        error_type=error_type,
                        variants=len(patterns),
                    )
                else:
                    result["skipped"] += 1
            else:
                result["skipped"] += 1
        else:
            # 새 fixer 생성
            new_code = await _call_claude_for_fixer(
                slug=slug,
                error_type=error_type,
                patterns=patterns,
                existing_code=None,
            )
            if new_code:
                applied = await _apply_fixer_update(fixer_name, new_code)
                if applied:
                    result["promoted"] += 1
                    log.info(
                        "fixer_promoted_new",
                        error_type=error_type,
                        variants=len(patterns),
                    )
                else:
                    result["skipped"] += 1
            else:
                result["skipped"] += 1

    log.info("promotion_complete", **result)
    return result


def run_sync() -> dict[str, Any]:
    """Celery 태스크용 동기 진입점."""
    import asyncio

    async def _do() -> dict[str, Any]:
        from ada.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as s:
            return await check_and_promote(s)

    return asyncio.run(_do())

"""outputs.governance.signature — SHA256 봉인 (Phase 6, Part 16).

ReportContext + 생성 파일 바이트 → SHA256 → metadata.signature_sha256.
재현 가능성과 위변조 탐지에 사용.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from outputs.context.schema import ReportContext


def sign_report(file_bytes: bytes | str | Path, ctx: ReportContext) -> str:
    """파일 바이트 + ReportContext 직렬화 → SHA256."""
    h = hashlib.sha256()
    if isinstance(file_bytes, (str, Path)):
        try:
            file_bytes = Path(file_bytes).read_bytes()
        except Exception:
            file_bytes = b""
    h.update(file_bytes or b"")
    # ReportContext 직렬화 (안정적 — sort_keys)
    try:
        ctx_json = json.dumps(ctx.to_dict(), ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        ctx_json = ""
    h.update(ctx_json.encode("utf-8", errors="replace"))
    return h.hexdigest()


def verify_signature(file_bytes: bytes | str | Path, ctx: ReportContext, expected: str) -> bool:
    """서명 검증."""
    actual = sign_report(file_bytes, ctx)
    return actual == expected

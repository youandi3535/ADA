"""outputs.versioning — 산출물 버전 관리 + audit (Day15).

같은 job 의 같은 output_code 를 재생성하면 v2, v3... 자동 증가.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ada.db.models import Output


async def get_next_version(session: AsyncSession, job_id: str, code: str) -> int:
    count = await session.scalar(
        select(func.count(Output.id)).where(Output.job_id == job_id, Output.output_code == code)
    )
    return (count or 0) + 1


def versioned_path(base_path: str, version: int) -> str:
    if version == 1:
        return base_path
    # outputs/OUT-01/{job_id}/file.pptx → outputs/OUT-01/{job_id}/file_v2.pptx
    if "." in base_path:
        stem, ext = base_path.rsplit(".", 1)
        return f"{stem}_v{version}.{ext}"
    return f"{base_path}_v{version}"

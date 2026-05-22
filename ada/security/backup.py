"""ada.security.backup — 백업/DR (Day17 R-901/R-902).

postgres dump + minio sync + sha256 등록.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile

from sqlalchemy.ext.asyncio import AsyncSession

from ada.core.config import settings
from ada.core.logger import get_logger
from ada.db.models import BackupCatalog

log = get_logger("backup")


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dump_postgres(*, dsn: str | None = None) -> tuple[str, str, int]:
    """pg_dump 실행 → (local_path, sha256, size_bytes)."""
    dsn = dsn or settings.database_url
    out = tempfile.NamedTemporaryFile(delete=False, suffix=".sql.gz")
    out.close()
    cmd = ["pg_dump", dsn, "-Z9", "-Fp", "-f", out.name]
    subprocess.run(cmd, check=True, timeout=600)
    return out.name, _sha256(out.name), os.path.getsize(out.name)


async def register_backup(
    session: AsyncSession,
    *,
    backup_type: str,
    minio_path: str,
    sha256: str,
    size_bytes: int,
    note: str = "",
) -> str:
    """backup_catalog INSERT (R-901)."""
    row = BackupCatalog(
        backup_type=backup_type,
        minio_path=minio_path,
        sha256=sha256,
        size_bytes=size_bytes,
        status="ok",
        note=note,
    )
    session.add(row)
    await session.flush()
    return str(row.id)

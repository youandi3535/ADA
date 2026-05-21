"""ada.security.vault — HashiCorp Vault 클라이언트 (Day17 R-903).

Dev 모드 (Day01) 와 Raft 모드 (운영) 모두 지원. KV v2 마운트 사용.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

import hvac  # type: ignore

from ada.core.config import settings
from ada.core.logger import get_logger

log = get_logger("vault")


@lru_cache(maxsize=1)
def get_client() -> hvac.Client:
    client = hvac.Client(url=settings.vault_addr, token=settings.vault_dev_token)
    if not client.is_authenticated():
        log.warning("vault_not_authenticated")
    return client


def read_secret(path: str, *, mount: str = "secret") -> dict[str, Any]:
    client = get_client()
    try:
        resp = client.secrets.kv.v2.read_secret_version(path=path, mount_point=mount)
        return resp["data"]["data"]
    except Exception as e:
        log.warning("vault_read_failed", path=path, error=str(e))
        return {}


def write_secret(path: str, data: dict[str, Any], *, mount: str = "secret") -> bool:
    client = get_client()
    try:
        client.secrets.kv.v2.create_or_update_secret(
            path=path, secret=data, mount_point=mount,
        )
        return True
    except Exception as e:
        log.error("vault_write_failed", path=path, error=str(e))
        return False

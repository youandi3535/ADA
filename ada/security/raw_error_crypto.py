"""ada.security.raw_error_crypto — FailureLog.raw_error_encrypted 암·복호화 (R-103).

models.py 의 `raw_error_encrypted = Column(LargeBinary)` 컬럼은 PII 가 포함될
가능성이 있는 *원본* 에러 텍스트를 디버깅 목적으로 보관하기 위해 설계됐다.
평문 컬럼(error_message / stack_trace) 은 redactor 통과 후 저장하므로 마스킹된다.
본 모듈은 원본을 컬럼에 넣기 전에 대칭키 암호화를 적용한다.

키 관리:
    환경변수 ``ADA_FAILURELOG_ENC_KEY`` 에 Fernet 키 (urlsafe base64, 32 bytes) 제공.
    배포 환경에서는 외부 시크릿 매니저(Vault, AWS Secrets Manager) 에서 주입.
    설정이 없으면 None 반환 → 호출자는 원본 저장을 skip (R-103: 평문 PII 저장 금지).

키 생성 (개발):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

API:
    encrypt_raw_error(text: str) -> bytes | None
    decrypt_raw_error(blob: bytes) -> str | None
    is_encryption_enabled() -> bool
"""

from __future__ import annotations

import os
from typing import Optional

from ada.core.logger import get_logger

_log = get_logger("raw_error_crypto")
_KEY_ENV = "ADA_FAILURELOG_ENC_KEY"

_fernet = None  # 지연 초기화 싱글턴
_warned_missing_key = False


def _get_fernet():
    """Fernet 인스턴스 반환. 키 없거나 cryptography 미설치면 None."""
    global _fernet, _warned_missing_key  # noqa: PLW0603

    if _fernet is not None:
        return _fernet

    key = os.environ.get(_KEY_ENV, "").strip()
    if not key:
        if not _warned_missing_key:
            _log.warning(
                "raw_error_encryption_disabled",
                reason=f"{_KEY_ENV} not set — raw_error_encrypted 컬럼 사용 안 됨",
            )
            _warned_missing_key = True
        return None

    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        _log.error("cryptography_not_installed", error=str(e))
        return None

    try:
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
        return _fernet
    except Exception as e:  # noqa: BLE001
        _log.error("fernet_init_failed", error=str(e))
        return None


def is_encryption_enabled() -> bool:
    """배포 환경에서 암호화가 실제 작동 중인지 헬스체크용."""
    return _get_fernet() is not None


def encrypt_raw_error(text: Optional[str]) -> Optional[bytes]:
    """원본 에러 텍스트를 암호화. 키 없거나 빈 입력이면 None 반환."""
    if not text:
        return None
    f = _get_fernet()
    if f is None:
        return None
    try:
        return f.encrypt(text.encode("utf-8", errors="replace"))
    except Exception as e:  # noqa: BLE001
        _log.warning("encrypt_failed", error=str(e))
        return None


def decrypt_raw_error(blob: Optional[bytes]) -> Optional[str]:
    """저장된 암호문 → 평문. 키 없거나 잘못된 blob 이면 None."""
    if not blob:
        return None
    f = _get_fernet()
    if f is None:
        return None
    try:
        return f.decrypt(blob).decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        _log.warning("decrypt_failed", error=str(e))
        return None

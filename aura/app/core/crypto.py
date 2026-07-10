"""Symmetric encryption for secrets stored at rest in the database.

Tenant ITSM credentials (Jira/Zendesk API tokens) live in `platform_config`
now instead of a process-wide .env file, so they're encrypted with a key
derived from APP_SECRET_KEY before being written, and decrypted only at the
point of use (building that tenant's ITSM client).
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import get_settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    # Fernet requires a 32-byte url-safe base64 key; APP_SECRET_KEY is an
    # arbitrary-length string (min 32 chars), so derive a stable key from it.
    digest = hashlib.sha256(settings.app_secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a secret for storage. None/empty passes through unchanged so
    callers don't need a guard at every call site for an unset credential."""
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str | None) -> str | None:
    """Decrypt a stored secret. None/empty passes through unchanged.

    Raises cryptography.fernet.InvalidToken if APP_SECRET_KEY changed since
    encryption — callers should surface that as "credentials lost, re-enter
    them", never fall back to treating the ciphertext as plaintext.
    """
    if not ciphertext:
        return None
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")

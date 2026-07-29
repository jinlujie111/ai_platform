"""Encrypt/decrypt sensitive fields at rest (P0)."""
from __future__ import annotations

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:v1:"


def _derive_fernet_key(master: str) -> bytes:
    digest = hashlib.sha256(master.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _fernet() -> Fernet | None:
    master = (os.getenv("SECRETS_MASTER_KEY") or "").strip()
    if not master:
        # Dev fallback: stable key from AUTH_SECRET or fixed local string
        master = (os.getenv("AUTH_SECRET") or "ai-platform-dev-secrets-key").strip()
    return Fernet(_derive_fernet_key(master))


def encrypt_secret(plain: str | None) -> str:
    value = plain or ""
    if not value:
        return ""
    if value.startswith(PREFIX):
        return value
    token = _fernet().encrypt(value.encode("utf-8")).decode("utf-8")
    return PREFIX + token


def decrypt_secret(stored: str | None) -> str:
    value = stored or ""
    if not value:
        return ""
    if not value.startswith(PREFIX):
        # Legacy plaintext
        return value
    raw = value[len(PREFIX) :]
    try:
        return _fernet().decrypt(raw.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("无法解密密钥，请检查 SECRETS_MASTER_KEY 是否与写入时一致") from exc


def is_encrypted(stored: str | None) -> bool:
    return bool(stored) and str(stored).startswith(PREFIX)

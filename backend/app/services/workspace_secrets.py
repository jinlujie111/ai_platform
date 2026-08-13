"""Workspace field-level secret protection (at-rest encryption)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .secret_box import decrypt_secret, encrypt_secret, is_encrypted

# Whole-value encryption for opaque credential blobs.
ENCRYPT_WHOLE_KEYS = {"knowledge_credentials"}

# Nested field names commonly holding secrets.
SECRET_FIELD_NAMES = {
    "apiKey",
    "api_key",
    "token",
    "password",
    "secret",
    "access_token",
    "authorization",
    "proxy",
    "X-Tushare-Token",
    "X-Tushare-Proxy",
}


def _encrypt_value(value: Any) -> Any:
    if not isinstance(value, str) or not value or is_encrypted(value):
        return value
    return encrypt_secret(value)


def _decrypt_value(value: Any) -> Any:
    if not isinstance(value, str) or not value:
        return value
    if not is_encrypted(value):
        return value
    try:
        return decrypt_secret(value)
    except Exception:
        return value


def _walk(obj: Any, *, encrypt: bool) -> Any:
    transform = _encrypt_value if encrypt else _decrypt_value
    if isinstance(obj, dict):
        out = {}
        for key, value in obj.items():
            if key in SECRET_FIELD_NAMES and isinstance(value, str):
                out[key] = transform(value)
            else:
                out[key] = _walk(value, encrypt=encrypt)
        return out
    if isinstance(obj, list):
        return [_walk(item, encrypt=encrypt) for item in obj]
    return obj


def protect_workspace_settings(settings: dict) -> dict:
    """Encrypt sensitive fields before persisting to DB."""
    out: dict = {}
    for key, value in (settings or {}).items():
        if key in ENCRYPT_WHOLE_KEYS:
            encoded = value if isinstance(value, str) else __import__("json").dumps(
                value, ensure_ascii=False, separators=(",", ":")
            )
            out[key] = encrypt_secret(encoded) if encoded else value
        else:
            out[key] = _walk(deepcopy(value), encrypt=True)
    return out


def reveal_workspace_settings(settings: dict) -> dict:
    """Decrypt sensitive fields when loading for the client."""
    out: dict = {}
    for key, value in (settings or {}).items():
        if key in ENCRYPT_WHOLE_KEYS and isinstance(value, str) and is_encrypted(value):
            plain = decrypt_secret(value)
            try:
                out[key] = __import__("json").loads(plain)
            except Exception:
                out[key] = plain
        else:
            out[key] = _walk(deepcopy(value), encrypt=False)
    return out

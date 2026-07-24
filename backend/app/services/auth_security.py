"""Password hashing and signed session tokens."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
from pathlib import Path

import bcrypt

from ..database import DATA_DIR

TOKEN_TTL_SECONDS = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(7 * 24 * 3600)))
_SECRET_FILE = DATA_DIR / ".auth_secret"


def _load_or_create_secret() -> bytes:
    env = (os.getenv("AUTH_SECRET") or "").strip()
    if env:
        return env.encode("utf-8")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if _SECRET_FILE.exists():
        value = _SECRET_FILE.read_bytes().strip()
        if value:
            return value
    value = base64.urlsafe_b64encode(os.urandom(32))
    _SECRET_FILE.write_bytes(value)
    try:
        _SECRET_FILE.chmod(0o600)
    except Exception:
        pass
    return value


SECRET_KEY = _load_or_create_secret()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            (password_hash or "").encode("utf-8"),
        )
    except Exception:
        return False


def create_access_token(*, user_id: int, role: str, username: str) -> str:
    expires = int(time.time()) + TOKEN_TTL_SECONDS
    payload = f"{user_id}:{role}:{username}:{expires}"
    signature = hmac.new(SECRET_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{signature}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def decode_access_token(token: str) -> dict | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        user_id_s, role, username, expires_s, signature = raw.rsplit(":", 4)
        payload = f"{user_id_s}:{role}:{username}:{expires_s}"
        expected = hmac.new(SECRET_KEY, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return None
        if int(expires_s) < int(time.time()):
            return None
        return {
            "user_id": int(user_id_s),
            "role": role,
            "username": username,
            "expires": int(expires_s),
        }
    except Exception:
        return None

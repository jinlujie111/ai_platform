"""Platform API key + dual auth (JWT or API key)."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps_auth import _extract_token, bearer_scheme
from ..models import PlatformApiKey, User
from ..services.auth_security import decode_access_token


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Return (plaintext, prefix, hash). Plaintext shown once."""
    raw = "apk_" + secrets.token_urlsafe(32)
    prefix = raw[:8]
    return raw, prefix, hash_api_key(raw)


@dataclass
class GatewayPrincipal:
    user: User | None
    api_key: PlatformApiKey | None
    is_admin: bool

    @property
    def user_id(self) -> int | None:
        if self.user:
            return int(self.user.id)
        if self.api_key and self.api_key.owner_user_id:
            return int(self.api_key.owner_user_id)
        return None

    @property
    def api_key_id(self) -> int | None:
        return int(self.api_key.id) if self.api_key else None


def _lookup_api_key(db: Session, token: str) -> PlatformApiKey | None:
    if not token.startswith("apk_"):
        return None
    digest = hash_api_key(token)
    row = db.scalar(
        select(PlatformApiKey).where(
            PlatformApiKey.key_hash == digest,
            PlatformApiKey.is_active == 1,
        )
    )
    if not row or row.revoked_at is not None:
        return None
    row.last_used_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return row


def require_gateway_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> GatewayPrincipal:
    token = _extract_token(request, authorization, credentials)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "未登录或缺少 API Key"},
        )

    if token.startswith("apk_"):
        key = _lookup_api_key(db, token)
        if not key:
            raise HTTPException(
                status_code=401,
                detail={"code": "unauthorized", "message": "无效的 API Key"},
            )
        scopes = (key.scopes or "chat").lower()
        if "chat" not in scopes and "all" not in scopes:
            raise HTTPException(
                status_code=403,
                detail={"code": "forbidden", "message": "API Key 无 chat 权限"},
            )
        owner = db.get(User, key.owner_user_id) if key.owner_user_id else None
        is_admin = bool(owner and (owner.role or "").lower() == "admin")
        return GatewayPrincipal(user=owner, api_key=key, is_admin=is_admin)

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "未登录或登录已过期"},
        )
    user = db.get(User, payload["user_id"])
    if not user or not int(getattr(user, "is_active", 1)):
        raise HTTPException(
            status_code=401,
            detail={"code": "unauthorized", "message": "用户不存在或已停用"},
        )
    if int(getattr(user, "must_change_password", 0) or 0):
        raise HTTPException(status_code=403, detail="首次登录请先修改密码后再使用平台功能")
    is_admin = (user.role or "").strip().lower() == "admin"
    return GatewayPrincipal(user=user, api_key=None, is_admin=is_admin)

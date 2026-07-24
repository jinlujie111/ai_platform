"""FastAPI auth dependencies."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .services.auth_security import decode_access_token


def _extract_token(request: Request, authorization: str | None) -> str:
    if authorization:
        value = authorization.strip()
        if value.lower().startswith("bearer "):
            return value[7:].strip()
        return value
    return (request.cookies.get("ai_platform_token") or "").strip()


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(request, authorization)
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    user = db.get(User, payload["user_id"])
    if not user or not int(getattr(user, "is_active", 1)):
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


def get_optional_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User | None:
    token = _extract_token(request, authorization)
    payload = decode_access_token(token)
    if not payload:
        return None
    user = db.get(User, payload["user_id"])
    if not user or not int(getattr(user, "is_active", 1)):
        return None
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if (user.role or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

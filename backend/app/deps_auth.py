"""FastAPI auth dependencies."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .database import get_db
from .models import User
from .services.auth_security import decode_access_token

# Declared so Swagger UI shows the green "Authorize" button.
bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(
    request: Request,
    authorization: str | None = None,
    credentials: HTTPAuthorizationCredentials | None = None,
) -> str:
    if credentials and credentials.credentials:
        return credentials.credentials.strip()
    if authorization:
        value = authorization.strip()
        if value.lower().startswith("bearer "):
            return value[7:].strip()
        return value
    return (request.cookies.get("ai_platform_token") or "").strip()


def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(request, authorization, credentials)
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
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    token = _extract_token(request, authorization, credentials)
    payload = decode_access_token(token)
    if not payload:
        return None
    user = db.get(User, payload["user_id"])
    if not user or not int(getattr(user, "is_active", 1)):
        return None
    return user


def require_usable_user(user: User = Depends(get_current_user)) -> User:
    """Block business APIs until bootstrap password is changed."""
    if int(getattr(user, "must_change_password", 0) or 0):
        raise HTTPException(
            status_code=403,
            detail="首次登录请先修改密码后再使用平台功能",
        )
    return user


def require_admin(user: User = Depends(require_usable_user)) -> User:
    if (user.role or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user

"""Auth and user-management APIs."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps_auth import get_current_user, require_admin
from .models import User
from .services.auth_security import (
    create_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]{3,64}$")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=120)


class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(default="", max_length=120)
    role: str = Field(default="user")


class UserUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    role: str | None = None
    password: str | None = Field(default=None, min_length=6, max_length=128)
    is_active: bool | None = None


def _user_out(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "role": user.role,
        "is_active": bool(user.is_active),
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def _normalize_role(role: str) -> str:
    value = (role or "user").strip().lower()
    if value not in {"admin", "user"}:
        raise HTTPException(status_code=400, detail="角色仅支持 admin 或 user")
    return value


def seed_default_admin(db: Session) -> None:
    """Create bootstrap admin when users table is empty."""
    existing = db.scalar(select(User.id).limit(1))
    if existing:
        return
    username = (os.getenv("ADMIN_USERNAME") or "admin").strip() or "admin"
    password = (os.getenv("ADMIN_PASSWORD") or "admin123").strip() or "admin123"
    display_name = (os.getenv("ADMIN_DISPLAY_NAME") or "系统管理员").strip()
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name or "系统管理员",
        role="admin",
        is_active=1,
    )
    db.add(user)
    db.commit()


def _public_register_enabled() -> bool:
    return (os.getenv("ALLOW_PUBLIC_REGISTER") or "true").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _issue_session(user: User, response: Response) -> dict:
    token = create_access_token(user_id=user.id, role=user.role, username=user.username)
    response.set_cookie(
        key="ai_platform_token",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return {"token": token, "user": _user_out(user)}


def _create_user_record(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str = "",
    role: str = "user",
) -> User:
    username = (username or "").strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(status_code=400, detail="用户名需为 3–64 位字母数字或 _-.")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    if len(password or "") < 6:
        raise HTTPException(status_code=400, detail="密码至少 6 位")
    role = _normalize_role(role)
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=(display_name or "").strip() or username,
        role=role,
        is_active=1,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    username = payload.username.strip()
    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not int(getattr(user, "is_active", 1)):
        raise HTTPException(status_code=403, detail="账号已停用")
    return _issue_session(user, response)


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)):
    """Public self-service signup. Always creates a normal user (never admin)."""
    if not _public_register_enabled():
        raise HTTPException(status_code=403, detail="当前未开放公开注册，请联系管理员")
    user = _create_user_record(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role="user",
    )
    return _issue_session(user, response)


@router.get("/register-status")
def register_status():
    return {"enabled": _public_register_enabled()}


@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user)):
    response.delete_cookie("ai_platform_token")
    return {"ok": True, "username": user.username}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return _user_out(user)


@router.get("/users")
def list_users(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(User).order_by(User.id.asc())).all()
    return [_user_out(item) for item in rows]


@router.post("/users", status_code=201)
def create_user(
    payload: UserCreateRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _create_user_record(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        role=payload.role,
    )
    return _user_out(user)


@router.patch("/users/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    current: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or user.username
    if payload.role is not None:
        new_role = _normalize_role(payload.role)
        if user.id == current.id and new_role != "admin":
            raise HTTPException(status_code=400, detail="不能取消自己的管理员角色")
        user.role = new_role
    if payload.password:
        user.password_hash = hash_password(payload.password)
    if payload.is_active is not None:
        if user.id == current.id and not payload.is_active:
            raise HTTPException(status_code=400, detail="不能停用当前登录账号")
        # Prevent disabling the last admin
        if not payload.is_active and user.role == "admin":
            admins = db.scalars(
                select(User).where(User.role == "admin", User.is_active == 1)
            ).all()
            if len(admins) <= 1 and any(item.id == user.id for item in admins):
                raise HTTPException(status_code=400, detail="不能停用唯一的管理员")
        user.is_active = 1 if payload.is_active else 0
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    current: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    if user.role == "admin":
        admins = db.scalars(
            select(User).where(User.role == "admin", User.is_active == 1)
        ).all()
        if len(admins) <= 1:
            raise HTTPException(status_code=400, detail="不能删除唯一的管理员")
    db.delete(user)
    db.commit()
    return Response(status_code=204)

"""Per-user workspace settings (models, MCP, skills, chats, etc.)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .deps_auth import get_current_user
from .models import User, UserWorkspaceSetting

router = APIRouter(prefix="/api/workspace", tags=["workspace"])

# Keys formerly stored in browser localStorage (auth token stays local).
WORKSPACE_KEYS = {
    "configured_models",
    "active_model_id",
    "user_mcp_configs",
    "mcp_market_state",
    "custom_mcp_market",
    "user_skill_configs",
    "skill_market_state",
    "custom_skill_market",
    "user_agent_configs",
    "active_agent_id",
    "ai_platform_tool_settings",
    "knowledge_api_configs",
    "knowledge_credentials",
    "knowledge_self_enabled",
    "selected_knowledge_base_id",
    "chat_knowledge_base_ids",
    "chat_knowledge_base_id",
    "chat_data_source_ids",
    "ai_platform_conversations",
    "ai_platform_current_conversation",
    "ai_platform_approval_audit",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _encode_value(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_value(raw: str):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


class WorkspacePutRequest(BaseModel):
    settings: dict = Field(default_factory=dict)


def _load_settings(db: Session, user_id: int) -> dict:
    rows = db.scalars(
        select(UserWorkspaceSetting).where(UserWorkspaceSetting.user_id == user_id)
    ).all()
    out: dict = {}
    for row in rows:
        out[row.setting_key] = _decode_value(row.setting_value)
    return out


def _upsert_settings(db: Session, user_id: int, settings: dict) -> dict:
    existing = {
        row.setting_key: row
        for row in db.scalars(
            select(UserWorkspaceSetting).where(UserWorkspaceSetting.user_id == user_id)
        ).all()
    }
    now = _utcnow()
    for key, value in (settings or {}).items():
        key = str(key or "").strip()
        if not key or key not in WORKSPACE_KEYS:
            continue
        encoded = _encode_value(value)
        row = existing.get(key)
        if row:
            row.setting_value = encoded
            row.updated_at = now
            db.add(row)
        else:
            db.add(
                UserWorkspaceSetting(
                    user_id=user_id,
                    setting_key=key,
                    setting_value=encoded,
                    updated_at=now,
                )
            )
    db.commit()
    return _load_settings(db, user_id)


@router.get("")
def get_workspace(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    settings = _load_settings(db, user.id)
    return {
        "user_id": user.id,
        "settings": settings,
        "keys": sorted(WORKSPACE_KEYS),
        "empty": len(settings) == 0,
    }


@router.put("")
def put_workspace(
    payload: WorkspacePutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace/upsert provided keys (partial update is OK)."""
    settings = _upsert_settings(db, user.id, payload.settings or {})
    return {"user_id": user.id, "settings": settings, "empty": len(settings) == 0}


@router.delete("")
def clear_workspace(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(UserWorkspaceSetting).where(UserWorkspaceSetting.user_id == user.id)
    ).all()
    for row in rows:
        db.delete(row)
    db.commit()
    return {"ok": True}

"""Access helpers: ownership, admin bypass, and resource grants."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .models import GroupMember, ResourceGrant, User

RESOURCE_KB = "knowledge_base"
RESOURCE_DS = "datasource"

# Module-level capabilities (resource_id is always FEATURE_RESOURCE_ID).
RESOURCE_CAP_AGENT = "capability_agent"
RESOURCE_CAP_MCP = "capability_mcp"
RESOURCE_CAP_SKILL = "capability_skill"
RESOURCE_CAP_TOOL = "capability_tool"
FEATURE_RESOURCE_ID = 0

CAPABILITY_TYPES = {
    RESOURCE_CAP_AGENT,
    RESOURCE_CAP_MCP,
    RESOURCE_CAP_SKILL,
    RESOURCE_CAP_TOOL,
}

CAPABILITY_LABELS = {
    RESOURCE_CAP_AGENT: "Agent 管理",
    RESOURCE_CAP_MCP: "MCP 管理",
    RESOURCE_CAP_SKILL: "Skill 管理",
    RESOURCE_CAP_TOOL: "Tool 设置",
}

ENTITY_RESOURCE_TYPES = {RESOURCE_KB, RESOURCE_DS}
ALL_GRANT_RESOURCE_TYPES = ENTITY_RESOURCE_TYPES | CAPABILITY_TYPES


def is_admin(user: User | None) -> bool:
    return bool(user) and (user.role or "").strip().lower() == "admin"


def user_group_ids(db: Session, user_id: int) -> list[int]:
    return list(
        db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user_id)).all()
    )


def granted_resource_ids(db: Session, user: User, resource_type: str) -> set[int]:
    """Resource IDs granted to the user directly or via groups."""
    group_ids = user_group_ids(db, user.id)
    conds = [
        and_(
            ResourceGrant.grantee_type == "user",
            ResourceGrant.grantee_id == user.id,
        )
    ]
    if group_ids:
        conds.append(
            and_(
                ResourceGrant.grantee_type == "group",
                ResourceGrant.grantee_id.in_(group_ids),
            )
        )
    rows = db.scalars(
        select(ResourceGrant.resource_id).where(
            ResourceGrant.resource_type == resource_type,
            or_(*conds),
        )
    ).all()
    return {int(item) for item in rows}


def has_capability(db: Session, user: User | None, capability: str) -> bool:
    """Whether user may open a management module (admin always true)."""
    if user is None:
        return False
    if is_admin(user):
        return True
    cap = (capability or "").strip().lower()
    if cap not in CAPABILITY_TYPES:
        return False
    return FEATURE_RESOURCE_ID in granted_resource_ids(db, user, cap)


def user_capabilities(db: Session, user: User | None) -> dict[str, bool]:
    return {
        "agent": has_capability(db, user, RESOURCE_CAP_AGENT),
        "mcp": has_capability(db, user, RESOURCE_CAP_MCP),
        "skill": has_capability(db, user, RESOURCE_CAP_SKILL),
        "tool": has_capability(db, user, RESOURCE_CAP_TOOL),
    }


def can_use_resource(
    db: Session,
    user: User,
    resource,
    *,
    resource_type: str,
) -> bool:
    if resource is None:
        return False
    if is_admin(user):
        return True
    owner_id = getattr(resource, "owner_id", None)
    if owner_id is not None and int(owner_id) == int(user.id):
        return True
    return int(resource.id) in granted_resource_ids(db, user, resource_type)


def can_manage_resource(user: User, resource) -> bool:
    """Owner or admin may update/delete; grants are use-only."""
    if resource is None:
        return False
    if is_admin(user):
        return True
    owner_id = getattr(resource, "owner_id", None)
    return owner_id is not None and int(owner_id) == int(user.id)


def assert_can_use(
    db: Session,
    resource,
    user: User,
    *,
    resource_type: str,
    not_found_detail: str = "资源不存在",
) -> None:
    if not can_use_resource(db, user, resource, resource_type=resource_type):
        raise HTTPException(status_code=404, detail=not_found_detail)


def assert_can_manage(
    resource,
    user: User,
    *,
    not_found_detail: str = "资源不存在",
) -> None:
    if not can_manage_resource(user, resource):
        raise HTTPException(status_code=404, detail=not_found_detail)


def assert_owner(resource, user: User, *, not_found_detail: str = "资源不存在") -> None:
    """Backward-compatible alias: manage semantics (owner/admin)."""
    assert_can_manage(resource, user, not_found_detail=not_found_detail)


def accessible_query(
    stmt,
    model,
    user: User,
    db: Session,
    *,
    resource_type: str,
    all_for_admin: bool = True,
):
    """Filter list to owned + granted resources (admins see all)."""
    if all_for_admin and is_admin(user):
        return stmt
    granted = granted_resource_ids(db, user, resource_type)
    if granted:
        return stmt.where(or_(model.owner_id == user.id, model.id.in_(granted)))
    return stmt.where(model.owner_id == user.id)


def owned_query(stmt, model, user: User, *, all_for_admin: bool = True):
    """Legacy owner-only filter (no grants). Prefer accessible_query for KB/DS."""
    if all_for_admin and is_admin(user):
        return stmt
    return stmt.where(model.owner_id == user.id)


def resolve_default_owner_id(db: Session) -> int | None:
    """Pick bootstrap admin for backfilling legacy rows."""
    from .models import User as UserModel

    admin = db.scalar(
        select(UserModel).where(UserModel.role == "admin").order_by(UserModel.id.asc())
    )
    if admin:
        return admin.id
    any_user = db.scalar(select(UserModel).order_by(UserModel.id.asc()))
    return any_user.id if any_user else None

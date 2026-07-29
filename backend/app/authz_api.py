"""Admin APIs for groups and resource authorization."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .access_control import (
    ALL_GRANT_RESOURCE_TYPES,
    CAPABILITY_LABELS,
    CAPABILITY_TYPES,
    FEATURE_RESOURCE_ID,
    RESOURCE_CAP_AGENT,
    RESOURCE_CAP_MCP,
    RESOURCE_CAP_SKILL,
    RESOURCE_CAP_TOOL,
    RESOURCE_DS,
    RESOURCE_KB,
    is_admin,
    user_group_ids,
)
from .database import get_db
from .deps_auth import require_admin
from .models import DataSource, Group, GroupMember, KnowledgeBase, ResourceGrant, User

router = APIRouter(prefix="/api/authz", tags=["authz"])

ALLOWED_RESOURCE_TYPES = ALL_GRANT_RESOURCE_TYPES
ALLOWED_GRANTEE_TYPES = {"user", "group"}


class GroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class GroupMembersPut(BaseModel):
    user_ids: list[int] = Field(default_factory=list)


class GrantCreate(BaseModel):
    resource_type: str = Field(..., min_length=1, max_length=32)
    resource_id: int = Field(default=FEATURE_RESOURCE_ID)
    grantee_type: str = Field(..., min_length=1, max_length=16)
    grantee_id: int
    permission: str = Field(default="use", max_length=16)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _group_out(group: Group) -> dict:
    members = group.members or []
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description or "",
        "member_count": len(members),
        "member_ids": [int(item.user_id) for item in members],
        "created_at": group.created_at,
        "updated_at": group.updated_at,
    }


def _grant_out(db: Session, grant: ResourceGrant) -> dict:
    resource_name = ""
    if grant.resource_type in CAPABILITY_TYPES:
        resource_name = CAPABILITY_LABELS.get(grant.resource_type, grant.resource_type)
    elif grant.resource_type == RESOURCE_KB:
        kb = db.get(KnowledgeBase, grant.resource_id)
        resource_name = kb.name if kb else f"#{grant.resource_id}"
    elif grant.resource_type == RESOURCE_DS:
        ds = db.get(DataSource, grant.resource_id)
        resource_name = ds.name if ds else f"#{grant.resource_id}"
    else:
        resource_name = f"#{grant.resource_id}"

    grantee_name = ""
    if grant.grantee_type == "user":
        user = db.get(User, grant.grantee_id)
        grantee_name = (user.display_name or user.username) if user else f"#{grant.grantee_id}"
    else:
        group = db.get(Group, grant.grantee_id)
        grantee_name = group.name if group else f"#{grant.grantee_id}"

    return {
        "id": grant.id,
        "resource_type": grant.resource_type,
        "resource_id": grant.resource_id,
        "resource_name": resource_name,
        "grantee_type": grant.grantee_type,
        "grantee_id": grant.grantee_id,
        "grantee_name": grantee_name,
        "permission": grant.permission or "use",
        "granted_by": grant.granted_by,
        "created_at": grant.created_at,
        "is_capability": grant.resource_type in CAPABILITY_TYPES,
    }


def _get_group(db: Session, group_id: int) -> Group:
    group = db.scalars(
        select(Group)
        .where(Group.id == group_id)
        .options(selectinload(Group.members))
    ).first()
    if not group:
        raise HTTPException(status_code=404, detail="用户组不存在")
    return group


def _validate_grant_target(db: Session, payload: GrantCreate) -> None:
    rtype = (payload.resource_type or "").strip().lower()
    gtype = (payload.grantee_type or "").strip().lower()
    if rtype not in ALLOWED_RESOURCE_TYPES:
        raise HTTPException(
            status_code=400,
            detail="resource_type 仅支持 knowledge_base / datasource / capability_agent / capability_mcp / capability_skill / capability_tool",
        )
    if gtype not in ALLOWED_GRANTEE_TYPES:
        raise HTTPException(status_code=400, detail="grantee_type 仅支持 user / group")

    perm = (payload.permission or "use").strip().lower()
    if rtype in CAPABILITY_TYPES:
        if perm not in {"use", "manage"}:
            raise HTTPException(status_code=400, detail="permission 仅支持 use / manage")
        if int(payload.resource_id or 0) not in {0, FEATURE_RESOURCE_ID}:
            raise HTTPException(status_code=400, detail="能力授权无需选择具体资源")
    else:
        if perm not in {"use", "manage"}:
            raise HTTPException(status_code=400, detail="permission 仅支持 use / manage")
        if rtype == RESOURCE_KB:
            if not db.get(KnowledgeBase, payload.resource_id):
                raise HTTPException(status_code=404, detail="知识库不存在")
        elif rtype == RESOURCE_DS:
            if not db.get(DataSource, payload.resource_id):
                raise HTTPException(status_code=404, detail="数据源不存在")

    if gtype == "user":
        user = db.get(User, payload.grantee_id)
        if not user or not int(getattr(user, "is_active", 1)):
            raise HTTPException(status_code=404, detail="用户不存在或已停用")
    else:
        if not db.get(Group, payload.grantee_id):
            raise HTTPException(status_code=404, detail="用户组不存在")


@router.get("/groups")
def list_groups(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Group).options(selectinload(Group.members)).order_by(Group.id.asc())
    ).all()
    return [_group_out(item) for item in rows]


@router.post("/groups", status_code=201)
def create_group(
    payload: GroupCreate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请填写组名")
    group = Group(name=name, description=(payload.description or "").strip())
    db.add(group)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="组名已存在")
    group = _get_group(db, group.id)
    return _group_out(group)


@router.patch("/groups/{group_id}")
def update_group(
    group_id: int,
    payload: GroupUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    group = _get_group(db, group_id)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="组名不能为空")
        group.name = name
    if payload.description is not None:
        group.description = payload.description.strip()
    group.updated_at = _utcnow()
    db.add(group)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="组名已存在")
    return _group_out(_get_group(db, group_id))


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(
    group_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    group = _get_group(db, group_id)
    # remove grants targeting this group
    grants = db.scalars(
        select(ResourceGrant).where(
            ResourceGrant.grantee_type == "group",
            ResourceGrant.grantee_id == group_id,
        )
    ).all()
    for grant in grants:
        db.delete(grant)
    db.delete(group)
    db.commit()
    return None


@router.put("/groups/{group_id}/members")
def put_group_members(
    group_id: int,
    payload: GroupMembersPut,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    group = _get_group(db, group_id)
    wanted = sorted({int(item) for item in (payload.user_ids or []) if item})
    if wanted:
        users = db.scalars(select(User).where(User.id.in_(wanted))).all()
        found = {int(item.id) for item in users}
        missing = [item for item in wanted if item not in found]
        if missing:
            raise HTTPException(status_code=400, detail=f"用户不存在: {missing}")
    existing = {int(item.user_id): item for item in (group.members or [])}
    for user_id, row in list(existing.items()):
        if user_id not in wanted:
            db.delete(row)
    for user_id in wanted:
        if user_id not in existing:
            db.add(GroupMember(group_id=group.id, user_id=user_id))
    group.updated_at = _utcnow()
    db.add(group)
    db.commit()
    return _group_out(_get_group(db, group_id))


@router.get("/grants")
def list_grants(
    resource_type: str | None = Query(default=None),
    grantee_type: str | None = Query(default=None),
    grantee_id: int | None = Query(default=None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(ResourceGrant).order_by(ResourceGrant.id.desc())
    if resource_type:
        stmt = stmt.where(ResourceGrant.resource_type == resource_type.strip().lower())
    if grantee_type:
        gtype = grantee_type.strip().lower()
        if gtype not in ALLOWED_GRANTEE_TYPES:
            raise HTTPException(status_code=400, detail="grantee_type 仅支持 user / group")
        stmt = stmt.where(ResourceGrant.grantee_type == gtype)
    if grantee_id is not None:
        stmt = stmt.where(ResourceGrant.grantee_id == int(grantee_id))
    rows = db.scalars(stmt).all()
    return [_grant_out(db, item) for item in rows]


def _permission_item(
    *,
    resource_type: str,
    resource_id: int,
    resource_name: str,
    permission: str,
    source: str,
    source_label: str,
    grant_id: int | None = None,
    grantee_type: str | None = None,
    grantee_id: int | None = None,
    grantee_name: str | None = None,
) -> dict:
    return {
        "resource_type": resource_type,
        "resource_id": resource_id,
        "resource_name": resource_name,
        "permission": permission or "use",
        "source": source,
        "source_label": source_label,
        "grant_id": grant_id,
        "grantee_type": grantee_type,
        "grantee_id": grantee_id,
        "grantee_name": grantee_name or "",
    }


@router.get("/permissions")
def query_permissions(
    subject_type: str = Query(..., description="user 或 group"),
    subject_id: int = Query(..., ge=1),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Query effective permissions for a user or group."""
    stype = (subject_type or "").strip().lower()
    if stype not in ALLOWED_GRANTEE_TYPES:
        raise HTTPException(status_code=400, detail="subject_type 仅支持 user / group")

    items: list[dict] = []
    groups_out: list[dict] = []
    subject: dict

    if stype == "user":
        user = db.get(User, subject_id)
        if not user or not int(getattr(user, "is_active", 1)):
            raise HTTPException(status_code=404, detail="用户不存在或已停用")
        subject = {
            "type": "user",
            "id": user.id,
            "name": user.display_name or user.username,
            "username": user.username,
            "role": user.role,
            "is_admin": is_admin(user),
        }

        owned_kbs = db.scalars(
            select(KnowledgeBase).where(KnowledgeBase.owner_id == user.id).order_by(KnowledgeBase.id.asc())
        ).all()
        for kb in owned_kbs:
            items.append(
                _permission_item(
                    resource_type=RESOURCE_KB,
                    resource_id=int(kb.id),
                    resource_name=kb.name,
                    permission="manage",
                    source="owner",
                    source_label="资源所有者",
                )
            )
        owned_dss = db.scalars(
            select(DataSource).where(DataSource.owner_id == user.id).order_by(DataSource.id.asc())
        ).all()
        for ds in owned_dss:
            items.append(
                _permission_item(
                    resource_type=RESOURCE_DS,
                    resource_id=int(ds.id),
                    resource_name=ds.name,
                    permission="manage",
                    source="owner",
                    source_label="资源所有者",
                )
            )

        direct_grants = db.scalars(
            select(ResourceGrant)
            .where(
                ResourceGrant.grantee_type == "user",
                ResourceGrant.grantee_id == user.id,
            )
            .order_by(ResourceGrant.id.desc())
        ).all()
        for grant in direct_grants:
            row = _grant_out(db, grant)
            items.append(
                _permission_item(
                    resource_type=row["resource_type"],
                    resource_id=row["resource_id"],
                    resource_name=row["resource_name"],
                    permission=row["permission"],
                    source="direct",
                    source_label="直接授权",
                    grant_id=row["id"],
                    grantee_type="user",
                    grantee_id=user.id,
                    grantee_name=subject["name"],
                )
            )

        group_ids = user_group_ids(db, user.id)
        if group_ids:
            groups = db.scalars(select(Group).where(Group.id.in_(group_ids)).order_by(Group.id.asc())).all()
            group_name_map = {int(g.id): g.name for g in groups}
            groups_out = [{"id": int(g.id), "name": g.name} for g in groups]
            group_grants = db.scalars(
                select(ResourceGrant)
                .where(
                    ResourceGrant.grantee_type == "group",
                    ResourceGrant.grantee_id.in_(group_ids),
                )
                .order_by(ResourceGrant.id.desc())
            ).all()
            for grant in group_grants:
                row = _grant_out(db, grant)
                gname = group_name_map.get(int(grant.grantee_id), row["grantee_name"])
                items.append(
                    _permission_item(
                        resource_type=row["resource_type"],
                        resource_id=row["resource_id"],
                        resource_name=row["resource_name"],
                        permission=row["permission"],
                        source="group",
                        source_label=f"用户组：{gname}",
                        grant_id=row["id"],
                        grantee_type="group",
                        grantee_id=int(grant.grantee_id),
                        grantee_name=gname,
                    )
                )
    else:
        group = _get_group(db, subject_id)
        subject = {
            "type": "group",
            "id": group.id,
            "name": group.name,
            "member_count": len(group.members or []),
            "is_admin": False,
        }
        groups_out = [{"id": group.id, "name": group.name}]
        grants = db.scalars(
            select(ResourceGrant)
            .where(
                ResourceGrant.grantee_type == "group",
                ResourceGrant.grantee_id == group.id,
            )
            .order_by(ResourceGrant.id.desc())
        ).all()
        for grant in grants:
            row = _grant_out(db, grant)
            items.append(
                _permission_item(
                    resource_type=row["resource_type"],
                    resource_id=row["resource_id"],
                    resource_name=row["resource_name"],
                    permission=row["permission"],
                    source="direct",
                    source_label="组直接授权",
                    grant_id=row["id"],
                    grantee_type="group",
                    grantee_id=group.id,
                    grantee_name=group.name,
                )
            )

    # Stable display order: owner → direct → group, then resource type/name
    source_rank = {"owner": 0, "direct": 1, "group": 2}
    items.sort(
        key=lambda x: (
            source_rank.get(x.get("source") or "", 9),
            x.get("resource_type") or "",
            (x.get("resource_name") or "").lower(),
            int(x.get("resource_id") or 0),
        )
    )

    return {
        "subject": subject,
        "groups": groups_out,
        "total": len(items),
        "items": items,
        "note": "管理员默认拥有全部资源访问权" if subject.get("is_admin") else "",
    }


@router.post("/grants", status_code=201)
def create_grant(
    payload: GrantCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _validate_grant_target(db, payload)
    rtype = payload.resource_type.strip().lower()
    resource_id = FEATURE_RESOURCE_ID if rtype in CAPABILITY_TYPES else int(payload.resource_id)
    permission = (payload.permission or "use").strip().lower() or "use"
    if rtype in CAPABILITY_TYPES:
        permission = "manage"
    grant = ResourceGrant(
        resource_type=rtype,
        resource_id=resource_id,
        grantee_type=payload.grantee_type.strip().lower(),
        grantee_id=int(payload.grantee_id),
        permission=permission,
        granted_by=admin.id,
    )
    db.add(grant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该授权已存在")
    db.refresh(grant)
    return _grant_out(db, grant)


@router.delete("/grants/{grant_id}", status_code=204)
def delete_grant(
    grant_id: int,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    grant = db.get(ResourceGrant, grant_id)
    if not grant:
        raise HTTPException(status_code=404, detail="授权记录不存在")
    db.delete(grant)
    db.commit()
    return None


@router.get("/options")
def authz_options(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Dropdown data for the admin authorization UI."""
    users = db.scalars(select(User).where(User.is_active == 1).order_by(User.id.asc())).all()
    groups = db.scalars(select(Group).order_by(Group.id.asc())).all()
    kbs = db.scalars(select(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc())).all()
    dss = db.scalars(select(DataSource).order_by(DataSource.updated_at.desc())).all()
    return {
        "users": [
            {
                "id": item.id,
                "username": item.username,
                "display_name": item.display_name or item.username,
                "role": item.role,
            }
            for item in users
        ],
        "groups": [{"id": item.id, "name": item.name} for item in groups],
        "knowledge_bases": [{"id": item.id, "name": item.name} for item in kbs],
        "datasources": [{"id": item.id, "name": item.name} for item in dss],
        "resource_types": [
            {"id": RESOURCE_KB, "label": "知识库", "kind": "entity"},
            {"id": RESOURCE_DS, "label": "数据源", "kind": "entity"},
            {"id": RESOURCE_CAP_AGENT, "label": "Agent 管理", "kind": "capability"},
            {"id": RESOURCE_CAP_MCP, "label": "MCP 管理", "kind": "capability"},
            {"id": RESOURCE_CAP_SKILL, "label": "Skill 管理", "kind": "capability"},
            {"id": RESOURCE_CAP_TOOL, "label": "Tool 设置", "kind": "capability"},
        ],
        "capabilities": [
            {"id": RESOURCE_CAP_AGENT, "label": CAPABILITY_LABELS[RESOURCE_CAP_AGENT]},
            {"id": RESOURCE_CAP_MCP, "label": CAPABILITY_LABELS[RESOURCE_CAP_MCP]},
            {"id": RESOURCE_CAP_SKILL, "label": CAPABILITY_LABELS[RESOURCE_CAP_SKILL]},
            {"id": RESOURCE_CAP_TOOL, "label": CAPABILITY_LABELS[RESOURCE_CAP_TOOL]},
        ],
        "grantee_types": [
            {"id": "user", "label": "用户"},
            {"id": "group", "label": "用户组"},
        ],
    }

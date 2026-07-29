"""Admin CRUD for providers / models / routes / API keys."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps_auth import require_admin
from ..models import ModelDefinition, ModelProvider, ModelRoute, PlatformApiKey, User
from ..services.secret_box import encrypt_secret
from .schemas import (
    ApiKeyCreate,
    ModelDefCreate,
    ModelDefUpdate,
    ProviderCreate,
    ProviderUpdate,
    RouteCreate,
    RouteUpdate,
)
from .security import generate_api_key

router = APIRouter(prefix="/admin", tags=["gateway-admin"])


def _provider_out(p: ModelProvider) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "adapter": p.adapter,
        "base_url": p.base_url,
        "has_api_key": bool(p.api_key_enc),
        "is_active": bool(p.is_active),
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _model_out(m: ModelDefinition) -> dict:
    return {
        "id": m.id,
        "model_id": m.model_id,
        "display_name": m.display_name,
        "provider_id": m.provider_id,
        "provider_name": m.provider.name if m.provider else "",
        "upstream_model": m.upstream_model,
        "price_prompt_per_1k": float(m.price_prompt_per_1k or 0),
        "price_completion_per_1k": float(m.price_completion_per_1k or 0),
        "is_active": bool(m.is_active),
    }


def _route_out(r: ModelRoute) -> dict:
    try:
        ids = json.loads(r.model_ids_json or "[]")
    except Exception:
        ids = []
    return {
        "id": r.id,
        "name": r.name,
        "description": r.description,
        "model_ids": ids,
        "is_active": bool(r.is_active),
    }


@router.get("/providers")
def list_providers(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.scalars(select(ModelProvider).order_by(ModelProvider.id.asc())).all()
    return {"items": [_provider_out(p) for p in rows]}


@router.post("/providers")
def create_provider(
    body: ProviderCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    exists = db.scalar(select(ModelProvider).where(ModelProvider.name == body.name.strip()))
    if exists:
        raise HTTPException(status_code=400, detail="厂商名称已存在")
    row = ModelProvider(
        name=body.name.strip(),
        adapter=body.adapter,
        base_url=(body.base_url or "").strip(),
        api_key_enc=encrypt_secret(body.api_key) if body.api_key else "",
        is_active=1 if body.is_active else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _provider_out(row)


@router.patch("/providers/{provider_id}")
def update_provider(
    provider_id: int,
    body: ProviderUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(ModelProvider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="厂商不存在")
    if body.name is not None:
        row.name = body.name.strip()
    if body.adapter is not None:
        row.adapter = body.adapter
    if body.base_url is not None:
        row.base_url = body.base_url.strip()
    if body.api_key is not None and body.api_key != "":
        row.api_key_enc = encrypt_secret(body.api_key)
    if body.is_active is not None:
        row.is_active = 1 if body.is_active else 0
    db.add(row)
    db.commit()
    db.refresh(row)
    return _provider_out(row)


@router.delete("/providers/{provider_id}")
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(ModelProvider, provider_id)
    if not row:
        raise HTTPException(status_code=404, detail="厂商不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/models")
def list_models(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.scalars(
        select(ModelDefinition)
        .options(joinedload(ModelDefinition.provider))
        .order_by(ModelDefinition.id.asc())
    ).all()
    return {"items": [_model_out(m) for m in rows]}


@router.post("/models")
def create_model(
    body: ModelDefCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(ModelProvider, body.provider_id):
        raise HTTPException(status_code=400, detail="厂商不存在")
    exists = db.scalar(
        select(ModelDefinition).where(ModelDefinition.model_id == body.model_id.strip())
    )
    if exists:
        raise HTTPException(status_code=400, detail="逻辑模型 ID 已存在")
    row = ModelDefinition(
        model_id=body.model_id.strip(),
        display_name=body.display_name or body.model_id,
        provider_id=body.provider_id,
        upstream_model=body.upstream_model.strip(),
        price_prompt_per_1k=body.price_prompt_per_1k,
        price_completion_per_1k=body.price_completion_per_1k,
        is_active=1 if body.is_active else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    row = db.scalar(
        select(ModelDefinition)
        .options(joinedload(ModelDefinition.provider))
        .where(ModelDefinition.id == row.id)
    )
    return _model_out(row)


@router.patch("/models/{model_pk}")
def update_model(
    model_pk: int,
    body: ModelDefUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(ModelDefinition, model_pk)
    if not row:
        raise HTTPException(status_code=404, detail="逻辑模型不存在")
    if body.display_name is not None:
        row.display_name = body.display_name
    if body.provider_id is not None:
        if not db.get(ModelProvider, body.provider_id):
            raise HTTPException(status_code=400, detail="厂商不存在")
        row.provider_id = body.provider_id
    if body.upstream_model is not None:
        row.upstream_model = body.upstream_model.strip()
    if body.price_prompt_per_1k is not None:
        row.price_prompt_per_1k = body.price_prompt_per_1k
    if body.price_completion_per_1k is not None:
        row.price_completion_per_1k = body.price_completion_per_1k
    if body.is_active is not None:
        row.is_active = 1 if body.is_active else 0
    db.add(row)
    db.commit()
    row = db.scalar(
        select(ModelDefinition)
        .options(joinedload(ModelDefinition.provider))
        .where(ModelDefinition.id == model_pk)
    )
    return _model_out(row)


@router.delete("/models/{model_pk}")
def delete_model(
    model_pk: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(ModelDefinition, model_pk)
    if not row:
        raise HTTPException(status_code=404, detail="逻辑模型不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/routes")
def list_routes(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.scalars(select(ModelRoute).order_by(ModelRoute.id.asc())).all()
    return {"items": [_route_out(r) for r in rows]}


@router.post("/routes")
def create_route(
    body: RouteCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    exists = db.scalar(select(ModelRoute).where(ModelRoute.name == body.name.strip()))
    if exists:
        raise HTTPException(status_code=400, detail="路由名称已存在")
    row = ModelRoute(
        name=body.name.strip(),
        description=body.description or "",
        model_ids_json=json.dumps(body.model_ids or [], ensure_ascii=False),
        is_active=1 if body.is_active else 0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _route_out(row)


@router.patch("/routes/{route_id}")
def update_route(
    route_id: int,
    body: RouteUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(ModelRoute, route_id)
    if not row:
        raise HTTPException(status_code=404, detail="路由不存在")
    if body.description is not None:
        row.description = body.description
    if body.model_ids is not None:
        row.model_ids_json = json.dumps(body.model_ids, ensure_ascii=False)
    if body.is_active is not None:
        row.is_active = 1 if body.is_active else 0
    db.add(row)
    db.commit()
    db.refresh(row)
    return _route_out(row)


@router.get("/api-keys")
def list_api_keys(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.scalars(select(PlatformApiKey).order_by(PlatformApiKey.id.desc())).all()
    return {
        "items": [
            {
                "id": r.id,
                "name": r.name,
                "key_prefix": r.key_prefix,
                "scopes": r.scopes,
                "is_active": bool(r.is_active) and r.revoked_at is None,
                "owner_user_id": r.owner_user_id,
                "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("/api-keys")
def create_api_key(
    body: ApiKeyCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    raw, prefix, digest = generate_api_key()
    row = PlatformApiKey(
        name=(body.name or "").strip() or "unnamed",
        key_prefix=prefix,
        key_hash=digest,
        owner_user_id=admin.id,
        scopes=(body.scopes or "chat").strip() or "chat",
        is_active=1,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "name": row.name,
        "key_prefix": row.key_prefix,
        "api_key": raw,
        "scopes": row.scopes,
        "message": "请立即保存 API Key，明文仅展示一次",
    }


@router.post("/api-keys/{key_id}/revoke")
def revoke_api_key(
    key_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = db.get(PlatformApiKey, key_id)
    if not row:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    row.is_active = 0
    row.revoked_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    return {"ok": True}

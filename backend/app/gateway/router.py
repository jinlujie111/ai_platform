"""Public Gateway HTTP routes."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps_auth import require_admin, require_usable_user
from ..models import User
from .admin_api import router as admin_router
from .errors import GatewayError, error_response
from .schemas import ChatCompletionRequest, ModelTestRequest
from .security import GatewayPrincipal, require_gateway_principal
from .service import chat_completion, test_model_connection
from .usage import aggregate_usage

router = APIRouter(prefix="/api/gateway/v1", tags=["gateway"])
router.include_router(admin_router)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or ""


@router.post("/chat/completions")
async def gateway_chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: GatewayPrincipal = Depends(require_gateway_principal),
):
    if body.stream:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "unsupported", "message": "暂不支持 stream=true"}},
        )
    source = (body.metadata.source if body.metadata else None) or (
        "api_key" if principal.api_key else "web_chat"
    )
    try:
        result = await chat_completion(
            db,
            model=body.model,
            messages=body.messages,
            temperature=body.temperature,
            tools=body.tools,
            tool_choice=body.tool_choice,
            timeout=body.timeout,
            upstream=body.upstream,
            user_id=principal.user_id,
            api_key_id=principal.api_key_id,
            is_admin=principal.is_admin,
            source=source,
            request_id=_request_id(request),
        )
    except GatewayError as exc:
        return error_response(exc)

    raw = dict(result.raw or {})
    raw["gateway"] = {
        "model_id": result.logical_model_id,
        "provider": result.provider,
        "upstream_model": result.upstream_model,
        "latency_ms": result.latency_ms,
        "request_id": _request_id(request),
        "cost_cny": result.cost_cny,
        "estimated": result.usage.estimated,
    }
    if "usage" not in raw:
        raw["usage"] = {
            "prompt_tokens": result.usage.prompt_tokens,
            "completion_tokens": result.usage.completion_tokens,
            "total_tokens": result.usage.total_tokens,
            "estimated": result.usage.estimated,
        }
    return raw


@router.post("/models/test")
async def gateway_models_test(
    body: ModelTestRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: GatewayPrincipal = Depends(require_gateway_principal),
):
    try:
        result = await test_model_connection(
            db,
            model=body.model,
            upstream=body.upstream,
            user_id=principal.user_id,
            api_key_id=principal.api_key_id,
            is_admin=principal.is_admin,
            request_id=_request_id(request),
        )
        return {"ok": True, "message": "连接成功", "reply": (result.text or "")[:200]}
    except GatewayError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "message": exc.message, "code": exc.code},
            headers=exc.headers or None,
        )


@router.get("/usage")
def gateway_usage(
    request: Request,
    db: Session = Depends(get_db),
    principal: GatewayPrincipal = Depends(require_gateway_principal),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
    group_by: str = Query(default="model"),
):
    def _parse(s: str | None) -> datetime | None:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    uid = None if principal.is_admin else principal.user_id
    items = aggregate_usage(
        db,
        date_from=_parse(date_from),
        date_to=_parse(date_to),
        group_by=group_by,
        user_id=uid,
    )
    return {"items": items, "group_by": group_by}


@router.get("/models")
def list_logical_models_for_admin(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Admin-facing list of active logical models + routes."""
    from sqlalchemy import select

    from ..models import ModelDefinition, ModelRoute

    models = db.scalars(
        select(ModelDefinition).where(ModelDefinition.is_active == 1).order_by(ModelDefinition.id.asc())
    ).all()
    routes = db.scalars(
        select(ModelRoute).where(ModelRoute.is_active == 1).order_by(ModelRoute.id.asc())
    ).all()
    import json

    return {
        "models": [
            {
                "model_id": m.model_id,
                "display_name": m.display_name or m.model_id,
                "provider_id": m.provider_id,
            }
            for m in models
        ],
        "routes": [
            {
                "name": r.name,
                "description": r.description,
                "model_ids": json.loads(r.model_ids_json or "[]"),
            }
            for r in routes
        ],
    }


@router.get("/catalog")
def list_gateway_catalog(
    db: Session = Depends(get_db),
    _: User = Depends(require_usable_user),
):
    """Usable platform models/routes for all logged-in users (no secrets).

    Only includes logical models whose provider has an API key configured,
    and routes that still have at least one such model.
    """
    import json

    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from ..models import ModelDefinition, ModelRoute

    defs = db.scalars(
        select(ModelDefinition)
        .options(joinedload(ModelDefinition.provider))
        .where(ModelDefinition.is_active == 1)
        .order_by(ModelDefinition.id.asc())
    ).all()
    usable_ids: list[str] = []
    models_out = []
    for m in defs:
        provider = m.provider
        if not provider or not int(provider.is_active or 0):
            continue
        if not (provider.api_key_enc or "").strip():
            continue
        usable_ids.append(m.model_id)
        models_out.append(
            {
                "model_id": m.model_id,
                "display_name": m.display_name or m.model_id,
                "kind": "model",
                "provider_name": provider.name,
            }
        )
    usable_set = set(usable_ids)
    routes_out = []
    for r in db.scalars(
        select(ModelRoute).where(ModelRoute.is_active == 1).order_by(ModelRoute.id.asc())
    ).all():
        try:
            ids = [str(x) for x in json.loads(r.model_ids_json or "[]") if x]
        except Exception:
            ids = []
        available = [x for x in ids if x in usable_set]
        if not available:
            continue
        routes_out.append(
            {
                "model_id": r.name,
                "display_name": r.name,
                "kind": "route",
                "description": r.description or "",
                "model_ids": available,
            }
        )
    return {"models": models_out, "routes": routes_out}

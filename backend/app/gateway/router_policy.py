"""Resolve logical model / route strategy to UpstreamRef."""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from ..models import ModelDefinition, ModelProvider, ModelRoute
from ..services.secret_box import decrypt_secret
from .adapters.base import UpstreamRef
from .errors import GatewayError
from .schemas import UpstreamConfig

logger = logging.getLogger(__name__)

ADAPTER_ALIASES = {
    "openai": "openai_compatible",
    "deepseek": "openai_compatible",
    "qwen": "openai_compatible",
    "moonshot": "openai_compatible",
    "minimax": "openai_compatible",
    "zhipu": "openai_compatible",
    "spark": "openai_compatible",
    "baidu": "openai_compatible",
    "custom": "openai_compatible",
    "openai_compatible": "openai_compatible",
    "anthropic": "anthropic",
    "google": "google",
}


def provider_to_adapter(provider: str) -> str:
    key = (provider or "custom").lower().strip()
    return ADAPTER_ALIASES.get(key, "openai_compatible")


def upstream_from_ephemeral(cfg: UpstreamConfig, *, logical_model_id: str = "") -> UpstreamRef:
    if not cfg.api_key:
        raise GatewayError("upstream_auth", "当前模型未配置 API Key", status_code=400)
    if not cfg.model:
        raise GatewayError("model_not_found", "当前模型未配置模型名称", status_code=400)
    adapter = provider_to_adapter(cfg.provider)
    if adapter == "openai_compatible" and not (cfg.base_url or "").strip():
        raise GatewayError("upstream_error", "缺少官方连接 (Base URL)", status_code=400)
    return UpstreamRef(
        provider_type=adapter,
        provider_name=(cfg.provider or "custom").lower().strip(),
        base_url=(cfg.base_url or "").strip(),
        api_key=cfg.api_key,
        model=cfg.model,
        logical_model_id=logical_model_id or cfg.model,
    )


def _definition_to_upstream(defn: ModelDefinition) -> UpstreamRef:
    provider: ModelProvider = defn.provider
    if not provider or not int(provider.is_active or 0):
        raise GatewayError("model_not_found", f"厂商未启用：{defn.model_id}", status_code=404)
    try:
        api_key = decrypt_secret(provider.api_key_enc or "")
    except ValueError as exc:
        raise GatewayError("upstream_auth", str(exc), status_code=500) from exc
    if not api_key:
        raise GatewayError(
            "upstream_auth",
            f"逻辑模型 {defn.model_id} 对应厂商未配置 API Key",
            status_code=400,
        )
    adapter = (provider.adapter or "openai_compatible").lower().strip()
    if adapter not in ("openai_compatible", "anthropic", "google"):
        adapter = provider_to_adapter(adapter)
    return UpstreamRef(
        provider_type=adapter,
        provider_name=provider.name,
        base_url=(provider.base_url or "").strip(),
        api_key=api_key,
        model=defn.upstream_model,
        price_prompt_per_1k=float(defn.price_prompt_per_1k or 0),
        price_completion_per_1k=float(defn.price_completion_per_1k or 0),
        logical_model_id=defn.model_id,
    )


def get_definition(db: Session, model_id: str) -> ModelDefinition | None:
    return db.scalar(
        select(ModelDefinition)
        .options(joinedload(ModelDefinition.provider))
        .where(ModelDefinition.model_id == model_id, ModelDefinition.is_active == 1)
    )


def resolve_route_model_ids(db: Session, route_name: str) -> list[str]:
    route = db.scalar(
        select(ModelRoute).where(ModelRoute.name == route_name, ModelRoute.is_active == 1)
    )
    if not route:
        return []
    try:
        ids = json.loads(route.model_ids_json or "[]")
    except Exception:
        ids = []
    return [str(x) for x in ids if x]


def resolve_upstreams(
    db: Session,
    model: str,
    *,
    ephemeral: Optional[UpstreamConfig] = None,
) -> list[UpstreamRef]:
    """Return ordered UpstreamRef list (preferred first, then fallbacks)."""
    name = (model or "default").strip() or "default"

    # Compat: frontend still sends full upstream config
    if ephemeral and (ephemeral.api_key or ephemeral.model or ephemeral.base_url):
        return [upstream_from_ephemeral(ephemeral, logical_model_id=name)]

    # Direct logical model
    defn = get_definition(db, name)
    if defn:
        return [_definition_to_upstream(defn)]

    # Route strategy
    model_ids = resolve_route_model_ids(db, name)
    if not model_ids and name == "default":
        # Fallback: first active definition
        first = db.scalar(
            select(ModelDefinition)
            .options(joinedload(ModelDefinition.provider))
            .where(ModelDefinition.is_active == 1)
            .order_by(ModelDefinition.id.asc())
        )
        if first:
            return [_definition_to_upstream(first)]

    if not model_ids:
        raise GatewayError(
            "model_not_found",
            f"未找到逻辑模型或路由策略：{name}",
            status_code=404,
        )

    refs: list[UpstreamRef] = []
    for mid in model_ids:
        d = get_definition(db, mid)
        if not d:
            logger.warning("route %s references missing model %s", name, mid)
            continue
        try:
            refs.append(_definition_to_upstream(d))
        except GatewayError as exc:
            logger.warning("skip model %s: %s", mid, exc.message)
            continue
    if not refs:
        raise GatewayError(
            "model_not_found",
            f"路由 {name} 无可用上游模型",
            status_code=404,
        )
    return refs

"""Seed default providers / models / routes (idempotent)."""
from __future__ import annotations

import json
import logging
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ModelDefinition, ModelProvider, ModelRoute
from ..services.secret_box import encrypt_secret

logger = logging.getLogger(__name__)


def _ensure_provider(
    db: Session,
    *,
    name: str,
    adapter: str,
    base_url: str,
    api_key: str = "",
) -> ModelProvider:
    row = db.scalar(select(ModelProvider).where(ModelProvider.name == name))
    if row:
        # Backfill API key from env when provider was seeded earlier without one
        if api_key and not (row.api_key_enc or "").strip():
            row.api_key_enc = encrypt_secret(api_key)
            db.add(row)
        return row
    row = ModelProvider(
        name=name,
        adapter=adapter,
        base_url=base_url,
        api_key_enc=encrypt_secret(api_key) if api_key else "",
        is_active=1,
    )
    db.add(row)
    db.flush()
    return row


def _ensure_model(
    db: Session,
    *,
    model_id: str,
    display_name: str,
    provider: ModelProvider,
    upstream_model: str,
    price_prompt: float,
    price_completion: float,
) -> ModelDefinition:
    row = db.scalar(select(ModelDefinition).where(ModelDefinition.model_id == model_id))
    if row:
        return row
    row = ModelDefinition(
        model_id=model_id,
        display_name=display_name,
        provider_id=provider.id,
        upstream_model=upstream_model,
        price_prompt_per_1k=price_prompt,
        price_completion_per_1k=price_completion,
        is_active=1,
    )
    db.add(row)
    db.flush()
    return row


def _ensure_route(db: Session, *, name: str, description: str, model_ids: list[str]) -> ModelRoute:
    row = db.scalar(select(ModelRoute).where(ModelRoute.name == name))
    if row:
        return row
    row = ModelRoute(
        name=name,
        description=description,
        model_ids_json=json.dumps(model_ids, ensure_ascii=False),
        is_active=1,
    )
    db.add(row)
    db.flush()
    return row


def seed_gateway_defaults(db: Session) -> None:
    """Create sample providers/models/routes if missing.

    API keys prefer env overrides so seeds are usable out of the box when configured.
    """
    deepseek_key = (os.getenv("GATEWAY_SEED_DEEPSEEK_KEY") or os.getenv("FEISHU_LLM_API_KEY") or "").strip()
    qwen_key = (os.getenv("GATEWAY_SEED_QWEN_KEY") or "").strip()
    openai_key = (os.getenv("GATEWAY_SEED_OPENAI_KEY") or "").strip()
    anthropic_key = (os.getenv("GATEWAY_SEED_ANTHROPIC_KEY") or "").strip()

    deepseek = _ensure_provider(
        db,
        name="deepseek",
        adapter="openai_compatible",
        base_url="https://api.deepseek.com",
        api_key=deepseek_key,
    )
    qwen = _ensure_provider(
        db,
        name="qwen",
        adapter="openai_compatible",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key=qwen_key,
    )
    openai = _ensure_provider(
        db,
        name="openai",
        adapter="openai_compatible",
        base_url="https://api.openai.com/v1",
        api_key=openai_key,
    )
    anthropic = _ensure_provider(
        db,
        name="anthropic",
        adapter="anthropic",
        base_url="https://api.anthropic.com",
        api_key=anthropic_key,
    )

    _ensure_model(
        db,
        model_id="deepseek-chat",
        display_name="DeepSeek Chat",
        provider=deepseek,
        upstream_model="deepseek-chat",
        price_prompt=0.001,
        price_completion=0.002,
    )
    _ensure_model(
        db,
        model_id="qwen-turbo",
        display_name="通义千问 Turbo",
        provider=qwen,
        upstream_model="qwen-turbo",
        price_prompt=0.0008,
        price_completion=0.002,
    )
    _ensure_model(
        db,
        model_id="gpt-4o-mini",
        display_name="GPT-4o mini",
        provider=openai,
        upstream_model="gpt-4o-mini",
        price_prompt=0.0011,
        price_completion=0.0044,
    )
    _ensure_model(
        db,
        model_id="claude-sonnet",
        display_name="Claude Sonnet",
        provider=anthropic,
        upstream_model="claude-sonnet-4-20250514",
        price_prompt=0.022,
        price_completion=0.11,
    )

    _ensure_route(
        db,
        name="cheap",
        description="低成本优先",
        model_ids=["deepseek-chat", "qwen-turbo"],
    )
    _ensure_route(
        db,
        name="quality",
        description="高质量优先",
        model_ids=["gpt-4o-mini", "claude-sonnet", "deepseek-chat"],
    )
    _ensure_route(
        db,
        name="default",
        description="默认路由",
        model_ids=["deepseek-chat", "qwen-turbo"],
    )
    db.commit()
    logger.info("gateway seed defaults ensured")

"""Pydantic schemas for Gateway API."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class UpstreamConfig(BaseModel):
    """Ephemeral upstream (compat with current frontend model config)."""

    provider: str = "custom"
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class ChatMetadata(BaseModel):
    source: str = "web_chat"
    conversation_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str = "default"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 0.7
    stream: bool = False
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[str] = None
    timeout: float = 90.0
    upstream: Optional[UpstreamConfig] = None
    metadata: Optional[ChatMetadata] = None


class ModelTestRequest(BaseModel):
    model: str = ""
    upstream: Optional[UpstreamConfig] = None


class ProviderCreate(BaseModel):
    name: str
    adapter: Literal["openai_compatible", "anthropic", "google"] = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    is_active: bool = True


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    adapter: Optional[Literal["openai_compatible", "anthropic", "google"]] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    is_active: Optional[bool] = None


class ModelDefCreate(BaseModel):
    model_id: str
    display_name: str = ""
    provider_id: int
    upstream_model: str
    price_prompt_per_1k: float = 0.0
    price_completion_per_1k: float = 0.0
    is_active: bool = True


class ModelDefUpdate(BaseModel):
    display_name: Optional[str] = None
    provider_id: Optional[int] = None
    upstream_model: Optional[str] = None
    price_prompt_per_1k: Optional[float] = None
    price_completion_per_1k: Optional[float] = None
    is_active: Optional[bool] = None


class RouteCreate(BaseModel):
    name: str
    description: str = ""
    model_ids: list[str] = Field(default_factory=list)
    is_active: bool = True


class RouteUpdate(BaseModel):
    description: Optional[str] = None
    model_ids: Optional[list[str]] = None
    is_active: Optional[bool] = None


class ApiKeyCreate(BaseModel):
    name: str = ""
    scopes: str = "chat"

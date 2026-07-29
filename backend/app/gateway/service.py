"""Gateway orchestration: resolve → rate-limit → adapt → ledger."""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from .adapters import dispatch_chat
from .adapters.base import ChatResult
from .errors import GatewayError, map_upstream_error
from .rate_limit import check_daily_tokens, check_rate_limit, record_daily_tokens
from .router_policy import resolve_upstreams
from .schemas import UpstreamConfig
from .usage import write_ledger

logger = logging.getLogger(__name__)


async def chat_completion(
    db: Session,
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float = 0.7,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    timeout: float = 90.0,
    upstream: Optional[UpstreamConfig] = None,
    user_id: int | None = None,
    api_key_id: int | None = None,
    is_admin: bool = False,
    source: str = "web_chat",
    request_id: str = "",
) -> ChatResult:
    rid = (request_id or "").strip() or uuid.uuid4().hex
    check_rate_limit(user_id=user_id, api_key_id=api_key_id, is_admin=is_admin)
    check_daily_tokens(user_id=user_id, is_admin=is_admin)

    refs = resolve_upstreams(db, model, ephemeral=upstream)
    last_error: GatewayError | None = None

    for idx, ref in enumerate(refs):
        try:
            result = await dispatch_chat(
                ref,
                messages,
                temperature=temperature,
                tools=tools,
                tool_choice=tool_choice,
                timeout=timeout,
            )
            write_ledger(
                db,
                result=result,
                request_id=rid,
                user_id=user_id,
                api_key_id=api_key_id,
                source=source,
                status="ok",
            )
            record_daily_tokens(user_id=user_id, tokens=result.usage.total_tokens)
            return result
        except GatewayError as exc:
            last_error = exc
            logger.warning(
                "gateway upstream failed model=%s provider=%s: %s",
                ref.logical_model_id,
                ref.provider_name,
                exc.message,
            )
            if idx + 1 < len(refs):
                continue
            write_ledger(
                db,
                result=None,
                request_id=rid,
                user_id=user_id,
                api_key_id=api_key_id,
                source=source,
                status="error",
                error_code=exc.code,
                model_id=ref.logical_model_id,
                provider=ref.provider_name,
                upstream_model=ref.model,
            )
            raise
        except Exception as exc:
            mapped = map_upstream_error(exc)
            last_error = mapped
            logger.warning(
                "gateway upstream exception model=%s: %s",
                ref.logical_model_id,
                mapped.message,
            )
            if idx + 1 < len(refs):
                continue
            write_ledger(
                db,
                result=None,
                request_id=rid,
                user_id=user_id,
                api_key_id=api_key_id,
                source=source,
                status="error",
                error_code=mapped.code,
                model_id=ref.logical_model_id,
                provider=ref.provider_name,
                upstream_model=ref.model,
            )
            raise mapped from exc

    raise last_error or GatewayError("upstream_error", "无可用上游", status_code=502)


async def test_model_connection(
    db: Session,
    *,
    model: str = "",
    upstream: Optional[UpstreamConfig] = None,
    user_id: int | None = None,
    api_key_id: int | None = None,
    is_admin: bool = False,
    request_id: str = "",
) -> ChatResult:
    from ..llm import SYSTEM_PROMPT

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "请只回复：连接成功"},
    ]
    return await chat_completion(
        db,
        model=model or (upstream.model if upstream else "default"),
        messages=messages,
        temperature=0.0,
        timeout=45.0,
        upstream=upstream,
        user_id=user_id,
        api_key_id=api_key_id,
        is_admin=is_admin,
        source="test",
        request_id=request_id,
    )


async def chat_text(
    db: Session,
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    message: str,
    history: Optional[list[dict[str, str]]] = None,
    system_context: str = "",
    user_id: int | None = None,
    source: str = "web_chat",
    request_id: str = "",
    is_admin: bool = False,
    use_gateway: bool = False,
) -> str:
    """Compat helper matching old call_llm signature via Gateway."""
    from ..llm import SYSTEM_PROMPT

    system_prompt = SYSTEM_PROMPT
    if system_context:
        system_prompt += (
            "\n\n## 知识库上下文\n"
            "仅依据下列检索内容回答与知识库相关的事实；信息不足时明确说明。"
            "引用事实时使用 [来源 N] 标记，不要编造来源。\n\n"
            + system_context
        )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    upstream = None
    if not use_gateway:
        upstream = UpstreamConfig(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )

    result = await chat_completion(
        db,
        model=model or "default",
        messages=messages,
        upstream=upstream,
        user_id=user_id,
        is_admin=is_admin,
        source=source,
        request_id=request_id,
    )
    return result.text


async def chat_messages_raw(
    db: Session,
    *,
    provider: str,
    model: str,
    api_key: str,
    base_url: str,
    messages: list[dict[str, Any]],
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    temperature: float = 0.7,
    timeout: float = 90.0,
    user_id: int | None = None,
    source: str = "agent",
    request_id: str = "",
    is_admin: bool = False,
    use_gateway: bool = False,
) -> dict[str, Any]:
    """Return OpenAI-shaped raw dict for tool loops."""
    upstream = None
    if not use_gateway:
        upstream = UpstreamConfig(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
    result = await chat_completion(
        db,
        model=model or "default",
        messages=messages,
        temperature=temperature,
        tools=tools,
        tool_choice=tool_choice,
        timeout=timeout,
        upstream=upstream,
        user_id=user_id,
        is_admin=is_admin,
        source=source,
        request_id=request_id,
    )
    return result.raw

"""Adapter package exports."""
from __future__ import annotations

from typing import Any, Optional

from . import anthropic, google, openai_compatible
from .base import ChatResult, UpstreamRef, calc_cost_cny


async def dispatch_chat(
    upstream: UpstreamRef,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.7,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    timeout: float = 90.0,
) -> ChatResult:
    import time

    adapter = (upstream.provider_type or "openai_compatible").lower().strip()
    t0 = time.perf_counter()

    if adapter == "anthropic":
        raw = await anthropic.chat(
            upstream, messages, temperature=temperature, timeout=timeout
        )
        text = ((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = anthropic.usage_from_raw(raw, messages, text)
        tool_calls = []
    elif adapter == "google":
        raw = await google.chat(
            upstream, messages, temperature=temperature, timeout=timeout
        )
        text = ((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        usage = google.usage_from_raw(raw, messages, text)
        tool_calls = []
    else:
        raw = await openai_compatible.chat(
            upstream,
            messages,
            temperature=temperature,
            tools=tools,
            tool_choice=tool_choice,
            timeout=timeout,
        )
        msg = ((raw.get("choices") or [{}])[0].get("message") or {})
        text = openai_compatible.extract_openai_text(raw) if not msg.get("tool_calls") else (msg.get("content") or "")
        if msg.get("tool_calls") and not text:
            try:
                text = ""
            except Exception:
                text = ""
        usage = openai_compatible.usage_from_raw(raw, messages, text or "")
        tool_calls = list(msg.get("tool_calls") or [])

    latency_ms = int((time.perf_counter() - t0) * 1000)
    cost = calc_cost_cny(usage, upstream)
    return ChatResult(
        text=text or "",
        raw=raw,
        usage=usage,
        provider=upstream.provider_name,
        upstream_model=upstream.model,
        logical_model_id=upstream.logical_model_id or upstream.model,
        latency_ms=latency_ms,
        cost_cny=cost,
        tool_calls=tool_calls,
    )

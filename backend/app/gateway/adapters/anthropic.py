"""Anthropic Messages API adapter."""
from __future__ import annotations

from typing import Any

import httpx

from .base import UpstreamRef, parse_usage


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _extract_error(data: Any, status: int, raw: str) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            return f"HTTP {status}: {err.get('message') or err}"
        if data.get("message"):
            return f"HTTP {status}: {data.get('message')}"
    return f"HTTP {status}: {(raw or '')[:300] or '请求失败'}"


async def chat(
    upstream: UpstreamRef,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.7,
    timeout: float = 90.0,
    **_kwargs: Any,
) -> dict[str, Any]:
    base = _normalize_base_url(upstream.base_url) or "https://api.anthropic.com"
    url = f"{base}/v1/messages" if not base.endswith("/messages") else base

    system_parts: list[str] = []
    anth_messages: list[dict[str, str]] = []
    for item in messages or []:
        role = item.get("role")
        content = item.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if role == "system":
            system_parts.append(content)
            continue
        if role in ("user", "assistant"):
            anth_messages.append({"role": role, "content": content})

    headers = {
        "x-api-key": upstream.api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": upstream.model,
        "max_tokens": 2048,
        "messages": anth_messages or [{"role": "user", "content": ""}],
        "temperature": temperature,
    }
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error(data, resp.status_code, resp.text))
        if not isinstance(data, dict):
            raise RuntimeError("Anthropic 返回格式异常")
        content = data.get("content") or []
        texts = [
            c.get("text", "")
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        ]
        text = "\n".join(t for t in texts if t).strip()
        return {
            "id": data.get("id") or "",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": data.get("stop_reason") or "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int((data.get("usage") or {}).get("input_tokens") or 0),
                "completion_tokens": int((data.get("usage") or {}).get("output_tokens") or 0),
                "total_tokens": int((data.get("usage") or {}).get("input_tokens") or 0)
                + int((data.get("usage") or {}).get("output_tokens") or 0),
            },
            "raw_anthropic": data,
        }


def usage_from_raw(raw: dict[str, Any], messages: list[dict[str, Any]], reply: str):
    return parse_usage(raw, messages=messages, reply=reply)

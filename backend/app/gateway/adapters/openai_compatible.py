"""OpenAI-compatible chat adapter (OpenAI / DeepSeek / Qwen / custom)."""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .base import UpstreamRef, parse_usage


def _normalize_base_url(base_url: str) -> str:
    return (base_url or "").strip().rstrip("/")


def _openai_chat_url(base_url: str) -> str:
    base = _normalize_base_url(base_url)
    if not base:
        raise ValueError("缺少官方连接 (Base URL)")
    if base.endswith("/chat/completions"):
        return base
    return f"{base}/chat/completions"


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return {"raw": resp.text}


def _extract_error(data: Any, status: int, raw: str) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("msg") or str(err)
            return f"HTTP {status}: {msg}"
        if isinstance(err, str):
            return f"HTTP {status}: {err}"
        if data.get("message"):
            return f"HTTP {status}: {data.get('message')}"
    text = (raw or "").strip()
    return f"HTTP {status}: {text[:300] or '请求失败'}"


def extract_openai_text(data: Any) -> str:
    if not isinstance(data, dict):
        raise RuntimeError("模型返回格式异常")
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("模型未返回内容")
    choice = choices[0] or {}
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        text = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        ).strip()
        if text:
            return text
    if isinstance(content, str) and content.strip():
        return content.strip()
    text = choice.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    # tool-only turn may have empty content
    if message.get("tool_calls"):
        return ""
    raise RuntimeError("模型返回内容为空")


async def chat(
    upstream: UpstreamRef,
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.7,
    tools: Optional[list[dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    url = _openai_chat_url(upstream.base_url)
    headers = {
        "Authorization": f"Bearer {upstream.api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": upstream.model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        if tool_choice:
            payload["tool_choice"] = tool_choice

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error(data, resp.status_code, resp.text))
        return data if isinstance(data, dict) else {"raw": data}


def usage_from_raw(raw: dict[str, Any], messages: list[dict[str, Any]], reply: str):
    return parse_usage(raw, messages=messages, reply=reply)

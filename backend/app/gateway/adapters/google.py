"""Google Gemini generateContent adapter."""
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
    base = _normalize_base_url(upstream.base_url) or (
        "https://generativelanguage.googleapis.com/v1beta"
    )
    api_key = upstream.api_key
    if "generateContent" in base:
        url = f"{base}?key={api_key}" if "key=" not in base else base
    else:
        url = f"{base}/models/{upstream.model}:generateContent?key={api_key}"

    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for item in messages or []:
        role = item.get("role")
        content = item.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if role == "system":
            system_parts.append(content)
            continue
        g_role = "model" if role == "assistant" else "user"
        contents.append({"role": g_role, "parts": [{"text": content}]})

    payload: dict[str, Any] = {
        "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
        "generationConfig": {"temperature": temperature},
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers={"Content-Type": "application/json"}, json=payload)
        data = _safe_json(resp)
        if resp.status_code >= 400:
            raise RuntimeError(_extract_error(data, resp.status_code, resp.text))
        if not isinstance(data, dict):
            raise RuntimeError("Google Gemini 返回格式异常")
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Google Gemini 返回为空")
        parts = (((candidates[0] or {}).get("content") or {}).get("parts")) or []
        text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
        usage_meta = data.get("usageMetadata") or {}
        return {
            "id": "",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": int(usage_meta.get("promptTokenCount") or 0),
                "completion_tokens": int(usage_meta.get("candidatesTokenCount") or 0),
                "total_tokens": int(usage_meta.get("totalTokenCount") or 0),
            },
            "raw_google": data,
        }


def usage_from_raw(raw: dict[str, Any], messages: list[dict[str, Any]], reply: str):
    return parse_usage(raw, messages=messages, reply=reply)

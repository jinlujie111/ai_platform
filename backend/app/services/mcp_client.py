"""Minimal HTTP MCP client: tools/list + tools/call for chat agent."""
from __future__ import annotations

import json
from typing import Any

import httpx


def resolve_mcp_server(name: str, config: dict[str, Any]) -> dict[str, Any]:
    servers = config.get("mcpServers")
    if isinstance(servers, dict):
        server = servers.get(name)
        if server is None and len(servers) == 1:
            server = next(iter(servers.values()))
        if not isinstance(server, dict):
            raise ValueError("mcp.json 中未找到对应的 MCP 服务器配置")
        return server
    if isinstance(config, dict) and (config.get("url") or config.get("command")):
        return config
    raise ValueError("无效的 MCP 配置")


def _headers(server: dict[str, Any]) -> dict[str, str]:
    raw = server.get("headers") if isinstance(server.get("headers"), dict) else {}
    headers = {str(k): str(v) for k, v in raw.items()}
    headers.setdefault("Accept", "application/json, text/event-stream")
    headers.setdefault("Content-Type", "application/json")
    # Project MCP config fields (preferred over env): token / proxy
    token = str(server.get("token") or server.get("apiKey") or server.get("api_key") or "").strip()
    if token:
        headers.setdefault("X-Tushare-Token", token)
        headers.setdefault("Authorization", f"Bearer {token}")
    proxy = str(server.get("proxy") or "").strip()
    if proxy:
        headers.setdefault("X-Tushare-Proxy", proxy)
    return headers


def _parse_jsonrpc_body(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    # SSE: data: {...}
    if "data:" in text and ("\n" in text or text.startswith("data:")):
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    try:
                        return json.loads(payload)
                    except json.JSONDecodeError:
                        continue
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"MCP 响应不是合法 JSON：{exc}") from exc


async def _jsonrpc(
    url: str,
    headers: dict[str, str],
    method: str,
    params: dict[str, Any] | None = None,
    *,
    timeout: float = 20.0,
) -> Any:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=8.0), follow_redirects=True) as client:
        response = await client.post(url, headers=headers, json=payload)
        body = _parse_jsonrpc_body(response.text)
        if response.status_code >= 400 and not body:
            raise ValueError(f"MCP HTTP {response.status_code}")
        if isinstance(body, dict) and body.get("error"):
            err = body["error"]
            if isinstance(err, dict):
                raise ValueError(err.get("message") or json.dumps(err, ensure_ascii=False))
            raise ValueError(str(err))
        if isinstance(body, dict) and "result" in body:
            return body["result"]
        if response.status_code >= 400:
            raise ValueError(f"MCP HTTP {response.status_code}: {response.text[:300]}")
        return body


async def list_mcp_tools(name: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return OpenAI-style tool definitions prefixed with mcp__{safe}__."""
    server = resolve_mcp_server(name, config)
    url = str(server.get("url") or server.get("serverUrl") or "").strip()
    command = str(server.get("command") or "").strip()
    if command and not url:
        raise ValueError(f"MCP「{name}」为 stdio 模式，对话暂仅支持 HTTP/SSE URL")
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"MCP「{name}」URL 无效")

    # Best-effort initialize (some servers require it)
    try:
        await _jsonrpc(
            url,
            _headers(server),
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "ai-platform", "version": "1.0"},
            },
            timeout=12.0,
        )
    except Exception:
        pass

    result = await _jsonrpc(url, _headers(server), "tools/list", {})
    tools = []
    if isinstance(result, dict):
        tools = result.get("tools") or []
    elif isinstance(result, list):
        tools = result

    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (name or "mcp"))[:40] or "mcp"
    definitions: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("name") or "").strip()
        if not tool_name:
            continue
        schema = item.get("inputSchema") or item.get("parameters") or {
            "type": "object",
            "properties": {},
        }
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": f"mcp__{safe}__{tool_name}"[:64],
                    "description": (
                        f"[MCP:{name}] " + str(item.get("description") or tool_name)
                    )[:500],
                    "parameters": schema,
                },
                "_mcp": {
                    "server_name": name,
                    "config": config,
                    "tool_name": tool_name,
                },
            }
        )
    return definitions


async def call_mcp_tool(
    name: str,
    config: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    server = resolve_mcp_server(name, config)
    url = str(server.get("url") or server.get("serverUrl") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"MCP「{name}」仅支持 HTTP URL 调用")
    result = await _jsonrpc(
        url,
        _headers(server),
        "tools/call",
        {"name": tool_name, "arguments": arguments or {}},
        timeout=45.0,
    )
    if isinstance(result, dict):
        return result
    return {"content": result}

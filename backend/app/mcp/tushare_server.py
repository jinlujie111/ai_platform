"""Built-in Tushare MCP server (HTTP JSON-RPC).

Token / HTTP proxy are provided by the caller's MCP project config
(mcp.json ``token`` / ``proxy``), forwarded as request headers:
  X-Tushare-Token, X-Tushare-Proxy
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["mcp-tushare"])

TUSHARE_API_URL = "http://api.tushare.pro"
DISCLAIMER = (
    "数据来自 Tushare，可能存在延时；仅供研究参考，不构成投资建议。"
)

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "tushare_query",
        "description": (
            "通用 Tushare Pro 查询。传入 api_name（如 daily、stock_basic、income）"
            "与 params；可选 fields 逗号分隔。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "api_name": {
                    "type": "string",
                    "description": "Tushare 接口名，如 daily / stock_basic / trade_cal",
                },
                "params": {
                    "type": "object",
                    "description": "接口参数对象，如 {\"ts_code\":\"000001.SZ\",\"start_date\":\"20240101\"}",
                    "additionalProperties": True,
                },
                "fields": {
                    "type": "string",
                    "description": "可选，返回字段，逗号分隔",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回行数，默认 100，最大 500",
                    "default": 100,
                },
            },
            "required": ["api_name"],
        },
    },
    {
        "name": "stock_basic",
        "description": "查询 A 股基础信息列表（基于 Tushare stock_basic）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "exchange": {
                    "type": "string",
                    "description": "交易所 SSE/SZSE，可空",
                },
                "list_status": {
                    "type": "string",
                    "description": "上市状态 L/D/P，默认 L",
                    "default": "L",
                },
                "fields": {
                    "type": "string",
                    "description": "可选字段，默认 ts_code,symbol,name,area,industry,list_date",
                },
                "limit": {"type": "integer", "default": 100},
            },
        },
    },
    {
        "name": "daily",
        "description": "查询股票日线行情（基于 Tushare daily）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ts_code": {
                    "type": "string",
                    "description": "股票代码，如 000001.SZ",
                },
                "trade_date": {
                    "type": "string",
                    "description": "交易日 YYYYMMDD，与起止日期二选一",
                },
                "start_date": {"type": "string", "description": "开始日期 YYYYMMDD"},
                "end_date": {"type": "string", "description": "结束日期 YYYYMMDD"},
                "limit": {"type": "integer", "default": 100},
            },
            "required": ["ts_code"],
        },
    },
]


def _proxy_from_request(request: Request | None) -> str | None:
    if request is None:
        return None
    value = (request.headers.get("x-tushare-proxy") or "").strip()
    return value or None


def _token_from_request(request: Request | None) -> str:
    if request is None:
        return ""
    header = (request.headers.get("x-tushare-token") or "").strip()
    if header:
        return header
    auth = (request.headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _jsonrpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _wrap_tool_text(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": payload,
        "isError": bool(payload.get("error")),
    }


async def _tushare_query(
    *,
    token: str,
    api_name: str,
    params: dict[str, Any] | None = None,
    fields: str = "",
    limit: int = 100,
    proxy: str | None = None,
) -> dict[str, Any]:
    if not token:
        raise ValueError(
            "未配置 Tushare Token。请在 MCP 配置中填写 token"
            "（mcp.json 的 token 字段，将以 X-Tushare-Token 传递）。"
        )
    api_name = (api_name or "").strip()
    if not api_name:
        raise ValueError("api_name 不能为空")

    limit = max(1, min(int(limit or 100), 500))
    body = {
        "api_name": api_name,
        "token": token,
        "params": params or {},
        "fields": fields or "",
    }
    proxy = (proxy or "").strip() or None
    timeout = httpx.Timeout(30.0, connect=10.0)
    client_kwargs: dict[str, Any] = {
        "timeout": timeout,
        "follow_redirects": True,
    }
    # httpx>=0.28 uses `proxy=`; older builds used `proxies=`
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        client = httpx.AsyncClient(**client_kwargs)
    except TypeError:
        client_kwargs.pop("proxy", None)
        if proxy:
            client_kwargs["proxies"] = proxy
        client = httpx.AsyncClient(**client_kwargs)

    async with client:
        response = await client.post(TUSHARE_API_URL, json=body)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise ValueError("Tushare 返回格式异常")
    if int(data.get("code") or 0) != 0:
        raise ValueError(str(data.get("msg") or "Tushare 接口错误"))

    raw = data.get("data") or {}
    columns = list(raw.get("fields") or [])
    items = list(raw.get("items") or [])
    rows = [dict(zip(columns, row)) for row in items[:limit]]
    return {
        "api_name": api_name,
        "params": params or {},
        "fields": columns,
        "row_count": len(rows),
        "rows": rows,
        "source": "tushare.pro",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "proxy_used": bool(proxy),
        "disclaimer": DISCLAIMER,
    }


async def _call_tool(
    name: str,
    arguments: dict[str, Any],
    token: str,
    proxy: str | None = None,
) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    common = {"token": token, "proxy": proxy}
    if name == "tushare_query":
        params = args.get("params") if isinstance(args.get("params"), dict) else {}
        return await _tushare_query(
            api_name=str(args.get("api_name") or ""),
            params=params,
            fields=str(args.get("fields") or ""),
            limit=int(args.get("limit") or 100),
            **common,
        )
    if name == "stock_basic":
        params = {
            "list_status": str(args.get("list_status") or "L"),
        }
        if args.get("exchange"):
            params["exchange"] = str(args["exchange"])
        fields = str(
            args.get("fields")
            or "ts_code,symbol,name,area,industry,list_date"
        )
        return await _tushare_query(
            api_name="stock_basic",
            params=params,
            fields=fields,
            limit=int(args.get("limit") or 100),
            **common,
        )
    if name == "daily":
        ts_code = str(args.get("ts_code") or "").strip()
        if not ts_code:
            raise ValueError("ts_code 不能为空")
        params = {"ts_code": ts_code}
        for key in ("trade_date", "start_date", "end_date"):
            if args.get(key):
                params[key] = str(args[key])
        return await _tushare_query(
            api_name="daily",
            params=params,
            fields="",
            limit=int(args.get("limit") or 100),
            **common,
        )
    raise ValueError(f"未知工具：{name}")


async def _handle_rpc(payload: dict[str, Any], request: Request) -> dict[str, Any]:
    req_id = payload.get("id")
    method = str(payload.get("method") or "").strip()
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    token = _token_from_request(request)
    proxy = _proxy_from_request(request)

    if method in ("initialize", "notifications/initialized"):
        return _jsonrpc_result(
            req_id,
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "ai-platform-tushare",
                    "version": "1.0.0",
                },
                "instructions": (
                    "Tushare Pro MCP。请在项目 MCP 配置中填写 token / proxy。"
                    f" {DISCLAIMER}"
                ),
            },
        )

    if method == "tools/list":
        return _jsonrpc_result(req_id, {"tools": TOOL_DEFINITIONS})

    if method == "ping":
        return _jsonrpc_result(req_id, {})

    if method == "tools/call":
        tool_name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            result = await _call_tool(tool_name, arguments, token, proxy)
            return _jsonrpc_result(req_id, _wrap_tool_text(result))
        except Exception as exc:
            return _jsonrpc_result(
                req_id,
                _wrap_tool_text(
                    {
                        "error": str(exc),
                        "source": "tushare.pro",
                        "as_of": datetime.now(timezone.utc).isoformat(),
                        "proxy_used": bool(proxy),
                        "disclaimer": DISCLAIMER,
                    }
                ),
            )

    return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


@router.api_route("/mcp/tushare", methods=["GET", "POST", "OPTIONS"])
async def tushare_mcp_endpoint(request: Request):
    if request.method == "OPTIONS":
        return JSONResponse({"ok": True})
    if request.method == "GET":
        return {
            "ok": True,
            "name": "tushare",
            "transport": "http",
            "proxy_configured": bool(_proxy_from_request(request)),
            "token_configured": bool(_token_from_request(request)),
            "tools": [item["name"] for item in TOOL_DEFINITIONS],
            "message": (
                "在 MCP 配置中填写 token / proxy；"
                "POST JSON-RPC: initialize / tools/list / tools/call"
            ),
        }

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            _jsonrpc_error(None, -32700, "Parse error: body must be JSON"),
            status_code=400,
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            _jsonrpc_error(None, -32600, "Invalid Request"),
            status_code=400,
        )
    return await _handle_rpc(payload, request)

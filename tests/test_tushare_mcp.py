"""Tests for built-in Tushare MCP (proxy-aware)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from backend.app.mcp import tushare_server
from backend.app.mcp.tushare_server import router as tushare_router


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(tushare_router)
    return app


@pytest.mark.asyncio
async def test_tushare_mcp_get_status():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/mcp/tushare")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "tushare_query" in data["tools"]


@pytest.mark.asyncio
async def test_tushare_mcp_tools_list():
    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/mcp/tushare",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
    assert resp.status_code == 200
    body = resp.json()
    names = [t["name"] for t in body["result"]["tools"]]
    assert names == ["tushare_query", "stock_basic", "daily"]


@pytest.mark.asyncio
async def test_tushare_query_uses_proxy(monkeypatch):
    monkeypatch.setenv("TUSHARE_TOKEN", "demo-token")
    monkeypatch.setenv("TUSHARE_HTTP_PROXY", "http://127.0.0.1:7890")

    mock_response = MagicMock(spec=Response)
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "code": 0,
        "msg": "",
        "data": {
            "fields": ["ts_code", "close"],
            "items": [["000001.SZ", 10.5]],
        },
    }

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("backend.app.mcp.tushare_server.httpx.AsyncClient", return_value=mock_client) as client_cls:
        result = await tushare_server._tushare_query(
            token="demo-token",
            api_name="daily",
            params={"ts_code": "000001.SZ"},
            limit=10,
        )

    kwargs = client_cls.call_args.kwargs
    assert kwargs.get("proxy") == "http://127.0.0.1:7890" or kwargs.get("proxies") == "http://127.0.0.1:7890"
    assert result["row_count"] == 1
    assert result["rows"][0]["ts_code"] == "000001.SZ"
    assert result["proxy_used"] is True
    assert "disclaimer" in result


@pytest.mark.asyncio
async def test_tools_call_missing_token(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    for key in (
        "TUSHARE_HTTP_PROXY",
        "TUSHARE_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        monkeypatch.delenv(key, raising=False)

    transport = ASGITransport(app=_app())
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/mcp/tushare",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "daily",
                    "arguments": {"ts_code": "000001.SZ"},
                },
            },
        )
    body = resp.json()
    text = body["result"]["content"][0]["text"]
    payload = json.loads(text)
    assert "token" in payload["error"].lower()

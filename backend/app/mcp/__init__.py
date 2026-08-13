"""Built-in MCP HTTP servers hosted by the platform."""

from .tushare_server import router as tushare_mcp_router

__all__ = ["tushare_mcp_router"]

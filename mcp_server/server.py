"""FastMCP server factory and stdio runner (ADR-010)."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from mcp_server.tools import register_tools


def create_server() -> FastMCP:
    """Build FastMCP instance with M1 tools registered."""
    server = FastMCP("1c-dev")
    register_tools(server)
    return server


def run() -> None:
    """Serve MCP over stdio (blocks until client disconnects)."""
    create_server().run(transport="stdio")

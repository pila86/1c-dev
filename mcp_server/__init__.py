"""MCP server package (ADR-010, Issue #6)."""

from __future__ import annotations

from mcp_server.server import create_server, run

__all__ = ["create_server", "run"]

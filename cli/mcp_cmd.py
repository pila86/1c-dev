"""CLI: 1c-dev mcp."""

from __future__ import annotations

from mcp_server import run


def mcp_command() -> None:
    """Start MCP server over stdio for AI agents (ADR-010)."""
    # stdout is reserved for the MCP protocol — do not print here.
    run()

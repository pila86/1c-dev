"""Resolve optional path argument for MCP tools."""

from __future__ import annotations

from pathlib import Path


def resolve_path(path: str | None) -> Path:
    """Return absolute project path; default is process cwd."""
    if path is None or path.strip() == "":
        return Path.cwd()
    return Path(path).expanduser().resolve()

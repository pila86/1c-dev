"""Platform installation and tool discovery."""

from __future__ import annotations

from .discovery import (
    DiscoveryResult,
    PlatformInfo,
    ToolInfo,
    discover_environment,
    version_from_path,
)

__all__ = [
    "DiscoveryResult",
    "PlatformInfo",
    "ToolInfo",
    "discover_environment",
    "version_from_path",
]

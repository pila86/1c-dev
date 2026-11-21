"""External tools subsystem (ADR-033): catalog, install, registry."""

from __future__ import annotations

from core.tools.catalog import ToolRecipe, catalog_root, list_catalog, load_recipe
from core.tools.install import (
    InstallResult,
    RemoveResult,
    install_tool,
    is_installed,
    list_installed,
    remove_tool,
    tool_info,
)
from core.tools.paths import share_root, tools_share_dir

__all__ = [
    "InstallResult",
    "RemoveResult",
    "ToolRecipe",
    "catalog_root",
    "install_tool",
    "is_installed",
    "list_catalog",
    "list_installed",
    "load_recipe",
    "remove_tool",
    "share_root",
    "tool_info",
    "tools_share_dir",
]

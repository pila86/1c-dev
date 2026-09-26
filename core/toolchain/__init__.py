"""User toolchain cache: sync / clean / uninstall (ADR-013 / #48)."""

from __future__ import annotations

from core.toolchain.cache import cache_root, docs_cache_dir, tools_cache_dir

__all__ = [
    "SyncResult",
    "UninstallResult",
    "cache_root",
    "clean_tools_cache",
    "docs_cache_dir",
    "sync_tools",
    "tools_cache_dir",
    "uninstall_tools",
]


def __getattr__(name: str) -> object:
    if name == "SyncResult":
        from core.toolchain.result import SyncResult

        return SyncResult
    if name == "UninstallResult":
        from core.toolchain.result import UninstallResult

        return UninstallResult
    if name == "sync_tools":
        from core.toolchain.sync import sync_tools

        return sync_tools
    if name == "clean_tools_cache":
        from core.toolchain.uninstall import clean_tools_cache

        return clean_tools_cache
    if name == "uninstall_tools":
        from core.toolchain.uninstall import uninstall_tools

        return uninstall_tools
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

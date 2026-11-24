"""Resolve and store source paths (in-tree and external test paths, ADR-034)."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_source_path(root: Path, path: str) -> Path:
    """Resolve manifest source.path against scope root (absolute or relative)."""
    raw = Path(path)
    if raw.is_absolute():
        return raw.resolve()
    return (root / raw).resolve()


def is_within_scope(root: Path, path: Path) -> bool:
    """True if ``path`` is inside ``root`` (after resolve)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def path_escapes_scope(root: Path, path: str) -> bool:
    """True if relative path uses ``..`` or resolves outside scope / is absolute."""
    raw = Path(path)
    if raw.is_absolute():
        return True
    parts = raw.parts
    if ".." in parts:
        return True
    return not is_within_scope(root, resolve_source_path(root, path))


def store_source_path(root: Path, abs_path: Path) -> str:
    """
    Prefer portable path for the manifest.

    In-tree → relative to root.
    Outside → ``os.path.relpath`` (may start with ``../``); if that fails → absolute.
    """
    resolved_root = root.resolve()
    resolved = abs_path.resolve()
    try:
        return resolved.relative_to(resolved_root).as_posix()
    except ValueError:
        pass
    try:
        rel = os.path.relpath(str(resolved), str(resolved_root))
        return Path(rel).as_posix()
    except ValueError:
        return resolved.as_posix()

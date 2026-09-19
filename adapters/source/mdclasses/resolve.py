"""Resolve md-reader jar and Java runtime (ADR-012)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from adapters.source.mdclasses.constants import (
    MDREADER_JAR_ENV,
    MDREADER_PIN,
    MIN_JAVA_MAJOR,
)
from adapters.source.xmlgen.resolve import (
    ToolResolve,
    tools_cache_dir,
)
from adapters.source.xmlgen.resolve import resolve_java as _resolve_java

__all__ = [
    "ToolResolve",
    "default_jar_path",
    "fetch_script_suggestion",
    "pinned_jar_path",
    "resolve_jar",
    "resolve_java",
    "tools_cache_dir",
]


def resolve_java(*, env: dict[str, str] | None = None) -> ToolResolve:
    """Find Java >= MDClasses/md-reader requirement (JDK 21+)."""
    return _resolve_java(env=env, min_major=MIN_JAVA_MAJOR)


def default_jar_path() -> Path:
    """Stable jar name in cache."""
    return tools_cache_dir() / "md-reader.jar"


def pinned_jar_path() -> Path:
    """Versioned jar name for pinned MDClasses revision."""
    return tools_cache_dir() / f"md-reader-{MDREADER_PIN}.jar"


def fetch_script_suggestion() -> str:
    """OS-specific hint to build md-reader."""
    if sys.platform == "win32":
        return "pwsh scripts/fetch-md-reader.ps1"
    return "./scripts/fetch-md-reader.sh"


def resolve_jar(*, env: dict[str, str] | None = None) -> ToolResolve:
    """Find md-reader jar: ONEC_MDREADER_JAR, then cache md-reader.jar."""
    environ = env if env is not None else os.environ
    override = environ.get(MDREADER_JAR_ENV, "").strip()
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return ToolResolve(found=True, path=path.resolve())
        return ToolResolve(found=False, path=path)
    cached = default_jar_path()
    if cached.is_file():
        return ToolResolve(found=True, path=cached.resolve())
    pinned = pinned_jar_path()
    if pinned.is_file():
        return ToolResolve(found=True, path=pinned.resolve())
    return ToolResolve(found=False, path=cached)

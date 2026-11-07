"""Resolve md-sparrow jar and Java runtime (ADR-032 / #153)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from adapters.source.mdsparrow.constants import (
    MDSPARROW_JAR_ENV,
    MDSPARROW_PIN,
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
    """Find Java >= Temurin 25+ required by md-sparrow."""
    return _resolve_java(env=env, min_major=MIN_JAVA_MAJOR)


def default_jar_path() -> Path:
    """Stable jar name in cache."""
    return tools_cache_dir() / "md-sparrow.jar"


def pinned_jar_path() -> Path:
    """Versioned jar name for pinned md-sparrow release."""
    return tools_cache_dir() / f"md-sparrow-{MDSPARROW_PIN}.jar"


def fetch_script_suggestion() -> str:
    """Hint to bootstrap md-sparrow via tools sync."""
    if sys.platform == "win32":
        return (
            "1c-dev doctor --fix  # или: 1c-dev tools sync "
            f"/ задайте {MDSPARROW_JAR_ENV}"
        )
    return (
        "1c-dev doctor --fix  # или: 1c-dev tools sync "
        f"/ задайте {MDSPARROW_JAR_ENV}"
    )


def resolve_jar(*, env: dict[str, str] | None = None) -> ToolResolve:
    """Find md-sparrow jar: ONEC_MDSPARROW_JAR, then cache md-sparrow.jar."""
    environ = env if env is not None else os.environ
    override = environ.get(MDSPARROW_JAR_ENV, "").strip()
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

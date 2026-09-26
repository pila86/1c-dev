"""Resolve docs-facade jar and Java runtime (ADR-017)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from adapters.docs.constants import DOCS_FACADE_JAR_ENV, DOCS_FACADE_PIN, MIN_JAVA_MAJOR
from adapters.source.xmlgen.resolve import ToolResolve, tools_cache_dir
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
    """Find Java >= docs-facade / bsl-context requirement (JDK 21+)."""
    return _resolve_java(env=env, min_major=MIN_JAVA_MAJOR)


def default_jar_path() -> Path:
    """Stable jar name in cache."""
    return tools_cache_dir() / "docs-facade.jar"


def pinned_jar_path() -> Path:
    """Versioned jar name for pinned bsl-context revision."""
    return tools_cache_dir() / f"docs-facade-{DOCS_FACADE_PIN}.jar"


def fetch_script_suggestion() -> str:
    """Hint to bootstrap docs-facade."""
    if sys.platform == "win32":
        return "1c-dev doctor --fix  # или: 1c-dev tools sync"
    return "1c-dev doctor --fix  # или: 1c-dev tools sync"


def resolve_jar(*, env: dict[str, str] | None = None) -> ToolResolve:
    """Find docs-facade jar: ONEC_DOCS_FACADE_JAR, then cache."""
    environ = env if env is not None else os.environ
    override = environ.get(DOCS_FACADE_JAR_ENV, "").strip()
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

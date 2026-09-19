"""MDClasses read adapter (ADR-012)."""

from __future__ import annotations

from adapters.source.mdclasses.constants import MDREADER_JAR_ENV, MDREADER_PIN, MIN_JAVA_MAJOR
from adapters.source.mdclasses.read import MdReaderError, run_md_reader
from adapters.source.mdclasses.resolve import (
    ToolResolve,
    default_jar_path,
    fetch_script_suggestion,
    pinned_jar_path,
    resolve_jar,
    resolve_java,
    tools_cache_dir,
)

__all__ = [
    "MDREADER_JAR_ENV",
    "MDREADER_PIN",
    "MIN_JAVA_MAJOR",
    "MdReaderError",
    "ToolResolve",
    "default_jar_path",
    "fetch_script_suggestion",
    "pinned_jar_path",
    "resolve_jar",
    "resolve_java",
    "run_md_reader",
    "tools_cache_dir",
]

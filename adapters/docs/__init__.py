"""Docs facade adapter over bsl-context (ADR-017)."""

from __future__ import annotations

from adapters.docs.constants import (
    DOCS_FACADE_JAR_ENV,
    DOCS_FACADE_PIN,
    DOCS_INDEX_DIR_ENV,
    HBK_PATH_ENV,
    MIN_JAVA_MAJOR,
)
from adapters.docs.hbk import HbkResolve, find_hbk
from adapters.docs.resolve import (
    ToolResolve,
    fetch_script_suggestion,
    resolve_jar,
    resolve_java,
)
from adapters.docs.run import (
    DocsFacadeError,
    ensure_index,
    get_index_entry,
    run_docs_facade,
    search_index,
)

__all__ = [
    "DOCS_FACADE_JAR_ENV",
    "DOCS_FACADE_PIN",
    "DOCS_INDEX_DIR_ENV",
    "DocsFacadeError",
    "HBK_PATH_ENV",
    "HbkResolve",
    "MIN_JAVA_MAJOR",
    "ToolResolve",
    "ensure_index",
    "fetch_script_suggestion",
    "find_hbk",
    "get_index_entry",
    "resolve_jar",
    "resolve_java",
    "run_docs_facade",
    "search_index",
]

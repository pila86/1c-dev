"""Documentation / platform context API (ADR-017)."""

from __future__ import annotations

from core.docs.result import DocsResult
from core.docs.run import get_docs, search_docs

__all__ = [
    "DocsResult",
    "get_docs",
    "search_docs",
]

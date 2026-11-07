"""Source format adapters (xml-gen / mdclasses / edt / mdsparrow / xml)."""

from __future__ import annotations

from adapters.source.capabilities import (
    EDT_WRITE_KNOWN_GAPS,
    SOURCE_ADAPTER_CAPABILITIES,
    capabilities_payload,
    get_capabilities,
)

__all__ = [
    "EDT_WRITE_KNOWN_GAPS",
    "SOURCE_ADAPTER_CAPABILITIES",
    "capabilities_payload",
    "get_capabilities",
]

"""Capability matrix for doctor (ADR-005, ADR-007, ADR-012, ADR-015, #25, #49)."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from core.metadata.ir import (
    CREATE_OBJECT_TYPES,
    M2_OBJECT_TYPES,
    UPDATE_OBJECT_TYPES,
)
from core.toolchain.resolve import sync_suggestion

# Capability → required tool names (keys in tools map).
CAPABILITY_REQUIREMENTS: dict[str, list[str]] = {
    "build": ["ibcmd"],
    "check": ["ibcmd"],
    "project.import": ["ibcmd"],
    "metadata.create": ["java", "xml-gen"],
    "metadata.update": ["java", "xml-gen"],
    "metadata.delete": ["java", "xml-gen"],
    "metadata.read": ["java", "md-reader"],
}

# Write capabilities → supported Metadata IR object types (ADR-011 / #25).
_SUPPORTED_TYPES: dict[str, frozenset[str]] = {
    "metadata.create": CREATE_OBJECT_TYPES,
    "metadata.update": UPDATE_OBJECT_TYPES,
    "metadata.delete": M2_OBJECT_TYPES,
}

_TOOL_HINTS: dict[str, str] = {
    "ibcmd": (
        "Установите платформу 1С и добавьте ibcmd в PATH "
        "(или в стандартный каталог установки)."
    ),
    "java": "Установите JDK 17+ и добавьте java в PATH (или задайте JAVA_HOME).",
    "xml-gen": "{suggest} (или задайте ONEC_XMLGEN_JAR).",
    "md-reader": "{suggest} (или задайте ONEC_MDREADER_JAR).",
}


class CapabilityStatus(TypedDict):
    available: bool
    requires: list[str]
    supportedTypes: NotRequired[list[str]]


class CapabilityGap(TypedDict, total=False):
    capability: str
    missing: list[str]
    reason: str
    suggestion: str


def resolve_capabilities(
    tools_found: dict[str, bool],
) -> tuple[dict[str, CapabilityStatus], list[CapabilityGap]]:
    """Compute capability availability and gaps from discovered tools."""
    capabilities: dict[str, CapabilityStatus] = {}
    gaps: list[CapabilityGap] = []
    suggest = sync_suggestion()

    for name, requires in CAPABILITY_REQUIREMENTS.items():
        missing = [t for t in requires if not tools_found.get(t, False)]
        available = not missing
        status: CapabilityStatus = {
            "available": available,
            "requires": list(requires),
        }
        types = _SUPPORTED_TYPES.get(name)
        if types is not None:
            status["supportedTypes"] = sorted(types)
        capabilities[name] = status
        if missing:
            first = missing[0]
            raw = _TOOL_HINTS.get(first, f"Требуется: {', '.join(missing)}")
            if "{suggest}" in raw:
                hint = raw.format(suggest=suggest)
            else:
                hint = raw
            gap: CapabilityGap = {
                "capability": name,
                "missing": missing,
                "reason": f"недоступно без {', '.join(missing)}",
                "suggestion": hint,
            }
            gaps.append(gap)

    return capabilities, gaps

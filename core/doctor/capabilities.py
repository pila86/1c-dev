"""Capability matrix for doctor (ADR-005, ADR-007, ADR-012)."""

from __future__ import annotations

from typing import TypedDict

from adapters.source.mdclasses.resolve import fetch_script_suggestion as mdreader_suggest
from adapters.source.xmlgen.resolve import fetch_script_suggestion as xmlgen_suggest

# Capability → required tool names (keys in tools map).
CAPABILITY_REQUIREMENTS: dict[str, list[str]] = {
    "build": ["ibcmd"],
    "check": ["ibcmd"],
    "metadata.create": ["java", "xml-gen"],
    "metadata.read": ["java", "md-reader"],
}

_TOOL_HINTS: dict[str, str] = {
    "ibcmd": (
        "Установите платформу 1С и добавьте ibcmd в PATH "
        "(или в стандартный каталог установки)."
    ),
    "java": "Установите JDK 17+ и добавьте java в PATH (или задайте JAVA_HOME).",
    "xml-gen": ("Соберите xml-gen: {suggest} (или задайте ONEC_XMLGEN_JAR)."),
    "md-reader": ("Соберите md-reader: {suggest} (или задайте ONEC_MDREADER_JAR)."),
}


class CapabilityStatus(TypedDict):
    available: bool
    requires: list[str]


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

    for name, requires in CAPABILITY_REQUIREMENTS.items():
        missing = [t for t in requires if not tools_found.get(t, False)]
        available = not missing
        capabilities[name] = {"available": available, "requires": list(requires)}
        if missing:
            first = missing[0]
            raw = _TOOL_HINTS.get(first, f"Требуется: {', '.join(missing)}")
            if "{suggest}" in raw:
                suggest = mdreader_suggest() if first == "md-reader" else xmlgen_suggest()
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

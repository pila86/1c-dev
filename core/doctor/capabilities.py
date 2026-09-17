"""Capability matrix for M1 doctor (ADR-005, ADR-007)."""

from __future__ import annotations

from typing import TypedDict

from adapters.source.xmlgen.resolve import fetch_script_suggestion

# Capability → required tool names (keys in tools map).
CAPABILITY_REQUIREMENTS: dict[str, list[str]] = {
    "build": ["ibcmd"],
    "check": ["ibcmd"],
    "metadata.create": ["java", "xml-gen"],
}

_TOOL_HINTS: dict[str, str] = {
    "ibcmd": (
        "Установите платформу 1С и добавьте ibcmd в PATH "
        "(или в стандартный каталог установки)."
    ),
    "java": "Установите JDK 17+ и добавьте java в PATH (или задайте JAVA_HOME).",
    "xml-gen": (
        "Соберите xml-gen: {suggest} (или задайте ONEC_XMLGEN_JAR)."
    ),
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
            hint = raw.format(suggest=fetch_script_suggestion()) if "{suggest}" in raw else raw
            gap: CapabilityGap = {
                "capability": name,
                "missing": missing,
                "reason": f"недоступно без {', '.join(missing)}",
                "suggestion": hint,
            }
            gaps.append(gap)

    return capabilities, gaps

"""Capability matrix for doctor (ADR-005/007/012/018/024/028, #25, #49, #60, #91)."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from core.metadata.types import WRITE_OBJECT_TYPES_SORTED
from core.toolchain.resolve import sync_suggestion

# Capability → required tool names (keys in tools map).
CAPABILITY_REQUIREMENTS: dict[str, list[str]] = {
    "build": ["ibcmd"],
    "check": ["ibcmd"],
    "configuration.import": ["ibcmd"],
    "ibsrv": ["ibsrv"],
    "templates": ["templates"],
    "metadata.create": ["java", "xml-gen"],
    "metadata.update": ["java", "xml-gen"],
    "metadata.delete": ["java", "xml-gen"],
    "metadata.read": ["java", "md-reader"],
}

# Write capabilities → ADR-018 coverage catalog (23 Meta DSL + Subsystem).
_SUPPORTED_TYPES: dict[str, tuple[str, ...]] = {
    "metadata.create": WRITE_OBJECT_TYPES_SORTED,
    "metadata.update": WRITE_OBJECT_TYPES_SORTED,
    "metadata.delete": WRITE_OBJECT_TYPES_SORTED,
}

_TOOL_HINTS: dict[str, str] = {
    "ibcmd": (
        "Установите платформу 1С и добавьте ibcmd в PATH "
        "(или в стандартный каталог установки)."
    ),
    "ibsrv": (
        "Установите платформу 1С с автономным сервером и добавьте ibsrv в PATH "
        "(рядом с ibcmd; нужен для publish.up)."
    ),
    "templates": (
        "Установите шаблоны конфигураций платформы (tmplts) "
        "или задайте ConfigurationTemplatesLocation в 1cestart.cfg "
        "(нужно для templates.list / import --from-template)."
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
            status["supportedTypes"] = list(types)
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

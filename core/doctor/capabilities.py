"""Capability matrix for M1 doctor (ADR-005)."""

from __future__ import annotations

from typing import TypedDict

# Capability → required tool names (keys in tools map).
CAPABILITY_REQUIREMENTS: dict[str, list[str]] = {
    "build": ["ibcmd"],
    "check": ["ibcmd"],
}

_TOOL_HINTS: dict[str, str] = {
    "ibcmd": (
        "Установите платформу 1С и добавьте ibcmd в PATH "
        "(или в стандартный каталог установки)."
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
            hint = _TOOL_HINTS.get(missing[0], f"Требуется: {', '.join(missing)}")
            gap: CapabilityGap = {
                "capability": name,
                "missing": missing,
                "reason": f"недоступно без {', '.join(missing)}",
                "suggestion": hint,
            }
            gaps.append(gap)

    return capabilities, gaps

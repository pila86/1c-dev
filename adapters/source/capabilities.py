"""Source Adapter capability matrix (PRD §50 / ADR-032 / #158)."""

from __future__ import annotations

from typing import Any, Literal

SourceFormat = Literal["xml", "edt"]
CapabilityName = Literal[
    "detect",
    "inspect",
    "read",
    "write",
    "validate",
    "create",
    "sync",
    "convert",
    "incrementalSync",
]

# True / False — M7 product contract; None — TBD (PRD §50).
CapabilityValue = bool | None

# ADR-032 §2 / PRD §50 — общий набор capabilities для XML и EDT.
SOURCE_ADAPTER_CAPABILITIES: dict[SourceFormat, dict[CapabilityName, CapabilityValue]] = {
    "xml": {
        "detect": True,
        "inspect": True,
        "read": True,
        "write": True,
        "validate": True,
        "create": True,
        "sync": False,  # PRD §13 — вне M7 must
        "convert": True,
        "incrementalSync": None,  # TBD
    },
    "edt": {
        "detect": True,
        "inspect": True,
        "read": True,
        "write": True,
        "validate": True,
        "create": True,
        "sync": False,
        "convert": True,
        "incrementalSync": None,
    },
}

# Известные gaps EDT write path D (bake-off S2 / ADR-032) — warning/hard 1CS010.
EDT_WRITE_KNOWN_GAPS: frozenset[str] = frozenset(
    {
        "number_precision_scale",
        "tabular_section_synonym",
        "subsystem_content",  # hard refuse; md-sparrow#78 / #165
    }
)


def get_capabilities(fmt: SourceFormat) -> dict[CapabilityName, CapabilityValue]:
    """Return capability matrix row for ``xml`` / ``edt``."""
    return dict(SOURCE_ADAPTER_CAPABILITIES[fmt])


def capabilities_payload(fmt: SourceFormat) -> dict[str, Any]:
    """PRD §11-shaped capabilities() payload."""
    caps = get_capabilities(fmt)
    convert_to = ["edt"] if fmt == "xml" else ["xml"]
    return {
        "format": fmt,
        "capabilities": {
            "read": caps["read"],
            "write": caps["write"],
            "create": caps["create"],
            "validate": caps["validate"],
            "sync": caps["sync"],
            "convert": caps["convert"],
            "incrementalSync": caps["incrementalSync"],
            "convertTo": convert_to if caps["convert"] else [],
        },
    }

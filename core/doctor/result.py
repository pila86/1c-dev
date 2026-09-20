"""Doctor result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from core.diagnostics import Diagnostic
from core.doctor.capabilities import CapabilityGap, CapabilityStatus

Status = Literal["ok", "error"]


@dataclass
class DoctorResult:
    """Structured result for `1c-dev doctor`."""

    status: Status
    platform: dict[str, Any]
    tools: dict[str, Any]
    capabilities: dict[str, CapabilityStatus]
    gaps: list[CapabilityGap] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Machine-readable payload for CLI/MCP."""
        caps: dict[str, Any] = {}
        for name, cap in self.capabilities.items():
            entry: dict[str, Any] = {
                "available": cap["available"],
                "requires": list(cap["requires"]),
            }
            if "supportedTypes" in cap:
                entry["supportedTypes"] = list(cap["supportedTypes"])
            caps[name] = entry
        payload: dict[str, Any] = {
            "status": self.status,
            "platform": self.platform,
            "tools": self.tools,
            "capabilities": caps,
            "gaps": [dict(g) for g in self.gaps],
            "diagnostics": list(self.diagnostics),
        }
        return payload

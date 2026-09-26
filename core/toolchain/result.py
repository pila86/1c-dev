"""Result payloads for tools sync / uninstall."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from core.diagnostics import Diagnostic

ComponentStatus = Literal["ok", "skipped", "deferred", "error", "warning"]
OverallStatus = Literal["ok", "degraded", "error"]


@dataclass
class ComponentResult:
    """Per-component sync outcome."""

    id: str
    status: ComponentStatus
    path: str | None = None
    pin: str | None = None
    message: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "status": self.status}
        if self.path is not None:
            payload["path"] = self.path
        if self.pin is not None:
            payload["pin"] = self.pin
        if self.message is not None:
            payload["message"] = self.message
        return payload


@dataclass
class SyncResult:
    """Outcome of `1c-dev tools sync`."""

    status: OverallStatus
    components: list[ComponentResult] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "components": [c.to_payload() for c in self.components],
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class UninstallResult:
    """Outcome of `tools clean` / `uninstall`."""

    status: OverallStatus
    cache_removed: bool
    package_uninstalled: bool | None
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "cacheRemoved": self.cache_removed,
            "packageUninstalled": self.package_uninstalled,
            "diagnostics": list(self.diagnostics),
        }

"""Result types for project API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "error"]


@dataclass
class ProjectResult:
    """Structured result for project detect/validate/info/init/ide configure."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    path: Path | None = None
    root: Path | None = None
    manifest: dict[str, Any] | None = None
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_payload(self, *, include_manifest: bool = False) -> dict[str, Any]:
        """Machine-readable payload for CLI/MCP."""
        payload: dict[str, Any] = {"status": self.status}
        if self.path is not None:
            payload["path"] = str(self.path)
        if self.root is not None:
            payload["root"] = str(self.root)
        if include_manifest and self.manifest is not None:
            payload["manifest"] = self.manifest
        elif self.manifest is not None and self.status == "ok" and not include_manifest:
            # detect: краткие поля, если манифест распарсен
            project = self.manifest.get("project")
            if isinstance(project, dict):
                payload["project"] = {
                    k: project[k] for k in ("name", "type") if k in project
                }
        if self.created:
            payload["created"] = list(self.created)
        if self.updated:
            payload["updated"] = list(self.updated)
        if self.skipped:
            payload["skipped"] = list(self.skipped)
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload

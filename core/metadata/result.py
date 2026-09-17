"""Result types for metadata API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "error"]


@dataclass
class MetadataResult:
    """Structured result for metadata.create."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    object: str | None = None
    root: Path | None = None
    source_path: Path | None = None
    created: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.object is not None:
            payload["object"] = self.object
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.source_path is not None:
            payload["sourcePath"] = str(self.source_path)
        if self.created:
            payload["created"] = list(self.created)
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload

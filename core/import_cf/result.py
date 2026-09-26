"""Result types for project.import / runtime.load (ADR-015)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from core.diagnostics import Diagnostic

Status = Literal["ok", "failed"]


@dataclass
class ImportResult:
    """Structured result for project.import / runtime.load."""

    status: Status
    diagnostics: list[Diagnostic] = field(default_factory=list)
    duration: float | None = None
    root: Path | None = None
    runtime_path: Path | None = None
    source_path: Path | None = None
    from_path: Path | None = None
    steps: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": self.status}
        if self.duration is not None:
            payload["duration"] = round(self.duration, 3)
        if self.root is not None:
            payload["root"] = str(self.root)
        if self.runtime_path is not None:
            payload["runtimePath"] = self._rel_or_str(self.runtime_path)
        if self.source_path is not None:
            payload["sourcePath"] = self._rel_or_str(self.source_path)
        if self.from_path is not None:
            payload["from"] = str(self.from_path)
        if self.steps:
            payload["steps"] = list(self.steps)
        if self.created:
            payload["created"] = list(self.created)
        if self.diagnostics:
            payload["diagnostics"] = list(self.diagnostics)
        return payload

    def _rel_or_str(self, path: Path) -> str:
        try:
            if self.root is not None:
                return path.relative_to(self.root).as_posix()
        except ValueError:
            pass
        return str(path)
